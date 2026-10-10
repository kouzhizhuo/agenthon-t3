"""Source-only Stage 1 driver draft. Main permits only a fully bound Linux run.

The source may be inspected inertly. It imports no participant, control module,
specialized worker, or native extension. No diagnostic timing is ordinary EPS.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
READ_ONLY = HERE / 'read_only'
HOST = READ_ONLY / 'host'
AUDITOR = READ_ONLY / 'frozen_saved_auditor_v1'
ENTRY = '/opt/t3-classic-structural-v2/cost-diagnostic-v1/cost_entry_draft_v1.py'
PUBLIC_ENTRY = ['/usr/local/bin/python', '-B', '/opt/classic-native-kernels-v1/delivery_entry.py']
PUBLIC_RE = r'ghcr\.io/kouzhizhuo/agenthon-t3-classic@sha256:[0-9a-f]{64}'
OLD_PUBLIC = 'ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba'
BASE_RUN = 38072276259
BASE_HEAD = '2164738b7508d9554cb6bd0a37ec46375cee8199'
BASE_WORKFLOW = 't3-classic-expectations-delivery-v2.yml'
BASE_PINS_SHA = 'b5cf9f49879ad5fe90b760831914e6e3e19f92186df2503c5b5ca2ff0bc34279'
ROOTS = {'native': '/opt/classic-native-kernels-v1', 'harness': '/opt/t3-classic-structural-v2', 'licenses': '/licenses'}
SAVED_ROOTS = {'native': 'installed', 'harness': 'installed-harness', 'licenses': 'installed-licenses'}
ARMS = {'parent': 'classic_native_kernels_v1', 'expectations': 'classic_build_expectations_v1'}
MODES = ('state', 'cost')
UNITS = ('t3-s001-price-time-priority', 't3-as06-throughput-fast', 't3-mp01-stp-newest-baseline',
    't3-ra01-fundamental-shock-mid', 't3-mr-deep-book-state-size', 't3-gbatch-hetero-mix')
VOLATILE = {'wall_clock_sec', 'events_per_sec', 'peak_memory_bytes', 'gpu_seconds'}
LOG_CAP = 16 * 1024**2
DIAGNOSTIC_LOG_CAP = 256 * 1024**2
SOURCE_CAP = 64 * 1024**2
SCREEN_BUDGET = 7200
WORKER_TIMEOUT = 3900
CLEANUP_GRACE = 90


def require(value, message):
    if not value:
        raise ValueError(message)


def object_pairs(pairs):
    answer = {}
    for key, value in pairs:
        require(key not in answer, 'duplicate JSON key refused')
        answer[key] = value
    return answer


def read(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=object_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON refused')))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def pin(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'regular nonsymlink file required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def absolute(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)),
        'absolute ordinary path without symlink ancestors required')
    return path


def bound_file(value):
    require(type(value) is dict and set(value) == {'path', 'bytes', 'sha256'}, 'exact bound-file schema')
    path = absolute(value['path'])
    require(pin(path) == {k: value[k] for k in ('bytes', 'sha256')}, 'actual bound-file bytes differ')
    return path


def inventory(root):
    root = absolute(root)
    require(root.is_dir(), 'actual ordinary inventory root required')
    answer = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'inventory symlink refused')
        if any(part.startswith('._') or part in ('__MACOSX', '__pycache__') for part in path.parts):
            continue
        if path.is_file():
            row = pin(path)
            require(row['bytes'] <= SOURCE_CAP, 'unchanged64MiB source-member boundary')
            answer[path.relative_to(root).as_posix()] = row
    require(answer, 'nonempty actual inventory required')
    return answer


def full_equal(left, right):
    if pin(left)['bytes'] != pin(right)['bytes']:
        return False
    with Path(left).open('rb') as a, Path(right).open('rb') as b:
        while True:
            x, y = a.read(1024**2), b.read(1024**2)
            if x != y:
                return False
            if not x:
                return True


def plain_output_inventory(root):
    root = absolute(root)
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'output symlink refused')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = pin(path)
    require(result and sum(p['bytes'] for p in result.values()) <= DIAGNOSTIC_LOG_CAP, 'finite complete actual output')
    return result


def strip_volatile(value):
    if type(value) is dict:
        return {key: strip_volatile(item) for key, item in value.items() if key not in VOLATILE}
    if type(value) is list:
        return [strip_volatile(item) for item in value]
    return value


def pair(left, right):
    left, right = absolute(left), absolute(right)
    a, b = plain_output_inventory(left), plain_output_inventory(right)
    require(set(a) == set(b), 'complete output file roster differs')
    for name in a:
        if name.endswith('.parquet'):
            require(full_equal(left / name, right / name), 'complete trace/ledger bytes differ')
        else:
            require(strip_volatile(read(left / name)) == strip_volatile(read(right / name)), 'stable sidecar differs')
    return {'passed': True, 'files': len(a), 'volatile_fields': sorted(VOLATILE), 'full_trace_ledger_bytes_equal': True}


def normalize_unit(item):
    require(type(item) is dict and set(item) == {'unit', 'shape', 'subs', 'scenario_paths', 'reference_frames',
        'input_sha256', 'reference_sha256'}, 'exact original unit schema')
    require(type(item['unit']) is str and item['shape'] in ('single', 'batch'), 'typed unit/shape')
    unit = {'unit': item['unit'], 'shape': item['shape'], 'subs': item['subs'],
        'input_sha256': item['input_sha256'], 'reference_sha256': item['reference_sha256']}
    if item['shape'] == 'single':
        require(item['subs'] == [] and len(item['scenario_paths']) == 1 and len(item['reference_frames']) == 2, 'single exact roster')
    else:
        require(type(item['subs']) is list and 1 <= len(item['subs']) <= 5 and len(item['scenario_paths']) == len(item['subs'])
            and len(item['reference_frames']) == 2 * len(item['subs']), 'batch exact roster')
        names = []
        for sub in item['subs']:
            require(type(sub) is dict and type(sub.get('sub')) is str and type(sub.get('scenario_file')) is str,
                'typed organizer sub/source')
            names.append(sub['sub'])
            relative = PurePosixPath(sub['scenario_file'])
            require(not relative.is_absolute() and '..' not in relative.parts and relative.as_posix() == 'scenarios/' + sub['sub'] + '.json',
                'exact original sub/source mapping')
        require(len(set(names)) == len(names), 'unique original batch subs')
    for mapping in ('input_sha256', 'reference_sha256'):
        require(type(item[mapping]) is dict and all(type(k) is str and type(v) is str and re.fullmatch('[0-9a-f]{64}', v)
            for k, v in item[mapping].items()), 'typed complete source/reference SHA map')
    return unit


def validate_base_document(document, binding):
    require(document.get('schema') == 't3-cost-actual-base-authority-v1' and document.get('ready_for_linux') is True
        and document.get('run_id') == BASE_RUN and type(document.get('run_id')) is int and document.get('run_attempt') == 1 and type(document.get('run_attempt')) is int
        and document.get('head') == BASE_HEAD and document.get('workflow') == BASE_WORKFLOW
        and document.get('sourcepins_sha256') == BASE_PINS_SHA, 'actual unique successfulv2 base authority required')
    require(binding.get('schema') == 't3-expectations-cost-image-binding-v1' and binding.get('ready_for_linux') is True
        and binding.get('runtime_changed') is False and binding.get('base_publication_authority') is True
        and binding.get('publication_authority') is False and binding.get('rankable') is False,
        'diagnostic binding requires auditedbase, unchangedruntime and nooverlaypublication')
    image, digest = binding.get('actual_final_image_id'), binding.get('actual_final_public_digest')
    require(type(image) is str and re.fullmatch('sha256:[0-9a-f]{64}', image)
        and type(digest) is str and re.fullmatch(PUBLIC_RE, digest) and digest != OLD_PUBLIC,
        'new actual immutable successfulv2 base image/digest required')
    require(document.get('base_image_id') == image and document.get('public_digest') == digest,
        'base document and embedded binding image/digest differ')
    return image, digest


def validate_overlay_metadata(base, overlay, digest):
    require(base.get('Id') != overlay.get('Id') and base.get('Os') == overlay.get('Os') == 'linux'
        and base.get('Architecture') == overlay.get('Architecture') == 'amd64' and digest in base.get('RepoDigests', []),
        'deriveddiagnostic ID distinct; original public/platform identity')
    config = base['Config']
    require(config.get('Entrypoint') == PUBLIC_ENTRY and config.get('Cmd') in (None, []) and config.get('User') == '65534:65534'
        and config.get('WorkingDir') == '/output' and not config.get('Volumes') and not config.get('OnBuild'),
        'actual unchanged publicdefault config required')
    require(overlay['Config'] == config, 'overlay must inherit exact config')
    roots = base['RootFS']['Layers']
    require(base['RootFS']['Type'] == overlay['RootFS']['Type'] == 'layers'
        and len(overlay['RootFS']['Layers']) == len(roots) + 1 and overlay['RootFS']['Layers'][:-1] == roots,
        'exact base RootFS prefix plus oneCOPY layer')
    require(type(overlay.get('Size')) is int and overlay['Size'] > base['Size'], 'positive additive layer size')


def load_frozen_host():
    require('verify_linux' not in sys.modules and 'verify_public' not in sys.modules and 'source_copy' not in sys.modules,
        'fresh host module namespace required')
    original_path = sys.path[:]
    try:
        sys.path.insert(0, str(HOST))
        import verify_linux as linux
        import verify_public as public
    finally:
        sys.path[:] = original_path
    require(Path(linux.__file__).resolve() == HOST / 'verify_linux.py' and Path(public.__file__).resolve() == HOST / 'verify_public.py',
        'exact copied frozen host files required')
    spec = importlib.util.spec_from_file_location('t3_cost_unchanged_source_copy', READ_ONLY / 'source_copy.py')
    source_copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(source_copy)
    return linux, public, source_copy


def source_freeze(args):
    pins_path = absolute(args.source_pins)
    doc = read(pins_path)
    require(doc.get('schema') == 't3-cost-host-source-pins-v1' and doc.get('reviewed') is True
        and doc.get('ready_for_linux') is True and doc.get('runtime_changed') is False,
        'independently finalized source freeze required; draft cannotrun')
    require(re.fullmatch('[0-9a-f]{40}', args.head), 'exact active remote head')
    files = doc['files']
    require(type(files) is dict and all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in files),
        'safe frozen source roster')
    for name, wanted in files.items():
        require(pin(HERE / name) == wanted, 'reviewed actual source byte differs: ' + name)
    require({'driver.py', 'worker.py', 'parser.py', 'Dockerfile', 'overlay/cost_entry_draft_v1.py', 'overlay/IMAGE_BINDING.json',
        'READ_ONLY_SOURCE_PINS_v1.json', 'read_only/source_copy.py', 'read_only/host/verify_linux.py',
        'read_only/host/verify_public.py'}.issubset(files), 'all executing source/entry/binding paths mustbefrozen')
    carried = read(HERE / 'READ_ONLY_SOURCE_PINS_v1.json')['files']
    for name, wanted in carried.items():
        require(files.get(name) == wanted and pin(HERE / name) == wanted, 'all17 read-only frozen helper byte pins')
    remote = read(absolute(args.remote_readback))
    require(remote.get('all_passed') is True and remote.get('head') == args.head
        and remote.get('participant_imported') is False, 'independent samehead source readback required')
    expected = {doc['remote_prefix'] + name: wanted for name, wanted in files.items()}
    expected[doc['remote_prefix'] + pins_path.name] = pin(pins_path)
    expected[doc['active_workflow']] = files[doc['workflow_source']]
    checks = remote['checks']
    require(len(checks) == len(expected) and all(r.get('passed') is True and r.get('expected') == r.get('actual') for r in checks)
        and {r['path']: r['actual'] for r in checks} == expected, 'all source+independent workflow atonehead exact roster')
    require(full_equal(absolute(args.binding), HERE / 'overlay/IMAGE_BINDING.json'), 'exactfrozen embeddedbinding')
    return files


def run_process(args, linux, command, label, seconds, cap=LOG_CAP, anonymous=False):
    log = args.evidence / 'host-processes' / (label + '.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    process, failure, read_count = None, None, 0
    record = {'argv': command, 'timeout_sec': seconds, 'cleanup_grace_sec': CLEANUP_GRACE, 'rankable': False,
        'timing_included': False, 'creator_reaped': False, 'cancelled': False, 'timed_out': False, 'error': None,
        'secondary_cleanup_errors': [], 'per_log_file_hard_bytes': cap, 'hard_limit_reached': False, 'succeeded': False}
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    if anonymous:
        folder = args.evidence / 'anonymous-docker-config'
        folder.mkdir(exist_ok=True)
        env['DOCKER_CONFIG'] = str(folder)
    deadline = min(args.deadline, time.monotonic() + seconds)
    selector = selectors.DefaultSelector()
    def drain(stream, selected, finite_tail=False):
        nonlocal read_count
        for key, _ in selected:
            try:
                block = os.read(key.fileobj.fileno(), 65536)
            except BlockingIOError:
                continue
            if not block:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                continue
            remaining = cap - read_count
            stream.write(block[:remaining])
            read_count += min(len(block), remaining)
            if len(block) >= remaining:
                record['hard_limit_reached'] = True
                if not finite_tail:
                    raise ValueError('finite complete parent process streamcap')
    stream = log.open('xb')
    try:
        linux.check_cancelled()
        require(deadline > time.monotonic(), 'whole Stage1 budget exhausted before fresh process')
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
        try:
            def child_signal_restore():
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True, env=env, preexec_fn=child_signal_restore)
            record['pid'] = process.pid
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        selector.register(process.stdout, selectors.EVENT_READ)
        os.set_blocking(process.stdout.fileno(), False)
        # Do not poll/reap the leader while inherited pipes remain open.
        # Its unreaped PID is the ownership anchor for the entire group.
        while selector.get_map():
            linux.check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                record['timed_out'] = True
                raise TimeoutError('finite Stage1 process or whole budget reached')
            drain(stream, selector.select(timeout=min(.1, remaining)))
        while True:
            linux.check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                record['timed_out'] = True
                raise TimeoutError('finite Stage1 reap budget reached')
            try:
                process.wait(timeout=min(.1, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
    except BaseException as error:
        failure = error
        record['error'] = {'type': type(error).__name__, 'message': str(error)}
        record['cancelled'] = isinstance(error, (InterruptedError, KeyboardInterrupt))
        if process is not None and process.returncode is None:
            # Signal only the unreaped owned leader first. Its handler lets
            # the original verifier settle the owned Docker container.
            try:
                os.kill(process.pid, signal.SIGTERM)
                record['graceful_SIGTERM_sent'] = True
            except ProcessLookupError:
                record['leader_already_exited'] = True
            except BaseException as cleanup_error:
                record['secondary_cleanup_errors'].append({'phase': 'SIGTERM', 'error': repr(cleanup_error)})
            grace_deadline = time.monotonic() + CLEANUP_GRACE
            try:
                while selector.get_map() and time.monotonic() < grace_deadline:
                    drain(stream, selector.select(timeout=.1), finite_tail=True)
                if not selector.get_map():
                    process.wait(timeout=max(.001, grace_deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            except BaseException as cleanup_error:
                record['secondary_cleanup_errors'].append({'phase': 'grace-drain', 'error': repr(cleanup_error)})
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    record['owned_group_SIGKILL_after_grace'] = True
                except ProcessLookupError:
                    record['owned_group_already_absent'] = True
                except BaseException as cleanup_error:
                    record['secondary_cleanup_errors'].append({'phase': 'SIGKILL', 'error': repr(cleanup_error)})
                try:
                    process.wait(timeout=5)
                except BaseException as cleanup_error:
                    record['secondary_cleanup_errors'].append({'phase': 'reap', 'error': repr(cleanup_error)})
    finally:
        try:
            selector.close()
        except BaseException as cleanup_error:
            record['secondary_cleanup_errors'].append({'phase': 'selector-close', 'error': repr(cleanup_error)})
        if process is not None:
            if process.stdout and not process.stdout.closed:
                try:
                    process.stdout.close()
                except BaseException as cleanup_error:
                    record['secondary_cleanup_errors'].append({'phase': 'pipe-close', 'error': repr(cleanup_error)})
            record['returncode'] = process.returncode
            record['creator_reaped'] = process.returncode is not None
        # Hash only fully flushed stream bytes. The stream closes before
        # the immutable receipt is emitted below.
        try:
            stream.flush()
        except BaseException as cleanup_error:
            record['secondary_cleanup_errors'].append({'phase': 'stream-flush', 'error': repr(cleanup_error)})
        try:
            stream.close()
        except BaseException as cleanup_error:
            record['secondary_cleanup_errors'].append({'phase': 'stream-close', 'error': repr(cleanup_error)})
    try:
        record['log'] = {'path': str(log), **pin(log)}
        record['succeeded'] = failure is None and record.get('returncode') == 0 and record['creator_reaped'] and not record['secondary_cleanup_errors'] and not record['hard_limit_reached']
        write(log.with_suffix('.json'), record)
    except BaseException as cleanup_error:
        record['secondary_cleanup_errors'].append({'phase': 'receipt-pin-write', 'error': repr(cleanup_error)})
        if failure is None:
            raise
    if failure is not None:
        raise failure
    require(process is not None and record['returncode'] == 0 and record['creator_reaped']
        and not record['secondary_cleanup_errors'], 'fresh host process failed: ' + label)
    return record


def replay_base(args, linux, document, binding):
    image, digest = validate_base_document(document, binding)
    zipfile = bound_file(document['artifact_zip'])
    audited = bound_file(document['saved_audit'])
    registry = bound_file(document['anonymous_registry'])
    artifact = absolute(document['artifact_root'])
    source = absolute(document['source_root'])
    require(pin(source / 'SOURCE_PINS.json')['sha256'] == BASE_PINS_SHA, 'actualsuccessfulv2 source pins')
    saved = read(audited)
    require(saved.get('schema') == 't3-independent-saved-expectations-delivery-report-v1'
        and saved.get('all_passed') is True and saved.get('all_execution_checks_passed') is True
        and saved.get('publication_passed') is True and saved.get('eligible_for_official_submission') is True
        and saved.get('failures') == [] and saved.get('pending') == []
        and saved['authority']['remote_head'] == BASE_HEAD and saved['authority']['public_image'] == digest
        and saved['authority']['artifact'] == pin(zipfile), 'actual complete independent v2 pass required')
    replay = args.evidence / 'base-audit-replay.json'
    command = [sys.executable, '-B', str(AUDITOR / 'audit_saved_delivery_v1.py'), '--artifact', str(artifact), '--zip', str(zipfile),
        '--expected-zip-sha256', pin(zipfile)['sha256'], '--expected-zip-bytes', str(pin(zipfile)['bytes']), '--source', str(source),
        '--expected-source-pins-sha256', BASE_PINS_SHA, '--expected-head', BASE_HEAD, '--expected-workflow', BASE_WORKFLOW,
        '--remote-readback', str(bound_file(document['remote_source_readback'])), '--frozen-payload', str(absolute(document['frozen_payload'])),
        '--baseline-payload', str(absolute(document['baseline_payload'])), '--baseline-reference-plan', str(bound_file(document['baseline_reference_plan'])),
        '--expected-run-id', str(BASE_RUN), '--expected-run-attempt', '1', '--remote-evidence-marker', 'expectations-delivery-evidence/',
        '--registry-readback', str(registry), '--out', str(replay)]
    run_process(args, linux, command, 'independent-complete-base-audit', 2400)
    checked = read(replay)
    require(checked['all_passed'] is True and checked['publication_passed'] is True and checked['all_execution_checks_passed'] is True
        and checked['failures'] == checked['pending'] == [] and checked['authority']['public_image'] == digest,
        'fresh exact frozen auditor full replay required before Docker')
    evidence = artifact / 'evidence'
    base_meta = read(evidence / 'before/IMAGE.json')
    require(base_meta['Id'] == image and read(evidence / 'after/IMAGE.json') == base_meta
        and read(evidence / 'BUILD_READY.json')['image_id'] == image and read(evidence / 'PUBLICATION.json')['image'] == digest,
        'actual same successful base immutable config andpublication')
    original = {key: inventory(evidence / name) for key, name in SAVED_ROOTS.items()}
    for key, name in SAVED_ROOTS.items():
        require(original[key] == inventory(evidence / (name + '-after')), 'successfulbase before/aftercomplete source unchanged')
    candidates = {name: inventory(evidence / 'installed/completion1009/candidates' / name) for name in ARMS.values()}
    require(binding.get('candidate_source_files') == candidates and binding.get('base_source_inventory') == original,
        'complete botharm source/C/object/ELF/licence inventories in binding')
    published_meta = read(evidence / 'published-metadata/IMAGE.json')
    require(published_meta['Id'] == image and digest in published_meta['RepoDigests']
        and all(published_meta[k] == base_meta[k] for k in ('Id', 'Config', 'RootFS', 'Os', 'Architecture', 'Size')),
        'actualpublished base immutableinspection')
    return evidence, published_meta, original, {'saved_audit': pin(audited), 'fresh_audit': pin(replay), 'registry': pin(registry), 'artifact': pin(zipfile)}


def extract(args, linux, source_copy, image, remote, target, label, original_class):
    require(linux.DockerCommands is original_class, 'original commandclass before sourcecopy')
    name, owner = 't3-structural-source-' + uuid.uuid4().hex, uuid.uuid4().hex
    commands = original_class('docker', args.evidence / (label + '-commands'), LOG_CAP)
    copied, primary, cleanup, secondary = False, None, None, []
    try:
        linux.check_cancelled()
        require(args.deadline > time.monotonic(), 'whole Stage1 budget exhausted before sourcecopy')
        made = commands.call(['create', '--name', name, '--label', linux.OWNER_LABEL + '=' + owner, '--pull', 'never', image],
            'create', min(30, args.deadline - time.monotonic()))
        require(made['succeeded'], 'sourcecopy create failed')
        info, _ = commands.inspect(name, cleanup=True, seconds=min(30, max(0, args.deadline - time.monotonic())))
        linux.require_owned(info, name, owner, image)
        copied = source_copy.source_copy_command(commands, linux, ['cp', name + ':' + remote, str(target)], 'copy',
            min(120, max(0, args.deadline - time.monotonic())))['succeeded']
        require(copied, 'complete sourcecopy failed')
    except BaseException:
        primary = sys.exc_info()
    finally:
        try:
            cleanup = linux.settle_container(commands, name, owner, image, creation_uncertain=True)
        except BaseException as error:
            secondary.append({'phase': 'settle', 'type': type(error).__name__, 'message': str(error)})
        try:
            write(args.evidence / (label + '.json'), {'commands': commands.rows, 'cleanup': cleanup, 'copy_succeeded': copied,
                'container_never_started': True, 'rankable': False, 'timing_included': False, 'secondary_errors': secondary,
                'failure': {'type': type(primary[1]).__name__, 'message': str(primary[1])} if primary else None,
                'source_command_class_original': linux.DockerCommands is original_class})
        except BaseException as error:
            secondary.append({'phase': 'receipt-write', 'type': type(error).__name__, 'message': str(error)})
    if primary:
        raise primary[1].with_traceback(primary[2])
    require(not secondary and cleanup is not None and cleanup['settled'] and cleanup['removed']
        and cleanup['final_absent'] and cleanup['errors'] == [], 'sourcecopy exact owned lifecycle')
    require(linux.DockerCommands is original_class, 'original commandclass after sourcecopy')


def check_overlay_inventory(original, actual, overlay):
    require(actual['native'] == original['native'] and actual['licenses'] == original['licenses'], 'all source/C/object/ELF/licenses unchanged')
    expected = dict(original['harness'])
    added = {'cost-diagnostic-v1/' + name: value for name, value in overlay.items()}
    require(not set(added).intersection(expected), 'overlay cannot overwrite existingharness')
    expected.update(added)
    require(actual['harness'] == expected, 'exact originalharness plus reviewed twofile overlay')


def frozen_dockerfile(digest):
    return 'FROM ' + digest + '\nCOPY --chown=0:0 --chmod=0444 overlay/ /opt/t3-classic-structural-v2/cost-diagnostic-v1/\n'


def build_overlay(args, linux, binding, base_meta, original, original_class):
    digest = binding['actual_final_public_digest']
    require((HERE / 'Dockerfile').read_text() == frozen_dockerfile(digest), 'onlyexact frozen FROM+COPY permitted; unresolveddraft refused')
    overlay = inventory(HERE / 'overlay')
    require(set(overlay) == {'cost_entry_draft_v1.py', 'IMAGE_BINDING.json'}, 'exact additiveoverlayfiles')
    process = run_process(args, linux, ['docker', 'pull', '--platform', 'linux/amd64', digest], 'anonymous-auditedbase-pull', 900, anonymous=True)
    require(args.deadline - time.monotonic() >= 30, 'wholebudget reserve originalmetadata30sec')
    actual_base = linux.image_metadata(args, digest, args.evidence / 'base-image-metadata')
    require(actual_base['id'] == base_meta['Id'] and all(actual_base['inspection'][k] == base_meta[k]
        for k in ('Id', 'Config', 'RootFS', 'Os', 'Architecture', 'Size')), 'pulled exactactual base config/rootfs')
    context = args.evidence / 'overlay-context'
    context.mkdir()
    shutil.copytree(HERE / 'overlay', context / 'overlay')
    shutil.copyfile(HERE / 'Dockerfile', context / 'Dockerfile')
    require(inventory(context / 'overlay') == overlay, 'frozen overlaycontext copies exact')
    tag = 't3-expectations-cost-diagnostic:' + uuid.uuid4().hex
    run_process(args, linux, ['docker', 'build', '--platform', 'linux/amd64', '--pull=false', '--network=none', '--progress=plain',
        '-t', tag, '-f', str(context / 'Dockerfile'), str(context)], 'one-additive-overlay-build', 900)
    require(args.deadline - time.monotonic() >= 30, 'wholebudget reserve originalmetadata30sec')
    meta = linux.image_metadata(args, tag, args.evidence / 'overlay-image-metadata')
    validate_overlay_metadata(actual_base['inspection'], meta['inspection'], digest)
    return meta, overlay, process


def roster(args, public, saved_evidence):
    plan = public.collect_plan(args.reference_root, None)
    current = {row['unit']: row for row in plan['units']}
    require(len(current) == len(plan['units']) == 71 and plan['reference_frame_count'] == 190
        and sum(1 if row['shape'] == 'single' else len(row['subs']) for row in plan['units']) == 95,
        'exact71unit95market190referenceframe authority')
    saved = read(saved_evidence / 'REFERENCE_PLAN.json')
    prior = read(bound_file(args.base_document['baseline_reference_plan']))
    for old in (saved, prior):
        require({r['unit']: normalize_unit(r) for r in old['units']} == {n: normalize_unit(r) for n, r in current.items()},
            'all unit/shape/sub/input/reference SHA maps equalactual savedauthority')
    require(sum(1 if current[u]['shape'] == 'single' else len(current[u]['subs']) for u in UNITS) == 10
        and len(current[UNITS[-1]]['subs']) == 5, 'exact6unit10market selectedschedule')
    for row in current.values():
        unit = args.reference_root / row['unit']
        for mapping in ('input_sha256', 'reference_sha256'):
            for name, digest in row[mapping].items():
                require(public.sha256(unit / name) == digest, 'actual full public inputs/references changed')
    write(args.evidence / 'REFERENCE_PLAN.json', plan)
    return plan, current


def timestamp_ns(value):
    require(type(value) is str, 'actual typed daemon timestamp')
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z', value)
    require(match is not None, 'actual UTC daemon timestamp')
    seconds = int(datetime.datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp())
    return seconds * 10**9 + int((match[2] or '').ljust(9, '0') or '0')


def serial_intervals(rows):
    intervals = []
    for row in rows:
        execution = row['execution']
        cleanup = execution['cleanup']
        require(execution['succeeded'] is True and execution['exit_code'] == 0 and execution['OOMKilled'] is False
            and cleanup['settled'] and cleanup['removed'] and cleanup['final_absent'] and cleanup['errors'] == [], 'eachactualserialdiagnostic lifecycle')
        start, finish = timestamp_ns(execution['state']['StartedAt']), timestamp_ns(execution['state']['FinishedAt'])
        require(finish > start, 'positive actualdaemon interval')
        intervals.append([start, finish, execution['name']])
    intervals.sort()
    require(len({r[2] for r in intervals}) == len(intervals) and all(a[1] < b[0] for a, b in zip(intervals, intervals[1:])),
        'unique actualdiagnostics strictlyserial')
    return intervals


def saved_path(saved_evidence, remote):
    require(type(remote) is str and remote.count('expectations-delivery-evidence/') == 1, 'oneexact savedevidence marker')
    relative = PurePosixPath(remote.split('expectations-delivery-evidence/', 1)[1])
    require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in remote, 'safe saved marketpath')
    return absolute(saved_evidence / relative.as_posix())


def compare_cell(row, saved_evidence, first):
    require(row['passed'] is True and row['parsed']['passed'] is True and row['rankable'] is False and row['timing_included'] is False,
        'complete untimed diagnostic cell required')
    arm, mode, unit = row['arm'], row['cost_mode'], row['unit']
    output = absolute(row['output'])
    pairs = {'successful_v2_ordinary': pair(output, saved_evidence / 'ordinary/0' / unit / 'output')}
    base = read(saved_evidence / 'diagnostic' / arm / unit / 'RUN_RESULT.json')
    graphs = {r['sub']: saved_path(saved_evidence, r['path']) for r in base['state_receipts']}
    new = {r['mapping']['sub']: absolute(r['path']) for r in row['parsed']['states']}
    require(len(new) == len(row['parsed']['states']) and set(new) == set(graphs), 'complete uniqueSTATE subroster')
    for sub in new:
        require(full_equal(new[sub], graphs[sub]), 'completeSTATE/RNG/cache/aliases equal successfulbase')
    previous = first.setdefault(unit, {'output': output, 'graphs': new})
    pairs['state_cost_crossarm_output'] = pair(output, previous['output'])
    require(set(previous['graphs']) == set(new) and all(full_equal(path, previous['graphs'][sub]) for sub, path in new.items()),
        'completeSTATE equal acrossstate/cost/botharms')
    return {'arm': arm, 'cost_mode': mode, 'unit': unit, 'pairs': pairs, 'successful_base_STATE_equal': True,
        'state_cost_crossarm_STATE_equal': True, 'timing_included': False}


def main():
    cli = argparse.ArgumentParser(allow_abbrev=False)
    for name in ('base-authority', 'binding', 'source-pins', 'remote-readback', 'reference-root', 'gate-kit', 'evidence'):
        cli.add_argument('--' + name, type=Path, required=True)
    cli.add_argument('--head', required=True)
    args = cli.parse_args()
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'actual Linuxamd64 only; draft doesnotrun locally')
    args.evidence = absolute(args.evidence)
    require(not args.evidence.exists(), 'fresh entireStage1 evidencepath')
    args.evidence.mkdir(parents=True)
    args.reference_root, args.gate_kit = absolute(args.reference_root), absolute(args.gate_kit)
    args.docker, args.log_cap_bytes, args.deadline = 'docker', LOG_CAP, time.monotonic() + SCREEN_BUDGET
    rows, comparisons, first, secondary, primary = [], [], {}, [], None
    original_class, overlay_id, before, after, meta = None, None, None, None, None
    authority_path = args.evidence / 'HOST_AUTHORITY.json'
    try:
        source_files = source_freeze(args)
        retained = args.evidence / 'authority-inputs'
        retained.mkdir()
        for label, path in (('base-authority.json', args.base_authority), ('IMAGE_BINDING.json', args.binding),
                ('SOURCE_PINS.json', args.source_pins), ('REMOTE_SOURCE_READBACK.json', args.remote_readback)):
            shutil.copyfile(absolute(path), retained / label)
            require(full_equal(path, retained / label), 'carried runtime authority exactbytes')
        copied_source = args.evidence / 'source-harness'
        copied_source.mkdir()
        for name, wanted in source_files.items():
            target = copied_source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(HERE / name, target)
            require(pin(target) == wanted, 'carried entirefrozen sourceharness')
        args.base_document, binding = read(absolute(args.base_authority)), read(absolute(args.binding))
        parent_receipts = retained / 'base-receipts'
        parent_receipts.mkdir()
        for label in ('saved_audit', 'anonymous_registry', 'remote_source_readback', 'baseline_reference_plan'):
            source = bound_file(args.base_document[label])
            shutil.copyfile(source, parent_receipts / (label + '.json'))
            require(full_equal(source, parent_receipts / (label + '.json')), 'carried actualbase receiptbytes')
        write(retained / 'EXTERNAL_COMPLETE_BASE_AUTHORITY.json', {
            'artifact_zip': args.base_document['artifact_zip'], 'artifact_root': args.base_document['artifact_root'],
            'registry_receipt': args.base_document['anonymous_registry'],
            'policy': 'final saved auditor must receive and independently revalidate complete parentZIP and registry layerbytes; receipts alone cannot authorize'})
        validate_base_document(args.base_document, binding)
        linux, public, source_copy = load_frozen_host()
        original_class = linux.DockerCommands
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, linux.cancellation)
        saved, base_meta, original, base_pins = replay_base(args, linux, args.base_document, binding)
        plan, items = roster(args, public, saved)
        meta, overlay, _ = build_overlay(args, linux, binding, base_meta, original, original_class)
        overlay_id = meta['id']
        before = {}
        for key, remote in ROOTS.items():
            target = args.evidence / ('overlay-' + key + '-before')
            extract(args, linux, source_copy, overlay_id, remote, target, key + '-before-copy', original_class)
            before[key] = inventory(target)
        check_overlay_inventory(original, before, overlay)
        authority = {'schema': 't3-cost-host-authority-v1', 'ready_for_linux': True, 'all_passed': True,
            'base_publication_authority': True, 'publication_authority': False, 'runtime_changed': False, 'rankable': False,
            'base_image_id': base_meta['Id'], 'public_digest': binding['actual_final_public_digest'], 'overlay_image_id': overlay_id,
            'binding': binding, 'overlay_entry': ENTRY, 'base_metadata': base_meta, 'overlay_metadata': meta['inspection'],
            'verified_before_source_inventory': before, 'overlay_files': overlay, 'base_pins': base_pins,
            'source_pins': pin(args.source_pins), 'host_pins': {n: pin(HOST / n) for n in ('verify_linux.py', 'verify_public.py')},
            'production_source_paths': {name: str(saved / 'installed/completion1009/candidates' / name / 'production_cli.py') for name in ARMS.values()},
            'full71_plan': plan, 'checks': {name: True for name in ('base_saved_audit_passed', 'anonymous_registry_full_bytes_verified',
                'base_manifest_config_bound', 'base_source_C_object_ELF_licenses_verified', 'overlay_config_inherited_exactly',
                'overlay_rootfs_additive', 'overlay_before_inventory_exact', 'source_command_class_original', 'full71_roster_inputs_refs_bound')}}
        write(authority_path, authority)
        schedule = [{'label': 'cost-%02d-%s-%s' % (i, arm, mode), 'unit': unit, 'arm': arm, 'cost_mode': mode}
            for i, unit in enumerate(UNITS) for arm in ARMS for mode in MODES]
        write(args.evidence / 'SCHEDULE.json', {'cells': schedule, 'diagnostic_containers': 24, 'complete_STATE_graphs': 40,
            'official_gates': 96, 'Parquet_copies': 80, 'ordinary': 0, 'warmup': 0, 'controls': 0, 'rankable': False})
        for cell in schedule:
            require(linux.DockerCommands is original_class, 'original drivercommandclass beforeworker')
            request = {'schema': 't3-cost-worker-request-v1', 'arm': cell['arm'], 'cost_mode': cell['cost_mode'],
                'item': items[cell['unit']], 'image_id': overlay_id, 'owner': uuid.uuid4().hex, 'binding': binding,
                'authority_path': str(authority_path), 'authority_pin': pin(authority_path), 'host_pins': authority['host_pins'],
                'entry': ENTRY, 'timeout_sec': 3600, 'log_cap_bytes': DIAGNOSTIC_LOG_CAP,
                'production_source_path': authority['production_source_paths'][ARMS[cell['arm']]],
                'production_source_pin': binding['candidate_source_files'][ARMS[cell['arm']]]['production_cli.py'],
                'reference_root': str(args.reference_root), 'gate_kit': str(args.gate_kit), 'saved_graph_helper_root': str(AUDITOR),
                'saved_graph_helper_pins': {n: pin(AUDITOR / n) for n in ('graph_saved_v1.py', 'saved_base_v1.py')}}
            request_path = args.evidence / 'worker-requests' / (cell['label'] + '.json')
            write(request_path, request)
            worker_error = None
            try:
                run_process(args, linux, [sys.executable, '-B', str(HERE / 'worker.py'), '--host', str(HOST), '--worker-args', str(request_path),
                    '--evidence', str(args.evidence), '--label', cell['label']], cell['label'], WORKER_TIMEOUT, DIAGNOSTIC_LOG_CAP)
            except BaseException:
                worker_error = sys.exc_info()
            result = args.evidence / 'worker-results' / (cell['label'] + '.json')
            if result.is_file():
                row = read(result)
                rows.append(row)
            if worker_error:
                raise worker_error[1].with_traceback(worker_error[2])
            require(result.is_file(), 'actual freshworkerreceipt required')
            comparisons.append(compare_cell(row, saved, first))
            require(linux.DockerCommands is original_class, 'original drivercommandclass afterworker')
            print(cell['label'], 'complete untimed diagnostic PASS', flush=True)
    except BaseException:
        primary = sys.exc_info()
    finally:
        # Each after-copy is attempted independently, preserving the original error.
        # Cleanup may exceed the screen deadline only through the original finite grace.
        if overlay_id is not None:
            after = {}
            for key, remote in ROOTS.items():
                try:
                    target = args.evidence / ('overlay-' + key + '-after')
                    require(linux.DockerCommands is original_class, 'original driverclass finally')
                    extract(args, linux, source_copy, overlay_id, remote, target, key + '-after-copy', original_class)
                    after[key] = inventory(target)
                except BaseException as error:
                    secondary.append({'phase': key + '-after-copy', 'type': type(error).__name__, 'message': str(error)})
            try:
                require(before == after, 'exactderivedsource/C/object/ELF/licenses unchanged beforeafter')
                require(args.deadline - time.monotonic() >= 30, 'whole Stage1 budget reserve originalaftermetadata30sec')
                later = linux.image_metadata(args, overlay_id, args.evidence / 'overlay-image-metadata-after')
                require(later['inspection'] == meta['inspection'], 'derivedimage metadata immutable')
            except BaseException as error:
                secondary.append({'phase': 'after-immutability', 'type': type(error).__name__, 'message': str(error)})
        intervals = []
        try:
            intervals = serial_intervals(rows)
        except BaseException as error:
            secondary.append({'phase': 'actual-serial-lifecycle', 'type': type(error).__name__, 'message': str(error)})
        gates, graphs, parquets = 0, 0, 0
        for row in rows:
            gate = row.get('developer_verifier') or {}
            gates += sum(g.get('passed') is True for g in (gate.get('verdict') or {}).get('gate_results', {}).values())
            graphs += len((row.get('parsed') or {}).get('states', []))
            if row.get('output') and Path(row['output']).is_dir():
                try:
                    parquets += sum(n.endswith('.parquet') for n in plain_output_inventory(absolute(row['output'])))
                except BaseException as error:
                    secondary.append({'phase': 'partial-output-inventory', 'type': type(error).__name__, 'message': str(error)})
        summary = {'schema': 't3-cost-stage1-host-summary-v1', 'all_passed': primary is None and not secondary and len(rows) == 24
            and len(comparisons) == 24 and graphs == 40 and gates == 96 and parquets == 80 and len(intervals) == 24,
            'failure': {'type': type(primary[1]).__name__, 'message': str(primary[1])} if primary else None,
            'secondary_errors': secondary, 'actual_diagnostic_containers': len(rows), 'actual_complete_STATE_graphs': graphs,
            'actual_official_gates': gates, 'actual_Parquet_copies': parquets, 'actual_serial_intervals': intervals,
            'ordinary': 0, 'warmup': 0, 'controls': 0, 'rankable': False, 'official_submission': False,
            'performance_usable': False, 'threshold_232000_verified': False, 'diagnostic_time_is_not_ordinary_EPS': True,
            'before_after_source_equal': before is not None and before == after, 'primary_error_preserved': True}
        for filename, value in (('RAW_RESULTS.json', rows), ('COMPLETE_COMPARISONS.json', comparisons), ('SUMMARY.json', summary)):
            try:
                write(args.evidence / filename, value)
            except BaseException as error:
                secondary.append({'phase': filename + '-write', 'type': type(error).__name__, 'message': str(error)})
                summary['all_passed'] = False
    if primary:
        raise primary[1].with_traceback(primary[2])
    require(summary['all_passed'], 'complete Stage1diagnostic failed; raw evidence retained')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
