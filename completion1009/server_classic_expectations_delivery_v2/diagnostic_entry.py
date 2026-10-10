"""Separate untimed pilot witness route around each unchanged production CLI."""
import base64
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys
import zlib

ROOT = Path('/opt/classic-native-kernels-v1/completion1009/candidates')
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
PREFIX = 'T3_STRUCTURAL_DIAGNOSTIC_V2 '
STATE_PREFIX = 'T3_STRUCTURAL_STATE_V2 '
BLOCK_PREFIX = 'T3_STRUCTURAL_STATE_BLOCK_V2 '


def main():
    options = list(sys.argv[1:])
    if not options or options[0] not in ('simulate', 'simulate-batch') or options.count('--mode') != 1:
        raise ValueError('leading verb and exact diagnostic mode required')
    position = options.index('--mode')
    if position + 1 != len(options) - 1 or options[position + 1] not in ARMS:
        raise ValueError('trailing diagnostic mode required')
    arm = options[position + 1]
    options = options[:position]
    if any(value.split('=', 1)[0] in ('--arm', '--runtime', '--build', '--output-witness') for value in options[1:]):
        raise ValueError('diagnostic route owns internal source choices')
    candidate = ROOT / ARMS[arm]
    source = candidate / 'production_cli.py'
    temporary = Path('/tmp/structural-pilot-witness-v2')
    temporary.mkdir()
    witness_path = temporary / ('single.json' if options[0] == 'simulate' else 'markets')
    actual, pending, state_rows, retained, bindings = [], [], [], [], []
    config_source = str(candidate / 'runtime/abides_fork/config.py')
    abides_source = str(candidate / 'runtime/vendor/abides/abides-core/abides_core/abides.py')

    def emit_state(graph, identity):
        encoder = json.JSONEncoder(ensure_ascii=True, indent=2, allow_nan=False)
        compressor = zlib.compressobj(6)
        digest = hashlib.sha256()
        size = 0
        block_count = 0
        pending_compressed = bytearray()
        def emit_block(block):
            nonlocal block_count
            print(BLOCK_PREFIX + json.dumps({'schema': 't3-structural-state-stream-block-v2',
                'arm': arm, 'scenario_id': identity['scenario_id'], 'seed': identity['seed'],
                'block_index': block_count, 'compressed_bytes': len(block),
                'data_base64': base64.b64encode(block).decode('ascii'),
                'timing_included': False, 'rankable': False}, sort_keys=True), flush=True)
            block_count += 1
        for fragment in encoder.iterencode(graph):
            data = fragment.encode('utf-8')
            digest.update(data)
            size += len(data)
            pending_compressed.extend(compressor.compress(data))
            while len(pending_compressed) >= 1024**2:
                emit_block(bytes(pending_compressed[:1024**2]))
                del pending_compressed[:1024**2]
        digest.update(b'\n')
        size += 1
        pending_compressed.extend(compressor.compress(b'\n'))
        pending_compressed.extend(compressor.flush())
        while pending_compressed:
            emit_block(bytes(pending_compressed[:1024**2]))
            del pending_compressed[:1024**2]
        return {'state_sha256': digest.hexdigest(), 'state_bytes': size, 'state_blocks': block_count}

    def profile(frame, event, value):
        if event != 'return':
            return
        code = frame.f_code
        if code.co_filename == config_source and code.co_name == 'build_config':
            scenario = frame.f_locals['scenario']
            pending.append({'scenario_id': str(scenario['scenario_id']), 'seed': int(scenario['seed'])})
            from abides_core import abides
            from abides_core.kernel import Kernel
            bindings.append((abides.Kernel, Kernel.write_summary_log))
        elif code.co_filename == abides_source and code.co_name == 'run':
            if len(pending) != 1:
                raise ValueError('one config per actual diagnostic market required')
            record = pending.pop()
            exchange = value['agents'][0]
            kernel = exchange.kernel
            books = list(exchange.order_books.values())
            record.update(actual_kernel=type(kernel).__module__ + '.' + type(kernel).__qualname__,
                actual_authority_migration=hasattr(kernel, '_chain_migration'),
                actual_book_classes=[type(book).__module__ + '.' + type(book).__qualname__ for book in books],
                actual_price_indexes=[book.price_index_witness() if hasattr(book, 'price_index_witness') else None for book in books],
                actual_stp_policy=exchange.stp_policy,
                actual_pipeline_delay=int(exchange.pipeline_delay), actual_computation_delay=int(exchange.computation_delay))
            actual.append(record)
            # Read actual index witness first. The known cold snapshot reads the
            # canonical business lists, so its alias exposure disables this
            # diagnostic index only after the completed market. No ordinary
            # performance process imports this control graph.
            import numpy as np
            import observer
            from control_graph import snapshot
            graph = snapshot(value, np)
            state_binding = emit_state(graph, record)
            retained.append((value, observer.STATE, graph, record))
            state_rows.append({'schema': 't3-classic-structural-full-state-v2',
                'scenario_id': record['scenario_id'], 'seed': record['seed'], 'arm': arm,
                **state_binding,
                'index_witness_recorded_before_business_alias_snapshot': True,
                'full_original_control_graph': True, 'timing_included': False, 'rankable': False})
        elif code.co_filename == str(source) and code.co_name == 'simulate':
            if len(retained) != 1:
                raise ValueError('one retained actual state per completed output episode required')
            state, episode, before, record = retained.pop()
            import numpy as np
            import observer
            from control_graph import snapshot
            after = snapshot(state, np, episode)
            if after != before or observer.STATE is not None:
                raise ValueError('output mutated full state/RNG/alias or left observer active')
            from abides_core import abides
            from abides_core.kernel import Kernel
            original_kernel, original_summary = bindings.pop()
            if abides.Kernel is not original_kernel or Kernel.write_summary_log is not original_summary:
                raise ValueError('production did not restore original kernel/summary bindings')
            state_rows[-1]['graph_output_readonly'] = True
            state_rows[-1]['observer_finished'] = True
            state_rows[-1]['kernel_and_summary_bindings_restored'] = True
            del after, before, state, episode

    sys.path.insert(0, str(candidate))
    sys.argv = [str(source), *options, '--arm', 'light_dynamic', '--output-witness', str(witness_path)]
    if sys.getprofile() is not None:
        raise ValueError('fresh profile slot required')
    try:
        sys.setprofile(profile)
        try:
            runpy.run_path(str(source), run_name='__main__')
        finally:
            sys.setprofile(None)
        files = [witness_path] if options[0] == 'simulate' else sorted(witness_path.glob('*.json'))
        if pending or retained or bindings or len(files) != len(actual) or len(state_rows) != len(actual):
            raise ValueError('actual pilot witness roster differs')
        for path, record in zip(files, actual):
            witness = json.loads(path.read_bytes())
            print(PREFIX + json.dumps({'schema': 't3-classic-structural-pilot-witness-v2', 'arm': arm,
                'sub': None if options[0] == 'simulate' else path.stem, 'actual_execution': record,
                'production_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'witness': witness,
                'native_rejection_reason': None if witness['native_admitted'] else
                    'source-authentication-returned-false' if not witness['source_authenticated'] else 'arena-admission-returned-false',
                'market_rerun': False, 'timing_included': False, 'rankable': False}, sort_keys=True), flush=True)
        for path, state in zip(files, state_rows):
            state['sub'] = None if options[0] == 'simulate' else path.stem
            print(STATE_PREFIX + json.dumps(state, sort_keys=True), flush=True)
    finally:
        sys.setprofile(None)
        shutil.rmtree(temporary)


if __name__ == '__main__':
    main()
