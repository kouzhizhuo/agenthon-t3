"""Finite same-image cold launches; environment diagnosis, no simulation."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import uuid

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
VERSION_PRINT = ";import sys,json;print(json.dumps({'python':sys.version,'modules':{n:getattr(sys.modules[n],'__version__',None) for n in ('numpy','pandas','pyarrow') if n in sys.modules}}))"
ARMS = [
    ("true", ["/usr/bin/true"]),
    ("python", ["/usr/local/bin/python", "-B", "-c", "pass"]),
    ("python_isolated", ["/usr/local/bin/python", "-I", "-S", "-B", "-c", "pass"]),
    ("numpy", ["/usr/local/bin/python", "-B", "-c", "import numpy" + VERSION_PRINT]),
    ("numpy_pandas", ["/usr/local/bin/python", "-B", "-c", "import numpy,pandas" + VERSION_PRINT]),
    ("numpy_arrow", ["/usr/local/bin/python", "-B", "-c", "import numpy,pyarrow" + VERSION_PRINT]),
    ("numpy_pandas_arrow", ["/usr/local/bin/python", "-B", "-c", "import numpy,pandas,pyarrow" + VERSION_PRINT]),
]
RESOURCE = {
    "NanoCpus": 4000000000, "Memory": 17179869184, "MemorySwap": 17179869184,
    "NetworkMode": "none", "ReadonlyRootfs": True, "PidsLimit": 256,
    "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"],
    "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=64m"},
}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run_command(root, label, command, timeout=60, allow=False):
    log = root / (label + ".log")
    start = time.monotonic()
    error, result = None, None
    with log.open("xb") as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        except BaseException as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
    row = {"command": command, "returncode": None if result is None else result.returncode,
           "error": error, "elapsed_host_sec": time.monotonic() - start,
           "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
    write(root / (label + ".json"), row)
    if not allow and (error or result.returncode):
        raise ValueError("actual bounded command failed: " + label)
    return row


def inspect(root, label, object_id):
    run_command(root, label, ["docker", "inspect", object_id])
    data = json.loads((root / (label + ".log")).read_text())
    if type(data) is not list or len(data) != 1:
        raise ValueError("exactly one Docker object required")
    return data[0]


def check(value, image_id, command):
    if value["Image"] != image_id or value["Config"]["User"] != "65534:65534":
        raise ValueError("actual image or user differs")
    if value["Config"]["Entrypoint"] != command[:1] or value["Config"]["Cmd"] != command[1:]:
        raise ValueError("actual executable and args differ")
    host = value["HostConfig"]
    if {k: host.get(k) for k in RESOURCE} != RESOURCE:
        raise ValueError("actual cold-launch resources differ")
    if any(m["Type"] != "tmpfs" or m["Destination"] != "/tmp" for m in value["Mounts"]):
        raise ValueError("unplanned image or host mount")
    limits = {r["Name"]: (r["Soft"], r["Hard"]) for r in host.get("Ulimits", [])}
    if limits != {"nofile": (1024, 1024), "nproc": (256, 256), "fsize": (268435456, 268435456)}:
        raise ValueError("actual process/file limits differ")
    for key, required in {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                          "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}.items():
        values = [s.split("=", 1)[1] for s in value["Config"]["Env"] if s.startswith(key + "=")]
        if values != [required]:
            raise ValueError("actual thread or interpreter env differs")


def parse_docker_time(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def launch(root, image_id, arm, command, repeat):
    target = root / (str(repeat) + "-" + arm)
    target.mkdir()
    name = "t3-cold-" + uuid.uuid4().hex
    created = False
    create_attempted = False
    row = {"arm": arm, "repeat": repeat, "passed": False, "cleanup": False}
    try:
        args = ["docker", "create", "--name", name, "--network", "none", "--read-only", "--cpus", "4",
                "--memory", str(RESOURCE["Memory"]), "--memory-swap", str(RESOURCE["MemorySwap"]),
                "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "65534:65534", "--tmpfs", "/tmp:" + RESOURCE["Tmpfs"]["/tmp"],
                "--ulimit", "nofile=1024:1024", "--ulimit", "nproc=256:256", "--ulimit", "fsize=268435456:268435456"]
        for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            args.extend(["--env", k + "=1"])
        args.extend(["--env", "PYTHONHASHSEED=0", "--env", "PYTHONDONTWRITEBYTECODE=1",
                     "--entrypoint", command[0], image_id] + command[1:])
        create_attempted = True
        run_command(target, "create", args)
        created = True
        before = inspect(target, "before", name)
        check(before, image_id, command)
        run_command(target, "start", ["docker", "start", name])
        run_command(target, "wait", ["docker", "wait", name], timeout=60)
        after = inspect(target, "after", name)
        check(after, image_id, command)
        state = after["State"]
        if state["Running"] or state["ExitCode"] or state["OOMKilled"] or state["Status"] != "exited":
            raise ValueError("actual cold process failed")
        elapsed = (parse_docker_time(state["FinishedAt"]) - parse_docker_time(state["StartedAt"])).total_seconds()
        if elapsed <= 0:
            raise ValueError("positive Docker lifecycle interval required")
        row.update(passed=True, docker_elapsed_sec=elapsed, state=state, command=command)
    except BaseException as exc:
        row["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        # Creation may reach the daemon even when the client times out. Inspect
        # this unique owned name after every attempt before releasing the serial
        # workload; absence and successful removal are distinct retained paths.
        if create_attempted:
            try:
                inspection = run_command(target, "cleanup-inspect", ["docker", "inspect", name], allow=True)
                lines = sorted(x.strip() for x in (target / "cleanup-inspect.log").read_text().splitlines() if x.strip())
                absent_lines = sorted(["[]", "Error: No such object: " + name])
                if (inspection["error"] is None and inspection["returncode"] == 1 and lines == absent_lines):
                    if created:
                        raise ValueError("created owned container unexpectedly absent before cleanup")
                    row["cleanup"] = True
                    row["cleanup_no_container_after_failed_create"] = True
                else:
                    if inspection["error"] is not None or inspection["returncode"] != 0:
                        raise ValueError("owned container state unknown after create attempt")
                    data = json.loads((target / "cleanup-inspect.log").read_text())
                    if type(data) is not list or len(data) != 1:
                        raise ValueError("exactly one owned cleanup container required")
                    value = data[0]
                    if value["Name"] != "/" + name or value["Image"] != image_id:
                        raise ValueError("cleanup container owned name/image identity differs")
                    if value["State"]["Running"]:
                        run_command(target, "cleanup-kill", ["docker", "kill", name], allow=True)
                    run_command(target, "cleanup-wait", ["docker", "wait", name], allow=True)
                    settled = inspect(target, "settled", name)
                    if settled["Name"] != "/" + name or settled["Image"] != image_id:
                        raise ValueError("settled cleanup container identity differs")
                    run_command(target, "stdout", ["docker", "logs", name], allow=True)
                    if not settled["State"]["Running"]:
                        removed = run_command(target, "remove", ["docker", "rm", name], allow=True)
                        absence = run_command(target, "absence", ["docker", "inspect", name], allow=True)
                        lines = sorted(x.strip() for x in (target / "absence.log").read_text().splitlines() if x.strip())
                        row["cleanup"] = (removed["error"] is None and removed["returncode"] == 0
                            and absence["error"] is None and absence["returncode"] == 1 and lines == absent_lines)
            except BaseException as exc:
                row["cleanup_failure"] = {"type": type(exc).__name__, "message": str(exc)}
        row["passed"] = row["passed"] and row["cleanup"]
        write(target / "RESULT.json", row)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64" or args.evidence.exists():
        raise ValueError("fresh Linux amd64 diagnostic required")
    args.evidence.mkdir(parents=True)
    config = args.evidence / "anonymous-config"
    config.mkdir()
    result = {"schema": "t3-cold-dependency-diagnostic-v2", "all_passed": False,
              "rankable": False, "simulation_executed": False, "official_submission": False,
              "irreducible_floor_claimed": False, "runs": []}
    try:
        old = os.environ.get("DOCKER_CONFIG")
        os.environ["DOCKER_CONFIG"] = str(config.resolve())
        try:
            run_command(args.evidence, "pull", ["docker", "pull", "--platform", "linux/amd64", BASE], timeout=600)
        finally:
            if old is None:
                os.environ.pop("DOCKER_CONFIG", None)
            else:
                os.environ["DOCKER_CONFIG"] = old
        before = inspect(args.evidence, "image-before", BASE)
        if before["Os"] != "linux" or before["Architecture"] != "amd64" or before["Config"].get("Volumes"):
            raise ValueError("actual base image Linux ABI or inherited volumes differ")
        if BASE.split("@", 1)[1] not in " ".join(before.get("RepoDigests", [])):
            raise ValueError("actual immutable base differs")
        for repeat in range(5):
            ordered = ARMS[repeat:] + ARMS[:repeat]
            for arm, command in ordered:
                row = launch(args.evidence, before["Id"], arm, command, repeat)
                result["runs"].append(row)
                if not row["passed"]:
                    raise ValueError("actual finite cold-launch failed: " + arm)
        after = inspect(args.evidence, "image-after", before["Id"])
        if before != after:
            raise ValueError("actual base image changed")
        result["image_unchanged"] = True
        result["median_docker_sec"] = {arm: statistics.median(r["docker_elapsed_sec"] for r in result["runs"] if r["arm"] == arm) for arm, _ in ARMS}
        result["all_passed"] = True
    except BaseException as exc:
        result["failure"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        write(args.evidence / "RESULT.json", result)
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
