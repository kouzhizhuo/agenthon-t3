"""Finite saved-only cost stdout parser. No participant/native/simulator imports.

Used by the Linux worker and standalone synthetic saved-data controls. Successful
parsing never implies delivery/publication or interpretable native cost.
"""
import base64
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import zlib

BLOCK = 'T3_EXPECTATIONS_COST_STATE_BLOCK_V1 '
STATE = 'T3_EXPECTATIONS_COST_STATE_V1 '
PROFILE = 'T3_EXPECTATIONS_COST_V1 '
LOG_CAP = 256 * 1024**2
GRAPH_CAP = 4 * 1024**3
BLOCK_BYTES = 1024**2
BLOCK_COUNT = 128
PROFILE_CAP = 8 * 1024**2
FUNCTIONS = 32768
CALLERS = 131072
TEXT_CAP = 16384
COUNT_CAP = 2**63 - 1
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
KEYS = ('arm', 'cost_mode', 'sub', 'scenario_id', 'seed')



def stable_simulate_AST_sha256(original):
    """Canonical business AST wire independent of CPython AST dump defaults.

    Only the frozen node/field schema is accepted. New nonempty fields and
    unknown nodes fail closed; empty Python3.12+ type_params is representation.
    The caller separately binds every source byte before using this digest.
    """
    schema = {'Add': [], 'And': [], 'Assign': ['targets', 'value', 'type_comment'], 'Attribute': ['value', 'attr', 'ctx'], 'BinOp': ['left', 'op', 'right'], 'BoolOp': ['op', 'values'], 'Call': ['func', 'args', 'keywords'], 'Compare': ['left', 'ops', 'comparators'], 'Constant': ['value', 'kind'], 'Dict': ['keys', 'values'], 'DictComp': ['key', 'value', 'generators'], 'Div': [], 'Eq': [], 'Expr': ['value'], 'FunctionDef': ['name', 'args', 'body', 'decorator_list', 'returns', 'type_comment'], 'If': ['test', 'body', 'orelse'], 'IfExp': ['test', 'body', 'orelse'], 'Import': ['names'], 'ImportFrom': ['module', 'names', 'level'], 'In': [], 'Is': [], 'IsNot': [], 'Lambda': ['args', 'body'], 'Load': [], 'Mult': [], 'Name': ['id', 'ctx'], 'Not': [], 'NotIn': [], 'Or': [], 'Raise': ['exc', 'cause'], 'Return': ['value'], 'Store': [], 'Sub': [], 'Subscript': ['value', 'slice', 'ctx'], 'Try': ['body', 'handlers', 'orelse', 'finalbody'], 'Tuple': ['elts', 'ctx'], 'UnaryOp': ['op', 'operand'], 'With': ['items', 'body', 'type_comment'], 'alias': ['name', 'asname'], 'arg': ['arg', 'annotation', 'type_comment'], 'arguments': ['posonlyargs', 'args', 'vararg', 'kwonlyargs', 'kw_defaults', 'kwarg', 'defaults'], 'comprehension': ['target', 'iter', 'ifs', 'is_async'], 'keyword': ['arg', 'value'], 'withitem': ['context_expr', 'optional_vars']}
    def wire(value):
        if isinstance(value, ast.AST):
            name = type(value).__name__
            if name not in schema:
                raise ValueError('unknown source AST node')
            known = schema[name]
            if not set(known) <= set(value._fields) or not all(hasattr(value, field) for field in known):
                raise ValueError('missing frozen AST field')
            extras = set(value._fields) - set(known)
            for field in extras:
                if not (name == 'FunctionDef' and field == 'type_params'
                        and getattr(value, field, None) == []):
                    raise ValueError('unsupported noncanonical AST field')
            return [name, [[field, wire(getattr(value, field, None))] for field in known]]
        if type(value) is list:
            return [wire(item) for item in value]
        if type(value) is float:
            if not (-float('inf') < value < float('inf')):
                raise ValueError('nonfinite source AST scalar')
            return ['float', value.hex()]
        if value is None or type(value) in (str, int, bool):
            return value
        raise ValueError('unsupported source AST scalar')
    encoded = json.dumps(wire(original), ensure_ascii=True, separators=(',', ':'),
                         allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()

def source_contract(source_bytes, arm, source_pin):
    """Independently read the original AST; never compile or execute it."""
    require(arm in ARMS and source_pin == {'bytes': len(source_bytes),
        'sha256': hashlib.sha256(source_bytes).hexdigest()}, 'exact original source bytes/pin')
    tree = ast.parse(source_bytes)
    functions = [node for node in tree.body if type(node) is ast.FunctionDef and node.name == 'simulate']
    require(len(functions) == 1, 'one original simulate definition')
    original = functions[0]
    require(not any(type(node) in (ast.FunctionDef, ast.AsyncFunctionDef)
        for node in ast.walk(original) if node is not original), 'no nested source function')
    labels, anchors = [], {}
    names = {'verify_sources': 'verify_sources', 'verify_runtime': 'verify_runtime',
        'configure_expectations': 'configure_expectations', 'validate_scenario': 'scenario_validate',
        'validate_admitted_columns': 'output_validate', 'validate_frames': 'fallback_validate',
        'write_outputs': 'joint_output_write'}
    assigns = {'authenticated': 'source_auth', 'config': 'build_config',
        'admitted_episode': 'observer_begin', 'trace': 'trace_projection', 'messages': 'message_projection'}
    def marker(node):
        label = None
        if type(node) is ast.Assign:
            if (len(node.targets) == 1 and type(node.targets[0]) is ast.Tuple
                    and [child.id for child in node.targets[0].elts if type(child) is ast.Name]
                    == ['original_kernel', 'summary_writer']):
                return [], 'original_bindings'
            targets = [child.id for child in node.targets if type(child) is ast.Name]
            if targets == ['end_state']:
                require(type(node.value) is ast.Call and type(node.value.func) is ast.Attribute
                    and type(node.value.func.value) is ast.Name and node.value.func.value.id == 'abides'
                    and node.value.func.attr == 'run', 'exact source simulation call anchor')
                return ['simulation_enter', 'simulation_exit'], 'abides_run'
            if len(targets) == 1:
                label = assigns.get(targets[0])
        elif type(node) is ast.Expr and type(node.value) is ast.Call:
            fn = node.value.func
            if type(fn) is ast.Name:
                label = names.get(fn.id)
            elif type(fn) is ast.Attribute and type(fn.value) is ast.Name:
                pair = fn.value.id, fn.attr
                if pair == ('observer', 'finish_episode'):
                    label = 'observer_finish'
                elif pair in (('trace', 'to_parquet'), ('messages', 'to_parquet')):
                    label = pair[0] + '_fallback_write'
        elif type(node) is ast.Return:
            return ['simulate_exit'], 'simulate_return'
        return ([label + '_enter', label + '_exit'], label) if label else ([], None)
    for node in ast.walk(original):
        phases, anchor = marker(node)
        if anchor:
            anchors[anchor] = anchors.get(anchor, 0) + 1
    def sequence(nodes, runtime):
        result = []
        for node in nodes:
            phases, _ = marker(node)
            if phases:
                result.extend(phases)
            elif type(node) is ast.If:
                if runtime and type(node.test) is ast.Name and node.test.id in ('native_admitted', 'declines'):
                    result.extend(sequence(node.body if node.test.id == 'native_admitted' else node.orelse, runtime))
                else:
                    body, other = sequence(node.body, runtime), sequence(node.orelse, runtime)
                    require(not runtime or (not body and not other), 'successful marker branch must be independently source-bound')
                    result.extend(body + other)
            elif type(node) in (ast.Try, ast.With):
                result.extend(sequence(node.body, runtime))
                if type(node) is ast.Try:
                    require(not node.handlers, 'no unbound diagnostic exception path')
                    result.extend(sequence(node.orelse, runtime) + sequence(node.finalbody, runtime))
            else:
                require(not any(marker(child)[0] for child in ast.walk(node) if child is not node),
                    'no unbound nested source marker')
        return result
    labels = sequence(original.body, False) + ['simulate_enter']
    required = {'abides_run': 2, 'original_bindings': 1, 'simulate_return': 1,
        'verify_sources': 1, 'verify_runtime': 1, 'configure_expectations': int(arm == 'expectations'),
        'source_auth': 1, 'build_config': 1, 'observer_begin': 1,
        'trace_projection': 2, 'message_projection': 2, 'observer_finish': 1, 'joint_output_write': 1}
    require(all(anchors.get(key, 0) == count for key, count in required.items()), 'exact source-derived original anchor counts')
    prepared = {'non_marker_business_AST_equal': True, 'arm': arm, 'source_pin': source_pin,
        'anchor_counts': anchors, 'static_labels': labels,
        'original_simulate_AST_sha256': stable_simulate_AST_sha256(original)}
    return {'schema': 't3-cost-source-contract-v1', 'prepared': prepared,
        'successful_native_tick_labels': ['simulate_enter', *sequence(original.body, True)],
        'source_compiled': False, 'source_executed': False}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json_bytes(data):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'duplicate JSON key: ' + key)
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=pairs,
        parse_constant=lambda item: (_ for _ in ()).throw(ValueError('nonfinite JSON constant: ' + item)))


def file_pin(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'saved regular file required')
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024**2), b''):
            digest.update(data)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def exact_pin(value):
    require(type(value) is dict and set(value) == {'bytes', 'sha256'}
        and type(value['bytes']) is int and value['bytes'] >= 0
        and type(value['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is not None, 'exact byte/hash pin required')
    return value


def exact_fields(row, wanted):
    require(type(row) is dict and all(key in row and exact_value(row[key], value)
        for key, value in wanted.items()), 'exact typed fields differ')


def exact_value(actual, wanted):
    if type(actual) is not type(wanted):
        return False
    if type(wanted) is dict:
        return set(actual) == set(wanted) and all(exact_value(actual[key], value) for key, value in wanted.items())
    if type(wanted) is list:
        return len(actual) == len(wanted) and all(exact_value(first, second) for first, second in zip(actual, wanted))
    return actual == wanted


def profile_rows(rows):
    require(type(rows) is list and len(rows) <= FUNCTIONS, 'finite profile function roster')
    identities = set()
    edges = 0
    def identity(row):
        require(type(row) is dict and type(row.get('file')) is str and type(row.get('function')) is str
            and type(row.get('line')) is int and 0 <= row['line'] <= COUNT_CAP
            and all(len(row[key].encode('utf-8')) <= TEXT_CAP for key in ('file', 'function')), 'finite typed function identity')
        return row['file'], row['line'], row['function']
    def count(value):
        require(type(value) is int and 0 <= value <= COUNT_CAP, 'finite typed nonnegative calls')
    def seconds(value):
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'finite nonnegative profile seconds')
    for row in rows:
        key = identity(row)
        require(key not in identities, 'unique profile function identity')
        identities.add(key)
        require(set(row) == {'file', 'line', 'function', 'primitive_calls', 'total_calls', 'self_sec', 'cumulative_sec', 'callers'}, 'exact profile row fields')
        count(row['primitive_calls']); count(row['total_calls'])
        seconds(row['self_sec']); seconds(row['cumulative_sec'])
        require(type(row['callers']) is list, 'finite caller list')
        caller_ids = set()
        for caller in row['callers']:
            edges += 1
            require(edges <= CALLERS, 'finite profile caller edge cap')
            cid = identity(caller)
            require(cid not in caller_ids, 'unique caller edge per function')
            caller_ids.add(cid)
            if 'legacy_calls' in caller:
                require(set(caller) == {'file', 'line', 'function', 'legacy_calls'}, 'exact legacy caller fields')
                count(caller['legacy_calls'])
            else:
                require(set(caller) == {'file', 'line', 'function', 'total_calls', 'primitive_calls', 'self_sec', 'cumulative_sec'}, 'exact cProfile caller fields')
                count(caller['total_calls']); count(caller['primitive_calls'])
                seconds(caller['self_sec']); seconds(caller['cumulative_sec'])
    return {'functions': len(rows), 'caller_edges': edges}


def roster_from_execution(item, execution, output):
    """Map original/staged host paths to their exact readonly container paths."""
    require(item['shape'] in ('single', 'batch') and type(item['scenario_paths']) is list, 'original item scenario roster')
    output = Path(output).resolve()
    staged = execution['staged_inputs']
    expected = {None: 'scenario.json'} if item['shape'] == 'single' else {row['sub']: row['scenario_file'] for row in item['subs']}
    require(len(expected) in range(1, 6) and len(staged) == len(expected), 'one complete staged input per original market')
    rows, seen, source_seen = [], set(), set()
    for record in staged:
        require(type(record) is dict and set(record) == {'source', 'staged', 'sha256'}
            and record['source'] in item['scenario_paths'] and record['source'] not in source_seen,
            'one exact original source path per staged market')
        source_seen.add(record['source'])
        host = Path(record['staged'])
        require(host.is_absolute() and host.is_file() and not host.is_symlink(), 'exact staged regular scenario path')
        input_root = output.parent / 'input'
        require(input_root in host.resolve().parents, 'staged scenario under exact worker input root')
        relative = host.relative_to(input_root).as_posix()
        matching = [sub for sub, wanted in expected.items() if relative == wanted]
        require(len(matching) == 1 and relative not in seen, 'exact unique original staged input mapping')
        seen.add(relative)
        pin = file_pin(host)
        require(pin['sha256'] == record['sha256'] == item['input_sha256'][relative], 'original/staged complete input hash equality')
        scenario = read_json_bytes(host.read_bytes())
        require(type(scenario['seed']) is int and type(scenario['scenario_id']) is str, 'typed actual scenario identity')
        sub = matching[0]
        container = '/input/' + relative
        target = output if sub is None else output / sub
        rows.append({'sub': sub, 'scenario_id': scenario['scenario_id'], 'seed': scenario['seed'],
            'scenario_path': container, 'scenario_source': pin, 'staged_host_path': str(host),
            'output_host_dir': str(target), 'actual_trace_output': '/output/trace.parquet' if sub is None else '/output/' + sub + '/trace.parquet'})
    require(seen == set(expected.values()) and source_seen == set(item['scenario_paths']), 'complete readonly staged scenario/source roster')
    rows.sort(key=lambda row: row['scenario_path'])
    return rows


def stream_key(row, arm, mode, roster):
    exact_fields(row, {'arm': arm, 'cost_mode': mode, 'timing_included': False, 'rankable': False})
    require(type(row.get('scenario_source')) is dict, 'full scenario source pin')
    exact_pin(row['scenario_source'])
    matched = [item for item in roster if all(type(row.get(key)) is type(item[key]) and row.get(key) == item[key]
        for key in ('sub', 'scenario_id', 'seed', 'scenario_path', 'scenario_source'))]
    require(len(matched) == 1, 'one exact source-bound scenario stream identity')
    return tuple(row[key] for key in KEYS) + (row['scenario_source']['sha256'],), matched[0]


def validate_observation(row, arm, mode, binding, source_pin, contract, roster):
    exact_fields(row, {'schema': 't3-expectations-cost-observation-v1', 'arm': arm, 'cost_mode': mode,
        'source_sha256': source_pin['sha256'], 'actual_image_binding': binding,
        'simulate_alias_restored': True, 'profile_slot_restored': True,
        'profiled_native_extension': False, 'profile_false_native_cdef_detail_missing': True,
        'cold_snapshot_and_emission_profiler_disabled': True, 'diagnostic_AST_preparation_profiler_disabled': True,
        'profile_segments_reset_caller_stack': True, 'diagnostic_timings_are_ordinary_partition': False,
        'diagnostic_timings_prove_removable_owner_cost': False, 'failure': None,
        'finalization_errors': [], 'observation_complete': True, 'timing_included': False, 'rankable': False})
    exact_fields(row, {'wrapper_and_profile_overhead_included_in_process_wall': True,
        'diagnostic_wrapper_imports_before_profile': ['ast', 'base64', 'cProfile', 'copy', 'hashlib',
            'importlib.util', 'json', 'math', 'pathlib', 'pstats', 'shutil', 'sys', 'zlib']})
    profile = profile_rows(row['profile_stats'])
    require((mode == 'state' and profile['functions'] == 0) or (mode == 'cost' and profile['functions'] > 0), 'exact profiled/unprofiled sibling mode')
    exact_fields(contract, {'schema': 't3-cost-source-contract-v1', 'source_compiled': False, 'source_executed': False})
    require(exact_value(row.get('prepared'), contract['prepared']),
        'entire source-derived original AST/anchors/staticlabels contract equal')
    exact_fields(contract['prepared'], {'non_marker_business_AST_equal': True, 'arm': arm, 'source_pin': source_pin})
    labels = contract['successful_native_tick_labels']
    require(type(labels) is list and len(labels) > 2 and labels[0] == 'simulate_enter' and labels[-1] == 'simulate_exit'
        and labels.count('simulation_exit') == 1 and all(type(label) is str for label in labels), 'finite exact successful native phase contract')
    def clock(value):
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'finite typed marker clock')
    clock(row['driver_started'])
    for field in ('ticks', 'milestones'):
        require(type(row.get(field)) is list and 0 < len(row[field]) <= 4096, 'finite complete diagnostic clock markers')
        for marker in row[field]:
            require(type(marker) is dict and set(marker) == ({'phase', 'perf_counter', 'config_path'} if field == 'ticks'
                else {'phase', 'perf_counter'}) and type(marker['phase']) is str, 'exact typed marker fields')
            clock(marker['perf_counter'])
    expected_tick = [(label, market['scenario_path'] if label == 'simulate_enter' else None)
        for market in roster for label in labels]
    require(len(row['ticks']) == len(expected_tick) and all(marker['phase'] == label
        and type(marker['config_path']) is type(path) and marker['config_path'] == path
        for marker, (label, path) in zip(row['ticks'], expected_tick)), 'exact source-bound permarket tick/configpath order')
    expected_milestones = ['actual_entry_import_enter', 'actual_entry_import_exit', 'actual_main_enter']
    permarket = ['cold_state_snapshot_enter', 'cold_state_snapshot_exit',
        'cold_state_output_compare_enter', 'cold_state_output_compare_exit']
    expected_milestones += permarket * len(roster) + ['actual_main_exit']
    require([marker['phase'] for marker in row['milestones']] == expected_milestones,
        'exact actual import/main/coldstate permarket milestone roster')
    clocks = [row['driver_started'], *[marker['perf_counter'] for marker in row['milestones'][:3]]]
    for index in range(len(roster)):
        ticks = row['ticks'][index * len(labels):(index + 1) * len(labels)]
        milestone = row['milestones'][3 + index * 4:7 + index * 4]
        for marker in ticks:
            if marker['phase'] == 'simulate_exit':
                clocks.extend(item['perf_counter'] for item in milestone[2:])
            clocks.append(marker['perf_counter'])
            if marker['phase'] == 'simulation_exit':
                clocks.extend(item['perf_counter'] for item in milestone[:2])
    clocks.append(row['milestones'][-1]['perf_counter'])
    require(all(first <= second for first, second in zip(clocks, clocks[1:])),
        'driver/import/main/tick/coldstate full chronological order')
    return profile


def parse_cost_stdout(execution, folder, arm, mode, roster, binding, source_pin, contract, graph_audit=None):
    """Write complete host STATE files outside official output; fail closed.

    Partial decoded streams and PARSE_RESULT.json remain on every failure.
    The original raw attach stdout is never rewritten or regenerated.
    """
    require(arm in ARMS and mode in ('state', 'cost'), 'exact arm/mode')
    require(type(roster) is list and 0 < len(roster) <= 5, 'finite actual market roster')
    folder = Path(folder)
    target = folder / 'cost-state'
    require(not target.exists(), 'fresh state evidence directory')
    target.mkdir()
    parse = {'schema': 't3-cost-stdout-parse-result-v1', 'passed': False, 'rankable': False,
        'timing_included': False, 'states': [], 'observation': None, 'failure': None,
        'market_executed': False, 'participant_imported': False, 'native_compiled': False}
    streams, metadata, observations = {}, {}, []
    original_error, final_errors = None, []
    expected_keys = {(arm, mode, row['sub'], row['scenario_id'], row['seed'], row['scenario_source']['sha256']) for row in roster}
    require(len(expected_keys) == len(roster), 'unique exact expected stream keys')
    try:
        require(execution['succeeded'] is True and execution['exit_code'] == 0 and execution['OOMKilled'] is False
            and execution['cleanup']['settled'] is execution['cleanup']['removed'] is execution['cleanup']['final_absent'] is True
            and execution['cleanup']['errors'] == [], 'actual exit0/noOOM/ownedsettledremoved container required')
        attach = execution['attach']
        require(attach['returncode'] == 0 and attach['succeeded'] is True and attach['timed_out'] is attach['cancelled'] is False
            and attach['error'] is None and attach['creator_reaped'] is True and attach['per_log_file_hard_bytes'] == LOG_CAP, 'full successful original attach receipt')
        raw_pins = {}
        for field in ('stdout', 'stderr'):
            saved = attach[field]
            require(file_pin(saved['path']) == exact_pin({key: saved[key] for key in ('bytes', 'sha256')})
                and saved['bytes'] < LOG_CAP and saved['hard_limit_reached'] is False, 'full original raw ' + field + ' pin/cap')
            raw_pins[field] = file_pin(saved['path'])
        stdout = Path(attach['stdout']['path'])
        max_line = PROFILE_CAP + 4 * 1024**2
        with stdout.open('rb') as source:
            while True:
                line = source.readline(max_line + 1)
                if not line:
                    break
                require(len(line) <= max_line and line.endswith(b'\n'), 'finite complete stdout line')
                text = line.decode('utf-8')
                if text.startswith(BLOCK):
                    require(not metadata and not observations, 'all state blocks precede metadata/profile emission')
                    row = read_json_bytes(text[len(BLOCK):])
                    exact_fields(row, {'schema': 't3-expectations-cost-state-block-v1'})
                    key, expected = stream_key(row, arm, mode, roster)
                    require(key not in metadata, 'state blocks precede final metadata')
                    if key not in streams:
                        dest = target / ('market-%02d' % len(streams))
                        dest.mkdir()
                        path = dest / 'STATE.json'
                        streams[key] = {'path': path, 'file': path.open('xb'), 'decoder': zlib.decompressobj(),
                            'digest': hashlib.sha256(), 'bytes': 0, 'blocks': 0, 'compressed_bytes': 0, 'expected': expected}
                    stream = streams[key]
                    require(type(row.get('block_index')) is int and row['block_index'] == stream['blocks'] < BLOCK_COUNT
                        and type(row.get('compressed_bytes')) is int and 0 < row['compressed_bytes'] <= BLOCK_BYTES
                        and type(row.get('data_base64')) is str and len(row['data_base64']) <= 4 * ((BLOCK_BYTES + 2) // 3), 'ordered finite state block')
                    data = base64.b64decode(row['data_base64'], validate=True)
                    require(len(data) == row['compressed_bytes'], 'complete compressed block size')
                    remain = data
                    while remain:
                        decoded = stream['decoder'].decompress(remain, BLOCK_BYTES)
                        remain = stream['decoder'].unconsumed_tail
                        require(not stream['decoder'].unused_data and (decoded or not remain), 'single bounded zlib stream no trailing payload')
                        stream['bytes'] += len(decoded)
                        require(stream['bytes'] <= GRAPH_CAP, 'complete decoded graph cap')
                        stream['file'].write(decoded); stream['digest'].update(decoded)
                    stream['blocks'] += 1; stream['compressed_bytes'] += len(data)
                elif text.startswith(STATE):
                    require(not observations and set(streams) == expected_keys, 'all blocks before metadata and metadata before profile')
                    row = read_json_bytes(text[len(STATE):]);exact_fields(row, {'schema': 't3-expectations-cost-full-state-v1'})
                    key, _ = stream_key(row, arm, mode, roster)
                    require(key not in metadata and key in streams, 'unique complete state metadata after blocks')
                    metadata[key] = row
                elif text.startswith(PROFILE):
                    payload = text[len(PROFILE):].strip()
                    require(len(payload.encode('utf-8')) <= PROFILE_CAP, 'complete profile JSON8MiBcap')
                    row = read_json_bytes(payload)
                    require(row.get('schema') != 't3-expectations-cost-terminal-failure-v1', 'terminal cost failure rejects observation')
                    require(not observations, 'exactly one profile observation per container')
                    require(set(metadata) == expected_keys, 'profile emitted only after all complete state metadata')
                    observations.append(row)
                else:
                    require(not text.startswith('T3_EXPECTATIONS_COST'), 'unknown cost record prefix')
        require(set(streams) == set(metadata) == expected_keys and len(observations) == 1, 'all actual streams/metadata and exact observation complete')
        profile = validate_observation(observations[0], arm, mode, binding, source_pin, contract, roster)
        for key in sorted(expected_keys, key=lambda value: str(value[2])):
            stream, row = streams[key], metadata[key]
            stream['file'].flush(); stream['file'].close()
            dec = stream['decoder']
            require(dec.eof and not dec.unused_data and not dec.unconsumed_tail, 'complete zlib EOF no residual bytes')
            exact_fields(row, {'state_sha256': stream['digest'].hexdigest(), 'state_bytes': stream['bytes'], 'state_blocks': stream['blocks'],
                'decoded_state_hard_bytes': GRAPH_CAP, 'state_block_hard_count': BLOCK_COUNT,
                'full_original_control_graph': True, 'graph_output_readonly': True, 'observer_finished': True,
                'kernel_and_summary_bindings_restored': True, 'actual_trace_output': stream['expected']['actual_trace_output']})
            require(file_pin(stream['path']) == {'bytes': stream['bytes'], 'sha256': stream['digest'].hexdigest()}, 'full retained graph byte pin')
            activity = row.get('actual_native_activity')
            require(type(activity) is dict and set(activity) == {'orders', 'messages'}, 'complete native activity groups')
            for kind, fields in [('orders', {'live_orders', 'order_clones', 'order_slots'}), ('messages', {'live_messages', 'constructed_messages', 'message_slots'})]:
                require(type(activity[kind]) is dict and set(activity[kind]) == fields and all(type(v) is int and 0 <= v <= COUNT_CAP for v in activity[kind].values()), 'finite actual native activity stats')
            require(activity['orders']['order_slots'] > 0 and activity['messages']['constructed_messages'] > 0, 'positive actual native order/message activity')
            expected = stream['expected'];output = Path(expected['output_host_dir'])
            events = read_json_bytes((output / 'events.json').read_bytes())
            trace, ledger = file_pin(output / 'trace.parquet'), file_pin(output / 'message_trace.parquet')
            exact_fields(row, {'events': events, 'trace': trace, 'message_trace': ledger})
            require(events['scenario_id'] == expected['scenario_id'] and type(events['seed']) is int and events['seed'] == expected['seed']
                and type(events['n_events']) is int and events['n_events'] > 0 and events['trace_sha256'] == trace['sha256'], 'source-bound event identity/fullcount/digest')
            witness = row.get('witness')
            exact_fields(witness, {'schema': 't3-cold-native-projection-buffers-output-witness-v1', 'requested_arm': 'light_dynamic',
                'source_authenticated': True, 'observer_admitted': True, 'native_admitted': True, 'selected_kernel': 'NativeOwnerKernel',
                'projectors_admitted': True, 'declines': {}, 'output_mode': 'native-canonical-arrow-buffers', 'native_output_pair': True,
                'actual_trace_sha256': trace['sha256'], 'actual_trace_rows': events['n_events'], 'market_rerun': False, 'rankable': False})
            exact_pin(row['witness_source'])
            require(file_pin_bytes_witness(witness) == row['witness_source'], 'embedded witness matches retained original witness wire pin')
            require(type(row.get('witness_path')) is str and row['witness_path'] == '/tmp/expectations-cost-diagnostic-v1/'
                + ('single.json' if expected['sub'] is None else 'markets/' + expected['sub'] + '.json'), 'exact temporary container witness path')
            graph = read_json_bytes(stream['path'].read_bytes())
            checked = graph_audit(graph) if graph_audit is not None else {'typed_graph_validation_pending': True}
            require(type(checked) is dict, 'complete graph audit result dictionary')
            require(graph_audit is not None, 'frozen complete typed/alias/MT624 graph auditor required')
            parse['states'].append({'key': list(key), 'state': row, 'path': str(stream['path']),
                'pin': file_pin(stream['path']), 'mapping': expected, 'graph_audit': checked, 'compressed_bytes': stream['compressed_bytes']})
        parse.update(passed=True, observation=observations[0], profile=profile,
            source_contract=contract, raw_stdout=raw_pins['stdout'], raw_stderr=raw_pins['stderr'])
    except BaseException as error:
        parse['failure'] = {'type': type(error).__name__, 'message': str(error)}
        original_error = sys.exc_info()
    finally:
        for stream in streams.values():
            try:
                if not stream['file'].closed:
                    stream['file'].close()
            except BaseException as error:
                final_errors.append({'stage': 'state_stream_close', 'type': type(error).__name__, 'message': str(error)})
        if final_errors:
            parse['passed'] = False
            parse['finalization_errors'] = final_errors
        try:
            (folder / 'PARSE_RESULT.json').write_text(json.dumps(parse, sort_keys=True, indent=2, allow_nan=False) + '\n')
        except BaseException:
            if original_error is None:
                raise
    if original_error is not None:
        raise original_error[1].with_traceback(original_error[2])
    if final_errors:
        raise ValueError('cost state parser stream finalization failed')
    return parse


def file_pin_bytes_witness(witness):
    data = (json.dumps(witness, sort_keys=True, indent=2) + '\n').encode('utf-8')
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
