"""Read source pins and compile syntax only; never import the participant."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    pins = json.loads((HERE / 'SOURCE_PINS.json').read_bytes())
    for name, expected in pins['files'].items():
        path = HERE / name
        data = path.read_bytes()
        actual = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if actual != expected:
            raise ValueError('actual reviewed harness source differs: ' + name)
        if name.endswith('.py'):
            ast.parse(data, filename=str(path))
            compile(data, str(path), 'exec')
    lock = json.loads((HERE / 'PARENT_SOURCE_LOCK.json').read_bytes())
    if lock['source_run_id'] != 38035913208 or lock['source_workflow_head'] != '93d5976dc37d3a175b0407f1c72fe8a5ab7aea6d':
        raise ValueError('exact delivery-source provenance required')
    print('CENSUS SOURCE PINS AND SYNTAX PASS; no participant import, native compile or market execution')


if __name__ == '__main__':
    main()
