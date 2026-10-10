"""Freeze reviewed small harness bytes only; no remote or runtime operation."""
import ast

from common import HERE, pin, require, write

FILES = ('common.py', 'driver.py', 'worker.py', 'collect_artifact.py', 'verify_source.py', 'verify_remote_source.py',
    'prepare_source.py', 'freeze_source.py', 'README.md', 't3-classic-startup-inventory-v2.yml',
    'startupinventory.py', 'SOURCE_LOCK.json', 'host/verify_public.py', 'host/verify_linux.py')


def main():
    require(not (HERE / 'SOURCE_PINS.json').exists(), 'fresh source freeze only')
    pins = {}
    for name in FILES:
        path = HERE / name
        pins[name] = pin(path)
        if name.endswith('.py'):
            data = path.read_bytes()
            ast.parse(data, filename=name)
            compile(data, name, 'exec', dont_inherit=True)
    write(HERE / 'SOURCE_PINS.json', {'schema': 't3-fixed-stock-startup-frozen-harness-v2', 'files': pins,
        'source_only': True, 'participant_imported': False, 'native_compiled': False, 'market_executed': False,
        'remote_writes': False, 'workflow_dispatch': False})
    print('SMALL14FILE STARTUP SOURCE PINS/AST FROZEN; no execution/remote write')


if __name__ == '__main__':
    main()
