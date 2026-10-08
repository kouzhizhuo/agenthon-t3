"""Separate correctness-only controller with journaled creation and checked cleanup."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from cleanup import cleanup_receipts, plan, sweep


HERE = Path(__file__).resolve().parent


def save(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def valid_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def operations(directory):
    rows = []
    for path in sorted(directory.glob("operation-*.json")):
        try:
            row = json.loads(path.read_text())
            if not isinstance(row, dict) or row.get("state") not in ("starting", "pending", "settled", "denied_cancel", "unresolved"):
                raise ValueError("invalid proxy journal")
            if not isinstance(row.get("name"), str) or not row["name"] or not isinstance(row.get("arguments"), list) or not row["arguments"] or not all(isinstance(x, str) for x in row["arguments"]) or row["arguments"][0] not in ("create", "run"):
                raise ValueError("invalid proxy name/arguments")
            returncode = row.get("returncode")
            if (returncode is not None and type(returncode) is not int) or (row["state"] in ("settled", "denied_cancel") and type(returncode) is not int):
                raise ValueError("invalid proxy returncode")
            if "created_id" in row and not valid_id(row["created_id"]):
                raise ValueError("invalid proxy-created ID")
            if row["state"] == "settled" and returncode == 0 and row["arguments"][0] == "create" and not valid_id(row.get("created_id")):
                raise ValueError("successful create requires exact proxy-created ID")
            rows.append(dict(row, journal=str(path)))
        except BaseException as exc:
            rows.append({"state": "unresolved", "error": str(exc), "journal": str(path)})
    return rows


def journal_admission(expected, rows):
    # Invalid journals are unresolved receipts, not a reason to abort the
    # controller's final cleanup. Count without assuming optional field types.
    creates, probes, created_ids = [], [], {}
    for row in rows:
        arguments = row.get("arguments")
        if not isinstance(arguments, list) or not arguments:
            continue
        name = row.get("name")
        identifier = row.get("created_id")
        if isinstance(name, str) and valid_id(identifier):
            created_ids[name] = identifier
        successful = isinstance(name, str) and bool(name) and row.get("state") == "settled" and type(row.get("returncode")) is int and row["returncode"] == 0
        if successful and arguments[0] == "create" and valid_id(identifier):
            creates.append(name)
        if successful and arguments[0] == "run":
            probes.append(name)
    passed = (sorted(creates) == sorted(r["name"] for r in expected["containers"] if not r["probe"])
              and probes == [expected["probe_name"]]
              and len(rows) == len(expected["containers"])
              and all(r.get("state") == "settled" and type(r.get("returncode")) is int and r["returncode"] == 0 for r in rows))
    return {"passed": passed, "successful_creates": creates, "successful_probes": probes, "created_ids": created_ids}


def settle(directory, timeout=100):
    deadline = time.monotonic() + timeout
    while True:
        rows = operations(directory)
        pending = [r for r in rows if r["state"] in ("starting", "pending")]
        if not pending or time.monotonic() >= deadline:
            return rows, not pending and not any(r["state"] == "unresolved" for r in rows)
        time.sleep(0.1)


def main():
    def interrupted(signum, frame):
        raise RuntimeError("correctness controller interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    root = Path.cwd().resolve()
    state = output / "cleanup_v3"
    correctness = output / "correctness"
    if state.exists() or correctness.exists():
        raise ValueError("fresh cleanup and correctness directories required")
    state.mkdir(parents=True)
    protocol_raw = (root / "t3/research1008v5b/linux_verification/PROTOCOL.json").read_bytes()
    if hashlib.sha256(protocol_raw).hexdigest() != "9f27cdbc0fb901f59471e487d263828361ea749ace9f82388b1d339c80f2e55c":
        save(state / "FINAL.json", {"admitted": False, "error": "frozen correctness protocol mismatch; no scope or removal"})
        raise RuntimeError("frozen correctness protocol mismatch")
    protocol = json.loads(protocol_raw)
    expected = plan(root, correctness, protocol)
    save(state / "PLAN.json", expected)
    docker = shutil.which("docker")
    if not docker:
        save(state / "FINAL.json", {"admitted": False, "error": "Docker unavailable"})
        raise RuntimeError("Docker unavailable")
    cpus = None
    stop, unhealthy, first = threading.Event(), threading.Event(), threading.Event()
    samples, monitor_errors = [], []
    proc = None
    error = None
    summary = controls = None
    preflight = None
    worker = None
    finalized = {"admitted": False, "correctness_admission": False, "correctness_completed": False,
                 "scope": "correctness_only", "timing_execution": False,
                 "performance_admission": False, "rankable": False}

    def monitor():
        try:
            while not stop.is_set():
                try:
                    memory = next(int(line.split()[1]) * 1024 for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
                    row = {"monotonic": time.monotonic(), "MemAvailable": memory,
                           "proc_stat_cpu": Path("/proc/stat").read_text().splitlines()[0],
                           "host_cpu_stat": Path("/sys/fs/cgroup/cpu.stat").read_text()}
                    samples.append(row)
                    if memory < 4 * 1024**3:
                        raise RuntimeError("host MemAvailable below guard")
                except BaseException as exc:
                    monitor_errors.append({"type": type(exc).__name__, "reason": str(exc)})
                    unhealthy.set()
                first.set()
                if unhealthy.is_set():
                    return
                stop.wait(0.5)
        finally:
            first.set()

    def cancel_and_stop():
        (state / "CANCEL").write_text("no new create/run\n")
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        _, settled = settle(state)
        if not settled:
            finalized["unsettled_creation"] = True
        for sig in (None, signal.SIGTERM, signal.SIGKILL):
            if proc.poll() is not None:
                break
            if sig is not None:
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=45 if sig != signal.SIGKILL else 10)
            except subprocess.TimeoutExpired:
                continue
        if proc.poll() is None:
            raise RuntimeError("own harness process did not exit; cleanup cannot be certified")

    try:
        cpus = (output / "cpuset.txt").read_text().strip()
        preflight = sweep(docker, expected, remove=False)
        save(state / "PRELAUNCH_ABSENCE.json", preflight)
        if preflight["errors"] or preflight["found"]:
            raise RuntimeError("exact planned container names not all demonstrably absent")
        controls = {v: json.loads((output / ("controls" + v) / ("controls_py" + v + ".json")).read_text()) for v in ("311", "313")}
        for v, c in controls.items():
            if not (c["passed"] and c["cases"] == 566 and c["python"].split()[0] == ("3.11.17" if v == "311" else "3.13.7")
                    and c["source_sha256"] == "b7cea49f0b992d60bbde435374d47e8558b2198ed9cb5d164d6c868b0c5aa141"
                    and c["baseline_sha256"] == "ac4a28892f903f1c5790f54e25833188efa7e57e32fab8e651092a9b329733e7"):
                raise RuntimeError("actual control identities/counts invalid before cohort")
        proxy = state / "bin"
        proxy.mkdir()
        launcher = proxy / "docker"
        launcher.write_text("#!" + sys.executable + "\nimport runpy\nrunpy.run_path(" + repr(str(HERE / "docker_proxy.py")) + ", run_name='__main__')\n")
        launcher.chmod(0o755)
        environment = dict(os.environ, PATH=str(proxy) + os.pathsep + os.environ.get("PATH", ""),
                           T3_REAL_DOCKER=docker, T3_PROXY_STATE=str(state))
        worker = threading.Thread(target=monitor, daemon=True)
        worker.start()
        if not first.wait(10) or unhealthy.is_set():
            raise RuntimeError("host monitor failed before cohort")
        cmd = [sys.executable, str(root / "t3/research1008v5b/linux_verification/run.py"), "correctness",
               "--evaluator-python", sys.executable, "--cpuset-cpus", cpus, "--runtime", "runc", "--out", str(correctness)]
        with (output / "correctness.log").open("w") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=environment, start_new_session=True)
            while proc.poll() is None:
                if unhealthy.is_set() or not worker.is_alive():
                    raise RuntimeError("host monitor failed during cohort")
                time.sleep(0.5)
            if proc.returncode:
                raise RuntimeError("frozen correctness failed; no replacement")
        summary = json.loads((correctness / "summary.json").read_text())
        raw = json.loads((correctness / "raw_runs.json").read_text())
        observed = [(r["unit"], r["variant"], r["pair"]) for r in raw]
        wanted = []
        for index, unit in enumerate(protocol["correctness_units"]):
            wanted.extend((unit, v, 0) for v in (("v3", "v5b") if index % 2 == 0 else ("v5b", "v3")))
        if observed != wanted or summary["processes"] != 142 or not summary["all_output_bytes_counts_reference_frames_and_developer_gates_exact"]:
            raise RuntimeError("incomplete/incorrect frozen roster")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "reason": str(exc), "no_replacement": True}
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop.set()
        if worker:
            worker.join(timeout=10)
            if worker.is_alive():
                monitor_errors.append({"type": "JoinFailure", "reason": "host monitor not terminated"})
        try:
            cancel_and_stop()
        except BaseException as exc:
            finalized["stop_error"] = str(exc)
        journals, settled = settle(state)
        save(state / "DOCKER_OPERATIONS.json", journals)
        journal_summary = journal_admission(expected, journals)
        journal_roster_pass = journal_summary["passed"]
        created_ids = journal_summary["created_ids"]
        save(state / "JOURNAL_ADMISSION.json", journal_summary)
        clean = cleanup_receipts(expected)
        save(state / "ORIGINAL_CLEANUP_CHECKS.json", clean)
        # No same-name object is removed without full image/source/input/output
        # identity. Use immutable ID after verification, never a broad prefix.
        reconciliation = sweep(docker, expected, remove=preflight is not None and not preflight["errors"] and not preflight["found"], created_ids=created_ids)
        save(state / "RECONCILIATION.json", reconciliation)
        final_absence = sweep(docker, expected, remove=False)
        save(state / "FINAL_ABSENCE.json", final_absence)
        save(state / "HOST_MONITOR_SAMPLES.json", samples)
        save(state / "HOST_MONITOR_ERRORS.json", monitor_errors)
        finalized.update(error=error, original_cleanup_pass=clean["passed"], operations_settled=settled,
                         journal_roster_pass=journal_roster_pass,
                         monitor_pass=bool(samples) and not monitor_errors and not unhealthy.is_set(),
                         reconciled_containers=reconciliation["found"], reconciliation_errors=reconciliation["errors"],
                         final_absence_pass=not final_absence["errors"] and not final_absence["found"])
        finalized["admitted"] = (error is None and summary is not None and clean["passed"] and settled and journal_roster_pass
                                  and finalized["monitor_pass"] and not reconciliation["found"] and not reconciliation["errors"]
                                  and finalized["final_absence_pass"] and not finalized.get("stop_error")
                                  and not finalized.get("unsettled_creation"))
        finalized["correctness_admission"] = finalized["admitted"]
        finalized["correctness_completed"] = summary is not None
        save(state / "FINAL.json", finalized)
    if not finalized["admitted"]:
        raise RuntimeError("correctness/cleanup admission failed; preserved without rerun")
    save(output / "CORRECTNESS_ONLY_RECEIPT.json", dict(finalized, actual_controls=controls, correctness_processes=142))


if __name__ == "__main__":
    main()
