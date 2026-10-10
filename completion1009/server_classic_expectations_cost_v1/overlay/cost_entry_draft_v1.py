"""Source-only draft: finite profile plus exact cold state around unchanged CLI.

This script is for a separately frozen Linux diagnostic overlay. The active
submission entry and native extension are never replaced. No local execution
of main is part of source preparation.
"""
import time
DRIVER_STARTED = time.perf_counter()
import ast
import base64
import cProfile
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pstats
import shutil
import sys
import zlib

ROOT = Path('/opt/classic-native-kernels-v1/completion1009/candidates')
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
PROFILE_PREFIX = 'T3_EXPECTATIONS_COST_V1 '
STATE_PREFIX = 'T3_EXPECTATIONS_COST_STATE_V1 '
BLOCK_PREFIX = 'T3_EXPECTATIONS_COST_STATE_BLOCK_V1 '
MAX_PROFILE_ROWS = 32768
MAX_PROFILE_JSON = 8 * 1024**2
MAX_TICKS = 4096
MAX_STATE_BYTES = 4 * 1024**3
MAX_STATE_BLOCKS = 128
STATE_BLOCK_BYTES = 1024**2
MAX_CALLER_ROWS = 131072
MAX_FUNCTION_TEXT = 16384
MAX_COUNT = 2**63 - 1
INJECTED_NAMES = ('_t3_cost_mark', '_t3_cost_state', '_t3_cost_finish', '_t3_cost_bindings')



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

def instrument_simulate(namespace, source_bytes, source_path, arm, source_pin):
    """Add only source-bound markers/state reads; removable business AST equal."""
    if (arm not in ARMS or source_pin != {'bytes': len(source_bytes),
            'sha256': hashlib.sha256(source_bytes).hexdigest()}):
        raise ValueError('exact per-arm production source binding required')
    parsed = ast.parse(source_bytes)
    original = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == 'simulate')
    target = copy.deepcopy(original)
    labels, anchors = [], {}

    def extra_call(name, args):
        return ast.Expr(value=ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=args, keywords=[]))

    def mark(label, config=False):
        labels.append(label)
        args = [ast.Constant(label)]
        if config:
            args.append(ast.Name(id='config_path', ctx=ast.Load()))
        return extra_call('_t3_cost_mark', args)

    def around(node, label):
        anchors[label] = anchors.get(label, 0) + 1
        return [mark(label + '_enter'), node, mark(label + '_exit')]

    class Insert(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node is not target:
                raise ValueError('nested diagnostic function transformation refused')
            self.generic_visit(node)
            node.body.insert(0, mark('simulate_enter', config=True))
            return node

        def visit_Assign(self, node):
            self.generic_visit(node)
            names = [child.id for child in node.targets if isinstance(child, ast.Name)]
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Tuple)
                    and [child.id for child in node.targets[0].elts if isinstance(child, ast.Name)]
                    == ['original_kernel', 'summary_writer']):
                anchors['original_bindings'] = anchors.get('original_bindings', 0) + 1
                return [node, extra_call('_t3_cost_bindings', [ast.Name(id='original_kernel', ctx=ast.Load()),
                    ast.Name(id='summary_writer', ctx=ast.Load())])]
            if names == ['end_state']:
                if not (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                        and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == 'abides'
                        and node.value.func.attr == 'run'):
                    raise ValueError('exact original simulation boundary required')
                anchors['abides_run'] = anchors.get('abides_run', 0) + 1
                return [mark('simulation_enter'), node, mark('simulation_exit'),
                    extra_call('_t3_cost_state', [ast.Name(id='end_state', ctx=ast.Load()), ast.Name(id='scenario', ctx=ast.Load())])]
            by_name = {'authenticated': 'source_auth', 'config': 'build_config',
                'admitted_episode': 'observer_begin', 'trace': 'trace_projection',
                'messages': 'message_projection'}
            if len(names) == 1 and names[0] in by_name:
                return around(node, by_name[names[0]])
            return node

        def visit_Expr(self, node):
            self.generic_visit(node)
            value = node.value
            if isinstance(value, ast.Call):
                function = value.func
                name = function.id if isinstance(function, ast.Name) else None
                attribute = (function.value.id, function.attr) if (isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)) else None
                by_name = {'verify_sources': 'verify_sources', 'verify_runtime': 'verify_runtime',
                    'configure_expectations': 'configure_expectations', 'validate_scenario': 'scenario_validate',
                    'validate_admitted_columns': 'output_validate', 'validate_frames': 'fallback_validate',
                    'write_outputs': 'joint_output_write'}
                if name in by_name:
                    return around(node, by_name[name])
                if attribute == ('observer', 'finish_episode'):
                    return around(node, 'observer_finish')
                if attribute in (('trace', 'to_parquet'), ('messages', 'to_parquet')):
                    return around(node, attribute[0] + '_fallback_write')
            return node

        def visit_Return(self, node):
            anchors['simulate_return'] = anchors.get('simulate_return', 0) + 1
            return [extra_call('_t3_cost_finish', [ast.Name(id='end_state', ctx=ast.Load()),
                ast.Name(id='scenario', ctx=ast.Load()), ast.Name(id='out_path', ctx=ast.Load())]),
                mark('simulate_exit'), node]

    transformed = Insert().visit(target)
    injected_names = {'_t3_cost_mark', '_t3_cost_state', '_t3_cost_finish', '_t3_cost_bindings'}

    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in injected_names:
                return None
            return self.generic_visit(node)

    stripped = Remove().visit(copy.deepcopy(transformed))
    if ast.dump(stripped, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError('non-marker business AST differs')
    required = {'abides_run': 2, 'original_bindings': 1, 'simulate_return': 1,
        'verify_sources': 1, 'verify_runtime': 1, 'configure_expectations': int(arm == 'expectations'),
        'source_auth': 1, 'build_config': 1, 'observer_begin': 1,
        'trace_projection': 2, 'message_projection': 2, 'observer_finish': 1,
        'joint_output_write': 1}
    if any(anchors.get(name, 0) != count for name, count in required.items()):
        raise ValueError('fixed original diagnostic anchor counts differ')
    prepared = ast.fix_missing_locations(ast.Module(body=[transformed], type_ignores=[]))
    exec(compile(prepared, str(source_path), 'exec'), namespace)
    return {'non_marker_business_AST_equal': True, 'arm': arm, 'source_pin': source_pin,
        'anchor_counts': anchors, 'static_labels': labels,
        'original_simulate_AST_sha256': stable_simulate_AST_sha256(original)}


def stream_state(graph, emit_block, decoded_cap=MAX_STATE_BYTES, block_cap=MAX_STATE_BLOCKS):
    """Finite saved-data encoder, identical graph wire bytes to full controls."""
    if (type(decoded_cap) is not int or not 0 < decoded_cap <= MAX_STATE_BYTES
            or type(block_cap) is not int or not 0 < block_cap <= MAX_STATE_BLOCKS):
        raise ValueError('finite decoded state and block caps required')
    compressor, digest = zlib.compressobj(6), hashlib.sha256()
    size, blocks, compressed = 0, 0, bytearray()
    def block(data):
        nonlocal blocks
        if not data or len(data) > STATE_BLOCK_BYTES or blocks >= block_cap:
            raise ValueError('finite state block roster exceeded')
        emit_block(data, blocks)
        blocks += 1
    for fragment in json.JSONEncoder(ensure_ascii=True, indent=2, allow_nan=False).iterencode(graph):
        data = fragment.encode('utf-8')
        if size + len(data) + 1 > decoded_cap:
            raise ValueError('four GiB decoded state cap exceeded')
        digest.update(data); size += len(data); compressed.extend(compressor.compress(data))
        while len(compressed) >= STATE_BLOCK_BYTES:
            block(bytes(compressed[:STATE_BLOCK_BYTES])); del compressed[:STATE_BLOCK_BYTES]
    digest.update(b'\n'); size += 1
    compressed.extend(compressor.compress(b'\n')); compressed.extend(compressor.flush())
    while compressed:
        block(bytes(compressed[:STATE_BLOCK_BYTES])); del compressed[:STATE_BLOCK_BYTES]
    return {'state_sha256': digest.hexdigest(), 'state_bytes': size, 'state_blocks': blocks,
        'decoded_state_hard_bytes': decoded_cap, 'state_block_hard_count': block_cap}


def profile_rows(stats):
    """Accept finite stdlib cProfile rows; retain caller edges without summing."""
    if type(stats) is not dict or len(stats) > MAX_PROFILE_ROWS:
        raise ValueError('finite diagnostic profile function roster exceeded')
    def key(value):
        if (type(value) is not tuple or len(value) != 3 or type(value[0]) is not str
                or type(value[1]) is not int or not 0 <= value[1] <= MAX_COUNT
                or type(value[2]) is not str
                or any(len(text.encode('utf-8')) > MAX_FUNCTION_TEXT for text in (value[0], value[2]))):
            raise ValueError('finite typed profile function identity required')
        return {'file': value[0], 'line': value[1], 'function': value[2]}
    def counts(value):
        if type(value) is not int or not 0 <= value <= MAX_COUNT:
            raise ValueError('finite integer profile call count required')
        return value
    def seconds(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('finite nonnegative profile time required')
        return value
    rows, callers_total = [], 0
    for identity, value in sorted(stats.items()):
        if type(value) is not tuple or len(value) != 5 or type(value[4]) is not dict:
            raise ValueError('exact cProfile row tuple required')
        callers = []
        for caller, detail in sorted(value[4].items()):
            callers_total += 1
            if callers_total > MAX_CALLER_ROWS:
                raise ValueError('finite diagnostic caller roster exceeded')
            if type(detail) is int:
                detail = {'legacy_calls': counts(detail)}
            elif type(detail) is tuple and len(detail) == 4:
                detail = {'total_calls': counts(detail[0]), 'primitive_calls': counts(detail[1]),
                    'self_sec': seconds(detail[2]), 'cumulative_sec': seconds(detail[3])}
            else:
                raise ValueError('exact cProfile caller tuple required')
            callers.append({**key(caller), **detail})
        rows.append({**key(identity), 'primitive_calls': counts(value[0]), 'total_calls': counts(value[1]),
            'self_sec': seconds(value[2]), 'cumulative_sec': seconds(value[3]), 'callers': callers})
    return rows


def validate_witness(witness, state, events, trace_pin, ledger_pin):
    required = {'schema': 't3-cold-native-projection-buffers-output-witness-v1',
        'requested_arm': 'light_dynamic', 'source_authenticated': True, 'observer_admitted': True,
        'native_admitted': True, 'selected_kernel': 'NativeOwnerKernel', 'projectors_admitted': True,
        'declines': {}, 'output_mode': 'native-canonical-arrow-buffers', 'native_output_pair': True,
        'actual_trace_sha256': trace_pin['sha256'], 'actual_trace_rows': events['n_events'],
        'market_rerun': False, 'rankable': False}
    if (type(witness) is not dict or any(witness.get(k) != value or type(witness.get(k)) is not type(value)
            for k, value in required.items()) or events.get('scenario_id') != state['scenario_id']
            or type(events.get('seed')) is not int or events['seed'] != state['seed']
            or type(events.get('n_events')) is not int or events['n_events'] <= 0
            or events.get('trace_sha256') != trace_pin['sha256'] or ledger_pin['bytes'] <= 0):
        raise ValueError('exact native witness and corresponding scenario/output binding required')
    return {'witness': witness, 'events': events, 'trace': trace_pin, 'message_trace': ledger_pin}


def main():
    options = list(sys.argv[1:])
    if (not options or options[0] not in ('simulate', 'simulate-batch')
            or options.count('--cost-arm') != 1 or options.count('--cost-mode') != 1):
        raise ValueError('leading verb and two exact diagnostic options required')
    arm_position, mode_position = options.index('--cost-arm'), options.index('--cost-mode')
    if (arm_position + 2 != mode_position or mode_position + 2 != len(options)
            or options[arm_position + 1] not in ARMS or options[mode_position + 1] not in ('state', 'cost')):
        raise ValueError('trailing exact diagnostic arm/mode required')
    arm, mode = options[arm_position + 1], options[mode_position + 1]
    options = options[:arm_position]
    if any(value.split('=', 1)[0] in ('--arm', '--runtime', '--build', '--output-witness', '--mode') for value in options[1:]):
        raise ValueError('diagnostic owns internal source choices')
    if sys.getprofile() is not None or sys.gettrace() is not None:
        raise ValueError('fresh diagnostic profile and trace slots required')
    candidate = ROOT / ARMS[arm]
    source = candidate / 'production_cli.py'
    def file_pin(path):
        path = Path(path)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for data in iter(lambda: stream.read(1024**2), b''):
                digest.update(data)
        return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    # The host must freeze this actual image binding after delivery. Empty draft
    # bindings do not authorize a run or permit selecting another base image.
    binding_path = Path(__file__).with_name('IMAGE_BINDING.json')
    binding = json.loads(binding_path.read_bytes())
    if (binding.get('ready_for_linux') is not True or binding.get('runtime_changed') is not False
            or binding.get('candidate_source_files', {}).get(ARMS[arm], {}).get('production_cli.py')
            != file_pin(source)):
        raise ValueError('fresh actual frozen expectations image/source binding required')
    source_pin = file_pin(source)
    leading = options[0]
    def option_value(name):
        if options.count(name) != 1 or options.index(name) + 1 >= len(options):
            raise ValueError('exact leading diagnostic scenario/output options required')
        return options[options.index(name) + 1]
    if leading == 'simulate':
        scenario_paths = [Path(option_value('--config')).resolve()]
        expected_outputs = {None: Path(option_value('--out')).resolve()}
    else:
        batch_path = Path(option_value('--batch-dir')).resolve()
        scenario_paths = sorted(path.resolve() for path in batch_path.glob('*.json') if not path.name.startswith('._'))
        expected_outputs = {path.stem: Path(option_value('--out-dir')).resolve() / path.stem / 'trace.parquet'
            for path in scenario_paths}
    if not scenario_paths or len(scenario_paths) > 5 or len(expected_outputs) != len(scenario_paths):
        raise ValueError('finite unique actual input market roster required')
    expected_scenarios = {}
    for path in scenario_paths:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024**2:
            raise ValueError('finite regular staged scenario required')
        scenario = json.loads(path.read_bytes())
        sub = None if leading == 'simulate' else path.stem
        expected_scenarios[str(path)] = {'sub': sub, 'scenario_id': str(scenario['scenario_id']),
            'seed': int(scenario['seed']), 'scenario_path': str(path), 'scenario_source': file_pin(path)}
    temporary = Path('/tmp/expectations-cost-diagnostic-v1')
    temporary.mkdir()
    witness_path = temporary / ('single.json' if options[0] == 'simulate' else 'markets')
    ticks, milestones, retained, states = [], [], [], []
    originals, native_activity = [], []
    current_scenario = None
    seen_scenarios = []
    profiler = cProfile.Profile()
    active = False
    old_argv, old_path = list(sys.argv), list(sys.path)
    actual, original_simulate, prepared = None, None, None
    failure, original_error = None, None
    injected_installed = False

    def milestone(label):
        if len(milestones) >= MAX_TICKS:
            raise ValueError('finite diagnostic milestone roster exceeded')
        milestones.append({'phase': label, 'perf_counter': time.perf_counter()})

    def mark(label, config_path=None):
        nonlocal current_scenario
        if len(ticks) >= MAX_TICKS:
            raise ValueError('finite diagnostic phase roster exceeded')
        if label == 'simulate_enter':
            path = str(Path(config_path).resolve())
            if current_scenario is not None or path not in expected_scenarios or path in seen_scenarios:
                raise ValueError('one-to-one actual input/episode roster required')
            if file_pin(Path(path)) != expected_scenarios[path]['scenario_source']:
                raise ValueError('actual staged scenario bytes changed')
            current_scenario = dict(expected_scenarios[path])
            seen_scenarios.append(path)
        ticks.append({'phase': label, 'perf_counter': time.perf_counter(),
            'config_path': None if config_path is None else str(config_path)})

    def capture_bindings(kernel_class, summary_writer):
        if originals or retained:
            raise ValueError('one actual episode binding required')
        originals.append((kernel_class, summary_writer))

    def pause():
        nonlocal active
        was_active = active
        if active:
            profiler.disable()
            active = False
        return was_active

    def resume(was_active):
        nonlocal active
        if was_active:
            profiler.enable()
            active = True

    def emit_state(graph, identity):
        def block(data, index):
            print(BLOCK_PREFIX + json.dumps({'schema': 't3-expectations-cost-state-block-v1',
                'arm': arm, 'cost_mode': mode, **identity, 'block_index': index,
                'compressed_bytes': len(data), 'data_base64': base64.b64encode(data).decode('ascii'),
                'timing_included': False, 'rankable': False}, sort_keys=True), flush=True)
        return stream_state(graph, block)

    def state_snapshot(end_state, scenario):
        if len(originals) != 1 or retained:
            raise ValueError('one market/binding per diagnostic state required')
        was_active = pause()
        milestone('cold_state_snapshot_enter')
        try:
            import numpy as np
            import observer
            from control_graph import snapshot
            from native_owner_kernel import NativeOwnerKernel
            from state_mapper import Migration
            from dynamic_arena_chain import ChainScheduler
            kernel = end_state['agents'][0].kernel
            if (type(kernel) is not NativeOwnerKernel or type(kernel.__dict__) is not dict
                    or kernel.__dict__.get('agents') is not end_state['agents']
                    or type(kernel.__dict__.get('_chain_migration')) is not Migration
                    or type(kernel.__dict__.get('_chain_scheduler')) is not ChainScheduler
                    or current_scenario is None
                    or current_scenario['scenario_id'] != str(scenario['scenario_id'])
                    or current_scenario['seed'] != int(scenario['seed'])):
                raise ValueError('cost diagnostic requires actual native owner selection')
            migration = kernel.__dict__['_chain_migration']
            if migration.kernel is not kernel or migration.assert_authority() is not True:
                raise ValueError('exact native kernel migration authority required')
            scheduler = kernel.__dict__['_chain_scheduler']
            activity = {'orders': scheduler.orders.statistics(), 'messages': scheduler.messages.statistics()}
            if activity['orders']['order_slots'] <= 0 or activity['messages']['constructed_messages'] <= 0:
                raise ValueError('nonzero actual native owner activity required')
            native_activity.append(activity)
            graph = snapshot(end_state, np)
            identity = dict(current_scenario)
            emitted = emit_state(graph, identity)
            retained.append((end_state, observer.STATE, graph, identity))
            states.append({'schema': 't3-expectations-cost-full-state-v1', 'arm': arm, 'cost_mode': mode,
                **identity, **emitted, 'full_original_control_graph': True,
                'timing_included': False, 'rankable': False})
        finally:
            milestone('cold_state_snapshot_exit')
            resume(was_active)

    def finish_snapshot(end_state, scenario, out_path):
        nonlocal current_scenario
        if len(retained) != 1 or len(originals) != 1:
            raise ValueError('one retained completed output state required')
        was_active = pause()
        milestone('cold_state_output_compare_enter')
        try:
            import numpy as np
            import observer
            from control_graph import snapshot
            from abides_core import abides
            from abides_core.kernel import Kernel
            saved_state, episode, before, identity = retained.pop()
            if (saved_state is not end_state or identity != current_scenario
                    or identity['scenario_id'] != str(scenario['scenario_id']) or identity['seed'] != int(scenario['seed'])
                    or Path(out_path).resolve() != expected_outputs[identity['sub']]
                    or file_pin(Path(identity['scenario_path'])) != identity['scenario_source']):
                raise ValueError('exact retained actual state/scenario identity required')
            after = snapshot(end_state, np, episode)
            saved_kernel, saved_summary = originals.pop()
            if (after != before or observer.STATE is not None or abides.Kernel is not saved_kernel
                    or Kernel.write_summary_log is not saved_summary):
                raise ValueError('output changed state/RNG/aliases or binding restoration failed')
            states[-1].update(graph_output_readonly=True, observer_finished=True,
                kernel_and_summary_bindings_restored=True, actual_trace_output=str(Path(out_path).resolve()))
            current_scenario = None
        finally:
            milestone('cold_state_output_compare_exit')
            resume(was_active)

    try:
        sys.path.insert(0, str(candidate))
        sys.argv = [str(source), *options, '--arm', 'light_dynamic', '--output-witness', str(witness_path)]
        milestone('actual_entry_import_enter')
        if mode == 'cost':
            profiler.enable(); active = True
        spec = importlib.util.spec_from_file_location('production_cli', source)
        actual = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(actual)
        milestone('actual_entry_import_exit')
        original_simulate = actual.simulate
        instrument_active = pause()
        namespace = vars(actual)
        if any(name in namespace for name in INJECTED_NAMES):
            raise ValueError('fresh diagnostic helper globals required')
        namespace.update(_t3_cost_mark=mark, _t3_cost_state=state_snapshot,
            _t3_cost_finish=finish_snapshot, _t3_cost_bindings=capture_bindings)
        injected_installed = True
        try:
            prepared = instrument_simulate(namespace, source.read_bytes(), source, arm, source_pin)
        finally:
            resume(instrument_active)
        milestone('actual_main_enter')
        actual.main()
        milestone('actual_main_exit')
        if active:
            profiler.disable(); active = False
        files = [witness_path] if options[0] == 'simulate' else sorted(witness_path.glob('*.json'))
        if (retained or originals or current_scenario is not None or len(files) != len(states)
                or len(native_activity) != len(states) or seen_scenarios != list(expected_scenarios)):
            raise ValueError('complete diagnostic actual market/state roster required')
        files_by_sub = {None if leading == 'simulate' else path.stem: path for path in files}
        if len(files_by_sub) != len(files) or set(files_by_sub) != set(expected_outputs):
            raise ValueError('exact complete witness filename/sub roster required')
        for state, activity in zip(states, native_activity):
            path = files_by_sub[state['sub']]
            witness = json.loads(path.read_bytes())
            trace = expected_outputs[state['sub']]
            events = json.loads((trace.parent / 'events.json').read_bytes())
            bound = validate_witness(witness, state, events, file_pin(trace), file_pin(trace.parent / 'message_trace.parquet'))
            state.update(**bound, actual_native_activity=activity, witness_path=str(path), witness_source=file_pin(path))
            print(STATE_PREFIX + json.dumps(state, sort_keys=True, allow_nan=False), flush=True)
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
        original_error = sys.exc_info()
    finally:
        final_errors = []
        def remember(stage, error):
            final_errors.append({'stage': stage, 'type': type(error).__name__, 'message': str(error)})
        try:
            try:
                if active:
                    profiler.disable(); active = False
                if actual is not None and original_simulate is not None:
                    actual.simulate = original_simulate
                    if injected_installed:
                        for name in INJECTED_NAMES:
                            vars(actual).pop(name, None)
                sys.argv[:] = old_argv
                sys.path[:] = old_path
            except BaseException as error:
                remember('restore', error)
            try:
                restored = actual is not None and original_simulate is not None and actual.simulate is original_simulate
                stats = pstats.Stats(profiler).stats if mode == 'cost' else {}
                rows = profile_rows(stats)
                report = {'schema': 't3-expectations-cost-observation-v1', 'arm': arm, 'cost_mode': mode,
                    'source_sha256': source_pin['sha256'], 'actual_image_binding': binding,
                    'driver_started': DRIVER_STARTED, 'ticks': ticks, 'milestones': milestones,
                    'profile_stats': rows, 'prepared': prepared, 'simulate_alias_restored': restored,
                    'profile_slot_restored': sys.getprofile() is None, 'profiled_native_extension': False,
                    'profile_false_native_cdef_detail_missing': True,
                    'cold_snapshot_and_emission_profiler_disabled': True,
                    'diagnostic_AST_preparation_profiler_disabled': True,
                    'profile_segments_reset_caller_stack': True,
                    'diagnostic_wrapper_imports_before_profile': ['ast', 'base64', 'cProfile', 'copy', 'hashlib',
                        'importlib.util', 'json', 'math', 'pathlib', 'pstats', 'shutil', 'sys', 'zlib'],
                    'wrapper_and_profile_overhead_included_in_process_wall': True,
                    'diagnostic_timings_are_ordinary_partition': False,
                    'diagnostic_timings_prove_removable_owner_cost': False,
                    'failure': failure, 'finalization_errors': list(final_errors),
                    'observation_complete': failure is None and not final_errors,
                    'timing_included': False, 'rankable': False}
                encoded = json.dumps(report, sort_keys=True, allow_nan=False)
                if len(encoded.encode('utf-8')) > MAX_PROFILE_JSON:
                    raise ValueError('finite diagnostic profile JSON cap exceeded')
                print(PROFILE_PREFIX + encoded, flush=True)
            except BaseException as error:
                remember('profile_report', error)
        finally:
            try:
                shutil.rmtree(temporary)
            except BaseException as error:
                remember('temporary_cleanup', error)
        if final_errors:
            # Retain a bounded terminal error independent of profile formatting.
            try:
                print(PROFILE_PREFIX + json.dumps({'schema': 't3-expectations-cost-terminal-failure-v1',
                    'arm': arm, 'cost_mode': mode,
                    'original_failure': None if failure is None else {key: str(value)[:4096] for key, value in failure.items()},
                    'finalization_errors': [{key: str(value)[:4096] for key, value in item.items()} for item in final_errors[:8]],
                    'observation_complete': False, 'timing_included': False, 'rankable': False}, sort_keys=True), flush=True)
            except BaseException:
                pass
        if original_error is not None:
            raise original_error[1].with_traceback(original_error[2])
        if final_errors:
            raise ValueError('cost diagnostic finalization failed; terminal evidence retained')


if __name__ == '__main__':
    main()
