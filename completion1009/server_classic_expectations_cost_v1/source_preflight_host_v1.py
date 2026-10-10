"""Inert host-driver controls only. No participant imports or process launch."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'driver.py'


def main():
    tree = ast.parse(SOURCE.read_bytes())
    allowed = {'require', 'validate_base_document', 'validate_overlay_metadata', 'check_overlay_inventory',
        'frozen_dockerfile', 'timestamp_ns', 'serial_intervals', 'normalize_unit'}
    constants = {'PUBLIC_ENTRY', 'PUBLIC_RE', 'OLD_PUBLIC', 'BASE_RUN', 'BASE_HEAD', 'BASE_WORKFLOW', 'BASE_PINS_SHA'}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in allowed:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id in constants for n in node.targets):
            nodes.append(node)
    namespace = {'re': re, 'datetime': __import__('datetime'), 'PurePosixPath': __import__('pathlib').PurePosixPath}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    results = []
    def case(name, fn, rejected=False):
        try:
            fn()
            okay = not rejected
        except ValueError:
            okay = rejected
        results.append({'case': name, 'passed': okay, 'expected_reject': rejected})
    image = 'sha256:' + '2' * 64
    digest = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:' + '3' * 64
    document = {'schema': 't3-cost-actual-base-authority-v1', 'ready_for_linux': True,
        'run_id': 38072276259, 'run_attempt': 1, 'head': namespace['BASE_HEAD'],
        'workflow': namespace['BASE_WORKFLOW'], 'sourcepins_sha256': namespace['BASE_PINS_SHA'],
        'base_image_id': image, 'public_digest': digest}
    binding = {'schema': 't3-expectations-cost-image-binding-v1', 'ready_for_linux': True,
        'runtime_changed': False, 'base_publication_authority': True, 'publication_authority': False,
        'rankable': False, 'actual_final_image_id': image, 'actual_final_public_digest': digest}
    validate = namespace['validate_base_document']
    case('typed_actual_base_schema_positive_only', lambda: validate(document, binding))
    for key, value in [('ready_for_linux', False), ('schema', 'source-only'), ('run_id', 38066939668),
        ('run_attempt', True), ('head', '0' * 40), ('sourcepins_sha256', '0' * 64), ('run_attempt', 2), ('workflow', 'v1.yml')]:
        changed = dict(document, **{key: value})
        case('base_' + key, lambda changed=changed: validate(changed, binding), True)
    for key, value in [('ready_for_linux', 1), ('runtime_changed', 0), ('base_publication_authority', False),
        ('publication_authority', True), ('rankable', True), ('actual_final_image_id', None),
        ('actual_final_image_id', 'sha256:' + '4' * 64), ('actual_final_public_digest', namespace['OLD_PUBLIC']),
        ('actual_final_public_digest', 'ghcr.io/kouzhizhuo/agenthon-t3-classic:latest'), ('schema', 'forged-ready')]:
        changed = dict(binding, **{key: value})
        case('binding_' + key + '_' + str(value)[:12], lambda changed=changed: validate(document, changed), True)
    base = {'Id': image, 'Os': 'linux', 'Architecture': 'amd64', 'RepoDigests': [digest], 'Size': 100,
        'Config': {'Entrypoint': namespace['PUBLIC_ENTRY'], 'Cmd': [], 'User': '65534:65534', 'WorkingDir': '/output',
            'Volumes': None, 'OnBuild': None, 'Env': ['A=B'], 'Labels': {'license': 'BSD-3-Clause'}},
        'RootFS': {'Type': 'layers', 'Layers': ['sha256:' + '5' * 64]}}
    overlay = copy.deepcopy(base)
    overlay.update(Id='sha256:' + '6' * 64, Size=200)
    overlay['RootFS']['Layers'].append('sha256:' + '7' * 64)
    overlaycheck = namespace['validate_overlay_metadata']
    case('additive_config_same_one_layer', lambda: overlaycheck(base, overlay, digest))
    for name, mutate in [('sameid', lambda o: o.update(Id=image)), ('user', lambda o: o['Config'].update(User='0:0')),
        ('entry', lambda o: o['Config'].update(Entrypoint=['/bin/sh'])), ('native_extra_layers', lambda o: o['RootFS']['Layers'].append('8')),
        ('missing_rootprefix', lambda o: o['RootFS']['Layers'].__setitem__(0, '9')), ('wrong_platform', lambda o: o.update(Architecture='arm64'))]:
        changed = copy.deepcopy(overlay)
        mutate(changed)
        case('overlay_' + name, lambda changed=changed: overlaycheck(base, changed, digest), True)
    changed = copy.deepcopy(base); changed['Config']['OnBuild'] = ['RUN pip install x']
    case('base_onbuild_rejected', lambda: overlaycheck(changed, overlay, digest), True)
    original = {'native': {'a.py': {'bytes': 1, 'sha256': '0'*64}}, 'harness': {'entry.py': {'bytes': 2, 'sha256': '1'*64}},
        'licenses': {'LICENSE': {'bytes': 3, 'sha256': '2'*64}}}
    addition = {'cost_entry_draft_v1.py': {'bytes': 4, 'sha256': '3'*64}, 'IMAGE_BINDING.json': {'bytes': 5, 'sha256': '4'*64}}
    actual = copy.deepcopy(original); actual['harness'].update({'cost-diagnostic-v1/' + n: p for n,p in addition.items()})
    check = namespace['check_overlay_inventory']
    case('two_exact_additive_files', lambda: check(original, actual, addition))
    for name, mutate in [('native', lambda d: d['native']['a.py'].update(sha256='f'*64)),
        ('license', lambda d: d['licenses']['LICENSE'].update(bytes=4)), ('harness', lambda d: d['harness']['entry.py'].update(bytes=4)),
        ('unknownoverlay', lambda d: d['harness'].update({'cost-diagnostic-v1/extra.py': {'bytes': 1, 'sha256': 'a'*64}}))]:
        changed = copy.deepcopy(actual); mutate(changed)
        case('inventory_' + name, lambda changed=changed: check(original, changed, addition), True)
    case('dockerfile_exact_onecopy', lambda: namespace['require'](namespace['frozen_dockerfile'](digest).splitlines() == [
        'FROM ' + digest, 'COPY --chown=0:0 --chmod=0444 overlay/ /opt/t3-classic-structural-v2/cost-diagnostic-v1/'], 'dockerfile'))
    execution = {'succeeded': True, 'exit_code': 0, 'OOMKilled': False,
        'cleanup': {'settled': True, 'removed': True, 'final_absent': True, 'errors': []},
        'name': 'owned-a', 'state': {'StartedAt': '2026-10-10T01:00:00.000000001Z', 'FinishedAt': '2026-10-10T01:00:01.000000001Z'}}
    second = copy.deepcopy(execution); second.update(name='owned-b'); second['state'] = {
        'StartedAt': '2026-10-10T01:00:02Z', 'FinishedAt': '2026-10-10T01:00:03Z'}
    case('positive_serial_intervals', lambda: namespace['serial_intervals']([{'execution': execution}, {'execution': second}]))
    second['state']['StartedAt'] = '2026-10-10T01:00:00.5Z'
    case('serial_overlap', lambda: namespace['serial_intervals']([{'execution': execution}, {'execution': second}]), True)
    case('serial_duplicate_name', lambda: namespace['serial_intervals']([{'execution': execution}, {'execution': execution}]), True)
    changed = copy.deepcopy(execution); changed['cleanup']['final_absent'] = False
    case('lifecycle_unremoved', lambda: namespace['serial_intervals']([{'execution': changed}]), True)
    # AST guardrails: no driver imports of specialized worker/controller or build natives.
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [n.name for v in ast.walk(tree)
        if isinstance(v, ast.Import) for n in v.names]
    case('no_participant_controller_worker_imports', lambda: namespace['require'](not any(n and any(token in n for token in (
        'controller', 'worker', 'dynamic_arena', 'production_cli', 'native_owner')) for n in imports), 'imports'))
    run_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_process')
    case('worker_leader_unreaped_pipe_anchor', lambda: namespace['require'](not any(isinstance(n, ast.Attribute) and n.attr == 'poll'
        for n in ast.walk(run_node)), 'poll reaps ownership anchor'))
    compile(SOURCE.read_bytes(), str(SOURCE), 'exec')
    report = {'schema': 't3-cost-host-inert-source-preflight-v1', 'source': {'bytes': SOURCE.stat().st_size,
        'sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest()}, 'case_count': len(results), 'cases': results,
        'all_passed': all(r['passed'] for r in results), 'independent_review': False, 'ready_for_linux': False,
        'participant_imported': False, 'participant_function_called': False, 'native_compiled': False,
        'Docker_executed': False, 'market_executed': False, 'process_launched': False}
    (HERE/'SOURCE_PREFLIGHT_HOST_v1.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n')
    print(json.dumps({'all_passed': report['all_passed'], 'case_count': len(results)}))
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
