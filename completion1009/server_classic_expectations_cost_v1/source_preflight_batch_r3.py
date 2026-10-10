"""Saved official roster and exact source-delta checks; never launch participant."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
OLD = HERE / 'read_only/driver_before_batch_repair_r1.py'
PLAN = HERE / 'workflow_source_v1/bound_data/ORIGINAL_REFERENCE_PLAN.json'
OLD_PREDICATE = b"type(item['subs']) is list and 1 <= len(item['subs']) <= 5"
NEW_PREDICATE = b"type(item['subs']) is list and len(item['subs']) >= 1"


def main():
    rows = []
    def check(name, call, reject=False):
        try:
            call()
            passed = not reject
        except (ValueError, KeyError, TypeError):
            passed = reject
        rows.append({'case': name, 'passed': passed, 'expected_reject': reject})
    def require(ok):
        if not ok:
            raise ValueError('preflight condition failed')
    spec = importlib.util.spec_from_file_location('batch_r2_inert_driver', HERE / 'driver.py')
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    plan = driver.read(PLAN)
    check('actual_pinned_full71_reference_plan', lambda: require(driver.pin(PLAN) == {
        'bytes': 103740, 'sha256': '4ed54fc6ef706b614f221a7af6b3f09a7d21c490d54260e2d75fe2a31607ca68'}))
    check('all71_95markets_190references', lambda: require(len(plan['units']) == 71
        and sum(1 if u['shape'] == 'single' else len(u['subs']) for u in plan['units']) == 95
        and sum(len(u['reference_frames']) for u in plan['units']) == 190))
    batches = {u['unit']: len(u['subs']) for u in plan['units'] if u['shape'] == 'batch'}
    check('all_six_real_batch_variants', lambda: require(batches == {
        't3-gbatch-dense-3': 3, 't3-gbatch-hetero-mix': 5, 't3-gbatch-homog-4': 4,
        't3-gbatch-homog-8': 8, 't3-gbatch-many-6': 6, 't3-gbatch-varsize': 4}))
    for row in plan['units']:
        check('accept_actual_' + row['unit'], lambda row=row: driver.normalize_unit(row))
    byunit = {u['unit']: u for u in plan['units']}
    selected = [byunit[u] for u in driver.UNITS]
    check('selected6_units_still10_markets_max5', lambda: require(len(selected) == 6
        and sum(1 if u['shape'] == 'single' else len(u['subs']) for u in selected) == 10
        and max(1 if u['shape'] == 'single' else len(u['subs']) for u in selected) == 5))
    batch = byunit['t3-gbatch-homog-8']
    bad = copy.deepcopy(batch); bad['subs'] = []
    check('reject_empty_batch', lambda: driver.normalize_unit(bad), True)
    bad_paths = copy.deepcopy(batch); bad_paths['scenario_paths'].pop()
    check('reject_missing_scenario_path', lambda: driver.normalize_unit(bad_paths), True)
    bad_frames = copy.deepcopy(batch); bad_frames['reference_frames'].pop()
    check('reject_missing_reference_frame', lambda: driver.normalize_unit(bad_frames), True)
    bad_dup = copy.deepcopy(batch); bad_dup['subs'][1] = copy.deepcopy(bad_dup['subs'][0])
    check('reject_duplicate_sub', lambda: driver.normalize_unit(bad_dup), True)
    bad_map = copy.deepcopy(batch); bad_map['subs'][0]['scenario_file'] = '../escape.json'
    check('reject_parent_sub_mapping', lambda: driver.normalize_unit(bad_map), True)
    bad_sha = copy.deepcopy(batch); bad_sha['input_sha256'][next(iter(bad_sha['input_sha256']))] = 'x' * 64
    check('reject_input_sha_not_hex', lambda: driver.normalize_unit(bad_sha), True)
    bad_shape = copy.deepcopy(batch); bad_shape['shape'] = 'single'
    check('reject_batch_as_single', lambda: driver.normalize_unit(bad_shape), True)
    original = OLD.read_bytes()
    check('exact_original_reviewed_driver_pin', lambda: require(driver.pin(OLD) == {
        'bytes': 46282, 'sha256': 'c9fb7fa76ac017715c386b2f3d452e9df22acdcf75d7853637a7824d538208cf'}))
    check('only_driver_predicate_changes', lambda: require(original.count(OLD_PREDICATE) == 1
        and (HERE / 'driver.py').read_bytes() == original.replace(OLD_PREDICATE, NEW_PREDICATE)))
    tree = ast.parse(original)
    original_normalize = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'normalize_unit')
    env = {'require': driver.require, 'PurePosixPath': driver.PurePosixPath, 're': driver.re}
    exec(compile(ast.Module(body=[original_normalize], type_ignores=[]), '<original normalize source>', 'exec'), env)
    for name in ('t3-gbatch-homog-8', 't3-gbatch-many-6'):
        check('old_exact_source_reproduces_false_reject_' + name,
            lambda name=name: env['normalize_unit'](byunit[name]), True)
    # Execute the actual saved-auditor binding block without running its other
    # stages or loading participant/native code. Real old review is unchanged.
    auditor = HERE / 'read_only/cost_saved_auditor_v1/audit_cost_saved_v1.py'
    source = ast.parse(auditor.read_bytes())
    source_method = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'Audit')
    source_method = next(n for n in source_method.body if isinstance(n, ast.FunctionDef) and n.name == 'source')
    start = next(i for i, n in enumerate(source_method.body) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'original_driver' for t in n.targets))
    end = next(i for i, n in enumerate(source_method.body[start:], start) if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'remote' for t in n.targets))
    helper_node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_AST_delta_r3')
    helper_code = compile(ast.Module(body=[helper_node], type_ignores=[]), '<actual canonical delta verifier>', 'exec')
    binding_code = compile(ast.Module(body=source_method.body[start:end], type_ignores=[]), '<actual auditor binding block>', 'exec')
    reviewed = driver.read(HERE / 'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json')
    check('complete_original_review_sha', lambda: require(driver.pin(HERE / 'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json')['sha256']
        == '780aa8fafaf2980a381e5dc63c0766aa6426702ba170156893d165eccab363a7'))
    with tempfile.TemporaryDirectory(prefix='t3-batch-r2-inert-') as tmp:
        carried = Path(tmp); (carried / 'read_only').mkdir(); (carried / 'overlay').mkdir()
        for name in ('driver.py', 'worker.py', 'parser.py', 'read_only/driver_before_batch_repair_r1.py', 'read_only/parser_before_AST_repair_r2.py', 'read_only/worker_before_AST_repair_r2.py', 'read_only/overlay_before_AST_repair_r2.py', 'overlay/cost_entry_draft_v1.py', 'canonical_AST_insertion_r3.txt'):
            (carried / name).write_bytes((HERE / name).read_bytes())
        def binding():
            env = {'carried': carried, 'reviewed': reviewed, 'pin': driver.pin, 'require': driver.require}
            exec(helper_code, env)
            exec(binding_code, env)
        check('auditor_accepts_original_review_plus_batch_and_canonical_delta', binding)
        for name in ('driver.py', 'worker.py', 'parser.py', 'read_only/driver_before_batch_repair_r1.py', 'read_only/parser_before_AST_repair_r2.py', 'read_only/worker_before_AST_repair_r2.py', 'read_only/overlay_before_AST_repair_r2.py', 'overlay/cost_entry_draft_v1.py', 'canonical_AST_insertion_r3.txt'):
            path = carried / name; data = path.read_bytes(); path.write_bytes(data + b'\n# unauthorized mutation\n')
            check('auditor_rejects_mutation_' + name, binding, True)
            path.write_bytes(data)
        driver_path = carried / 'driver.py'
        repaired = driver_path.read_bytes()
        driver_path.write_bytes(original)
        check('auditor_rejects_unrepaired_driver', binding, True)
        driver_path.write_bytes(repaired.replace(b">= 1", b">= 0", 1))
        check('auditor_rejects_same_length_semantic_mutation', binding, True)
        driver_path.write_bytes(repaired)
        check('auditor_accepts_after_exact_restoration', binding)
    report = {'schema': 't3-batch-r3-actual-roster-and-canonical-binding-source-preflight-v1', 'cases': rows,
        'case_count': len(rows), 'all_source_checks_passed': all(r['passed'] for r in rows),
        'batches': batches, 'source_pins': {n: driver.pin(HERE/n) for n in
            ('driver.py', 'read_only/driver_before_batch_repair_r1.py', 'read_only/cost_saved_auditor_v1/audit_cost_saved_v1.py')},
        'participant_imported': False, 'market_executed': False, 'native_compiled': False,
        'Docker_executed': False, 'process_launched': False, 'independent_review': False,
        'actual_cost_artifact_accepted': False, 'Linux_passed': False}
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report['all_source_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
