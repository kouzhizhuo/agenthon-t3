"""Exact reviewed host process manager copy; no execution on import."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
LOG_CAP = 16 * 1024**2
CLEANUP_GRACE = 90

def require(value,message):
    if not value:raise ValueError(message)

def pin(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=LOG_CAP,'boundedregularprocesslog')
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):digest.update(block)
    return {'bytes':path.stat().st_size,'sha256':digest.hexdigest()}

def write(path,value):
    with Path(path).open('x') as stream:stream.write(json.dumps(value,sort_keys=True,indent=2)+'\n')

def run_saved_process(args, linux, command, label, seconds, cap=LOG_CAP, anonymous=False):
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
