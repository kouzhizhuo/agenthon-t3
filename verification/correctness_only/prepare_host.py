"""Separate correctness-only host preflight; preserve observations before guard failure."""
import argparse
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = {"scope": "correctness_only", "rankable": False, "performance_admission": False,
               "platform": sys.platform, "host": platform.platform(), "machine": platform.machine(),
               "memory": None, "cpuset": None, "cpu_max": None, "lscpu": None,
               "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
               "read_errors": [], "guard_errors": [], "guard_passed": False}
    path = args.out / "HOST_PREFLIGHT.json"

    def save():
        path.write_text(json.dumps(receipt, indent=2) + "\n")

    save()
    readers = {
        "memory": lambda: {line.split(":")[0]: int(line.split()[1]) * 1024
                           for line in Path("/proc/meminfo").read_text().splitlines()
                           if line.split(":")[0] in ("MemTotal", "MemAvailable")},
        "cpuset": lambda: sorted(os.sched_getaffinity(0)),
        "cpu_max": lambda: Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
        "lscpu": lambda: subprocess.run(["lscpu"], capture_output=True, text=True, check=True).stdout,
    }
    for field, reader in readers.items():
        try:
            receipt[field] = reader()
        except BaseException as exc:
            receipt["read_errors"].append({"field": field, "type": type(exc).__name__, "reason": str(exc)})
        save()
    if receipt["platform"] != "linux" or receipt["machine"] != "x86_64":
        receipt["guard_errors"].append("actual Linuxamd64 required")
    mem = receipt["memory"] or {}
    if mem.get("MemTotal", 0) < 12 * 1024**3 or mem.get("MemAvailable", 0) < 4 * 1024**3:
        receipt["guard_errors"].append("VMRAM below unchanged environment guard")
    if not receipt["cgroup_v2"]:
        receipt["guard_errors"].append("readable cgroupv2 required")
    if not receipt["cpuset"]:
        receipt["guard_errors"].append("nonempty CPU affinity required")
    cpu_max = receipt["cpu_max"] or ""
    if not re.fullmatch(r"(?:max|[1-9][0-9]*) [1-9][0-9]*", cpu_max):
        receipt["guard_errors"].append("readable well-formed host cpu.max required")
    receipt["host_cpu_quota_imposed"] = not cpu_max.startswith("max ")
    receipt["host_cpu_quota_allowed_only_for_correctness"] = True
    receipt["guard_passed"] = not receipt["read_errors"] and not receipt["guard_errors"]
    save()
    if not receipt["guard_passed"]:
        raise RuntimeError("correctness-only host preflight failed; observations preserved")

    # Execute only the exact frozen reference-acquisition tail. It starts after all
    # host checks; original source bytes and strict timing preflight remain intact.
    frozen = Path("t3/research1008v5b/github_linux/prepare_host.py")
    spec = importlib.util.spec_from_file_location("frozen_reference_setup", frozen)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = frozen.read_text()
    start = original.index(" refs=json.loads(")
    end = original.index("if __name__=='__main__':")
    tail = "\n".join(line[1:] for line in original[start:end].splitlines())
    (args.out / "cpuset.txt").write_text(",".join(map(str, receipt["cpuset"])) + "\n")
    namespace = dict(vars(module), args=args, cpus=receipt["cpuset"], mem=mem)
    exec(compile(tail, str(frozen) + ":exact_reference_tail", "exec"), namespace)


if __name__ == "__main__":
    main()
