"""Saved-schema and corrupt-data preflight; does not run a new delivery."""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path

from audit_saved_delivery_v1 import Audit, HERE
from graph_saved_v1 import GraphAudit
from saved_base_v1 import ARMS, UNITS, pin, read, require

ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'fresh preflight report')
    imports = set()
    allowed = {'argparse', 'ast', 'base64', 'calendar', 'collections', 'copy', 'datetime', 'gzip', 'hashlib', 'json', 'math',
        'pathlib', 're', 'statistics', 'struct', 'sys', 'time', 'zipfile', 'zlib', 'pyarrow.parquet',
        'graph_saved_v1', 'saved_base_v1', 'audit_saved_delivery_v1'}
    files = [HERE / name for name in ('audit_saved_delivery_v1.py', 'graph_saved_v1.py', 'saved_base_v1.py', 'preflight_saved_auditor_v1.py')]
    for file in files:
        tree = ast.parse(file.read_bytes())
        compile(file.read_bytes(), str(file), 'exec')
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
    require(imports.issubset(allowed), 'exact saved-data-only import roster')
    source = ROOT / 'server_classic_expectations_delivery_v1'
    source_pins = read(source / 'SOURCE_PINS.json')
    require(pin(source / 'SOURCE_PINS.json')['sha256'] == 'be23f8dd407cc4624ef41a02720243b00cd51503925813d085bab414dda2f5ce'
        and len(source_pins['files']) == 22 and all(pin(source / name) == value for name, value in source_pins['files'].items()), 'final22frozen harness sources unchanged')
    namespace = argparse.Namespace(artifact=ROOT / 'server_classic_structural_v3/screen_result_v7/extracted', expected_head='6a59542ad3ca5841a63522d4bfe3d146ccd0c1dc',
        remote_evidence_marker='structural-v2-evidence/')
    v7 = Audit(namespace)
    v7.image = read(v7.evidence / 'BUILD_READY.json')['image_id']
    saved_admission_units = tuple(item['unit'] for item in read(v7.evidence / 'REFERENCE_PLAN.json')['units'])
    v7.control_groups(saved_roster=('parent', 'expectations', 'price_index'), saved_admission_units=saved_admission_units)
    rows = read(v7.evidence / 'DIAGNOSTIC_RESULTS.json')
    graph_results = []
    for row in rows:
        if row['arm'] not in ARMS:
            continue
        v7.execution(row['execution'], v7.image, 'diagnostic')
        v7.diagnostic_stream(row)
        for record in row['state_receipts']:
            file = v7.path(record['path'])
            graph_results.append({'unit': row['unit'], 'arm': row['arm'], **pin(file), **GraphAudit().audit(read(file))})
    require(len(graph_results) == 20, '20actual saved v7 parent/expectations fullgraphs decoded')
    class Classic(Audit):
        def path(self, remote):
            require(type(remote) is str and remote.count('classic-delivery-v1-evidence/') == 1, 'exact old saved evidence marker')
            tail = remote.split('classic-delivery-v1-evidence/', 1)[1]
            require(not tail.startswith('/') and '..' not in Path(tail).parts, 'safe old saved path')
            return self.evidence / tail
    old = Classic(argparse.Namespace(artifact=ROOT / 'server_classic_delivery_v1/attempt2/downloaded_v1', expected_head='0' * 40))
    old.evidence = old.artifact / 'evidence'
    items = {item['unit']: item for item in read(old.evidence / 'REFERENCE_PLAN.json')['units']}
    ordinary = read(old.evidence / 'RAW_RESULTS.json')
    selected = [next(row for row in ordinary if row['unit'] == next(item['unit'] for item in items.values()
        if item['shape'] == 'batch' and len(item['subs']) == size)) for size in (3, 4, 5, 6, 8)]
    selected.append(next(row for row in ordinary if items[row['unit']]['shape'] == 'single'))
    for row in selected:
        old.output(row, items[row['unit']])
    output_negatives = []
    for name, mutate in (
        ('duplicate_trace_frame_omits_ledger', lambda row: row['reference_checks']['frames'].__setitem__(1, copy.deepcopy(row['reference_checks']['frames'][0]))),
        ('missing_staged_scenario', lambda row: row['execution']['staged_inputs'].pop()),
    ):
        bad = copy.deepcopy(selected[0])
        mutate(bad)
        try:
            old.output(bad, items[bad['unit']])
        except (ValueError, KeyError, IndexError) as error:
            output_negatives.append({'case': name, 'rejected': True, 'reason': str(error)})
        else:
            raise ValueError('corrupt output coverage accepted: ' + name)
    sample = read(v7.path(rows[0]['state_receipts'][0]['path']))
    def first_tag(graph, tag):
        stack = [graph]
        while stack:
            node = stack.pop()
            if type(node) is list and node:
                if node[0] == tag:
                    return node
                stack.extend(value for value in node if isinstance(value, list))
        raise ValueError('sample required tag missing')
    mutators = {
        'forward_alias_ref': lambda graph: first_tag(graph, 'ref').__setitem__(1, 999999999),
        'missing_original_root': lambda graph: graph[2].pop(),
        'bool_as_integer': lambda graph: first_tag(graph, 'int').__setitem__(1, True),
        'truncated_MT624': lambda graph: first_tag(graph, 'RandomState')[2][2][1].__setitem__(4, ''),
        'duplicate_definition_serial': lambda graph: first_tag(graph, 'list').__setitem__(1, 0),
        'ledger_missing_field': lambda graph: next(value for key, value in graph[2] if key == ['str', 'ledger'])[2][0][2].pop(),
        'ledger_wrong_scalar_type': lambda graph: next(value for key, value in graph[2] if key == ['str', 'ledger'])[2][0][2].__setitem__(0, ['str', 'corrupted-not-id']),
        'unknown_original_type': lambda graph: first_tag(graph, 'Side').__setitem__(0, 'UndocumentedSide'),
        'wrong_root_container_type': lambda graph: next(value for key, value in graph[2] if key == ['str', 'agent_count_by_type']).__setitem__(0, 'list'),
        'unknown_original_object_class': lambda graph: next(value for key, value in graph[2] if key == ['str', 'latency']).__setitem__(1, 'FakeClass'),
    }
    negatives = []
    for name, mutate in mutators.items():
        graph = copy.deepcopy(sample)
        mutate(graph)
        try:
            GraphAudit().audit(graph)
        except (ValueError, TypeError, IndexError, KeyError) as error:
            negatives.append({'case': name, 'rejected': True, 'reason': str(error)})
        else:
            raise ValueError('corrupt graph accepted: ' + name)
    report = {'schema': 't3-independent-saved-expectations-delivery-auditor-preflight-v1', 'status': 'PASS_SOURCE_AND_SAVED_SCHEMA_ONLY',
        'files': {file.name: pin(file) for file in files}, 'source_pins': pin(source / 'SOURCE_PINS.json'),
        'exact_saved_data_only_imports': sorted(imports), 'AST_inert_compile_passed': True,
        'saved_v7_control_arms': list(ARMS), 'saved_v7_diagnostic_graphs_decoded': 20,
        'saved_v7_graph_results': graph_results, 'saved_classic_public_output_shape_cases': [
            {'unit': row['unit'], 'shape': items[row['unit']]['shape'], 'subs': len(items[row['unit']].get('subs', []))} for row in selected],
        'saved_classic_unique_Parquet_contents_full_decoded': len(old.decoded), 'corrupt_graph_negatives': negatives,
        'corrupt_output_coverage_negatives': output_negatives,
        'delivery_artifact_audit_executed': False, 'delivery_result_observed': False,
        'participant_imported': False, 'native_compiled': False, 'market_executed': False,
        'remote_writes': False, 'official_submission': False, 'performance_usable': False, 'eligible_for_official_submission': False}
    with args.out.open('x') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'saved_graphs': 20, 'output_schema_cases': len(selected), 'corrupt_graph_negatives': len(negatives)}), flush=True)


if __name__ == '__main__':
    main()
