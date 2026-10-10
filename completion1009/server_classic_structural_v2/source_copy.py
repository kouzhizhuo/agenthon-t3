"""Finite host-only Docker source extraction with independent file/log limits.

The official execution and its frozen host verifier are unchanged. This helper
is used only for a never-started, owned source-copy container. Docker's client
writes source/C/object/ELF files, so RLIMIT_FSIZE cannot also serve as the much
smaller stdout/stderr log limit. Pipes enforce that independent log bound.
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import resource
import re
import selectors
import signal
import subprocess
import time

LOG_BYTES = 16 * 1024**2
SOURCE_FILE_BYTES = 64 * 1024**2


def _child_limits(cap):
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})


def _pin(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def _run_bounded(argv, prefix, seconds, check_cancelled, log_cap=LOG_BYTES, file_cap=SOURCE_FILE_BYTES):
    """Reap one owned process group; write at most log_cap bytes per stream."""
    if not (type(log_cap) is int and 0 < log_cap <= LOG_BYTES
            and type(file_cap) is int and 0 < file_cap <= SOURCE_FILE_BYTES):
        raise ValueError('finite source-copy file and log limits required')
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {name: prefix.with_name(prefix.name + '.' + name + '.txt') for name in ('stdout', 'stderr')}
    started = time.perf_counter()
    row = {'argv': argv, 'timeout_sec': seconds, 'rankable': False, 'timing_included': False,
        'source_copy_only': True, 'per_log_file_hard_bytes': log_cap,
        'source_file_hard_bytes': file_cap, 'creator_reaped': False,
        'timed_out': False, 'cancelled': False, 'error': None,
        'log_limit_enforcement': 'nonblocking pipes; independently bounded host writes',
        'source_limit_enforcement': 'client RLIMIT_FSIZE; no participant execution'}
    process = None
    counts = {'stdout': 0, 'stderr': 0}
    hit = {'stdout': False, 'stderr': False}
    discarded = {'stdout': 0, 'stderr': 0}
    with paths['stdout'].open('xb') as stdout, paths['stderr'].open('xb') as stderr:
        outputs = {'stdout': stdout, 'stderr': stderr}
        selector = selectors.DefaultSelector()
        try:
            if seconds <= 0:
                raise TimeoutError('source-copy budget exhausted before launch')
            check_cancelled()
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
            try:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, start_new_session=True, preexec_fn=lambda: _child_limits(file_cap))
                row['pid'] = process.pid
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            for name in ('stdout', 'stderr'):
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            deadline = started + seconds
            # Keep the unreaped leader as ownership anchor until both pipes
            # close. A child holding a pipe keeps this bounded by the deadline.
            while selector.get_map():
                check_cancelled()
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    row['timed_out'] = True
                    raise TimeoutError('owned source-copy deadline')
                for key, _ in selector.select(min(.1, remaining)):
                    try:
                        data = os.read(key.fileobj.fileno(), 64 * 1024)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    name = key.data
                    available = log_cap - counts[name]
                    kept = data[:available]
                    outputs[name].write(kept)
                    counts[name] += len(kept)
                    if len(data) >= available:
                        hit[name] = True
                        raise ValueError('source-copy ' + name + ' log hard limit reached')
            while True:
                check_cancelled()
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    row['timed_out'] = True
                    raise TimeoutError('owned source-copy reap deadline')
                try:
                    process.wait(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            row['cancelled'] = isinstance(error, (InterruptedError, KeyboardInterrupt))
            if isinstance(error, TimeoutError):
                row['timed_out'] = True
            if process is not None and process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    row['owned_group_kill_sent'] = True
                except ProcessLookupError:
                    row['owned_group_already_absent'] = True
                except BaseException as kill_error:
                    row['kill_error'] = repr(kill_error)
                try:
                    process.wait(timeout=5)
                except BaseException as wait_error:
                    row['reap_error'] = repr(wait_error)
                # Drain only a finite already-buffered tail after the stop.
                # These bytes are discarded, never added beyond the log cap.
                for name in ('stdout', 'stderr'):
                    stream = getattr(process, name)
                    if stream is None or stream.closed:
                        continue
                    while discarded[name] < 1024**2:
                        try:
                            tail = os.read(stream.fileno(), min(64 * 1024, 1024**2 - discarded[name]))
                        except BlockingIOError:
                            break
                        if not tail:
                            break
                        discarded[name] += len(tail)
        finally:
            selector.close()
            if process is not None:
                for name in ('stdout', 'stderr'):
                    stream = getattr(process, name)
                    if stream is not None and not stream.closed:
                        stream.close()
            row['returncode'] = process.returncode if process is not None else None
            row['creator_reaped'] = process is not None and process.returncode is not None
    row['host_wall_sec'] = time.perf_counter() - started
    row['bounded_discarded_pipe_tail_bytes'] = discarded
    for name, path in paths.items():
        row[name] = {**_pin(path), 'hard_limit_reached': hit[name] or path.stat().st_size >= log_cap}
    row['succeeded'] = (row['error'] is None and row['returncode'] == 0 and row['creator_reaped']
                        and not any(row[name]['hard_limit_reached'] for name in paths))
    return row


def source_copy_command(commands, linux, arguments, label, seconds=120):
    """Append one exact Docker cp row; create/inspect/cleanup keep original code."""
    if (not isinstance(commands, linux.DockerCommands) or commands.docker != 'docker'
            or type(arguments) is not list or len(arguments) != 3 or arguments[0] != 'cp'
            or type(arguments[1]) is not str or type(arguments[2]) is not str
            or type(label) is not str or re.fullmatch(r'[a-z0-9-]+', label) is None):
        raise ValueError('source extraction permits only Docker cp')
    name, colon, remote = arguments[1].partition(':')
    path = PurePosixPath(remote)
    if (not colon or re.fullmatch(r't3-structural-source-[0-9a-f]{32}', name) is None
            or remote not in ('/opt/classic-native-kernels-v1', '/opt/t3-classic-structural-v2')
            or not path.is_absolute() or '..' in path.parts
            or path.as_posix() != remote or not Path(arguments[2]).is_absolute()):
        raise ValueError('exact owned container and absolute source-copy paths required')
    if commands.cap != LOG_BYTES:
        raise ValueError('source-copy log limit must remain16MiB')
    target = Path(arguments[2])
    if (target.parent != commands.folder.parent or target.exists() or target.is_symlink()
            or not target.parent.is_dir() or str(target) != str(target.resolve())):
        raise ValueError('fresh non-symlink evidence source target required')
    for candidate in (target.parent, commands.folder, *target.parent.parents):
        if candidate.is_symlink():
            raise ValueError('source-copy evidence parent symlink refused')
    if len(commands.rows) != 2:
        raise ValueError('one fresh create and inspect must precede source copy')
    create, inspected = commands.rows
    if (create['argv'][:2] != ['docker', 'create'] or create['returncode'] != 0
            or not create['succeeded'] or inspected['argv'] != ['docker', 'inspect', name]
            or not inspected['succeeded'] or create['argv'][create['argv'].index('--name') + 1] != name):
        raise ValueError('actual source-copy command provenance required')
    owner = create['argv'][create['argv'].index('--label') + 1]
    if re.fullmatch(r'qfbench2\.t3\.verifier_owner=[0-9a-f]{32}', owner) is None:
        raise ValueError('actual source-copy owner label required')
    image = create['argv'][-1]
    if re.fullmatch(r'sha256:[0-9a-f]{64}', image) is None:
        raise ValueError('actual immutable source-copy image required')
    if create['argv'] != ['docker', 'create', '--name', name, '--label', owner, '--pull', 'never', image]:
        raise ValueError('exact source-only Docker create command required')
    inspection = Path(inspected['stdout']['path'])
    if inspection.parent != commands.folder or inspection.is_symlink():
        raise ValueError('local exact source-copy inspection required')
    for previous in (create, inspected):
        if (previous.get('creator_reaped') is not True or previous.get('cancelled') is not False
                or previous.get('timed_out') is not False or previous.get('error') is not None):
            raise ValueError('actual source-copy command completion required')
        for stream_name in ('stdout', 'stderr'):
            recorded = previous[stream_name]
            path_to_log = Path(recorded['path'])
            if (path_to_log.parent != commands.folder or path_to_log.is_symlink()
                    or _pin(path_to_log) != {k: recorded[k] for k in ('path', 'bytes', 'sha256')}
                    or recorded.get('hard_limit_reached') is not False):
                raise ValueError('exact bounded source-copy provenance log required')
    import json
    values = json.loads(inspection.read_bytes())
    if len(values) != 1:
        raise ValueError('one actual owned source-copy container required')
    value = values[0]
    if (value['Name'] != '/' + name or value['Image'] != image
            or value['Config']['Labels'][linux.OWNER_LABEL] != owner.split('=', 1)[1]
            or value['State']['Status'] != 'created' or value['State']['Pid'] != 0
            or value['State']['Running'] is not False
            or value['State']['StartedAt'] != '0001-01-01T00:00:00Z'
            or value['State']['FinishedAt'] != '0001-01-01T00:00:00Z'):
        raise ValueError('source extraction requires never-started exact owned container')
    if Path(create['stdout']['path']).read_text() != value['Id'] + '\n':
        raise ValueError('source-copy actual created identity differs')
    prefix = commands.folder / ('%03d-%s' % (len(commands.rows), label))
    row = _run_bounded([commands.docker, *arguments], prefix, seconds, linux.check_cancelled)
    commands.rows.append(row)
    return row
