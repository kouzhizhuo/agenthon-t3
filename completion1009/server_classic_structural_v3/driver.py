"""One build, complete controls, separate diagnostics, ordinary long-window comparison."""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import uuid

from source_copy import source_copy_command

HERE = Path(__file__).resolve().parent
PARENT = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
IMAGE_ROOT = '/opt/classic-native-kernels-v1'
ARMS = ('parent', 'expectations', 'price_index')
CANDIDATES = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1', 'price_index': 'classic_price_index_v3'}
UNITS = ('t3-s001-price-time-priority', 't3-as06-throughput-fast', 't3-mp01-stp-newest-baseline',
    't3-ra01-fundamental-shock-mid', 't3-mr-deep-book-state-size', 't3-gbatch-hetero-mix')
REPEATS, WARMUPS = 18, 2
VOLATILE = {'wall_clock_sec', 'events_per_sec', 'peak_memory_bytes', 'gpu_seconds'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024**2):
            digest.update(data)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if any(part.startswith('._') or part in ('__pycache__', '__MACOSX') for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError('source/evidence symlink refused')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def verify_payload(payload):
    expected = read(payload / 'STRUCTURAL_MANIFEST.json')['files']
    actual = inventory(payload)
    actual.pop('STRUCTURAL_MANIFEST.json', None)
    if expected != actual:
        raise ValueError('frozen structural source payload changed')
    return expected


def extract(args, linux, image, remote, target, label):
    name, owner = 't3-structural-source-' + uuid.uuid4().hex, uuid.uuid4().hex
    commands = linux.DockerCommands(args.docker, args.evidence / (label + '-commands'), args.log_cap_bytes)
    copied = False
    try:
        made = commands.call(['create', '--name', name, '--label', linux.OWNER_LABEL + '=' + owner,
            '--pull', 'never', image], 'create')
        if not made['succeeded']:
            raise ValueError('source-copy create failed')
        info, _ = commands.inspect(name, cleanup=True)
        linux.require_owned(info, name, owner, image)
        copied = source_copy_command(commands, linux, ['cp', name + ':' + remote, str(target)], 'copy', 120)['succeeded']
    finally:
        cleanup = linux.settle_container(commands, name, owner, image, creation_uncertain=True)
        write(args.evidence / (label + '.json'), {'commands': commands.rows, 'cleanup': cleanup,
            'container_never_started': True, 'timing_included': False})
    if not copied or not cleanup['settled'] or not cleanup['removed'] or not cleanup['final_absent'] or cleanup['errors']:
        raise ValueError('source-copy or exact container cleanup failed')


def validate_native(candidate, construction, arm, lock):
    receipt = candidate / 'SOURCE_PREPARATION_RECEIPT_v1.json'
    spec = read(candidate / 'compile_spec.json')
    source = read(receipt)
    expected = {row['path']: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in source['files']}
    if sha(receipt) != lock['source_receipt_sha256'] or expected != lock['source_files']:
        raise ValueError('installed candidate source receipt binding differs')
    for name, pin in expected.items():
        path = candidate / name
        if path.stat().st_size != pin['bytes'] or sha(path) != pin['sha256']:
            raise ValueError('installed actual source differs: ' + arm + '/' + name)
    translation = read(candidate / 'translation/TRANSLATION_RECEIPT.json')
    build = read(candidate / 'build/BUILD_RECEIPT.json')
    pins = {'source_receipt_sha256': sha(receipt), 'runtime_pins_sha256': sha(candidate / 'RUNTIME_PINS.json'),
        'compile_spec_sha256': sha(candidate / 'compile_spec.json')}
    for report in (translation, build):
        if any(report.get(name) != value for name, value in pins.items()) or report.get('dependencies') != spec['dependencies']:
            raise ValueError('actual source/dependency build authority differs')
        if report.get('participant_imported') is not False or report.get('market_executed') is not False:
            raise ValueError('build must not import participant or run market')
    if spec['compile_flags'] != ['-O2', '-fPIC', '-fno-fast-math', '-ffp-contract=off']:
        raise ValueError('numeric compiler flags changed')
    if translation['translation_succeeded'] is not True or build['build_succeeded'] is not True or build['extension_build_count'] != 1:
        raise ValueError('one successful actual native build per candidate required')
    if build['ABI'] != {'python': [3, 11, 17], 'implementation': 'cpython', 'platform': 'linux', 'machine': 'x86_64',
            'pointer_bits': 64, 'byteorder': 'little', 'extension_suffix': '.cpython-311-x86_64-linux-gnu.so'}:
        raise ValueError('actual pinned native ABI differs')
    for row in build['extensions']:
        path = candidate / 'build' / row['path']
        elf = path.read_bytes()
        if row['module'] != 'dynamic_arena_chain' or elf[:6] != b'\x7fELF\x02\x01' or int.from_bytes(elf[18:20], 'little') != 62 or sha(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise ValueError('actual native ELF artifact differs')
    if not inventory(candidate / 'build/objects'):
        raise ValueError('actual compiler object files required')
    for name in ('translation', 'build'):
        if inventory(candidate / name) != construction['partial_artifacts'][arm][name]:
            raise ValueError('full generated C/object/ELF receipt inventory changed')
    for row in translation['generated_C']:
        path = candidate / 'translation' / row['path']
        if sha(path) != row['sha256'] or path.stat().st_size != row['bytes']:
            raise ValueError('actual translation C receipt differs')
        matches = list((candidate / 'build/generated').rglob(path.name))
        if len(matches) != 1 or matches[0].read_bytes() != path.read_bytes():
            raise ValueError('translation C and compiler input C must be byte identical')
    ambient = build['ambient_flags']
    unsafe = ('-ffast-math', '-Ofast', '-funsafe-math-optimizations', '-ffinite-math-only', '-freciprocal-math', '-fassociative-math')
    if ambient != construction['ambient_flags'] or any(flag in value for value in ambient.values() for flag in unsafe):
        raise ValueError('actual ambient compiler numeric flags differ')
    if arm == 'expectations':
        pin = build.get('expectations', {})
        path = candidate / 'build' / pin.get('path', '')
        if pin.get('source_count') != 22 or pin.get('artifact_count') != 45 or not path.is_file() or sha(path) != pin.get('sha256') or path.stat().st_size != pin.get('bytes'):
            raise ValueError('actual cold expectation manifest pin differs')
        expectation = read(path)
        if expectation.get('participant_imported') is not False or expectation.get('market_executed') is not False or expectation.get('admission_cached') is not False:
            raise ValueError('expectations cannot store actual permanent admission')
        expected_artifacts = {'EXPECTATIONS.json'}
        for source_row in expectation['sources']:
            source_path = candidate / 'runtime' / source_row['source']
            if sha(source_path) != source_row['source_sha256'] or source_path.stat().st_size != source_row['source_bytes']:
                raise ValueError('expectation source bytes differ')
            for name in ('code', 'defaults'):
                artifact = source_row[name]
                generated = path.parent / artifact['path']
                if sha(generated) != artifact['sha256'] or generated.stat().st_size != artifact['bytes']:
                    raise ValueError('actual expectation artifact differs')
                expected_artifacts.add(artifact['path'])
        if set(inventory(path.parent)) != expected_artifacts:
            raise ValueError('unexpected or missing cold expectation artifacts')
    return {'source_receipt_sha256': sha(receipt), 'full_source_files': len(expected), 'build_receipt_sha256': sha(candidate / 'build/BUILD_RECEIPT.json'),
        'translation_C_equals_build_C': True, 'extension_builds': 1, 'actual_ABI': build['ABI'], 'passed': True}


def build(args, linux):
    verify_payload(args.payload)
    commands = linux.DockerCommands(args.docker, args.evidence / 'build-commands', args.log_cap_bytes)
    anon = args.evidence / 'anonymous-docker-config'
    anon.mkdir()
    prior = os.environ.get('DOCKER_CONFIG')
    os.environ['DOCKER_CONFIG'] = str(anon)
    try:
        pulled = commands.call(['pull', '--platform', 'linux/amd64', PARENT], 'anonymous-parent-pull', 900)
    finally:
        if prior is None:
            os.environ.pop('DOCKER_CONFIG', None)
        else:
            os.environ['DOCKER_CONFIG'] = prior
    if not pulled['succeeded']:
        raise ValueError('actual pinned parent pull failed')
    parent = linux.image_metadata(args, PARENT, args.evidence / 'parent-metadata')
    if PARENT not in parent['inspection']['RepoDigests']:
        raise ValueError('actual parent public digest differs')
    tag = 't3-classic-structural-v3:' + uuid.uuid4().hex
    actual = commands.call(['build', '--platform', 'linux/amd64', '--pull=false', '--progress=plain', '-t', tag,
        '-f', str(args.payload / 'harness/Dockerfile'), str(args.payload)], 'one-image-build', 4800)
    if not actual['succeeded']:
        raise ValueError('actual one-time structural image construction failed')
    meta = linux.image_metadata(args, tag, args.evidence / 'image-metadata')
    if meta['inspection']['Config']['Entrypoint'] != ['/usr/local/bin/python', '-B', '/opt/t3-classic-structural-v2/production_entry.py']:
        raise ValueError('actual symmetric measurement entry differs')
    installed = args.evidence / 'installed'
    extract(args, linux, meta['id'], IMAGE_ROOT, installed, 'installed-source-copy')
    construction = read(installed / 'structural-v2-construction/CONSTRUCTION_RESULT.json')
    write(args.evidence / 'ACTUAL_BUILD_INVENTORY.json', inventory(installed))
    if construction.get('all_passed') is not True or construction.get('participant_imported') is not False or construction.get('market_executed') is not False:
        raise ValueError('partial construction rejected; all build files retained')
    expected_commands = [(arm, label) for arm in ('expectations', 'price_index') for label in ('translation', 'native-build')]
    if [(row['arm'], row['label']) for row in construction['commands']] != expected_commands:
        raise ValueError('actual complete one-build command roster differs')
    for row in construction['commands']:
        log = installed / 'structural-v2-construction' / (row['arm'] + '-' + row['label'] + '.log')
        if row['returncode'] != 0 or row['timed_out'] or row['log'] != {'bytes': log.stat().st_size, 'sha256': sha(log)}:
            raise ValueError('actual bounded construction log differs')
    parent_lock = read(args.payload / 'PARENT_SOURCE_LOCK.json')
    if inventory(installed / 'completion1009/candidates/classic_native_kernels_v1') != parent_lock['candidate_files']:
        raise ValueError('unchanged official parent source/C/object/ELF required')
    locks = read(args.payload / 'CANDIDATE_SOURCE_LOCK.json')['arms']
    candidates = {}
    for arm in ('expectations', 'price_index'):
        candidates[arm] = validate_native(installed / 'completion1009/candidates' / CANDIDATES[arm], construction, arm, locks[arm])
    harness = args.evidence / 'installed-harness'
    extract(args, linux, meta['id'], '/opt/t3-classic-structural-v2', harness, 'harness-source-copy')
    if inventory(harness) != inventory(args.payload / 'harness'):
        raise ValueError('installed measurement/control/diagnostic harness differs')
    write(args.evidence / 'BUILD_READY.json', {'image_id': meta['id'], 'parent_image': PARENT, 'parent_source_ELF_equal': True,
        'candidate_builds': candidates, 'installed_inventory': inventory(installed), 'native_builds': 2,
        'market_executed': False, 'rankable': False, 'timing_included': False})


def worker(args, stage, arm, label, request, seconds=900):
    request_path = args.evidence / 'requests' / (label + '.json')
    result_path = args.evidence / 'worker-results' / (label + '.json')
    write(request_path, request)
    command = [sys.executable, '-B', str(HERE / 'worker.py'), stage, '--payload', str(args.payload),
        '--evidence', str(args.evidence), '--reference-root', str(args.reference_root), '--gate-kit', str(args.gate_kit),
        '--request', str(request_path), '--result', str(result_path)]
    log = args.evidence / 'worker-logs' / (label + '.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('xb') as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=seconds)
    write(log.with_suffix('.json'), {'command': command, 'returncode': process.returncode,
        'log': {'bytes': log.stat().st_size, 'sha256': sha(log)}})
    if process.returncode:
        raise ValueError('actual fresh worker failed: ' + label)
    return read(result_path)


def pair(a, b):
    ia, ib = inventory(a), inventory(b)
    if set(ia) != set(ib):
        raise ValueError('actual complete output roster differs')
    for name in ia:
        if name.endswith('.parquet'):
            if (a / name).read_bytes() != (b / name).read_bytes():
                raise ValueError('actual full trace/ledger Parquet bytes differ')
        elif {key: value for key, value in read(a / name).items() if key not in VOLATILE} != {key: value for key, value in read(b / name).items() if key not in VOLATILE}:
            raise ValueError('actual stable sidecar differs')
    return {'passed': True, 'complete_files': len(ia)}


def full_file_equal(a, b):
    if a.stat().st_size != b.stat().st_size:
        return False
    with a.open('rb') as left, b.open('rb') as right:
        while True:
            x, y = left.read(1024**2), right.read(1024**2)
            if x != y:
                return False
            if not x:
                return True


def validate_controls(args, arm, row, admissions):
    sys.path.insert(0, str(args.payload / 'control'))
    import controller as original_controller
    output = Path(row['output']) / 'controls'
    observed = read(output / 'ADMISSION.json')
    expected = [{'unit': item['unit'], 'scenario_sha256': item['scenario_sha256'],
        'source_authenticated': True, 'native_admitted': True} for item in admissions]
    if observed['cases'] != expected or observed.get('fresh_check_per_market') is not True or observed.get('market_executed') is not False:
        raise ValueError('all actual selected ten-market admissions required')
    fixtures = original_controller.validate_native_output_fixtures(output / 'native-fixtures')
    children = output / 'children'
    report = read(children / 'CONTROLS.json')
    if report.get('all_passed') is not True or len(report['cases']) != 8 or any(case['passed'] is not True for case in report['cases']):
        raise ValueError('original eight full six-child control gates required')
    names = ('original', 'light_canonical', 'light_dynamic', 'light_dynamic_repeat', 'decline_trace', 'decline_message_trace')
    baseline = children / 'original'
    for name in names:
        child = children / name
        for filename in ('trace.parquet', 'message_trace.parquet', 'STATE.json'):
            if (child / filename).read_bytes() != (baseline / filename).read_bytes():
                raise ValueError('complete original state/RNG/IDs/alias/heap/trace/ledger control differs')
        status = read(child / 'CONTROL_CHILD.json')
        if status['actual_markets'] != 1 or status['graph_output_readonly'] is not True or status['bindings_restored'] is not True or status['observer_finished'] is not True:
            raise ValueError('one market, immutable output graph and context restoration required')
        if name != 'original':
            witness = read(child / 'OUTPUT_WITNESS.json')
            if witness['source_authenticated'] is not True or witness['observer_admitted'] is not True or witness['market_rerun'] is not False:
                raise ValueError('actual authenticated control output episode required')
            native = name != 'light_canonical'
            declined = {'decline_trace': 'trace', 'decline_message_trace': 'message_trace'}.get(name)
            expected_kernel = 'NativeOwnerKernel' if native else 'CanonicalKernel'
            expected_mode = 'legacy-pandas' if declined else 'native-canonical-arrow-buffers' if native else 'canonical-arrow-buffers'
            if witness['native_admitted'] is not native or witness['selected_kernel'] != expected_kernel or witness['projectors_admitted'] is not (declined is None) or witness['output_mode'] != expected_mode or witness['native_output_pair'] is not (native and declined is None):
                raise ValueError('actual native/canonical/fallback selection differs')
            if witness['declines'] != ({} if declined is None else {declined: 'control-forced-projector-decline'}):
                raise ValueError('each forced projector must finish complete original output pair without rerun')
            if witness['actual_trace_sha256'] != sha(child / 'trace.parquet') or witness['actual_trace_rows'] != read(child / 'events.json')['n_events']:
                raise ValueError('control witness full actual trace binding differs')
            if status.get('production_import_attempts') != []:
                raise ValueError('ordinary control production dependency boundary differed')
        if name in ('light_dynamic', 'light_dynamic_repeat', 'decline_trace', 'decline_message_trace'):
            arena = read(child / 'ARENA_DIAGNOSTICS.json')
            if arena['orders']['order_slots'] <= 0 or arena['messages']['constructed_messages'] <= 0:
                raise ValueError('full controls require actual constructed native orders/messages')
    if read(children / 'light_dynamic/ARENA_DIAGNOSTICS.json') != read(children / 'light_dynamic_repeat/ARENA_DIAGNOSTICS.json'):
        raise ValueError('repeat actual arena lifecycle differs')
    extra = None
    if arm == 'expectations':
        extra = read(output / 'extra/BUILD_EXPECTATION_CONTROLS.json')
        if extra.get('all_passed') is not True or extra.get('market_executed') is not False or len(extra.get('cases', [])) != 30 or not all(case['passed'] is True for case in extra['cases']):
            raise ValueError('all cold expectation corruption/context negative controls required')
    elif arm == 'price_index':
        extra = read(output / 'PRICE_INDEX_CHECKS.json')
        if extra.get('all_passed') is not True or extra.get('market_executed') is not False or not all(case['passed'] is True for case in extra['cases']):
            raise ValueError('all native indexed book negative controls required')
    return {'arm': arm, 'native_fixture_readback': fixtures, 'full_STATE_RNG_alias_bytes_equal': True,
        'six_children': 6, 'admission_markets': len(admissions), 'extra': extra, 'passed': True, 'timing_included': False}


def screen(args, public):
    verify_payload(args.payload)
    plan = public.collect_plan(args.reference_root, list(UNITS))
    items = {item['unit']: item for item in plan['units']}
    if set(items) != set(UNITS) or len(items[UNITS[-1]]['subs']) != 5:
        raise ValueError('exact six-unit ten-market diagnostic roster required')
    write(args.evidence / 'REFERENCE_PLAN.json', plan)
    admissions = [{'unit': item['unit'] + ('/' + Path(path).stem if item['shape'] == 'batch' else ''),
        'scenario_sha256': public.sha256(path), 'scenario': public.read_json(path)} for item in plan['units'] for path in item['scenario_paths']]
    owner = uuid.uuid4().hex
    rows, diagnostic, controls, pairs, failure = [], [], {}, [], None
    before = worker(args, 'metadata', 'parent', 'before', {'folder': str(args.evidence / 'before')})
    first = {}
    try:
        for arm in ARMS:
            bundle = args.evidence / 'control-bundles' / (arm + '.json')
            write(bundle, {'structural_arm': arm, 'scenario': read(args.payload / 'control/control_scenario.json'),
                'admission_scenarios': admissions})
            row = worker(args, 'controls', arm, arm + '-controls', {'arm': arm, 'owner': owner,
                'bundle_path': str(bundle), 'folder': str(args.evidence / 'controls' / arm), 'suffix': arm + '-controls'}, 5400)
            controls[arm] = {'execution': row['execution'], **validate_controls(args, arm, row, admissions)}
        for arm in ARMS[1:]:
            for filename in ('trace.parquet', 'message_trace.parquet', 'STATE.json'):
                a = args.evidence / 'controls' / 'parent/output/controls/children/light_dynamic' / filename
                b = args.evidence / 'controls' / arm / 'output/controls/children/light_dynamic' / filename
                if a.read_bytes() != b.read_bytes():
                    raise ValueError('cross-version actual complete native state/output differs')
        for index, unit in enumerate(UNITS):
            state_parent = None
            for arm in ARMS:
                label = 'diagnostic-%02d-%s' % (index, arm)
                row = worker(args, 'diagnostic', arm, label, {'arm': arm, 'owner': owner, 'item': items[unit],
                    'folder': str(args.evidence / 'diagnostic' / arm / unit), 'suffix': label}, 3900)
                if not all(record['witness']['native_admitted'] is True for record in row['admission_witnesses']):
                    raise ValueError('pilot candidate must demonstrate actual native admission, not silent fallback')
                if arm == 'price_index' and not all(record['actual_execution']['actual_price_indexes'] and
                        all(index is not None and index.get('enabled') is True for index in record['actual_execution']['actual_price_indexes'])
                        for record in row['admission_witnesses']):
                    raise ValueError('pilot indexed candidate must demonstrate actual enabled index before snapshot')
                graphs = {receipt['sub']: Path(receipt['path']) for receipt in row['state_receipts']}
                if state_parent is None:
                    state_parent = graphs
                if set(graphs) != set(state_parent) or any(not full_file_equal(graphs[name], state_parent[name]) for name in graphs):
                    raise ValueError('each actual ten-market full state/RNG/alias graph must match parent')
                row['all_actual_market_full_STATE_RNG_alias_parent_equal'] = True
                diagnostic.append(row)
        for repeat in range(REPEATS):
            for index, unit in enumerate(UNITS):
                order = list(ARMS if (repeat + index) % 2 == 0 else reversed(ARMS))
                current = {}
                for arm in order:
                    label = 'r%02d-u%02d-%s' % (repeat, index, arm)
                    row = worker(args, 'one', arm, label, {'arm': arm, 'owner': owner, 'item': items[unit],
                        'folder': str(args.evidence / 'ordinary' / str(repeat) / arm / unit), 'suffix': label,
                        'repeat': repeat, 'warmup': repeat < WARMUPS, 'timing_included': repeat >= WARMUPS, 'order': order})
                    row.update(direct_arm=arm, repeat=repeat, warmup=repeat < WARMUPS,
                        timing_included=repeat >= WARMUPS, order=order)
                    rows.append(row)
                    current[arm] = row
                    write(args.evidence / 'raw-progress' / (label + '.json'), row)
                    print(label, 'PASS', flush=True)
                for arm in ARMS:
                    output = Path(current[arm]['output'])
                    previous = first.setdefault((unit, arm), output)
                    pairs.append({'unit': unit, 'arm': arm, 'repeat': repeat,
                        'same_round_parent': pair(output, Path(current['parent']['output'])),
                        'same_arm_repeat': pair(output, previous)})
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    after = worker(args, 'metadata', 'parent', 'after', {'folder': str(args.evidence / 'after')})
    unchanged = all(public.sha256(args.reference_root / item['unit'] / name) == digest for item in plan['units']
        for mapping in (item['input_sha256'], item['reference_sha256']) for name, digest in mapping.items())
    immutable = before['inspection'] == after['inspection']
    installed_unchanged = inventory(args.evidence / 'installed') == read(args.evidence / 'BUILD_READY.json')['installed_inventory']
    gates = sum(gate['passed'] is True for row in rows + diagnostic for gate in row['developer_verifier']['verdict']['gate_results'].values())
    executions = [row['execution'] for row in rows + diagnostic] + [row['execution'] for row in controls.values()]
    settled = all(ex['succeeded'] is True and ex['exit_code'] == 0 and ex['OOMKilled'] is False and ex['cleanup']['settled']
        and ex['cleanup']['removed'] and ex['cleanup']['final_absent'] and ex['cleanup']['errors'] == [] for ex in executions)
    from worker import duration, timestamp_ns
    intervals = []
    for execution in executions:
        state = execution['state']
        if duration(state) <= 0:
            raise ValueError('positive real process interval required')
        intervals.append((timestamp_ns(state['StartedAt']), timestamp_ns(state['FinishedAt']), execution['name']))
    intervals.sort()
    serial = len(intervals) == len({row[2] for row in intervals}) and all(a[1] < b[0] for a, b in zip(intervals, intervals[1:]))
    write(args.evidence / 'RAW_RESULTS.json', rows)
    write(args.evidence / 'DIAGNOSTIC_RESULTS.json', diagnostic)
    write(args.evidence / 'CONTROLS.json', controls)
    write(args.evidence / 'PAIRS.json', pairs)
    rates = []
    for unit in UNITS:
        medians = {arm: statistics.median(row['EPS'] for row in rows if row['unit'] == unit and row['direct_arm'] == arm and row['timing_included'])
            for arm in ARMS if len([row for row in rows if row['unit'] == unit and row['direct_arm'] == arm and row['timing_included']]) == REPEATS - WARMUPS}
        if len(medians) == 3:
            rates.append({'unit': unit, 'median_EPS': medians,
                'candidate_vs_parent': {arm: medians[arm] / medians['parent'] for arm in ARMS[1:]}})
    means = {arm: statistics.mean(row['median_EPS'][arm] for row in rates) for arm in ARMS} if len(rates) == len(UNITS) else None
    state_graphs = sum(len(row['state_receipts']) for row in diagnostic)
    summary = {'all_passed': failure is None and len(rows) == 324 and len(diagnostic) == 18 and state_graphs == 30 and len(controls) == 3
        and len(pairs) == 324 and gates == 1368 and unchanged and immutable and installed_unchanged and settled and serial,
        'failure': failure, 'ordinary_runs': len(rows), 'measured_runs': sum(row['timing_included'] for row in rows),
        'untimed_diagnostic_runs': len(diagnostic), 'untimed_control_containers': len(controls), 'official_gate_passes': gates,
        'untimed_complete_market_STATE_graphs': state_graphs,
        'public_references_unchanged': unchanged, 'image_immutable': immutable, 'installed_artifacts_unchanged': installed_unchanged,
        'all_settled_removed': settled, 'per_unit': rates, 'six_unit_mean_of_median_EPS': means,
        'actual_serial_execution_intervals': serial,
        'candidate_vs_parent': None if means is None else {arm: means[arm] / means['parent'] for arm in ARMS[1:]},
        'repeat_policy': {'total': REPEATS, 'warmups_discarded': WARMUPS, 'measured': REPEATS-WARMUPS, 'balanced_AB_BA_per_candidate': True},
        'timing_scope': 'ordinary production Docker daemon StartedAt to FinishedAt, actual full output event count divided by runtime',
        'full71': False, 'official_submission': False, 'rankable': False, 'threshold_232000_verified': False}
    write(args.evidence / 'SUMMARY.json', summary)
    if not summary['all_passed']:
        raise ValueError('complete structural long-window screen failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('build', 'screen', 'artifact'))
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--gate-kit', type=Path, required=True)
    parser.add_argument('--artifact', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('real Linux amd64 only; no local simulator or native compilation')
    args.payload, args.evidence = args.payload.resolve(), args.evidence.resolve()
    args.reference_root, args.gate_kit = args.reference_root.resolve(), args.gate_kit.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.payload / 'host'))
    import verify_linux as linux
    import verify_public as public
    args.docker, args.log_cap_bytes = 'docker', 16 * 1024**2
    if args.stage == 'build':
        build(args, linux)
    elif args.stage == 'screen':
        screen(args, public)
    else:
        if args.artifact is None or args.artifact.exists():
            raise ValueError('fresh full evidence artifact required')
        shutil.copytree(args.evidence, args.artifact / 'evidence', ignore=shutil.ignore_patterns('anonymous-docker-config'))
        shutil.copytree(args.payload, args.artifact / 'source-payload')
        for name in ('driver.py', 'worker.py', 'source_copy.py', 'SOURCE_PINS.json', 'verify_source.py', 'README.md'):
            shutil.copyfile(HERE / name, args.artifact / name)
        write(args.artifact / 'ARTIFACT.json', {'files': inventory(args.artifact),
            'all_actual_output_bytes_retained': True, 'full71': False, 'rankable': False})


if __name__ == '__main__':
    main()
