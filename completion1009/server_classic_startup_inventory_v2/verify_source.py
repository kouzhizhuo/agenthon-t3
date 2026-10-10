"""Frozen source hashes and inert AST verification; no participant execution."""
import ast
from common import HERE, read, verify_sources


def main():
    verify_sources()
    for name in read(HERE / 'SOURCE_PINS.json')['files']:
        if name.endswith('.py'):
            data = (HERE / name).read_bytes()
            ast.parse(data, filename=name)
            compile(data, name, 'exec', dont_inherit=True)
    print('STARTUP-ONLY SOURCES/HOST2 HASHES/AST PASS; no participant import or execution')


if __name__ == '__main__':
    main()
