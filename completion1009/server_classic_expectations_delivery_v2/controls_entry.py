"""Untimed finite original controls and candidate-specific negative witnesses."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path('/opt/classic-native-kernels-v1')
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def run(command, log, seconds):
    with log.open('xb') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=seconds)
    if result.returncode:
        raise ValueError('untimed actual control failed: ' + log.name)
    return {'command': command, 'returncode': result.returncode,
        'log': {'bytes': log.stat().st_size, 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('verb', choices=('simulate',))
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.config != '/input/scenario.json' or args.out != '/output/trace.parquet':
        raise ValueError('fixed isolated control bundle paths required')
    bundle = json.loads(Path(args.config).read_bytes())
    arm = bundle['structural_arm']
    if arm not in ARMS or len(bundle['admission_scenarios']) != 10:
        raise ValueError('exact six-unit ten-market structural control roster required')
    candidate = ROOT / 'completion1009/candidates' / ARMS[arm]
    runtime, build = candidate / 'runtime', candidate / 'build'
    baseline = ROOT / 'completion1009/candidates/lean_production_native_projection_v1/runtime'
    out = Path('/output/controls')
    out.mkdir()
    scenario = out / 'scenario.json'
    write(scenario, bundle['scenario'])
    sys.path.insert(0, str(candidate))
    from source_provenance import verify_sources, verify_runtime
    verify_sources()
    verify_runtime(runtime)
    from production_cli import activate_paths
    activate_paths(runtime)
    from native_loader import load
    engine = load(build, runtime)['dynamic_arena_chain']
    from observer_domain import authenticate_loaded
    from arena_admission import admit
    admissions = []
    for row in bundle['admission_scenarios']:
        authenticated = authenticate_loaded()
        admitted = authenticated and admit(row['scenario'], runtime)
        admissions.append({'unit': row['unit'], 'scenario_sha256': row['scenario_sha256'],
            'source_authenticated': authenticated, 'native_admitted': admitted})
    write(out / 'ADMISSION.json', {'cases': admissions, 'fresh_check_per_market': True,
        'source_and_native_ELF_checked': True, 'market_executed': False, 'rankable': False})
    if not all(row['native_admitted'] for row in admissions):
        raise ValueError('selected structural pilot market not admitted to actual native path')
    commands = []
    commands.append(run([sys.executable, '-B', str(candidate / 'controls/native_output_fixtures_v1.py'),
        '--baseline-runtime', str(baseline), '--runtime', str(runtime), '--build', str(build),
        '--out', str(out / 'native-fixtures')], out / 'native-fixtures.log', 1200))
    commands.append(run([sys.executable, '-B', str(candidate / 'controls/controls.py'),
        '--baseline-runtime', str(baseline), '--runtime', str(runtime), '--build', str(build),
        '--config', str(scenario), '--out', str(out / 'children')], out / 'children.log', 3600))
    if arm == 'expectations':
        commands.append(run([sys.executable, '-B', str(candidate / 'controls/build_expectation_controls_v1.py'),
            '--runtime', str(runtime), '--build', str(build), '--out', str(out / 'extra')], out / 'extra.log', 1200))
    write(out / 'STRUCTURAL_CONTROL_RESULT.json', {'arm': arm, 'all_passed': True,
        'commands': commands, 'six_independent_markets_and_full_state_graph': True,
        'source_native_admission_and_extra_controls': True, 'timing_included': False, 'rankable': False})


if __name__ == '__main__':
    main()
