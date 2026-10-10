"""Finite synthetic saved-data parser controls. No market/native execution."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zlib

from parser import (BLOCK, STATE, PROFILE, LOG_CAP, GRAPH_CAP, BLOCK_COUNT,
    file_pin, file_pin_bytes_witness, parse_cost_stdout, profile_rows, read_json_bytes)

HERE = Path(__file__).resolve().parent


def wire(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def run_case(root, name, mutate=None, mode='state'):
    folder = root / name
    folder.mkdir()
    out = folder / 'output'; out.mkdir()
    trace = out / 'trace.parquet'; trace.write_bytes(b'synthetic trace bytes are data; not decoded')
    ledger = out / 'message_trace.parquet'; ledger.write_bytes(b'synthetic ledger bytes are data; not decoded')
    scenario_source = {'bytes': 123, 'sha256': 'a' * 64}
    events = {'scenario_id': 'synthetic-source-only-scenario', 'seed': 7, 'n_events': 4, 'trace_sha256': file_pin(trace)['sha256']}
    (out / 'events.json').write_bytes(wire(events))
    roster = [{'sub': None, 'scenario_id': events['scenario_id'], 'seed': 7, 'scenario_path': '/input/scenario.json',
        'scenario_source': scenario_source, 'staged_host_path': '/synthetic-unused-input', 'output_host_dir': str(out), 'actual_trace_output': '/output/trace.parquet'}]
    graph = ['synthetic-finite-graph', {'value': 1}]
    graph_bytes = (json.dumps(graph, ensure_ascii=True, indent=2, allow_nan=False) + '\n').encode()
    compressed = zlib.compress(graph_bytes, 6)
    ident = {'arm': 'parent', 'cost_mode': mode, 'sub': None, 'scenario_id': events['scenario_id'], 'seed': 7,
        'scenario_path': '/input/scenario.json', 'scenario_source': dict(scenario_source), 'timing_included': False, 'rankable': False}
    block = {'schema': 't3-expectations-cost-state-block-v1', **ident, 'block_index': 0,
        'compressed_bytes': len(compressed), 'data_base64': base64.b64encode(compressed).decode()}
    witness = {'schema': 't3-cold-native-projection-buffers-output-witness-v1', 'requested_arm': 'light_dynamic',
        'source_authenticated': True, 'observer_admitted': True, 'native_admitted': True, 'selected_kernel': 'NativeOwnerKernel',
        'projectors_admitted': True, 'declines': {}, 'output_mode': 'native-canonical-arrow-buffers', 'native_output_pair': True,
        'actual_trace_sha256': file_pin(trace)['sha256'], 'actual_trace_rows': 4, 'market_rerun': False, 'rankable': False}
    state = {'schema': 't3-expectations-cost-full-state-v1', **copy.deepcopy(ident), 'state_sha256': hashlib.sha256(graph_bytes).hexdigest(),
        'state_bytes': len(graph_bytes), 'state_blocks': 1, 'decoded_state_hard_bytes': GRAPH_CAP, 'state_block_hard_count': BLOCK_COUNT,
        'full_original_control_graph': True, 'graph_output_readonly': True, 'observer_finished': True, 'kernel_and_summary_bindings_restored': True,
        'actual_trace_output': '/output/trace.parquet', 'actual_native_activity': {'orders': {'live_orders': 1, 'order_clones': 0, 'order_slots': 1},
        'messages': {'live_messages': 0, 'constructed_messages': 5, 'message_slots': 1}}, 'events': events, 'trace': file_pin(trace), 'message_trace': file_pin(ledger),
        'witness': witness, 'witness_source': file_pin_bytes_witness(witness), 'witness_path': '/tmp/expectations-cost-diagnostic-v1/single.json'}
    binding = {'source_only_synthetic': True}
    source_pin = {'bytes': 99, 'sha256': 'b' * 64}
    p_rows = [] if mode == 'state' else [{'file': '/opt/synthetic.py', 'line': 1, 'function': 'f', 'primitive_calls': 1, 'total_calls': 1,
        'self_sec': .1, 'cumulative_sec': .1, 'callers': [{'file': '~', 'line': 0, 'function': '<builtin>', 'legacy_calls': 1}]}]
    contract = {'schema': 't3-cost-source-contract-v1', 'source_compiled': False, 'source_executed': False,
        'prepared': {'non_marker_business_AST_equal': True, 'arm': 'parent', 'source_pin': source_pin,
            'original_simulate_AST_sha256': 'c' * 64, 'anchor_counts': {'synthetic': 1},
            'static_labels': ['simulate_exit', 'simulate_enter']},
        'successful_native_tick_labels': ['simulate_enter', 'simulation_enter', 'simulation_exit', 'simulate_exit']}
    ticks = [{'phase': label, 'perf_counter': second, 'config_path': '/input/scenario.json' if label == 'simulate_enter' else None}
        for label, second in [('simulate_enter',4), ('simulation_enter',5), ('simulation_exit',6), ('simulate_exit',11)]]
    milestones = [{'phase': label, 'perf_counter': second} for label, second in [
        ('actual_entry_import_enter',1), ('actual_entry_import_exit',2), ('actual_main_enter',3),
        ('cold_state_snapshot_enter',7), ('cold_state_snapshot_exit',8), ('cold_state_output_compare_enter',9),
        ('cold_state_output_compare_exit',10), ('actual_main_exit',12)]]
    obs = {'schema': 't3-expectations-cost-observation-v1', 'arm': 'parent', 'cost_mode': mode, 'source_sha256': source_pin['sha256'], 'actual_image_binding': binding,
        'simulate_alias_restored': True, 'profile_slot_restored': True, 'profiled_native_extension': False, 'profile_false_native_cdef_detail_missing': True,
        'cold_snapshot_and_emission_profiler_disabled': True, 'diagnostic_AST_preparation_profiler_disabled': True, 'profile_segments_reset_caller_stack': True,
        'diagnostic_timings_are_ordinary_partition': False, 'diagnostic_timings_prove_removable_owner_cost': False, 'failure': None, 'finalization_errors': [],
        'observation_complete': True, 'timing_included': False, 'rankable': False, 'profile_stats': p_rows,
        'prepared': copy.deepcopy(contract['prepared']), 'driver_started': 0,
        'ticks': ticks, 'milestones': milestones, 'wrapper_and_profile_overhead_included_in_process_wall': True,
        'diagnostic_wrapper_imports_before_profile': ['ast', 'base64', 'cProfile', 'copy', 'hashlib',
            'importlib.util', 'json', 'math', 'pathlib', 'pstats', 'shutil', 'sys', 'zlib']}
    rows = [(BLOCK, block), (STATE, state), (PROFILE, obs)]
    execution = {'succeeded': True, 'exit_code': 0, 'OOMKilled': False, 'cleanup': {'settled': True, 'removed': True, 'final_absent': True, 'errors': []}}
    raw = None
    if mutate is not None:
        raw = mutate(rows, execution)
    stdout = folder / 'stdout.txt'
    stderr = folder / 'stderr.txt';stderr.write_bytes(b'')
    stdout.write_bytes(raw if raw is not None else b''.join((prefix + json.dumps(row, sort_keys=True, allow_nan=False) + '\n').encode() for prefix, row in rows))
    execution['attach'] = {'returncode': 0, 'succeeded': True, 'timed_out': False, 'cancelled': False, 'error': None, 'creator_reaped': True,
        'per_log_file_hard_bytes': LOG_CAP, 'stdout': {'path': str(stdout), **file_pin(stdout), 'hard_limit_reached': False},
        'stderr': {'path': str(stderr), **file_pin(stderr), 'hard_limit_reached': False}}
    attachment_mutator = execution.pop('synthetic_attachment_mutator', None)
    if attachment_mutator:
        attachment_mutator(execution['attach'])
    result = parse_cost_stdout(execution, folder, 'parent', mode, roster, binding, source_pin, contract,
        graph_audit=lambda value: {'synthetic_only': True, 'accepted': value == graph})
    assert result['passed'] is True and len(result['states']) == 1
    assert result['states'][0]['pin']['sha256'] == hashlib.sha256(graph_bytes).hexdigest()
    return result


def main():
    temporary = Path(tempfile.mkdtemp(prefix='t3-cost-parser-synthetic-'))
    cases = []
    try:
        for mode in ('state', 'cost'):
            run_case(temporary, 'valid_' + mode, mode=mode)
            cases.append({'case': 'valid_exact_synthetic_' + mode, 'passed': True})
        def wrong_arm(rows, ex): rows[0][1]['arm'] = 'expectations'
        def wrong_mode(rows, ex): rows[0][1]['cost_mode'] = 'cost'
        def wrong_sub(rows, ex): rows[0][1]['sub'] = 'wrong'
        def wrong_input(rows, ex): rows[0][1]['scenario_source']['sha256'] = 'd' * 64
        def duplicate_stream(rows, ex): rows.insert(1, copy.deepcopy(rows[0]))
        def lost_block(rows, ex): rows.pop(0)
        def wrong_index(rows, ex): rows[0][1]['block_index'] = 1
        def wrong_sha(rows, ex): rows[1][1]['state_sha256'] = 'f' * 64
        def wrong_output(rows, ex): rows[1][1]['actual_trace_output'] = '/output/wrong.parquet'
        def not_restored(rows, ex): rows[1][1]['graph_output_readonly'] = False
        def terminal(rows, ex): rows[2][1]['schema'] = 't3-expectations-cost-terminal-failure-v1'
        def duplicate_obs(rows, ex): rows.append(copy.deepcopy(rows[2]))
        def incomplete(rows, ex): rows[2][1]['observation_complete'] = False
        def nonzero(rows, ex): ex['exit_code'] = 1
        def wrong_witness(rows, ex): rows[1][1]['witness']['actual_trace_rows'] = 3
        def wrong_metadata(rows, ex): rows[1][1]['seed'] = 8
        def wrong_ast(rows, ex): rows[2][1]['prepared']['original_simulate_AST_sha256'] = 'd' * 64
        def wrong_anchors(rows, ex): rows[2][1]['prepared']['anchor_counts']['synthetic'] = 2
        def bool_anchor(rows, ex): rows[2][1]['prepared']['anchor_counts']['synthetic'] = True
        def wrong_labels(rows, ex): rows[2][1]['prepared']['static_labels'].append('forged')
        def wrong_tick_order(rows, ex): rows[2][1]['ticks'][1:3] = rows[2][1]['ticks'][2:0:-1]
        def wrong_clock(rows, ex): rows[2][1]['ticks'][1]['perf_counter'] = 1
        def wrong_driverstart(rows, ex): rows[2][1]['driver_started'] = 13
        def missing_tick(rows, ex): rows[2][1]['ticks'].pop()
        def wrong_configpath(rows, ex): rows[2][1]['ticks'][0]['config_path'] = '/input/forged.json'
        def missing_milestone(rows, ex): rows[2][1]['milestones'].pop(3)
        def wrong_milestone_clock(rows, ex): rows[2][1]['milestones'][3]['perf_counter'] = 2
        def wrong_stderr_pin(rows, ex): ex['synthetic_attachment_mutator'] = lambda attach: attach['stderr'].update(sha256='d' * 64)
        def stderr_at_cap(rows, ex): ex['synthetic_attachment_mutator'] = lambda attach: attach['stderr'].update(hard_limit_reached=True)
        def profile_first(rows, ex): rows.insert(0, rows.pop())
        def state_after_profile(rows, ex): rows.append(copy.deepcopy(rows[1]))
        def block_after_meta(rows, ex): rows.insert(2, copy.deepcopy(rows[0]))
        def trailing(rows, ex):
            data = base64.b64decode(rows[0][1]['data_base64']) + b'junk';rows[0][1]['data_base64'] = base64.b64encode(data).decode();rows[0][1]['compressed_bytes'] = len(data)
        def truncated(rows, ex):
            data = base64.b64decode(rows[0][1]['data_base64'])[:-2];rows[0][1]['data_base64'] = base64.b64encode(data).decode();rows[0][1]['compressed_bytes'] = len(data)
        def duplicate_key(rows, ex): return (BLOCK + '{"schema":"x","schema":"x"}\n').encode()
        negatives = [('wrong_arm',wrong_arm),('wrong_mode',wrong_mode),('wrong_sub',wrong_sub),('wrong_input_sha',wrong_input),('duplicate_state_block',duplicate_stream),
            ('missing_state_block',lost_block),('wrong_block_index',wrong_index),('wrong_graph_sha',wrong_sha),('wrong_output_map',wrong_output),('not_restored',not_restored),
            ('terminal_observation',terminal),('duplicate_observation',duplicate_obs),('incomplete_observation',incomplete),('nonzero_container',nonzero),('wrong_witness',wrong_witness),
            ('wrong_metadata_seed',wrong_metadata),('trailing_zlib',trailing),('truncated_zlib',truncated),('duplicate_json_key',duplicate_key),
            ('wrong_ast_digest',wrong_ast),('wrong_source_anchors',wrong_anchors),('bool_source_anchor',bool_anchor),('wrong_static_labels',wrong_labels),('wrong_tick_order',wrong_tick_order),
            ('wrong_tick_clock',wrong_clock),('wrong_driver_started',wrong_driverstart),('missing_tick',missing_tick),('wrong_config_path',wrong_configpath),
            ('missing_milestone',missing_milestone),('wrong_milestone_clock',wrong_milestone_clock),('wrong_stderr_pin',wrong_stderr_pin),
            ('stderr_limit_reached',stderr_at_cap),('profile_before_states',profile_first),('state_after_profile',state_after_profile),('block_after_meta',block_after_meta)]
        for name, mutate in negatives:
            try:
                run_case(temporary, name, mutate)
            except (ValueError, KeyError, zlib.error) as error:
                receipt = read_json_bytes((temporary / name / 'PARSE_RESULT.json').read_bytes())
                assert receipt['passed'] is False and receipt['failure'] is not None
                cases.append({'case': 'reject_' + name, 'passed': True, 'failure_type': type(error).__name__})
            else:
                raise AssertionError('negative accepted: ' + name)
        for name, rows in [('bool_count',[{'file':'x','line':1,'function':'f','primitive_calls':True,'total_calls':1,'self_sec':0,'cumulative_sec':0,'callers':[]}]),
            ('excessive_count',[{'file':'x','line':1,'function':'f','primitive_calls':2**63,'total_calls':1,'self_sec':0,'cumulative_sec':0,'callers':[]}]),
            ('nonfinite_time',[{'file':'x','line':1,'function':'f','primitive_calls':1,'total_calls':1,'self_sec':float('nan'),'cumulative_sec':0,'callers':[]}])]:
            try: profile_rows(rows)
            except ValueError: cases.append({'case':'reject_profile_'+name,'passed':True})
            else:raise AssertionError('invalid profile accepted')
        result = {'schema':'t3-cost-host-parser-source-preflight-v1','all_cases_passed':True,'case_count':len(cases),'cases':cases,
            'ready_for_linux':False,'participant_imported':False,'market_executed':False,'native_compiled':False,
            'graph_validation_real_runtime_proven':False,'synthetic_only':True,'parser':file_pin(HERE/'parser.py'),'source':file_pin(Path(__file__))}
        (HERE/'PARSER_SOURCE_PREFLIGHT_v1.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print(json.dumps({'all_cases_passed':True,'cases':len(cases),'receipt':str(HERE/'PARSER_SOURCE_PREFLIGHT_v1.json')}))
    finally:
        shutil.rmtree(temporary)


if __name__ == '__main__':main()
