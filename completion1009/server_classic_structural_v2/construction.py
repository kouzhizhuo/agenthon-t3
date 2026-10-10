"""One Linux image construction, each independent candidate built exactly once."""
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib

ROOT = Path('/opt/classic-native-kernels-v1')
ARMS = {'expectations': 'classic_build_expectations_v1', 'price_index': 'classic_price_index_v2'}


def inventory(root):
    return {path.relative_to(root).as_posix(): {'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(root.rglob('*'))
        if path.is_file() and not any(part.startswith('._') or part in ('__pycache__', '__MACOSX') for part in path.parts)}


def main():
    out = ROOT / 'structural-v2-construction'
    out.mkdir()
    report = {'schema': 't3-classic-structural-build-once-v2', 'all_passed': False,
        'participant_imported': False, 'market_executed': False, 'rankable': False,
        'construction_times_not_performance': True, 'commands': []}
    parent_runtime = ROOT / 'completion1009/candidates/classic_native_kernels_v1/runtime'
    try:
        for arm, directory in ARMS.items():
            candidate = ROOT / 'completion1009/candidates' / directory
            for name in ('schema_metadata_v1.json', 'schema_metadata_pin_v1.py'):
                destination = candidate / 'runtime' / name
                if destination.exists():
                    raise ValueError('candidate payload must omit generated schema metadata')
                destination.write_bytes((parent_runtime / name).read_bytes())
            commands = (('translation', [sys.executable, '-B', str(candidate / 'translate_native_preflight.py'),
                '--runtime', str(candidate / 'runtime'), '--out', str(candidate / 'translation')], 900),
                ('native-build', [sys.executable, '-B', str(candidate / 'build_native.py'),
                '--runtime', str(candidate / 'runtime'), '--out', str(candidate / 'build')], 1500))
            for label, command, timeout in commands:
                log = out / (arm + '-' + label + '.log')
                with log.open('xb') as stream:
                    try:
                        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
                        row = {'arm': arm, 'label': label, 'command': command,
                            'returncode': process.returncode, 'timed_out': False}
                    except BaseException as error:
                        row = {'arm': arm, 'label': label, 'command': command, 'returncode': None,
                            'timed_out': isinstance(error, subprocess.TimeoutExpired),
                            'failure': {'type': type(error).__name__, 'message': str(error)}}
                row['log'] = {'bytes': log.stat().st_size, 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
                report['commands'].append(row)
                if row['returncode'] != 0:
                    raise ValueError('actual one-time construction failed: ' + arm + '/' + label)
        report['all_passed'] = True
    except BaseException as error:
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['partial_artifacts'] = {arm: {name: inventory(ROOT / 'completion1009/candidates' / directory / name)
            for name in ('translation', 'build')} for arm, directory in ARMS.items()}
        report['ambient_flags'] = {name: os.environ.get(name, '') for name in ('CFLAGS', 'CPPFLAGS', 'LDFLAGS')}
        (out / 'CONSTRUCTION_RESULT.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    # Partial build files are data-carried into the final image for host rejection.


if __name__ == '__main__':
    main()
