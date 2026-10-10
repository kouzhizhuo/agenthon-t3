"""Linux-only, exact-public-digest full71 admission and execution census."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid

HERE = Path(__file__).resolve().parent
PARENT = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
CANDIDATE = '/opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1'
ENTRY = ['/usr/local/bin/python', '-B', '/opt/t3-structural-census-v1/entry.py']
PREFIX = 'T3_STRUCTURAL_CENSUS_V1 '


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if any(part.startswith('._') or part in ('__pycache__', '__MACOSX') for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError('source or evidence symlink refused')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def strict_commands(linux):
    class Strict(linux.DockerCommands):
        def call(self, arguments, label, seconds=30, cleanup=False):
            if arguments and arguments[0] == 'create':
                arguments = [arguments[0], '--env', 'PYTHONHASHSEED=0', '--ulimit', 'nproc=256:256',
                    '--ulimit', 'fsize=268435456:268435456', *arguments[1:]]
            return super().call(arguments, label, seconds, cleanup)

        def inspect(self, name, cleanup=False, seconds=30):
            value, record = super().inspect(name, cleanup, seconds)
            if value is not None and not cleanup:
                if value['Config']['Entrypoint'] != ENTRY or '--mode' in value['Config']['Cmd']:
                    raise ValueError('exact leading-verb diagnostic entry required')
                binds = [row for row in value['Mounts'] if row['Type'] == 'bind']
                if len(binds) != 2 or {row['Destination']: row['RW'] for row in binds} != {'/input': False, '/output': True}:
                    raise ValueError('input/output-only official mount envelope required')
                expected = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                    'NUMEXPR_NUM_THREADS': '1', 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
                environment = dict(value.split('=', 1) for value in value['Config']['Env'] if '=' in value)
                if any(environment.get(key) != expected_value for key, expected_value in expected.items()):
                    raise ValueError('fixed deterministic environment differs')
                limits = {row['Name']: (row['Soft'], row['Hard']) for row in value['HostConfig']['Ulimits']}
                if limits != {'nofile': (1024, 1024), 'nproc': (256, 256), 'fsize': (268435456, 268435456)}:
                    raise ValueError('full finite ulimits required')
            return value, record
    return Strict


def extract(args, linux, image, remote, target, label):
    name = 't3-census-source-' + uuid.uuid4().hex
    commands = linux.DockerCommands(args.docker, args.evidence / (label + '-commands'), args.log_cap_bytes)
    owner = uuid.uuid4().hex
    copied = False
    try:
        made = commands.call(['create', '--name', name, '--label', linux.OWNER_LABEL + '=' + owner,
            '--pull', 'never', image], 'create')
        if not made['succeeded']:
            raise ValueError('exact source-copy create failed')
        info, _ = commands.inspect(name, cleanup=True)
        linux.require_owned(info, name, owner, image)
        copied = commands.call(['cp', name + ':' + remote, str(target)], 'source-copy', 120)['succeeded']
    finally:
        cleanup = linux.settle_container(commands, name, owner, image, creation_uncertain=True)
        write(args.evidence / (label + '.json'), {'commands': commands.rows, 'cleanup': cleanup,
            'container_never_started': True, 'timing_included': False})
    if not copied or not cleanup['settled'] or not cleanup['removed'] or not cleanup['final_absent'] or cleanup['errors']:
        raise ValueError('source extraction or exact cleanup failed')


def build(args, linux):
    lock = read(HERE / 'PARENT_SOURCE_LOCK.json')
    if lock['image'] != PARENT or lock['parent_delivery_source_sha256'] != 'f0f697185a65fcc5c77fec23adbd20c57859cc26e2ba6259e2bb6e2167a472f1':
        raise ValueError('exact official parent source lock required')
    commands = linux.DockerCommands(args.docker, args.evidence / 'build-commands', args.log_cap_bytes)
    anon = args.evidence / 'anonymous-docker-config'
    anon.mkdir()
    prior = os.environ.get('DOCKER_CONFIG')
    os.environ['DOCKER_CONFIG'] = str(anon)
    try:
        pulled = commands.call(['pull', '--platform', 'linux/amd64', PARENT], 'anonymous-parent-pull', 900)
    finally:
        if prior is None:
            os.environ.pop('DOCKER_CONFIG', None)
        else:
            os.environ['DOCKER_CONFIG'] = prior
    if not pulled['succeeded']:
        raise ValueError('exact public parent pull failed')
    parent = linux.image_metadata(args, PARENT, args.evidence / 'parent-metadata')
    if PARENT not in parent['inspection']['RepoDigests']:
        raise ValueError('actual public digest differs')
    tag = 't3-structural-parent-census-v1:' + uuid.uuid4().hex
    built = commands.call(['build', '--platform', 'linux/amd64', '--pull=false', '--progress=plain',
        '-t', tag, '-f', str(HERE / 'Dockerfile'), str(HERE)], 'diagnostic-build', 900)
    if not built['succeeded']:
        raise ValueError('diagnostic wrapper image build failed')
    image = linux.image_metadata(args, tag, args.evidence / 'diagnostic-metadata')
    if image['inspection']['Config']['Entrypoint'] != ENTRY or image['inspection']['Config']['User'] != '65534:65534':
        raise ValueError('actual wrapper entry/user differs')
    installed = args.evidence / 'installed-parent'
    extract(args, linux, image['id'], CANDIDATE, installed, 'source-extraction')
    if inventory(installed) != lock['candidate_files']:
        raise ValueError('all frozen parent source, metadata, C, object and ELF bytes must match tested delivery')
    entry = args.evidence / 'installed-diagnostic-entry.py'
    extract(args, linux, image['id'], '/opt/t3-structural-census-v1/entry.py', entry, 'entry-extraction')
    if entry.read_bytes() != (HERE / 'entry.py').read_bytes():
        raise ValueError('actual diagnostic entry source differs')
    original_entry = args.evidence / 'installed-original-delivery-entry.py'
    extract(args, linux, image['id'], '/opt/classic-native-kernels-v1/delivery_entry.py', original_entry, 'original-entry-extraction')
    if sha(original_entry) != lock['parent_delivery_source_sha256']:
        raise ValueError('published parent entry source differs')
    write(args.evidence / 'BUILD_READY.json', {'image_id': image['id'], 'parent_digest': PARENT,
        'parent_image_id': parent['id'], 'parent_candidate_inventory_equal': True,
        'candidate_files': inventory(installed), 'original_entry_sha256': sha(original_entry),
        'diagnostic_entry_sha256': sha(entry), 'source_lock_sha256': sha(HERE / 'PARENT_SOURCE_LOCK.json'),
        'source_and_native_not_rebuilt': True, 'timing_included': False, 'rankable': False})


def validate_census(args, public, row, item, output, folder):
    prefix_rows = []
    for command in row['commands']:
        if len(command['argv']) >= 2 and command['argv'][1] == 'start':
            text = Path(command['stdout']['path']).read_text()
            prefix_rows.extend(json.loads(line[len(PREFIX):]) for line in text.splitlines() if line.startswith(PREFIX))
    inputs = [Path(path) for path in item['scenario_paths']]
    expected = {None: inputs[0]} if item['shape'] == 'single' else {path.stem: path for path in inputs}
    if len(prefix_rows) != len(expected) or {record['sub'] for record in prefix_rows} != set(expected):
        raise ValueError('one census record per actual market required')
    checked = []
    source_sha = read(HERE / 'PARENT_SOURCE_LOCK.json')['candidate_files']['production_cli.py']['sha256']
    for record in prefix_rows:
        source = expected[record['sub']]
        scenario = public.read_json(source)
        witness, actual = record['witness'], record['actual_execution']
        target = output if record['sub'] is None else output / record['sub']
        events = public.read_json(target / 'events.json')
        if record['production_source_sha256'] != source_sha or record['timing_included'] is not False:
            raise ValueError('exact untimed production source binding required')
        if actual['scenario_id'] != str(scenario['scenario_id']) or actual['seed'] != int(scenario['seed']):
            raise ValueError('actual config execution did not match input')
        if witness['actual_trace_sha256'] != public.sha256(target / 'trace.parquet') or witness['actual_trace_rows'] != events['n_events']:
            raise ValueError('census actual trace binding differs')
        if witness['market_rerun'] is not False or witness['rankable'] is not False or witness['requested_arm'] != 'light_dynamic':
            raise ValueError('diagnostic rerun or routing differs')
        if actual['actual_kernel_class'].rsplit('.', 1)[-1] != witness['selected_kernel']:
            raise ValueError('reported selected kernel differs from actual end state')
        if bool(witness['native_admitted']) != bool(actual['actual_authority_migration']):
            raise ValueError('native admission and actual authority migration differ')
        if actual['actual_agent_count'] != 1 + sum(int(config['count']) for config in scenario['agent_configs']):
            raise ValueError('actual config roster differs from input')
        requested = scenario['exchange_config']
        proto = bool(requested.get('protocol_enforcement', False))
        expected_protocol = {'actual_stp_policy': str(requested['stp_policy']) if proto and requested.get('stp_policy') else None,
            'actual_pipeline_delay': int(requested.get('ack_delay_ns', 0)) if proto else 0,
            'actual_computation_delay': int(requested.get('compute_delay_ns', 0)) if proto else 0,
            'actual_book_logging': True, 'actual_book_log_depth': 10, 'actual_symbols': ['ABM']}
        for state in ('actual_config_protocol', 'actual_end_protocol'):
            if any(actual[state][key] != value for key, value in expected_protocol.items()):
                raise ValueError('actual exchange protocol differs from exact official config semantics')
        checked.append({**record, 'unit': item['unit'], 'scenario_sha256': public.sha256(source),
            'actual_protocol_verified': True, 'full_trace_and_ledger_official_gate_verified': True})
    write(folder / 'CENSUS_MARKETS.json', checked)
    return checked


def census(args, linux, public):
    ready = read(args.evidence / 'BUILD_READY.json')
    roster = public.collect_plan(args.reference_root, None)
    if roster['selected_units'] != 71 or roster['reference_frame_count'] != 190:
        raise ValueError('full71 and all95 market references required')
    write(args.evidence / 'REFERENCE_PLAN.json', roster)
    linux.DockerCommands = strict_commands(linux)
    owner = uuid.uuid4().hex
    rows, markets, failure = [], [], None
    before = linux.image_metadata(args, ready['image_id'], args.evidence / 'before')
    try:
        for index, item in enumerate(roster['units']):
            folder = args.evidence / 'census-runs' / item['unit']
            execution, output = linux.run_container(args, ready['image_id'], 'original', item, folder, owner, str(index))
            row = {'unit': item['unit'], 'execution': execution, 'output': str(output),
                'timing_included': False, 'rankable': False, 'passed': False}
            rows.append(row)
            if not execution['succeeded'] or any(public.sha256(Path(value['staged'])) != value['sha256'] for value in execution['staged_inputs']):
                raise ValueError('diagnostic execution or staged input failed: ' + item['unit'])
            ref = public.verify_outputs(args.reference_root / item['unit'], output, item)
            gate = linux.gate(args, args.reference_root / item['unit'], output, folder)
            row.update(reference_checks=ref, developer_verifier=gate)
            if not ref['passed'] or gate['admissible'] is not True:
                raise ValueError('full official trace/ledger or unchanged gates failed: ' + item['unit'])
            actual = validate_census(args, public, execution, item, output, folder)
            markets.extend(actual)
            row.update(market_count=len(actual), output_inventory=inventory(output), passed=True)
            write(folder / 'RUN_RESULT.json', row)
            print(item['unit'], len(actual), 'CENSUS PASS', flush=True)
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    after = linux.image_metadata(args, ready['image_id'], args.evidence / 'after')
    unchanged = all(public.sha256(args.reference_root / item['unit'] / name) == digest
        for item in roster['units'] for mapping in (item['input_sha256'], item['reference_sha256']) for name, digest in mapping.items())
    gates = sum(gate['passed'] is True for row in rows for gate in row.get('developer_verifier', {}).get('verdict', {}).get('gate_results', {}).values())
    settled = all(row['execution']['succeeded'] and row['execution']['exit_code'] == 0 and row['execution']['OOMKilled'] is False
        and row['execution']['cleanup']['settled'] and row['execution']['cleanup']['removed']
        and row['execution']['cleanup']['final_absent'] and row['execution']['cleanup']['errors'] == [] for row in rows)
    immutable = before['inspection'] == after['inspection']
    summary = {'all_passed': failure is None and len(rows) == 71 and len(markets) == 95 and gates == 284
        and unchanged and settled and immutable, 'failure': failure, 'units': len(rows), 'markets': len(markets),
        'official_gate_passes': gates, 'public_references_unchanged': unchanged, 'all_settled_removed': settled,
        'actual_image_immutable': immutable, 'native_admitted_markets': sum(bool(row['witness']['native_admitted']) for row in markets),
        'source_authenticated_markets': sum(bool(row['witness']['source_authenticated']) for row in markets),
        'output_modes': {mode: sum(row['witness']['output_mode'] == mode for row in markets)
            for mode in sorted({row['witness']['output_mode'] for row in markets})},
        'selected_kernels': {name: sum(row['witness']['selected_kernel'] == name for row in markets)
            for name in sorted({row['witness']['selected_kernel'] for row in markets})},
        'diagnostic_timing_is_not_performance': True, 'timing_included': False, 'rankable': False,
        'official_submission': False, 'parent_image': PARENT}
    write(args.evidence / 'RAW_RESULTS.json', rows)
    write(args.evidence / 'CENSUS_MARKETS.json', markets)
    write(args.evidence / 'SUMMARY.json', summary)
    if not summary['all_passed']:
        raise ValueError('full95 exact parent diagnostic census failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('build', 'census', 'artifact'))
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--gate-kit', type=Path, required=True)
    parser.add_argument('--artifact', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('real Linux amd64 only; no local simulation')
    args.payload = args.payload.resolve()
    args.evidence = args.evidence.resolve()
    args.reference_root = args.reference_root.resolve()
    args.gate_kit = args.gate_kit.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.payload / 'control'))
    sys.path.insert(0, str(args.payload / 'host'))
    import common
    import verify_linux as linux
    import verify_public as public
    common.verify_payload(args.payload)
    args.docker, args.gate_python, args.timeout = 'docker', sys.executable, 600
    args.log_cap_bytes = 16 * 1024**2
    if args.stage == 'build':
        build(args, linux)
    elif args.stage == 'census':
        census(args, linux, public)
    else:
        if args.artifact is None or args.artifact.exists():
            raise ValueError('fresh artifact destination required')
        shutil.copytree(args.evidence, args.artifact / 'evidence', ignore=shutil.ignore_patterns('anonymous-docker-config'))
        shutil.copytree(HERE, args.artifact / 'census-source', ignore=shutil.ignore_patterns('._*', '__pycache__'))
        shutil.copytree(args.payload, args.artifact / 'frozen-parent-payload')
        write(args.artifact / 'ARTIFACT.json', {'files': inventory(args.artifact),
            'all_actual_output_bytes_retained': True, 'timing_included': False, 'rankable': False})


if __name__ == '__main__':
    main()
