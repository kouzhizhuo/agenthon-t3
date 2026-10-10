"""Saved-only resource and exact stage-bound contract checks; no market execution."""
import argparse
import ast
import copy
import json
from pathlib import Path

from audit_saved_delivery_v1 import Audit, HERE
from saved_base_v1 import pin, read, require

ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'fresh independent resource/stage receipt')
    v7_root = ROOT / 'server_classic_structural_v3/screen_result_v7/extracted'
    v1_root = ROOT / 'server_classic_expectations_delivery_v1/result_v1/extracted'
    roots = {'saved_v7': v7_root, 'actual_failed_v1': v1_root}
    counts = {}
    for label, root in roots.items():
        evidence = root / 'evidence'
        if label == 'saved_v7':
            rows = (read(evidence / 'RAW_RESULTS.json') + read(evidence / 'DIAGNOSTIC_RESULTS.json')
                + list(read(evidence / 'CONTROLS.json').values()))
        else:
            rows = [read(path) for path in sorted((evidence / 'worker-results').glob('*.json'))
                if not path.name.startswith('._')]
        executions = [row['execution'] for row in rows if 'execution' in row]
        for execution in executions:
            host = execution['effective_config']['HostConfig']
            require(host['Privileged'] is False and host['CapAdd'] in (None, [])
                and all(mount['Type'] in ('bind', 'tmpfs') for mount in execution['effective_config']['Mounts']),
                'complete saved resource compatibility before narrower requirements')
        counts[label] = len(executions)
    require(counts == {'saved_v7': 345, 'actual_failed_v1': 105}, 'exact saved raw execution resource roster')

    audit = Audit(argparse.Namespace(artifact=v1_root, expected_head='6a59542ad3ca5841a63522d4bfe3d146ccd0c1dc',
        remote_evidence_marker='expectations-delivery-evidence/'))
    audit.image = read(audit.evidence / 'BUILD_READY.json')['image_id']
    items = {item['unit']: item for item in read(audit.evidence / 'REFERENCE_PLAN.json')['units']}
    diagnostic = read(audit.evidence / 'worker-results/diagnostic-00-parent.json')
    ordinary = read(next(path for path in sorted((audit.evidence / 'raw-progress').glob('*.json'))
        if not path.name.startswith('._')))
    audit.execution(diagnostic['execution'], audit.image, 'diagnostic')
    audit.execution(ordinary['execution'], audit.image, 'one')
    audit.output(diagnostic, items[diagnostic['unit']], diagnostic=True)
    audit.output(ordinary, items[ordinary['unit']])
    require(diagnostic['developer_verifier']['execution']['per_log_file_hard_bytes'] == 256 * 1024**2
        and ordinary['developer_verifier']['execution']['per_log_file_hard_bytes'] == 16 * 1024**2,
        'actual distinct gate log caps retained exactly')

    negatives = []
    def rejected(name, function):
        try:
            function()
        except (ValueError, KeyError, IndexError, TypeError) as error:
            negatives.append({'case': name, 'rejected': True, 'reason': str(error)})
        else:
            raise ValueError('corrupt independent contract accepted: ' + name)

    for name, change in (
        ('privileged_true', lambda row: row['effective_config']['HostConfig'].__setitem__('Privileged', True)),
        ('cap_add_SYS_ADMIN', lambda row: row['effective_config']['HostConfig'].__setitem__('CapAdd', ['SYS_ADMIN'])),
        ('persistent_volume_mount', lambda row: row['effective_config']['Mounts'].append(
            {'Type': 'volume', 'Destination': '/external', 'RW': True})),
    ):
        bad = copy.deepcopy(ordinary['execution'])
        change(bad)
        rejected(name, lambda bad=bad: audit.execution(bad, audit.image, 'one'))
    for name, row, cap, route in (
        ('diagnostic_gate_cap_reduced_to16MiB', diagnostic, 16 * 1024**2, True),
        ('ordinary_gate_cap_increased_to256MiB', ordinary, 256 * 1024**2, False),
    ):
        bad = copy.deepcopy(row)
        bad['developer_verifier']['execution']['per_log_file_hard_bytes'] = cap
        rejected(name, lambda bad=bad, route=route: audit.output(bad, items[bad['unit']], diagnostic=route))
    rejected('diagnostic_row_with_ordinary_route', lambda: audit.output(diagnostic, items[diagnostic['unit']]))
    rejected('ordinary_row_with_diagnostic_route', lambda: audit.output(ordinary, items[ordinary['unit']], diagnostic=True))

    # Evaluate only the exact source-copy argv equality expression from the
    # current auditor on actual saved rows. This is not a lifecycle audit.
    tree = ast.parse((HERE / 'audit_saved_delivery_v1.py').read_bytes())
    method = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Audit')
    method = next(node for node in method.body if isinstance(node, ast.FunctionDef) and node.name == 'copy_lifecycle')
    equality = next(node for node in ast.walk(method) if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Subscript) and isinstance(node.left.value, ast.Name)
        and node.left.value.id == 'first' and isinstance(node.comparators[0], ast.List))
    expression = compile(ast.Expression(equality), '<saved source-copy argv comparison>', 'eval')
    sourcecopy_checks = []
    for label, path, expected in (
        ('saved_v7_exact_copy', v7_root / 'evidence/installed-source-copy.json', True),
        ('actual_v1_rejected_aftercopy_with_worker_flags', v1_root / 'evidence/installed-after-copy.json', False),
    ):
        row = read(path)
        actual = eval(expression, {'__builtins__': {}}, {'first': row['commands'][0],
            'cleanup': row['cleanup'], 'self': audit})
        # The v7 image is intentionally distinct; bind its own immutable image
        # for this exact argv expression, then restore the v1 target image.
        if label == 'saved_v7_exact_copy':
            old_image = audit.image
            audit.image = row['commands'][0]['argv'][-1]
            actual = eval(expression, {'__builtins__': {}}, {'first': row['commands'][0], 'cleanup': row['cleanup'], 'self': audit})
            audit.image = old_image
        require(actual is expected, 'exact actual saved source-copy argv control')
        sourcecopy_checks.append({'case': label, 'source': str(path.relative_to(ROOT)), 'source_pin': pin(path),
            'exact_argv_matched': actual, 'full_lifecycle_certified': False})

    report = {'schema': 't3-independent-resource-stage-saved-preflight-v2',
        'status': 'PASS_SOURCE_AND_SAVED_CONTRACT_ONLY', 'source_files': {name: pin(HERE / name) for name in
            ('audit_saved_delivery_v1.py', 'saved_base_v1.py', 'graph_saved_v1.py', 'independent_resource_stage_preflight_v2.py')},
        'complete_saved_raw_resource_compatibility_counts': counts,
        'positive_actual_failed_v1_saved_cases': ['ordinary_resources', 'diagnostic_resources', 'ordinary_gate16MiB', 'diagnostic_gate256MiB'],
        'negatives': negatives, 'sourcecopy_exact_argv_expression_checks': sourcecopy_checks,
        'sourcecopy_file_cap_bytes': 64 * 1024**2, 'sourcecopy_log_cap_bytes': 16 * 1024**2,
        'partial_failed_v1_samples_checked': True, 'full_delivery_artifact_audit': False,
        'participant_imported': False, 'native_compiled': False, 'market_executed': False,
        'harness_changed': False, 'official_submission_eligible': False, 'target_achieved': False}
    with args.out.open('x') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'saved_resource_rows': sum(counts.values()),
        'negative_cases': len(negatives), 'sourcecopy_expression_cases': len(sourcecopy_checks)}), flush=True)


if __name__ == '__main__':
    main()
