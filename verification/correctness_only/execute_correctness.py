"""One unchanged correctness cohort, with explicit host-monitor error propagation."""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cpus = (args.out / "cpuset.txt").read_text().strip()
    samples, failures = [], []
    stop, unhealthy, first_sample = threading.Event(), threading.Event(), threading.Event()
    proc = None
    controller_error = None

    def monitor():
        try:
            while not stop.is_set():
                try:
                    memory = {line.split(":")[0]: int(line.split()[1]) * 1024
                              for line in Path("/proc/meminfo").read_text().splitlines()
                              if line.startswith("MemAvailable:")}
                    row = {"wall_time": time.time(), "monotonic": time.monotonic(),
                           "MemAvailable": memory["MemAvailable"],
                           "proc_stat_cpu": Path("/proc/stat").read_text().splitlines()[0],
                           "host_cpu_stat": Path("/sys/fs/cgroup/cpu.stat").read_text()}
                    samples.append(row)
                    if row["MemAvailable"] < 4 * 1024**3:
                        failures.append({"type": "LowMemory", "row": row})
                        unhealthy.set()
                except BaseException as exc:
                    failures.append({"wall_time": time.time(), "type": type(exc).__name__, "reason": str(exc)})
                    unhealthy.set()
                first_sample.set()
                if unhealthy.is_set():
                    return
                stop.wait(0.5)
        finally:
            first_sample.set()

    worker = threading.Thread(target=monitor, daemon=True)
    worker.start()

    def stop_own_process():
        if proc is None or proc.poll() is not None:
            return
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            if proc.poll() is not None:
                return
            os.killpg(proc.pid, sig)
            try:
                proc.wait(timeout=45 if sig != signal.SIGKILL else 10)
                return
            except subprocess.TimeoutExpired:
                pass

    try:
        if not first_sample.wait(10) or unhealthy.is_set():
            raise RuntimeError("host monitor failed before correctness; no cohort")
        command = [sys.executable, "t3/research1008v5b/linux_verification/run.py", "correctness",
                   "--evaluator-python", sys.executable, "--cpuset-cpus", cpus,
                   "--runtime", "runc", "--out", str(args.out / "correctness")]
        with (args.out / "correctness.log").open("w") as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while proc.poll() is None:
                if unhealthy.is_set() or not worker.is_alive():
                    stop_own_process()
                    raise RuntimeError("host monitor failed; original own-container cleanup triggered")
                time.sleep(0.5)
            if proc.returncode:
                raise RuntimeError("frozen correctness failed; preserve partial evidence without replacement")
        stop.set()
        worker.join(timeout=10)
        if worker.is_alive() or unhealthy.is_set() or failures or not samples:
            raise RuntimeError("host-monitor evidence incomplete or failed")
        summary = json.loads((args.out / "correctness/summary.json").read_text())
        controls = {version: json.loads((args.out / ("controls" + version) / ("controls_py" + version + ".json")).read_text())
                    for version in ("311", "313")}
        exact = summary["processes"] == 142 and summary["all_output_bytes_counts_reference_frames_and_developer_gates_exact"]
        control_exact = all(c["passed"] and c["cases"] == 566
                            and c["python"].split()[0] == ("3.11.17" if version == "311" else "3.13.7")
                            and c["source_sha256"] == "b7cea49f0b992d60bbde435374d47e8558b2198ed9cb5d164d6c868b0c5aa141"
                            and c["baseline_sha256"] == "ac4a28892f903f1c5790f54e25833188efa7e57e32fab8e651092a9b329733e7"
                            for version, c in controls.items())
        if not exact or not control_exact:
            raise RuntimeError("incomplete correctness or differential controls")
        result = {"rankable": False, "scope": "correctness_only", "performance_admission": False,
                  "timing_execution": False, "correctness_completed": True,
                  "correctness_admission": True, "correctness_summary_path": "correctness/summary.json",
                  "correctness_processes": summary["processes"], "actual_controls": controls,
                  "note": "Incidental original correctness walls/rates/ratios are retained as raw diagnostics only. Hosted quota or throttling is not a timing result."}
        (args.out / "CORRECTNESS_ONLY_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
    except BaseException as exc:
        controller_error = {"type": type(exc).__name__, "reason": str(exc), "no_replacement_run": True}
        stop_own_process()
        raise
    finally:
        stop.set()
        worker.join(timeout=10)
        if worker.is_alive():
            failures.append({"type": "MonitorJoinFailure", "reason": "monitor did not terminate"})
        (args.out / "HOST_MONITOR_SAMPLES.json").write_text(json.dumps(samples, indent=2) + "\n")
        (args.out / "HOST_MONITOR_FAILURES.json").write_text(json.dumps(failures, indent=2) + "\n")
        if controller_error:
            (args.out / "CONTROLLER_FAILURE.json").write_text(json.dumps(controller_error, indent=2) + "\n")


if __name__ == "__main__":
    main()
