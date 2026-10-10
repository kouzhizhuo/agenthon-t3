"""One fixed Linux startup diagnostic with the unchanged bounded host runner."""
import argparse
from pathlib import Path
import platform
import signal
import sys

from common import HERE, LOG_CAP, PREFIX, pin, read, require, verify_sources, write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'actual Linux amd64 startup diagnostic only; no local execution')
    lock = verify_sources()
    args.evidence = args.evidence.resolve()
    request = read(args.request)
    require(request['input_path'] == str(HERE / 'startupinventory.py'), 'one exact reviewed diagnostic input source')
    sys.path.insert(0, str(HERE / 'host'))
    import verify_linux as linux
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, linux.cancellation)
    image = request['image_id']
    args.docker, args.gate_python, args.log_cap_bytes, args.timeout = 'docker', None, LOG_CAP, 600

    class Strict(linux.DockerCommands):
        def call(self, arguments, label, seconds=30, cleanup=False):
            if arguments and arguments[0] == 'create':
                position = arguments.index(image)
                extra = ['--env', 'PYTHONHASHSEED=0', '--ulimit', 'nproc=256:256',
                    '--ulimit', 'fsize=268435456:268435456', '--entrypoint', '/usr/local/bin/python']
                # Preserve the original runner's resource/create lifecycle.
                # Only replace its business CLI with the one fixed readonly
                # startup source already staged as /input/scenario.json.
                arguments = [arguments[0], *extra, *arguments[1:position + 1], '-B', '/input/scenario.json']
            return super().call(arguments, label, seconds, cleanup)

        def inspect(self, name, cleanup=False, seconds=30):
            value, record = super().inspect(name, cleanup, seconds)
            if value is not None and not cleanup:
                config, host = value['Config'], value['HostConfig']
                require(config['Entrypoint'] == ['/usr/local/bin/python'] and config['Cmd'] == ['-B', '/input/scenario.json'], 'fixed stock startup command only')
                require({row['Name']: (row['Soft'], row['Hard']) for row in host['Ulimits']}
                    == {'nofile': (1024, 1024), 'nproc': (256, 256), 'fsize': (268435456, 268435456)}, 'original finite limits')
                mounts = [row for row in value['Mounts'] if row['Type'] == 'bind']
                require(len(mounts) == 2 and {row['Destination']: row['RW'] for row in mounts} == {'/input': False, '/output': True}, 'inputRO/outputRW-only original mounts')
                environment = dict(row.split('=', 1) for row in config.get('Env', []) if '=' in row)
                require(all(environment.get(key) == expected for key, expected in {
                    'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'NUMEXPR_NUM_THREADS': '1',
                    'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'}.items()), 'original deterministic scientific environment')
            return value, record

    linux.DockerCommands = Strict
    item = {'shape': 'single', 'scenario_paths': [request['input_path']]}
    folder = Path(request['folder'])
    execution, output = linux.run_container(args, image, 'original', item, folder, request['owner'], 'stock-startup')
    row = {'schema': 't3-fixed-stock-startup-worker-v2', 'execution': execution, 'output': str(output),
        'passed': False, 'rankable': False, 'timing_included': False, 'market_executed': False,
        'native_compiled': False, 'participant_imported': False}
    try:
        require(execution['succeeded'] is True and execution['exit_code'] == 0 and execution['OOMKilled'] is False
            and execution['cleanup']['settled'] is execution['cleanup']['removed'] is execution['cleanup']['final_absent'] is True
            and execution['cleanup']['errors'] == [], 'successful exact settled/removed/absent owned startup container')
        staged = execution['staged_inputs']
        require(len(staged) == 1 and pin(Path(staged[0]['staged'])) == lock['inventory_source']
            and staged[0]['sha256'] == lock['inventory_source']['sha256'], 'readonly staged inventory source exact')
        require(not list(output.iterdir()), 'startup diagnostic must emit no output files')
        stream = Path(execution['attach']['stdout']['path'])
        require(stream.stat().st_size < LOG_CAP, 'complete finite diagnostic stdout')
        lines = stream.read_bytes().splitlines()
        require(len(lines) == 1 and lines[0].startswith(PREFIX.encode()) and len(lines[0]) <= 8 * 1024**2, 'one complete bounded startup JSON record')
        import json
        observed = json.loads(lines[0][len(PREFIX):])
        require(observed['schema'] == 't3-fixed-system-startup-inventory-v3'
            and all(observed[key] is False for key in ('participant_modules_loaded', 'participant_imported_by_diagnostic',
                'market_executed', 'environment_values_emitted', 'user_files_read', 'native_compiled', 'timing_included', 'rankable')),
            'fixed readonly startup source boundary required')
        require(observed['python']['executable'] == '/usr/local/bin/python' and observed['python']['version'] == [3, 11, 17]
            and observed['python']['implementation'] == 'cpython' and observed['python']['prefix'] == observed['python']['base_prefix'] == '/usr/local', 'published stock Python exact ABI')
        require(observed['setprofile_absent'] is observed['settrace_absent'] is True
            and observed['source_byte_ledger']['unique_source_cap'] == 4 * 1024**2
            and observed['source_byte_ledger']['unique_file_bytes'] <= 4 * 1024**2, 'unhooked finite startup inventory')
        ledger = observed['source_byte_ledger']
        files = ledger['files']
        require(len(files) == ledger['unique_files'] == len({value['path'] for value in files})
            and sum(value.get('bytes', 0) for value in files) == ledger['unique_file_bytes']
            and ledger['requested_source_bytes'] >= ledger['unique_file_bytes']
            and ledger['file_requests'] >= ledger['unique_files'], 'complete actual bounded source-byte ledger')
        for value in files:
            path = Path(value['path'])
            require(path.is_absolute() and path.is_relative_to(Path('/usr/local/lib/python3.11')) and '..' not in path.parts,
                'fixed system-only ledger source paths')
            if value['exists']:
                require(type(value['bytes']) is int and 0 <= value['bytes'] <= 1024**2
                    and type(value['sha256']) is str and len(value['sha256']) == 64, 'finite pinned actual system startup source')
        require(type(observed['sys_meta_path']) is list and len(observed['sys_meta_path']) <= 32
            and [value['position'] for value in observed['sys_meta_path']] == list(range(len(observed['sys_meta_path']))), 'complete ordered startup finder descriptors')
        row.update(passed=True, startup_inventory=observed, actual_stock_image_id=image,
            startup_source=lock['inventory_source'], FIFO_domain_certified=False, startup_pins_updated=False)
    except BaseException as error:
        row['failure'] = {'type': type(error).__name__, 'message': str(error)}
    write(folder / 'RUN_RESULT.json', row)
    write(args.result, row)
    require(row['passed'], 'complete stock startup diagnostic failed')


if __name__ == '__main__':
    main()
