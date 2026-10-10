"""Separate frozen-source phase screen; retain full daemon and output evidence."""
import argparse
import json
from pathlib import Path
import sys
import uuid
HERE = Path(__file__).resolve().parent
PAYLOAD = Path('latency-startup-phase-v1-payload').resolve()
sys.path.insert(0, str(PAYLOAD / 'control'))
import controller as core
import common
from common import sha, write, inventory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--gate-kit', type=Path, required=True)
    args = parser.parse_args()
    args.evidence = args.evidence.resolve(); args.evidence.mkdir(exist_ok=True)
    args.docker = 'docker'; args.log_cap_bytes = 16 * 1024 ** 2
    args.timeout = 300; args.owner = uuid.uuid4().hex; args.gate_python = sys.executable
    ready = json.loads((args.evidence / 'BUILD_READY.json').read_bytes())
    original = ready['image_id']; source_plan = common.verify_payload(PAYLOAD)
    core.ENTRYPOINT = common.ENTRYPOINT
    # Dockerfile FROM requires a named local image reference, not a bare image ID.
    local_base = 't3-latency-phase-base:' + uuid.uuid4().hex
    core.call(args, ['docker', 'tag', original, local_base], 'phase-base-tag', 30)
    tagged = core.linux.image_metadata(args, local_base, args.evidence / 'phase-base-image')
    if tagged['id'] != original: raise ValueError('named local base must resolve exact built image')
    tag = 't3-latency-phases:' + uuid.uuid4().hex
    core.call(args, ['docker', 'build', '--platform', 'linux/amd64', '--pull=false', '--build-arg', 'SCREEN_IMAGE='+local_base,
        '-t', tag, '-f', str(HERE / 'Dockerfile'), str(HERE)], 'phase-image-build', 180)
    meta = core.linux.image_metadata(args, tag, args.evidence / 'phase-image')
    diagnostic = meta['id']; entry = ['/usr/local/bin/python', '-B', '/opt/t3-phase/entry.py']
    if meta['inspection']['Config']['Entrypoint'] != entry:
        raise ValueError('exact separate diagnostic entry required')
    # Inspect the actual diagnostic source installed in the derived image.
    core.ENTRYPOINT = entry
    copy_name = 't3-phase-source-' + uuid.uuid4().hex
    commands = core.linux.DockerCommands('docker', args.evidence / 'phase-source-commands', args.log_cap_bytes)
    copied = args.evidence / 'phase-installed'
    try:
        made = commands.call(['create', '--name', copy_name, '--label', core.linux.OWNER_LABEL+'='+args.owner,
            '--pull', 'never', diagnostic], 'create', 30)
        if not made['succeeded']: raise ValueError('diagnostic source container create failed')
        info, _ = commands.inspect(copy_name, cleanup=True)
        core.linux.require_owned(info, copy_name, args.owner, diagnostic)
        copied_result = commands.call(['cp', copy_name+':/opt/t3-phase', str(copied)], 'copy', 30)
        if not copied_result['succeeded']: raise ValueError('actual diagnostic source copy failed')
    finally:
        cleanup = core.linux.settle_container(commands, copy_name, args.owner, diagnostic, creation_uncertain=True)
        write(args.evidence / 'PHASE_SOURCE_COPY.json', {'commands':commands.rows, 'cleanup':cleanup, 'rankable':False})
    if not cleanup['settled'] or not cleanup['removed'] or not cleanup['final_absent'] or cleanup['errors']:
        raise ValueError('diagnostic source copy cleanup failed')
    expected_source = {name:{'bytes':(HERE/name).stat().st_size, 'sha256':sha(HERE/name)} for name in ('entry.py','phase_entry.py')}
    if inventory(copied) != expected_source: raise ValueError('actual diagnostic entry source differs')
    core.ENTRYPOINT = common.ENTRYPOINT
    roster = core.public.collect_plan(args.reference_root, ['t3-as06-throughput-fast', common.BATCH])
    write(args.evidence / 'PHASE_REFERENCE_PLAN.json', roster)
    # The existing unchanged gate requires nine admissions; use the same original
    # five-unit roster for controls, separate from the two diagnostic units.
    control_roster = core.public.collect_plan(args.reference_root, list(common.SINGLES) + [common.BATCH])
    admissions = []
    for item in control_roster['units']:
        for path in item['scenario_paths']:
            original_path = Path(path)
            admissions.append({'unit':item['unit'] + ('/' + original_path.stem if item['shape']=='batch' else ''),
                'scenario_sha256':sha(original_path), 'scenario':core.public.read_json(original_path)})
    bundle = {'proof_command':'light-typed-noise-latency-market-six-children-and-owned-Noise-latency-v1',
        'scenario':core.public.read_json(PAYLOAD / 'control/control_scenario.json'), 'admission_scenarios':admissions}
    if len(admissions) != 9: raise ValueError('exact nine original admissions required')
    rows = []; failure = None
    try:
        control_input = args.evidence / 'phase-control-input.json'; write(control_input, bundle)
        args.timeout = 3600
        execution, output = core.linux.run_container(args, original, 'controls',
            {'shape':'single', 'scenario_paths':[str(control_input)]}, args.evidence / 'phase-controls', args.owner, 'controls')
        args.timeout = 300
        if not execution['succeeded']: raise ValueError('current build actual controls failed')
        controls = core.validate_controls(output / 'controls', source_plan, bundle)
        write(args.evidence / 'PHASE_CONTROL_RESULT.json', {'passed':True, 'execution':execution, **controls})
        for item in roster['units']:
            for arm in ('light_canonical', 'light_dynamic'):
                core.ENTRYPOINT = common.ENTRYPOINT
                normal = core.run_one(args, original, arm, item, args.evidence / 'phase-normal' / item['unit'] / arm, 'n'+str(len(rows)))
                if not normal['passed']: raise ValueError('separate normal output/gates failed')
                core.ENTRYPOINT = entry
                phase = core.run_one(args, diagnostic, arm, item, args.evidence / 'phase-diagnostic' / item['unit'] / arm, 'p'+str(len(rows)))
                if not phase['passed']: raise ValueError('diagnostic output/gates failed')
                paired = core.pair(Path(phase['output']), Path(normal['output']), item)
                if not paired['passed']: raise ValueError('marker-only full output equivalence failed')
                stdout = Path(phase['execution']['attach']['stdout']['path'])
                prefix = 'T3_CONTINUOUS_NATIVE_UNTIMED_PHASES='
                lines = [line[len(prefix):] for line in stdout.read_text().splitlines() if line.startswith(prefix)]
                if len(lines) != 1: raise ValueError('one raw phase report required')
                report = json.loads(lines[0])
                if (report['source_sha256'] != source_plan['actual_entry_sources'][arm]['sha256']
                    or report['arm'] != arm or report['failure'] is not None
                    or not report['non_marker_AST_equal'] or not report['simulate_alias_restored']
                    or not report['phase_global_removed'] or report['trace_hook_used']
                    or report['timing_included'] or report['rankable']):
                    raise ValueError('actual frozen-source phase scope differs')
                if not report['diagnostic_overhead_included'] or len(report['milestones']) != 5:
                    raise ValueError('exact diagnostic milestone scope required')
                for ticks in (report['ticks'], report['milestones']):
                    times = [tick['perf_counter'] for tick in ticks]
                    if times != sorted(times): raise ValueError('phase clocks are nonmonotonic')
                expected = 1 if item['shape'] == 'single' else len(item['subs'])
                if sum(t['phase']=='simulate_enter' for t in report['ticks']) != expected:
                    raise ValueError('complete episode phase roster required')
                groups = []
                for tick in report['ticks']:
                    if tick['phase']=='simulate_enter': groups.append([])
                    if not groups: raise ValueError('marker before actual episode')
                    groups[-1].append(tick)
                expected_paths = ['/input/scenario.json'] if item['shape']=='single' else [
                    '/input/scenarios/' + Path(p).name for p in sorted(item['scenario_paths'])]
                if [g[0]['config_path'] for g in groups] != expected_paths:
                    raise ValueError('exact input phase order required')
                intervals = []
                for group in groups:
                    labels = [t['phase'] for t in group]
                    if labels[-1] != 'simulate_exit' or labels.count('simulation_enter') != 1 or labels.count('simulation_exit') != 1:
                        raise ValueError('complete actual simulation boundary required')
                    intervals.append({'config_path':group[0]['config_path'], 'intervals':[
                        {'phase':a['phase'], 'next_phase':b['phase'], 'seconds':b['perf_counter']-a['perf_counter']}
                        for a,b in zip(group,group[1:])]})
                rows.append({'unit':item['unit'], 'arm':arm, 'normal':normal, 'diagnostic':phase,
                    'raw_phase_report':report, 'intervals_diagnostic_only':intervals, 'output_equivalence':paired, 'timing_included':False})
                write(args.evidence / 'PHASE_RAW_RESULTS.json', rows)
    except BaseException as error:
        failure = {'type':type(error).__name__, 'message':str(error)}
        raise
    finally:
        core.ENTRYPOINT = common.ENTRYPOINT
        unchanged_references = all(sha(args.reference_root / item['unit'] / name)==value for item in roster['units']
            for mapping in (item['input_sha256'], item['reference_sha256']) for name,value in mapping.items())
        common.verify_payload(PAYLOAD)
        write(args.evidence / 'PHASE_SUMMARY.json' , {'all_passed':failure is None and len(rows)==4 and unchanged_references,
            'rows':rows, 'failure':failure, 'rankable':False, 'speed_claim':False,
            'original_inputs_references_unchanged':unchanged_references, 'planned_ordinary_containers':8, 'planned_controls_containers':1, 'source_plan_sha256':sha(PAYLOAD / 'SCREEN_PLAN.json')})

if __name__ == '__main__': main()
