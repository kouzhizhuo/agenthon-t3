"""Verify frozen harness bytes and compile syntax without participant imports."""
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
        if {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} != expected:
            raise ValueError('frozen structural harness changed: ' + name)
        if name.endswith('.py'):
            ast.parse(data, filename=str(path))
            compile(data, str(path), 'exec', dont_inherit=True)
    print('STRUCTURAL HARNESS SOURCE PINS AND AST/SYNTAX PASS; no participant import or execution')


if __name__ == '__main__':
    main()
