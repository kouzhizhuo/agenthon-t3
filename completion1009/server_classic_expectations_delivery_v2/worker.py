"""Fresh Linux host worker for one immutable official-entry expectation image."""
import argparse
import base64
import calendar
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import signal
import sys
import zlib

HERE = Path(__file__).resolve().parent
ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
DIAGNOSTIC = '/opt/t3-classic-structural-v2/diagnostic_entry.py'
CONTROLS = '/opt/t3-classic-structural-v2/controls_entry.py'
STATE_LIMIT = 4 * 1024**3


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def timestamp_ns(value):
    if not value.endswith('Z'):
        raise ValueError('UTC daemon timestamp required')
    base, dot, fraction = value[:-1].partition('.')
    if dot and (not fraction.isdigit() or len(fraction) > 9):
        raise ValueError('finite nanosecond fraction required')
    return calendar.timegm(datetime.strptime(base, '%Y-%m-%dT%H:%M:%S').timetuple()) * 10**9 + (int(fraction.ljust(9, '0')) if dot else 0)


def duration(state):
    return (timestamp_ns(state['FinishedAt']) - timestamp_ns(state['StartedAt'])) / 10**9


def diagnostic_streams(execution, folder):
    prefix = 'T3_STRUCTURAL_DIAGNOSTIC_V2 '
    state_prefix = 'T3_STRUCTURAL_STATE_V2 '
    block_prefix = 'T3_STRUCTURAL_STATE_BLOCK_V2 '
    records, states, streams = [], [], {}
    try:
        for command in execution['commands']:
            if command['argv'][1:2] != ['start']:
                continue
            with Path(command['stdout']['path']).open() as source:
                for line in source:
                    if line.startswith(prefix):
                        records.append(json.loads(line[len(prefix):]))
                    elif line.startswith(state_prefix):
                        states.append(json.loads(line[len(state_prefix):]))
                    elif line.startswith(block_prefix):
                        block = json.loads(line[len(block_prefix):])
                        key = block['arm'], block['scenario_id'], block['seed']
                        if key not in streams:
                            destination = folder / 'diagnostic-state' / ('market-%02d' % len(streams)) / 'STATE.json'
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            streams[key] = {'path': destination, 'file': destination.open('xb'),
                                'decoder': zlib.decompressobj(), 'hash': hashlib.sha256(), 'bytes': 0,
                                'blocks': 0, 'compressed_bytes': 0}
                        stream = streams[key]
                        if block['block_index'] != stream['blocks'] or block['timing_included'] is not False or block['rankable'] is not False:
                            raise ValueError('exact ordered untimed state stream blocks required')
                        compressed = base64.b64decode(block['data_base64'], validate=True)
                        if len(compressed) != block['compressed_bytes'] or len(compressed) > 1024**2:
                            raise ValueError('one MiB maximum compressed state block required')
                        remaining = compressed
                        while remaining:
                            decoder = stream['decoder']
                            data = decoder.decompress(remaining, 1024**2)
                            remaining = decoder.unconsumed_tail
                            if decoder.unused_data:
                                raise ValueError('extra bytes after complete zlib state stream')
                            if not data and remaining:
                                raise ValueError('state stream made no decoding progress')
                            stream['bytes'] += len(data)
                            if stream['bytes'] > STATE_LIMIT:
                                raise ValueError('four GiB host state evidence cap exceeded')
                            stream['file'].write(data)
                            stream['hash'].update(data)
                        stream['blocks'] += 1
                        stream['compressed_bytes'] += len(compressed)
        finalized = {}
        for key, stream in streams.items():
            decoder = stream['decoder']
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('complete zlib state EOF required')
            finalized[key] = {'path': str(stream['path']), 'state_sha256': stream['hash'].hexdigest(),
                'state_bytes': stream['bytes'], 'state_blocks': stream['blocks'],
                'compressed_bytes': stream['compressed_bytes']}
        return records, states, finalized
    finally:
        for stream in streams.values():
            stream['file'].close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('one', 'diagnostic', 'controls', 'metadata'))
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--gate-kit', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('real Linux amd64 only')
    args.payload = args.payload.resolve()
    args.evidence = args.evidence.resolve()
    args.reference_root = args.reference_root.resolve()
    args.gate_kit = args.gate_kit.resolve()
    sys.path.insert(0, str(args.payload / 'host'))
    import verify_linux as linux
    import verify_public as public
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, linux.cancellation)
    args.docker, args.gate_python, args.log_cap_bytes, args.timeout = 'docker', sys.executable, 16 * 1024**2, 300
    if args.stage == 'diagnostic':
        args.log_cap_bytes = 256 * 1024**2
        args.timeout = 3600
    request = read(args.request)
    image = read(args.evidence / 'BUILD_READY.json')['image_id']
    if args.stage == 'metadata':
        write(args.result, linux.image_metadata(args, image, Path(request['folder'])))
        return

    class Strict(linux.DockerCommands):
        def call(self, arguments, label, seconds=30, cleanup=False):
            if arguments and arguments[0] == 'create':
                extra = ['--env', 'PYTHONHASHSEED=0', '--ulimit', 'nproc=256:256', '--ulimit', 'fsize=268435456:268435456']
                if args.stage in ('controls', 'diagnostic'):
                    extra += ['--entrypoint', '/usr/local/bin/python']
                    position = arguments.index(image)
                    script = CONTROLS if args.stage == 'controls' else DIAGNOSTIC
                    arguments = [*arguments[:position + 1], '-B', script, *arguments[position + 1:]]
                arguments = [arguments[0], *extra, *arguments[1:]]
            return super().call(arguments, label, seconds, cleanup)

        def inspect(self, name, cleanup=False, seconds=30):
            value, record = super().inspect(name, cleanup, seconds)
            if value is not None and not cleanup:
                expected = ['/usr/local/bin/python'] if args.stage in ('controls', 'diagnostic') else ENTRY
                if value['Config']['Entrypoint'] != expected:
                    raise ValueError('exact stage-specific entry required')
                if args.stage == 'one' and any(value.startswith(('--mode', '--output-witness', '--runtime', '--build', '--arm')) for value in value['Config']['Cmd']):
                    raise ValueError('ordinary production measurement cannot use diagnostic flags')
                limits = {row['Name']: (row['Soft'], row['Hard']) for row in value['HostConfig']['Ulimits']}
                if limits != {'nofile': (1024, 1024), 'nproc': (256, 256), 'fsize': (268435456, 268435456)}:
                    raise ValueError('exact finite ulimits required')
                binds = [row for row in value['Mounts'] if row['Type'] == 'bind']
                if len(binds) != 2 or {row['Destination']: row['RW'] for row in binds} != {'/input': False, '/output': True}:
                    raise ValueError('official bind envelope required')
                expected_environment = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                    'NUMEXPR_NUM_THREADS': '1', 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
                environment = dict(item.split('=', 1) for item in value['Config'].get('Env', []) if '=' in item)
                if any(environment.get(key) != expected for key, expected in expected_environment.items()):
                    raise ValueError('actual deterministic scientific environment differs')
            return value, record
    linux.DockerCommands = Strict
    args.owner = request['owner']
    folder = Path(request['folder'])
    if args.stage == 'controls':
        args.timeout = 4800
        item, arm = {'shape': 'single', 'scenario_paths': [request['bundle_path']]}, 'original'
    else:
        item, arm = request['item'], 'original' if args.stage == 'one' else request['arm']
    execution, output = linux.run_container(args, image, arm, item, folder, args.owner, request['suffix'])
    row = {'arm': request['arm'], 'execution': execution, 'output': str(output), 'passed': False,
        'timing_included': args.stage == 'one' and request.get('timing_included') is True,
        'warmup': args.stage == 'one' and request.get('warmup') is True,
        'repeat': request.get('repeat'), 'order': request.get('order'),
        'rankable': False, 'stage': args.stage}
    try:
        if not execution['succeeded'] or any(public.sha256(Path(value['staged'])) != value['sha256'] for value in execution['staged_inputs']):
            raise ValueError('actual container or original staged input failed')
        if args.stage != 'controls':
            row['unit'] = item['unit']
            row['reference_checks'] = public.verify_outputs(args.reference_root / item['unit'], output, item)
            row['developer_verifier'] = linux.gate(args, args.reference_root / item['unit'], output, folder)
            if not row['reference_checks']['passed'] or row['developer_verifier']['admissible'] is not True:
                raise ValueError('full original reference/gates failed')
            n, t = row['reference_checks']['actual_events'], duration(execution['state'])
            if t <= 0:
                raise ValueError('positive actual daemon duration required')
            row.update(actual_events=n, settled_container_runtime_sec=t, EPS=n/t)
            if args.stage == 'diagnostic':
                records, states, streamed = diagnostic_streams(execution, folder)
                scenarios = {None: Path(item['scenario_paths'][0])} if item['shape'] == 'single' else {Path(path).stem: Path(path) for path in item['scenario_paths']}
                if len(records) != len(scenarios) or {record['sub'] for record in records} != set(scenarios):
                    raise ValueError('actual admission witness coverage differs')
                if len(states) != len(scenarios) or {record['sub'] for record in states} != set(scenarios):
                    raise ValueError('one full STATE/RNG/alias graph per actual market required')
                state_receipts = []
                for record in states:
                    if record['arm'] != request['arm'] or record['graph_output_readonly'] is not True or record['observer_finished'] is not True or record['kernel_and_summary_bindings_restored'] is not True or record['index_witness_recorded_before_business_alias_snapshot'] is not True:
                        raise ValueError('complete readonly state graph and diagnostic index ordering required')
                    scenario = public.read_json(scenarios[record['sub']])
                    if record['scenario_id'] != str(scenario['scenario_id']) or record['seed'] != int(scenario['seed']):
                        raise ValueError('full state graph must bind actual scenario identity')
                    key = record['arm'], record['scenario_id'], record['seed']
                    actual_state = streamed.pop(key)
                    if any(record[field] != actual_state[field] for field in ('state_sha256', 'state_bytes', 'state_blocks')):
                        raise ValueError('complete actual streamed state SHA, size or block count differs')
                    state_receipts.append({**record, 'path': actual_state['path'], 'compressed_bytes': actual_state['compressed_bytes'],
                        'full_actual_STATE_bytes_retained': True})
                if streamed:
                    raise ValueError('unclaimed complete actual state stream refused')
                for record in records:
                    target = output if record['sub'] is None else output / record['sub']
                    scenario = public.read_json(scenarios[record['sub']])
                    witness, actual = record['witness'], record['actual_execution']
                    source_lock = read(args.payload / 'PARENT_SOURCE_LOCK.json')['candidate_files'] if request['arm'] == 'parent' else read(args.payload / 'CANDIDATE_SOURCE_LOCK.json')['arms'][request['arm']]['source_files']
                    if record['production_source_sha256'] != source_lock['production_cli.py']['sha256'] or record['timing_included'] is not False or record['market_rerun'] is not False:
                        raise ValueError('exact source-bound untimed single-pass diagnostic required')
                    if actual['scenario_id'] != str(scenario['scenario_id']) or actual['seed'] != int(scenario['seed']) or record['arm'] != request['arm']:
                        raise ValueError('witness actual input/arm differs')
                    if witness['actual_trace_sha256'] != public.sha256(target / 'trace.parquet') or witness['actual_trace_rows'] != public.read_json(target / 'events.json')['n_events']:
                        raise ValueError('witness actual trace binding differs')
                    if witness['selected_kernel'] != actual['actual_kernel'].rsplit('.', 1)[-1] or witness['native_admitted'] != actual['actual_authority_migration']:
                        raise ValueError('admission does not match actual selected engine')
                    if witness['source_authenticated'] is not True or witness['observer_admitted'] is not True or witness['market_rerun'] is not False:
                        raise ValueError('actual fresh source and observer admission required')
                    exchange = scenario['exchange_config']
                    proto = bool(exchange.get('protocol_enforcement', False))
                    stp = str(exchange['stp_policy']) if proto and exchange.get('stp_policy') else None
                    if actual['actual_stp_policy'] != stp or actual['actual_pipeline_delay'] != (int(exchange.get('ack_delay_ns', 0)) if proto else 0) or actual['actual_computation_delay'] != (int(exchange.get('compute_delay_ns', 0)) if proto else 0):
                        raise ValueError('actual diagnostic exchange protocol differs')
                    record['scenario_sha256'] = public.sha256(scenarios[record['sub']])
                write(folder / 'ADMISSION_WITNESSES.json', records)
                write(folder / 'STATE_RECEIPTS.json', state_receipts)
                row['admission_witnesses'] = records
                row['state_receipts'] = state_receipts
        else:
            result = read(output / 'controls/STRUCTURAL_CONTROL_RESULT.json')
            if result.get('all_passed') is not True or result['arm'] != request['arm']:
                raise ValueError('actual complete untimed controls failed')
            row['control_result'] = result
        output_bytes = sum(path.stat().st_size for path in output.rglob('*') if path.is_file())
        if output_bytes > 256 * 1024**2:
            raise ValueError('actual output directory exceeds official256MiB bound')
        row['actual_output_directory_bytes'] = output_bytes
        row['passed'] = True
    except BaseException as error:
        row['failure'] = {'type': type(error).__name__, 'message': str(error)}
    write(folder / 'RUN_RESULT.json', row)
    write(args.result, row)
    if not row['passed']:
        raise ValueError('actual structural worker failed')


if __name__ == '__main__':
    main()
