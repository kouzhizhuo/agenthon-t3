"""One expectation build, full controls and official-entry full71 delivery verification."""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time
import uuid

from source_copy import source_copy_command

HERE = Path(__file__).resolve().parent
PARENT = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
IMAGE_ROOT = '/opt/classic-native-kernels-v1'
ARMS = ('parent', 'expectations')
CANDIDATES = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
UNITS = ('t3-s001-price-time-priority', 't3-as06-throughput-fast', 't3-mp01-stp-newest-baseline',
    't3-ra01-fundamental-shock-mid', 't3-mr-deep-book-state-size', 't3-gbatch-hetero-mix')
FIVE = (UNITS[0], UNITS[1], UNITS[2], UNITS[3], UNITS[-1])
ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
PUBLIC_REPOSITORY = 'ghcr.io/kouzhizhuo/agenthon-t3-classic'
SCREEN_BUDGET_SEC = 7200
WORKER_CLEANUP_GRACE_SEC = 90
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
    tag = 't3-classic-expectations-delivery-v1:' + uuid.uuid4().hex
    actual = commands.call(['build', '--platform', 'linux/amd64', '--pull=false', '--progress=plain', '-t', tag,
        '-f', str(args.payload / 'harness/Dockerfile'), str(args.payload)], 'one-image-build', 4800)
    if not actual['succeeded']:
        raise ValueError('actual one-time structural image construction failed')
    meta = linux.image_metadata(args, tag, args.evidence / 'image-metadata')
    image_config = meta['inspection']['Config']
    if (image_config['Entrypoint'] != ENTRY or image_config.get('Cmd') not in ([], None)
            or image_config.get('User') != '65534:65534' or image_config.get('WorkingDir') != '/output'
            or image_config.get('Volumes') or image_config['Labels'].get('qfbench2.interface_version') != '2.0'
            or image_config['Labels'].get('qfbench2.license') != 'BSD-3-Clause'
            or image_config['Labels'].get('org.opencontainers.image.licenses') != 'BSD-3-Clause'):
        raise ValueError('actual final default-entry contract differs')
    installed = args.evidence / 'installed'
    extract(args, linux, meta['id'], IMAGE_ROOT, installed, 'installed-source-copy')
    construction = read(installed / 'structural-v2-construction/CONSTRUCTION_RESULT.json')
    write(args.evidence / 'ACTUAL_BUILD_INVENTORY.json', inventory(installed))
    if construction.get('all_passed') is not True or construction.get('participant_imported') is not False or construction.get('market_executed') is not False:
        raise ValueError('partial construction rejected; all build files retained')
    expected_commands = [(arm, label) for arm in ('expectations',) for label in ('translation', 'native-build')]
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
    for arm in ('expectations',):
        candidates[arm] = validate_native(installed / 'completion1009/candidates' / CANDIDATES[arm], construction, arm, locks[arm])
    harness = args.evidence / 'installed-harness'
    extract(args, linux, meta['id'], '/opt/t3-classic-structural-v2', harness, 'harness-source-copy')
    if inventory(harness) != inventory(args.payload / 'harness'):
        raise ValueError('installed public/control/diagnostic harness differs')
    if (installed / 'delivery_entry.py').read_bytes() != (args.payload / 'harness/delivery_entry.py').read_bytes():
        raise ValueError('actual public entry bytes differ from reviewed source')
    licenses = args.evidence / 'installed-licenses'
    extract(args, linux, meta['id'], '/licenses', licenses, 'licenses-source-copy')
    if (licenses / 'LICENSE-SUBMISSION').read_bytes() != (args.payload / 'harness/LICENSE-SUBMISSION').read_bytes():
        raise ValueError('actual participant BSD3 licence grant differs')
    write(args.evidence / 'BUILD_READY.json', {'image_id': meta['id'], 'parent_image': PARENT, 'parent_source_ELF_equal': True,
        'candidate_builds': candidates, 'installed_inventory': inventory(installed), 'harness_inventory': inventory(harness),
        'licenses_inventory': inventory(licenses), 'entry_sha256': sha(installed / 'delivery_entry.py'),
        'licence_sha256': sha(licenses / 'LICENSE-SUBMISSION'), 'native_builds': 1,
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
    sys.path.insert(0, str(args.payload / 'host'))
    import verify_linux as linux
    deadline = min(time.monotonic() + seconds, getattr(args, 'screen_deadline', math.inf))
    process, failure = None, None
    record = {'command': command, 'worker_timeout_sec': seconds,
        'cleanup_grace_sec': WORKER_CLEANUP_GRACE_SEC, 'rankable': False}
    with log.open('xb') as stream:
        try:
            linux.check_cancelled()
            if deadline <= time.monotonic():
                raise TimeoutError('finite delivery screen budget exhausted before new worker')
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True)
            record['pid'] = process.pid
            while process.poll() is None:
                linux.check_cancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError('finite delivery worker or whole-screen budget reached')
                try:
                    process.wait(timeout=min(.1, max(.001, deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            failure = error
            record['failure'] = {'type': type(error).__name__, 'message': str(error)}
            if process is not None and process.poll() is None:
                # Signal the owned worker first. Its registered cancellation
                # handler lets the unchanged host verifier settle the container.
                process.send_signal(signal.SIGTERM)
                record['graceful_worker_SIGTERM_sent'] = True
                try:
                    process.wait(timeout=WORKER_CLEANUP_GRACE_SEC)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    record['owned_worker_group_SIGKILL_after_grace'] = True
                    process.wait(timeout=5)
        finally:
            record['returncode'] = process.returncode if process is not None else None
            record['worker_reaped'] = process is not None and process.returncode is not None
    record['log'] = {'bytes': log.stat().st_size, 'sha256': sha(log)}
    write(log.with_suffix('.json'), record)
    if failure is not None:
        raise failure
    if process is None or process.returncode:
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
    return {'arm': arm, 'native_fixture_readback': fixtures, 'full_STATE_RNG_alias_bytes_equal': True,
        'six_children': 6, 'admission_markets': len(admissions), 'extra': extra, 'passed': True, 'timing_included': False}


def screen(args, public):
    args.screen_deadline = time.monotonic() + SCREEN_BUDGET_SEC
    verify_payload(args.payload)
    plan = public.collect_plan(args.reference_root, None)
    items = {item['unit']: item for item in plan['units']}
    if len(items) != 71 or plan['reference_frame_count'] != 190 or not set(UNITS).issubset(items) or len(items[UNITS[-1]]['subs']) != 5:
        raise ValueError('all71 units and190 original reference frames required')
    write(args.evidence / 'REFERENCE_PLAN.json', plan)
    admissions = [{'unit': item['unit'] + ('/' + Path(path).stem if item['shape'] == 'batch' else ''),
        'scenario_sha256': public.sha256(path), 'scenario': public.read_json(path)}
        for unit in UNITS for item in (items[unit],) for path in item['scenario_paths']]
    if len(admissions) != 10:
        raise ValueError('exact six-unit ten-market admission prerequisite required')
    schedule = [(0, unit) for unit in sorted(items)] + [(repeat, unit) for repeat in range(1, 5) for unit in FIVE]
    write(args.evidence / 'ORDINARY_SCHEDULE.json', {'public_entry': ENTRY, 'runs': [
        {'index': index, 'repeat': repeat, 'unit': unit, 'arm': 'expectations', 'internal_mode': False}
        for index, (repeat, unit) in enumerate(schedule)], 'runs_count': 91,
        'expected_gates': 364, 'expected_actual_Parquet_copies': 262,
        'full71': True, 'official_submission': False, 'rankable': False})
    owner = uuid.uuid4().hex
    rows, diagnostic, controls, pairs, failure = [], [], {}, [], None
    before = worker(args, 'metadata', 'expectations', 'before', {'folder': str(args.evidence / 'before')})
    first = {}
    try:
        for arm in ARMS:
            bundle = args.evidence / 'control-bundles' / (arm + '.json')
            write(bundle, {'structural_arm': arm, 'scenario': read(args.payload / 'control/control_scenario.json'),
                'admission_scenarios': admissions})
            row = worker(args, 'controls', arm, arm + '-controls', {'arm': arm, 'owner': owner,
                'bundle_path': str(bundle), 'folder': str(args.evidence / 'controls' / arm), 'suffix': arm + '-controls'}, 5400)
            controls[arm] = {'execution': row['execution'], **validate_controls(args, arm, row, admissions)}
        for filename in ('trace.parquet', 'message_trace.parquet', 'STATE.json'):
            a = args.evidence / 'controls/parent/output/controls/children/light_dynamic' / filename
            b = args.evidence / 'controls/expectations/output/controls/children/light_dynamic' / filename
            if not full_file_equal(a, b):
                raise ValueError('cross-version complete native control state/output differs')
        for index, unit in enumerate(UNITS):
            state_parent = None
            for arm in ARMS:
                label = 'diagnostic-%02d-%s' % (index, arm)
                row = worker(args, 'diagnostic', arm, label, {'arm': arm, 'owner': owner, 'item': items[unit],
                    'folder': str(args.evidence / 'diagnostic' / arm / unit), 'suffix': label}, 3900)
                if not all(record['witness']['native_admitted'] is True for record in row['admission_witnesses']):
                    raise ValueError('all selected actual markets must demonstrate native admission')
                graphs = {receipt['sub']: Path(receipt['path']) for receipt in row['state_receipts']}
                if state_parent is None:
                    state_parent = graphs
                if set(graphs) != set(state_parent) or any(not full_file_equal(graphs[name], state_parent[name]) for name in graphs):
                    raise ValueError('each actual ten-market full STATE/RNG/alias graph must match parent')
                row['all_actual_market_full_STATE_RNG_alias_parent_equal'] = True
                diagnostic.append(row)
        for index, (repeat, unit) in enumerate(schedule):
            label = 'ordinary-%03d-r%d-%s' % (index, repeat, unit)
            row = worker(args, 'one', 'expectations', label, {'arm': 'expectations', 'owner': owner,
                'item': items[unit], 'folder': str(args.evidence / 'ordinary' / str(repeat) / unit), 'suffix': str(index),
                'repeat': repeat, 'warmup': repeat == 0, 'timing_included': repeat > 0, 'order': index}, 900)
            row.update(direct_arm='expectations', actual_public_default_entry=True)
            rows.append(row)
            output = Path(row['output'])
            previous = first.setdefault(unit, output)
            pairs.append({'unit': unit, 'repeat': repeat, 'same_arm_repeat': pair(output, previous)})
            write(args.evidence / 'raw-progress' / (label + '.json'), row)
            print(label, 'PASS', flush=True)
    except BaseException as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    after = worker(args, 'metadata', 'expectations', 'after', {'folder': str(args.evidence / 'after')})
    ready = read(args.evidence / 'BUILD_READY.json')
    installed_after = args.evidence / 'installed-after'
    harness_after = args.evidence / 'installed-harness-after'
    licenses_after = args.evidence / 'installed-licenses-after'
    sys.path.insert(0, str(args.payload / 'host'))
    import verify_linux as linux
    for remote, target, label in ((IMAGE_ROOT, installed_after, 'installed-after-copy'),
            ('/opt/t3-classic-structural-v2', harness_after, 'harness-after-copy'),
            ('/licenses', licenses_after, 'licenses-after-copy')):
        extract(args, linux, ready['image_id'], remote, target, label)
    unchanged = all(public.sha256(args.reference_root / item['unit'] / name) == digest for item in plan['units']
        for mapping in (item['input_sha256'], item['reference_sha256']) for name, digest in mapping.items())
    immutable = before['inspection'] == after['inspection']
    installed_unchanged = (inventory(installed_after) == ready['installed_inventory']
        and inventory(harness_after) == ready['harness_inventory']
        and inventory(licenses_after) == ready['licenses_inventory'])
    ordinary_gates = sum(gate['passed'] is True for row in rows for gate in row['developer_verifier']['verdict']['gate_results'].values())
    diagnostic_gates = sum(gate['passed'] is True for row in diagnostic for gate in row['developer_verifier']['verdict']['gate_results'].values())
    actual_parquets = sum(sum(name.endswith('.parquet') for name in inventory(Path(row['output']))) for row in rows)
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
    write(args.evidence / 'SERIAL_INTERVALS.json', {'intervals': intervals, 'all_actual_execution_intervals_serial': serial,
        'ordinary': len(rows), 'untimed_diagnostics': len(diagnostic), 'untimed_controls': len(controls),
        'source_copy_containers_never_started': True, 'rankable': False})
    rates = []
    for unit in FIVE:
        selected = [row['EPS'] for row in rows if row['unit'] == unit and row['repeat'] > 0]
        if len(selected) == 4:
            rates.append({'unit': unit, 'total_runs': 5, 'warmup_discarded': 1,
                'measured_runs': 4, 'median_EPS': statistics.median(selected)})
    graphs = sum(len(row['state_receipts']) for row in diagnostic)
    verbs = {row['execution']['effective_config']['Config']['Cmd'][0] for row in rows}
    summary = {'all_passed': failure is None and len(rows) == 91 and len(first) == 71 and len(pairs) == 91
        and ordinary_gates == 364 and actual_parquets == 262 and len(diagnostic) == 12 and diagnostic_gates == 48
        and graphs == 20 and len(controls) == 2 and unchanged and immutable and installed_unchanged and settled and serial
        and verbs == {'simulate', 'simulate-batch'},
        'failure': failure, 'ordinary_runs': len(rows), 'ordinary_official_gate_passes': ordinary_gates,
        'ordinary_actual_Parquet_copies': actual_parquets, 'full71': len(first) == 71,
        'both_actual_default_entry_public_verbs': sorted(verbs), 'untimed_diagnostic_runs': len(diagnostic),
        'untimed_diagnostic_gate_passes': diagnostic_gates, 'untimed_complete_market_STATE_graphs': graphs,
        'untimed_control_containers': len(controls), 'total_actual_executions': len(executions),
        'public_references_unchanged': unchanged, 'image_immutable': immutable, 'installed_artifacts_unchanged': installed_unchanged,
        'all_settled_removed': settled, 'actual_serial_execution_intervals': serial, 'repeat_units': rates,
        'five_unit_mean_of_median_EPS': statistics.mean(row['median_EPS'] for row in rates) if len(rates) == 5 else None,
        'timing_scope': 'ordinary final default-entry Docker daemon StartedAt to FinishedAt; actual full output events divided by runtime',
        'diagnostic_control_and_construction_timings_excluded': True, 'official_submission': False, 'rankable': False,
        'threshold_232000_verified': False}
    write(args.evidence / 'SUMMARY.json', summary)
    if not summary['all_passed']:
        raise ValueError('complete final default-entry full71 delivery verification failed')


def publication(args, linux):
    if not read(args.evidence / 'SUMMARY.json')['all_passed'] or not args.tag or not args.tag.startswith(PUBLIC_REPOSITORY + ':'):
        raise ValueError('all final delivery checks and exact public repository tag required')
    ready = read(args.evidence / 'BUILD_READY.json')
    commands = linux.DockerCommands(args.docker, args.evidence / 'publication-commands', args.log_cap_bytes)
    prior = os.environ.get('DOCKER_CONFIG')
    anonymous = args.evidence / 'anonymous-published-config'
    anonymous.mkdir()
    os.environ['DOCKER_CONFIG'] = str(anonymous)
    try:
        pulled = commands.call(['pull', '--platform', 'linux/amd64', args.tag], 'anonymous-published-pull', 900)
        if not pulled['succeeded']:
            raise ValueError('anonymous published image pull failed')
        meta = linux.image_metadata(args, args.tag, args.evidence / 'published-metadata')
    finally:
        if prior is None:
            os.environ.pop('DOCKER_CONFIG', None)
        else:
            os.environ['DOCKER_CONFIG'] = prior
    refs = set(ref for ref in meta['inspection']['RepoDigests'] if ref.startswith(PUBLIC_REPOSITORY + '@sha256:'))
    if meta['id'] != ready['image_id'] or len(refs) != 1:
        raise ValueError('one immutable published digest and tested image equality required')
    write(args.evidence / 'PUBLICATION.json', {'image': next(iter(refs)), 'image_id': ready['image_id'],
        'anonymous_pull_passed': True, 'tested_image_id_equal': True, 'official_submission': False})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('build', 'screen', 'publication', 'artifact'))
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--gate-kit', type=Path, required=True)
    parser.add_argument('--artifact', type=Path)
    parser.add_argument('--tag')
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
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, linux.cancellation)
    if args.stage == 'build':
        build(args, linux)
    elif args.stage == 'screen':
        screen(args, public)
    elif args.stage == 'publication':
        publication(args, linux)
    else:
        if args.artifact is None or args.artifact.exists():
            raise ValueError('fresh full evidence artifact required')
        shutil.copytree(args.evidence, args.artifact / 'evidence', ignore=shutil.ignore_patterns('anonymous-docker-config', 'anonymous-published-config', 'registry-config'))
        shutil.copytree(args.payload, args.artifact / 'source-payload')
        for name in [*read(HERE / 'SOURCE_PINS.json')['files'], 'SOURCE_PINS.json']:
            shutil.copyfile(HERE / name, args.artifact / name)
        write(args.artifact / 'ARTIFACT.json', {'files': inventory(args.artifact),
            'all_actual_output_bytes_retained': True,
            'full71': (read(args.evidence / 'SUMMARY.json').get('full71') if (args.evidence / 'SUMMARY.json').is_file() else False),
            'rankable': False})


if __name__ == '__main__':
    main()
