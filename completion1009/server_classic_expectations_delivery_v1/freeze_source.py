"""Freeze this independent source-only delivery; never run participant code."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ('README.md', 'COUNTED_PLAN.json', 'PUBLIC_OPTIONS_PURE_FIXTURE_v1.json', 'PARENT_SOURCE_LOCK.json', 'CANDIDATE_SOURCE_LOCK.json',
    'prepare.py', 'materialize.py', 'source_copy.py', 'verify_source.py', 'verify_remote_source.py',
    'freeze_source.py', 'construction.py', 'production_entry.py', 'diagnostic_entry.py', 'controls_entry.py',
    'delivery_entry.py', 'LICENSE-SUBMISSION', 'Dockerfile', 'driver.py', 'worker.py',
    't3-classic-expectations-delivery-v1.yml', 'DELIVERY_PAYLOAD_v3.tar.xz')


def main():
    destination = HERE / 'SOURCE_PINS.json'
    if destination.exists():
        raise ValueError('fresh source-only freeze required')
    files = {}
    for name in FILES:
        path = HERE / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('ordinary complete delivery source required')
        data = path.read_bytes()
        files[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if name.endswith('.py'):
            ast.parse(data, filename=name)
            compile(data, name, 'exec', dont_inherit=True)
    with destination.open('x') as stream:
        stream.write(json.dumps({'schema': 't3-classic-expectations-delivery-frozen-harness-v1',
            'files': files, 'source_only': True, 'participant_imported': False,
            'native_compiled': False, 'market_executed': False, 'remote_writes': False,
            'workflow_dispatch': False}, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print('DELIVERY SOURCE PINS AND AST/SYNTAX FROZEN; no participant or remote execution')


if __name__ == '__main__':
    main()
