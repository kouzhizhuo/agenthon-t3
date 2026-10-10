"""Untimed, read-only execution census around the exact published production CLI."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys

ROOT = Path('/opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1')
SOURCE = ROOT / 'production_cli.py'
PREFIX = 'T3_STRUCTURAL_CENSUS_V1 '


def scalar(value):
    if value is None or type(value) in (bool, int, float, str):
        return value
    if type(value).__module__.startswith('numpy') and hasattr(value, 'item'):
        return scalar(value.item())
    raise TypeError('diagnostic primitive required')


def named(value):
    return type(value).__module__ + '.' + type(value).__qualname__


def protocol(exchange):
    return {'actual_exchange_class': named(exchange),
        'actual_stp_policy': scalar(exchange.stp_policy),
        'actual_pipeline_delay': scalar(exchange.pipeline_delay),
        'actual_computation_delay': scalar(exchange.computation_delay),
        'actual_book_logging': scalar(exchange.book_logging),
        'actual_book_log_depth': scalar(exchange.book_log_depth),
        'actual_symbols': [scalar(value) for value in exchange.symbols]}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('simulate', 'simulate-batch'):
        raise SystemExit('exact production verb required')
    if any(value.split('=', 1)[0] in ('--runtime', '--build', '--arm', '--output-witness')
           for value in sys.argv[2:]):
        raise ValueError('diagnostic wrapper owns internal arguments')
    if sys.getprofile() is not None:
        raise ValueError('fresh profiler slot required')
    verb = sys.argv[1]
    witness_root = Path('/tmp/structural-census-v1')
    if witness_root.exists():
        raise ValueError('fresh census temporary directory required')
    witness_root.mkdir()
    witness_path = witness_root / ('single.json' if verb == 'simulate' else 'markets')
    records = []
    pending = []
    config_source = str(ROOT / 'runtime/abides_fork/config.py')
    abides_source = str(ROOT / 'runtime/vendor/abides/abides-core/abides_core/abides.py')

    def profile(frame, event, result):
        if event != 'return':
            return
        code = frame.f_code
        if code.co_filename == config_source and code.co_name == 'build_config':
            if type(result) is not dict or not result.get('agents'):
                raise ValueError('actual config return absent')
            scenario = frame.f_locals['scenario']
            exchange, latency = result['agents'][0], result['agent_latency_model']
            row = {'scenario_id': str(scenario['scenario_id']), 'seed': int(scenario['seed']),
                'actual_config_protocol': protocol(exchange),
                'requested_exchange_config': scenario['exchange_config'],
                'actual_latency_class': named(latency),
                'actual_latency_model': scalar(getattr(latency, '_model', None)),
                'actual_latency_parameters': {name: scalar(getattr(latency, name, None))
                    for name in ('_mean_ns', '_sigma', '_min_ns', '_max_ns', '_alpha', '_mu')},
                'actual_agent_count': len(result['agents']),
                'actual_config_agent_classes': [named(agent) for agent in result['agents']],
                'actual_default_computation_delay': scalar(result['default_computation_delay']),
                'actual_start_time': scalar(result['start_time']),
                'actual_start_time_type': named(result['start_time']),
                'actual_stop_time': scalar(result['stop_time']),
                'actual_stop_time_type': named(result['stop_time'])}
            pending.append(row)
        elif code.co_filename == abides_source and code.co_name == 'run':
            if type(result) is not dict or len(pending) != 1:
                raise ValueError('one complete market per actual config required')
            row = pending.pop()
            agents = result['agents']
            kernel = agents[0].kernel
            row.update(actual_kernel_class=named(kernel),
                actual_end_protocol=protocol(agents[0]),
                actual_end_agent_classes=[named(agent) for agent in agents],
                actual_end_time=scalar(kernel.current_time),
                actual_end_time_type=named(kernel.current_time),
                actual_authority_migration=hasattr(kernel, '_chain_migration'))
            records.append(row)

    options = list(sys.argv[1:])
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(SOURCE), *options, '--arm', 'light_dynamic',
                '--output-witness', str(witness_path)]
    try:
        sys.setprofile(profile)
        try:
            runpy.run_path(str(SOURCE), run_name='__main__')
        finally:
            sys.setprofile(None)
        if pending:
            raise ValueError('unmatched actual config return')
        paths = [witness_path] if verb == 'simulate' else sorted(witness_path.glob('*.json'))
        if len(paths) != len(records):
            raise ValueError('actual market/witness count differs')
        for path, actual in zip(paths, records):
            witness = json.loads(path.read_bytes())
            report = {'schema': 't3-structural-census-market-v1',
                'sub': None if verb == 'simulate' else path.stem,
                'production_source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                'witness': witness, 'actual_execution': actual,
                'native_rejection_reason': (None if witness['native_admitted'] else
                    'source-authentication-returned-false' if not witness['source_authenticated'] else
                    'arena-admission-returned-false'),
                'observation': 'sys.setprofile return hook; participant functions and source unchanged',
                'timing_included': False, 'rankable': False}
            print(PREFIX + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    finally:
        sys.setprofile(None)
        shutil.rmtree(witness_root)


if __name__ == '__main__':
    main()
