"""Source-only AST schema check across host and container Python versions.

Execute only the diagnostic canonical encoder extracted from its source AST.
Never import, compile or invoke participant code. This is source-only evidence.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise ValueError(message)


def helper(path):
    parsed = ast.parse(path.read_bytes())
    nodes = [n for n in parsed.body if isinstance(n, ast.FunctionDef)
             and n.name == 'stable_simulate_AST_sha256']
    require(len(nodes) == 1, 'one canonical diagnostic helper')
    namespace = {'ast': ast, 'hashlib': hashlib, 'json': json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'inert-AST-encoder', 'exec'), namespace)
    return nodes[0], namespace['stable_simulate_AST_sha256']


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'fresh source-check report')
    left, encode = helper(HERE/'parser.py')
    right, overlay_encode = helper(HERE/'overlay/cost_entry_draft_v1.py')
    require(ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False),
            'both local diagnostic helpers identical')
    rows = []
    expected = {
        'classic_native_kernels_v1': ('88050802ab13e44cf5d193bb127a3cd98d4c89929b494491338e42f387fa9c17',
                                     '09467ca686a1bc95e89c5fc330b9383485ca6f34ec1f548b91dd41d776094fe9'),
        'classic_build_expectations_v1': ('7218ecf981fa7002865e862df9047e71a5915020962bff945329da79bb81c75c',
                                         '4305beb3a8f890809daddf539eeb8d41c50339365e1cfecfb709e972658ced8b')}
    for arm, (source_sha, canonical_sha) in expected.items():
        source = (args.sources/arm/'production_cli.py').read_bytes()
        require(hashlib.sha256(source).hexdigest() == source_sha, 'actual original source bytes')
        functions = [n for n in ast.parse(source).body
                     if isinstance(n, ast.FunctionDef) and n.name == 'simulate']
        require(len(functions) == 1, 'one real simulate AST')
        original = functions[0]
        require(encode(original) == overlay_encode(original) == canonical_sha,
                'cross-version fixed canonical digest')
        changed = copy.deepcopy(original)
        changed.args.args[0].arg = 'changed_argument'
        require(encode(changed) != canonical_sha, 'argument semantic mutation discriminated')
        changed = copy.deepcopy(original)
        if 'type_params' not in changed._fields:
            changed._fields = (*changed._fields, 'type_params')
        changed.type_params = []
        require(encode(changed) == canonical_sha, 'empty new representation stable')
        changed.type_params = [ast.Name(id='T', ctx=ast.Load())]
        try:
            encode(changed)
        except ValueError:
            pass
        else:
            raise ValueError('nonempty new business AST field accepted')
        changed = copy.deepcopy(original)
        changed._fields = (*changed._fields, 'future_unknown')
        changed.future_unknown = []
        try:
            encode(changed)
        except ValueError:
            pass
        else:
            raise ValueError('unknown AST field accepted')
        changed = copy.deepcopy(original)
        changed._fields = tuple(field for field in changed._fields if field != 'returns')
        try:
            encode(changed)
        except ValueError:
            pass
        else:
            raise ValueError('missing frozen AST field accepted')
        changed = copy.deepcopy(original)
        target = next(n for n in ast.walk(changed) if isinstance(n, ast.Constant) and type(n.value) is str)
        target.value += 'semantic_mutation'
        require(encode(changed) != canonical_sha, 'string semantic mutation discriminated')
        changed = copy.deepcopy(original)
        target = next(n for n in ast.walk(changed) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
        target.func.id += '_semantic_mutation'
        require(encode(changed) != canonical_sha, 'call target mutation discriminated')
        changed = copy.deepcopy(original)
        target = next(n for n in ast.walk(changed) if isinstance(n, ast.Constant) and type(n.value) is float)
        target.value += 0.125
        require(encode(changed) != canonical_sha, 'float semantic mutation discriminated')
        for invalid in (float('nan'), float('inf'), float('-inf')):
            target.value = invalid
            try:
                encode(changed)
            except ValueError:
                pass
            else:
                raise ValueError('nonfinite AST float accepted')
        rows.append({'arm': arm, 'source_sha256': source_sha,
                     'canonical_AST_sha256': canonical_sha, 'source_checks': 12})
    report = {'schema': 't3-r3-canonical-AST-version-source-check-v1',
              'python': sys.version, 'rows': rows, 'source_scope_passed': True,
              'participant_imported': False, 'participant_compiled': False,
              'simulation_executed': False, 'native_compiled': False,
              'Linux_runtime_passed': False, 'dispatch_allowed': False}
    with args.out.open('x') as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'python_version': sys.version.split()[0], 'source_checks': 24,
                      'two_real_source_canonical_digests_equal': True, 'participant_executed': False}))


if __name__ == '__main__':
    main()
