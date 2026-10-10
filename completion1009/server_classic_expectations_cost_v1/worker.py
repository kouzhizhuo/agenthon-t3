"""Fresh real-Linux-only cost worker draft around frozen host verification.

Importing this module performs no participant, native, Docker or market work.
Main is blocked until finalized hostauthority and exact copied helper pins exist.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import signal
import sys

from parser import (ARMS, LOG_CAP, exact_fields, exact_pin, file_pin,
                    parse_cost_stdout, read_json_bytes, require, roster_from_execution, source_contract)

HERE = Path(__file__).resolve().parent
ENTRY = '/opt/t3-classic-structural-v2/cost-diagnostic-v1/cost_entry_draft_v1.py'
PUBLIC_ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
CHECKS = ('base_saved_audit_passed', 'anonymous_registry_full_bytes_verified', 'base_manifest_config_bound',
    'base_source_C_object_ELF_licenses_verified', 'overlay_config_inherited_exactly', 'overlay_rootfs_additive',
    'overlay_before_inventory_exact', 'source_command_class_original', 'full71_roster_inputs_refs_bound')


def read(path):
    return read_json_bytes(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def inventory(root):
    root = Path(root)
    rows = {}
    for path in sorted(root.rglob('*')):
        if any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in path.parts):
            continue
        require(not path.is_symlink(), 'complete output tree has no symlinks')
        if path.is_file():
            rows[path.relative_to(root).as_posix()] = file_pin(path)
    return rows


def validate_authority(request, host):
    exact_fields(request, {'schema': 't3-cost-worker-request-v1', 'entry': ENTRY,
        'timeout_sec': 3600, 'log_cap_bytes': LOG_CAP})
    require(request['arm'] in ARMS and request['cost_mode'] in ('state', 'cost')
        and type(request['owner']) is str and re.fullmatch(r'[0-9a-f]{32}', request['owner']), 'exact requested arm/mode/owner')
    require(type(request['image_id']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', request['image_id']), 'exact overlay config image ID')
    path = Path(request['authority_path'])
    require(path.is_absolute() and file_pin(path) == exact_pin(request['authority_pin']), 'frozen exact hostauthority bytes')
    authority = read(path)
    exact_fields(authority, {'schema': 't3-cost-host-authority-v1', 'ready_for_linux': True, 'all_passed': True,
        'base_publication_authority': True, 'publication_authority': False, 'runtime_changed': False, 'rankable': False,
        'overlay_image_id': request['image_id'], 'binding': request['binding'], 'overlay_entry': ENTRY,
        'host_pins': request['host_pins']})
    require(type(authority.get('checks')) is dict and all(authority['checks'].get(k) is True for k in CHECKS), 'all actual base/public/overlay authority checks')
    binding = request['binding']
    exact_fields(binding, {'schema': 't3-expectations-cost-image-binding-v1', 'ready_for_linux': True,
        'runtime_changed': False, 'base_publication_authority': True, 'publication_authority': False, 'rankable': False,
        'actual_final_image_id': authority['base_image_id'], 'actual_final_public_digest': authority['public_digest']})
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', authority['base_image_id']) and re.fullmatch(
        r'ghcr\.io/kouzhizhuo/agenthon-t3-classic@sha256:[0-9a-f]{64}', authority['public_digest']), 'exact audited base image/digest')
    for name in ('verify_linux.py', 'verify_public.py'):
        require(file_pin(host / name) == exact_pin(request['host_pins'][name]), 'exact unchanged host verifier ' + name)
    for name in ('verify_linux', 'verify_public', 'graph_saved_v1', 'saved_base_v1'):
        require(name not in sys.modules, 'fresh exact verifier/graph module slot')
    helper_root = Path(request['saved_graph_helper_root'])
    require(helper_root.is_absolute(), 'absolute frozen graph helper directory')
    for name in ('graph_saved_v1.py', 'saved_base_v1.py'):
        require(file_pin(helper_root / name) == exact_pin(request['saved_graph_helper_pins'][name]), 'exact typed graph helper ' + name)
    source = binding['candidate_source_files'][ARMS[request['arm']]]['production_cli.py']
    exact_pin(source)
    source_path = Path(request['production_source_path'])
    require(source_path.is_absolute() and source_path == Path(authority['production_source_paths'][ARMS[request['arm']]])
        and source == exact_pin(request['production_source_pin']) == file_pin(source_path),
        'exact authority-bound actual saved original production source')
    contract = source_contract(source_path.read_bytes(), request['arm'], source)
    item = request['item']
    require(type(item) is dict and type(item.get('unit')) is str and item.get('shape') in ('single', 'batch')
        and type(item.get('scenario_paths')) is list and 1 <= len(item['scenario_paths']) <= 5, 'finite unchanged original unit')
    reference = Path(request['reference_root'])
    kit = Path(request['gate_kit'])
    require(reference.is_absolute() and kit.is_absolute() and reference.is_dir() and kit.is_dir(), 'actual reference/gate roots')
    return authority, source, helper_root, contract


def raw_metadata_match(value, authority):
    wanted = authority['overlay_metadata']
    require(value == wanted and value['Id'] == authority['overlay_image_id'], 'actual overlay metadata exact frozen before inspection')
    base = authority['base_metadata']
    require(base['Id'] == authority['base_image_id'] and authority['public_digest'] in base['RepoDigests'], 'base metadata id/public digest')
    require(value['Config'] == base['Config'] and value['Config']['Entrypoint'] == PUBLIC_ENTRY
        and value['Config'].get('Cmd') in (None, []) and value['Config']['User'] == '65534:65534'
        and value['Config']['WorkingDir'] == '/output' and not value['Config'].get('Volumes'), 'all inherited overlay config exact public contract')
    require(value['RootFS']['Type'] == base['RootFS']['Type'] == 'layers'
        and value['RootFS']['Layers'][:len(base['RootFS']['Layers'])] == base['RootFS']['Layers']
        and len(value['RootFS']['Layers']) == len(base['RootFS']['Layers']) + 1, 'exact base layers plus one additive overlay layer')


def main():
    cli = argparse.ArgumentParser(allow_abbrev=False)
    cli.add_argument('--host', type=Path, required=True)
    cli.add_argument('--worker-args', type=Path, required=True)
    cli.add_argument('--evidence', type=Path, required=True)
    cli.add_argument('--label', required=True)
    opts = cli.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('actual Linux amd64 cost worker only')
    require(re.fullmatch(r'cost-[0-9]{2}-(parent|expectations)-(state|cost)', opts.label), 'fixed cell label')
    host, evidence = opts.host.resolve(), opts.evidence.resolve()
    request = read(opts.worker_args)
    authority, source_pin, graph_helper, contract = validate_authority(request, host)
    folder = evidence / 'diagnostic' / opts.label
    require(not folder.exists(), 'fresh exact diagnostic cell directory')
    row = {'schema': 't3-cost-worker-result-v1', 'passed': False, 'rankable': False, 'timing_included': False,
        'arm': request['arm'], 'cost_mode': request['cost_mode'], 'unit': request['item']['unit'],
        'request': file_pin(opts.worker_args), 'authority': file_pin(Path(request['authority_path'])),
        'execution': None, 'reference_checks': None, 'developer_verifier': None, 'parsed': None, 'failure': None,
        'market_executed_by_this_worker': False, 'container_started_by_this_worker': False,
        'diagnostic_only': True, 'performance_usable': False, 'source_contract': contract}
    original_error = None
    sys.path.insert(0, str(host))
    import verify_linux as linux
    import verify_public as public
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, linux.cancellation)
    args = argparse.Namespace(docker='docker', gate_python=sys.executable, log_cap_bytes=LOG_CAP, timeout=3600,
        gate_kit=Path(request['gate_kit']), owner=request['owner'])
    image = request['image_id']
    # Metadata/source copying never shares this worker's subclass with the driver.
    original_class = linux.DockerCommands
    item = request['item']
    verb = 'simulate' if item['shape'] == 'single' else 'simulate-batch'
    public_args = [verb, '--config', '/input/scenario.json', '--out', '/output/trace.parquet'] if verb == 'simulate' else [verb, '--batch-dir', '/input/scenarios', '--out-dir', '/output']
    expected_cmd = ['-B', ENTRY, *public_args, '--cost-arm', request['arm'], '--cost-mode', request['cost_mode']]

    class Strict(original_class):
        def call(self, arguments, label, seconds=30, cleanup=False):
            if arguments and arguments[0] == 'create':
                position = arguments.index(image)
                require(arguments[position + 1:] == public_args, 'unchanged original public host arguments')
                arguments = [arguments[0], '--env', 'PYTHONHASHSEED=0', '--ulimit', 'nproc=256:256',
                    '--ulimit', 'fsize=268435456:268435456', '--entrypoint', '/usr/local/bin/python',
                    *arguments[1:position + 1], '-B', ENTRY, *arguments[position + 1:],
                    '--cost-arm', request['arm'], '--cost-mode', request['cost_mode']]
            return super().call(arguments, label, seconds, cleanup)

        def inspect(self, name, cleanup=False, seconds=30):
            value, record = super().inspect(name, cleanup, seconds)
            if value is not None and not cleanup:
                config, resource = value['Config'], value['HostConfig']
                require(config['Entrypoint'] == ['/usr/local/bin/python'] and config['Cmd'] == expected_cmd, 'actual exact cost command/entrypoint')
                limits = {x['Name']: (x['Soft'], x['Hard']) for x in resource['Ulimits']}
                require(limits == {'nofile': (1024, 1024), 'nproc': (256, 256), 'fsize': (268435456, 268435456)}, 'actual exact finite cost ulimits')
                binds = [x for x in value['Mounts'] if x['Type'] == 'bind']
                require(len(binds) == 2 and {x['Destination']: x['RW'] for x in binds} == {'/input': False, '/output': True}
                    and all(x['Type'] in ('bind', 'tmpfs') for x in value['Mounts'])
                    and resource['Privileged'] is False and resource.get('CapAdd') in (None, []), 'exact readonly input/output mounts/no extra privileges')
                environment = dict(x.split('=', 1) for x in config['Env'] if '=' in x)
                wanted = {'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                    'NUMEXPR_NUM_THREADS': '1', 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
                require(all(environment.get(k) == v for k, v in wanted.items()), 'exact deterministic cost environment')
            return value, record

    try:
        sys.path.insert(0, str(graph_helper))
        from saved_base_v1 import BaseAudit
        from graph_saved_v1 import GraphAudit
        class RawAudit(BaseAudit):
            def path(self, value):
                path = Path(value)
                require(path.is_absolute() and evidence in path.resolve().parents, 'raw log path under exact evidence root')
                return path
            def filepin(self, path):
                return file_pin(path)
        raw = RawAudit()
        raw.intervals, raw.executions = [], []
        meta = linux.image_metadata(args, image, evidence / 'worker-metadata' / opts.label)
        raw_metadata_match(meta['inspection'], authority)
        require(type(meta['commands']) is list and len(meta['commands']) == 1
            and meta['commands'][0]['argv'] == ['docker', 'image', 'inspect', image], 'exact metadata raw command')
        raw.command(meta['commands'][0])
        require(read(meta['commands'][0]['stdout']['path']) == [meta['inspection']], 'metadata raw bytes equal actual inspection')
        row['metadata'] = meta
        plan = public.collect_plan(Path(request['reference_root']), None)
        full = {unit['unit']: unit for unit in plan['units']}
        require(len(full) == 71 and plan['reference_frame_count'] == 190 and item['unit'] in full
            and all(item[key] == full[item['unit']][key] for key in ('shape', 'subs', 'input_sha256', 'reference_sha256', 'scenario_paths')), 'exact fresh full71 selected original reference item')
        linux.DockerCommands = Strict
        execution, output = linux.run_container(args, image, 'original', item, folder, request['owner'], opts.label)
        row.update(execution=execution, output=str(output))
        state = execution.get('state')
        row['container_started_by_this_worker'] = bool(type(state) is dict and execution.get('attach')
            and type(state.get('StartedAt')) is str and not state['StartedAt'].startswith('0001-01-01'))
        require(execution['succeeded'] is True and execution['exit_code'] == 0 and execution['OOMKilled'] is False, 'successful original actual cost container')
        require(execution['owner'] == request['owner'] and execution['name'] == 't3v-' + request['owner'][:12] + '-' + opts.label
            and execution['effective_config']['Config']['Entrypoint'] == ['/usr/local/bin/python']
            and execution['effective_config']['Config']['Cmd'] == expected_cmd, 'raw actual worker/command identity')
        raw.execution(execution, image, 'cost')
        require(all(command['per_log_file_hard_bytes'] == LOG_CAP for command in execution['commands']),
            'all original Docker commands exact diagnostic256MiB raw log caps')
        row['raw_command_audit'] = {'passed': True, 'frozen_base_auditor': request['saved_graph_helper_pins']['saved_base_v1.py'],
            'command_count': len(execution['commands']), 'metadata_commands': len(meta['commands']),
            'daemon_intervals': raw.intervals, 'all_full_stdout_stderr_pins_verified': True,
            'resource_lifecycle_owned_identity_verified': True, 'rankable': False, 'timing_included': False}
        roster = roster_from_execution(item, execution, output)
        row['scenario_mapping'] = roster
        row['reference_checks'] = public.verify_outputs(Path(request['reference_root']) / item['unit'], output, item)
        row['developer_verifier'] = linux.gate(args, Path(request['reference_root']) / item['unit'], output, folder)
        gate = row['developer_verifier']
        raw.command(gate['execution'])
        require(row['reference_checks']['passed'] is True and gate['admissible'] is True and gate['status'] == 'completed'
            and set(gate['verdict']['gate_results']) == {'g0_integrity', 'g1_schema', 'g2_cutoff_resource', 'g3_domain_semantics'}
            and all(v['passed'] is True for v in gate['verdict']['gate_results'].values()), 'all original reference outputs and4officialgates')
        row['parsed'] = parse_cost_stdout(execution, folder, request['arm'], request['cost_mode'], roster,
            request['binding'], source_pin, contract, graph_audit=lambda graph: GraphAudit().audit(graph))
        row['market_executed_by_this_worker'] = len(row['parsed']['states']) == len(roster)
        row['actual_output_directory_bytes'] = sum(v['bytes'] for v in inventory(output).values())
        require(row['actual_output_directory_bytes'] <= 256 * 1024**2, 'official output directory256MiBcap')
        row['passed'] = True
    except BaseException as error:
        row['failure'] = {'type': type(error).__name__, 'message': str(error)}
        original_error = sys.exc_info()
        try:
            if (folder / 'PARSE_RESULT.json').is_file():
                row['parsed'] = read(folder / 'PARSE_RESULT.json')
        except BaseException as parse_receipt_error:
            row['parse_receipt_error'] = {'type': type(parse_receipt_error).__name__, 'message': str(parse_receipt_error)}
    finally:
        linux.DockerCommands = original_class
        try:
            write(folder / 'RUN_RESULT.json', row)
            write(evidence / 'worker-results' / (opts.label + '.json'), row)
        except BaseException:
            if original_error is None:
                raise
    if original_error is not None:
        raise original_error[1].with_traceback(original_error[2])


if __name__ == '__main__':
    main()
