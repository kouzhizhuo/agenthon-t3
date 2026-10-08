#!/usr/bin/env python3
"""Evaluator-only journal around Docker creation; contestant/harness bytes unchanged."""
import json
import os
from pathlib import Path
import signal
import re
import subprocess
import sys
import time


def atomic(path, value):
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def main():
    directory = Path(os.environ["T3_PROXY_STATE"])
    directory.mkdir(parents=True, exist_ok=True)
    real = os.environ["T3_REAL_DOCKER"]
    arguments = sys.argv[1:]
    creates = bool(arguments) and arguments[0] in ("create", "run")
    if not creates:
        os.execv(real, [real] + arguments)
    # This process is outside the original harness group, and stays alive until
    # synchronous daemon creation has returned an ID or an explicit outcome.
    os.setsid()
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    plan = json.loads((directory / "PLAN.json").read_text())
    allowed = {row["name"] for row in plan["containers"]}
    if arguments[0] == "run":
        if "--name" in arguments:
            raise ValueError("unexpected named probe")
        arguments = [arguments[0], "--name", plan["probe_name"], "--cidfile", str(directory / "probe.cid")] + arguments[1:]
    name = arguments[arguments.index("--name") + 1] if "--name" in arguments else None
    if name not in allowed:
        raise ValueError("Docker create/run outside exact evaluator plan")
    journal = directory / ("operation-" + str(os.getpid()) + ".json")
    row = {"name": name, "arguments": arguments, "proxy_pid": os.getpid(),
           "started": time.time(), "state": "starting", "returncode": None,
           "stdout": None, "stderr": None}
    atomic(journal, row)
    if (directory / "CANCEL").exists():
        row.update(state="denied_cancel", returncode=125, finished=time.time())
        atomic(journal, row)
        sys.stderr.write("correctness controller cancelled; no new Docker creation\n")
        return 125
    process = None
    try:
        process = subprocess.Popen([real] + arguments, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        row.update(state="pending", real_pid=process.pid)
        atomic(journal, row)
        stdout, stderr = process.communicate(timeout=90)
        row.update(state="settled", returncode=process.returncode, stdout=stdout.decode(errors="replace"),
                   stderr=stderr.decode(errors="replace"), finished=time.time())
        if arguments[0] == "create" and process.returncode == 0:
            row["created_id"] = stdout.decode().strip()
        if arguments[0] == "run" and (directory / "probe.cid").is_file():
            identifier = (directory / "probe.cid").read_text().strip()
            if re.fullmatch(r"[0-9a-f]{64}", identifier):
                row["created_id"] = identifier
        atomic(journal, row)
        try:
            sys.stdout.buffer.write(stdout)
            sys.stdout.buffer.flush()
            sys.stderr.buffer.write(stderr)
            sys.stderr.buffer.flush()
        except BrokenPipeError:
            pass
        return process.returncode
    except BaseException as exc:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            except BaseException as cleanup_exc:
                row["termination_error"] = str(cleanup_exc)
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value
        row.update(state="unresolved", error_type=type(exc).__name__, error=str(exc),
                   partial_stdout=decode(getattr(exc, "output", None)),
                   partial_stderr=decode(getattr(exc, "stderr", None)), finished=time.time())
        if arguments[0] == "run" and (directory / "probe.cid").is_file():
            identifier = (directory / "probe.cid").read_text().strip()
            if re.fullmatch(r"[0-9a-f]{64}", identifier):
                row["created_id"] = identifier
        atomic(journal, row)
        return 125


if __name__ == "__main__":
    sys.exit(main())
