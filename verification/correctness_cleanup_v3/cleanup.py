"""Exact-plan Docker reconciliation and original cleanup receipt admission."""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def plan(root, output, protocol):
    rows = []
    for unit in protocol["correctness_units"]:
        scenario = root / "t3/evaluation_references" / unit
        batch = (scenario / "batch.json").exists()
        for variant in ("v3", "v5b"):
            out = output / variant / "0" / unit
            rows.append({"name": "t3verify-" + hashlib.sha256(str(out).encode()).hexdigest()[:24],
                         "unit": unit, "variant": variant, "output": str(out),
                         "cmd": ["simulate-batch", "--batch-dir", "/input/scenarios", "--out-dir", "/output"] if batch else ["simulate", "--config", "/input/scenario.json", "--out", "/output/trace.parquet"],
                         "mounts": [(str(root / "t3/research1008v5b" / ("baseline" if variant == "v3" else "runtime")), "/opt/t3", False),
                                    (str(scenario / ("scenarios" if batch else "scenario.json")), "/input/scenarios" if batch else "/input/scenario.json", False),
                                    (str(out), "/output", True)], "probe": False})
    probe_name = "t3probe-" + hashlib.sha256(str(output).encode()).hexdigest()[:24]
    rows.append({"name": probe_name, "mounts": [], "probe": True,
                 "cmd": ["-c", "import json,sys,numpy,pandas,scipy,pyarrow;print(json.dumps(dict(python=sys.version.split()[0],numpy=numpy.__version__,pandas=pandas.__version__,scipy=scipy.__version__,pyarrow=pyarrow.__version__)))"]})
    return {"image": protocol["existing_image"], "containers": rows, "probe_name": probe_name}


def command(docker, arguments):
    try:
        p = subprocess.run([docker] + arguments, capture_output=True, text=True, timeout=20)
        return {"arguments": arguments, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
    except BaseException as exc:
        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value
        return {"arguments": arguments, "returncode": None, "error": type(exc).__name__ + ": " + str(exc),
                "partial_stdout": decode(getattr(exc, "output", None)),
                "partial_stderr": decode(getattr(exc, "stderr", None))}


def inspect(docker, name):
    receipt = command(docker, ["container", "inspect", name])
    if receipt["returncode"] == 0:
        try:
            values = json.loads(receipt["stdout"])
            if len(values) != 1 or not re.fullmatch(r"[0-9a-f]{64}", values[0]["Id"]):
                raise ValueError("invalid container identity")
            return "present", values[0], receipt
        except BaseException as exc:
            receipt["parse_error"] = str(exc)
    # Only explicit daemon exact-container absence is accepted; permissions,
    # unavailable daemon, transport errors and malformed output are failures.
    elif receipt["returncode"] == 1 and receipt.get("stdout", "").strip() == "[]" and receipt.get("stderr", "").strip() in (
            "Error response from daemon: No such container: " + name,
            "Error: No such container: " + name):
        return "absent", None, receipt
    return "error", None, receipt


def owned(row, obj, image):
    actual = sorted((m.get("Source"), m.get("Destination"), m.get("RW")) for m in obj.get("Mounts", []) if m.get("Type") == "bind")
    mounts = sorted(tuple(m) for m in row["mounts"])
    config, host = obj.get("Config", {}), obj.get("HostConfig", {})
    return (obj.get("Name") == "/" + row["name"] and config.get("Image") == image
            and config.get("Cmd") == row["cmd"] and config.get("User") == "65534:65534"
            and host.get("ReadonlyRootfs") is True and host.get("NetworkMode") == "none"
            and actual == mounts and all(m.get("Type") in ("bind", "tmpfs") for m in obj.get("Mounts", [])))


def sweep(docker, expected, remove=False, created_ids=None):
    receipts, errors, found = [], [], []
    for row in expected["containers"]:
        state, obj, receipt = inspect(docker, row["name"])
        entry = {"name": row["name"], "inspection": receipt, "state": state}
        receipts.append(entry)
        if state == "error":
            errors.append("inspect unavailable/invalid: " + row["name"])
        elif state == "present":
            found.append(row["name"])
            try:
                entry["owned"] = owned(row, obj, expected["image"])
            except BaseException as exc:
                entry["owned"] = False
                entry["ownership_error"] = str(exc)
            if created_ids is not None:
                known = created_ids.get(row["name"])
                entry["journal_created_id"] = known
                if known is None or known != obj["Id"]:
                    entry["owned"] = False
                    entry["ownership_error"] = "No exact matching settled journal-created ID; no removal"
            entry["container_id"] = obj["Id"]
            entry["container_state"] = obj.get("State")
            if not entry["owned"]:
                errors.append("exact-name container ownership mismatch; no removal: " + row["name"])
            elif remove:
                identifier = obj["Id"]
                entry["logs"] = command(docker, ["logs", identifier])
                if entry["logs"]["returncode"] != 0:
                    errors.append("own container logs unavailable: " + identifier)
                entry["removal"] = command(docker, ["container", "rm", "--force", identifier])
                if entry["removal"]["returncode"] != 0:
                    errors.append("own container removal failed: " + identifier)
                after, _, check = inspect(docker, row["name"])
                entry["after_removal"] = check
                if after != "absent":
                    errors.append("own container absence not verified: " + row["name"])
    return {"receipts": receipts, "errors": errors, "found": found}


def cleanup_receipts(expected):
    errors, checks = [], []
    for row in expected["containers"]:
        if row["probe"]:
            continue
        path = Path(row["output"]) / "cleanup.json"
        try:
            records = json.loads(path.read_text())
            if not isinstance(records, list) or not records:
                raise ValueError("missing cleanup actions")
            failed = any("cleanup_error" in r or "cleanup_unresolved" in r or ("returncode" in r and r["returncode"] != 0) for r in records)
            removed = any(r.get("action") in ("rm_own_ephemeral_container", "rm_own_ephemeral_container_after_cleanup_error") and r.get("returncode") == 0 for r in records)
            if failed or not removed:
                raise ValueError("failed or unverified original cleanup")
            directory = path.parent
            state = json.loads((directory / "container_state.json").read_text())
            if state.get("Running") is not False or state.get("ExitCode") != 0 or state.get("OOMKilled") is not False:
                raise ValueError("container failure/state mismatch")
            cgroups = json.loads((directory / "cgroup_samples.json").read_text())
            if not isinstance(cgroups, list) or not cgroups:
                raise ValueError("container cgroup evidence missing")
            for sample in cgroups:
                if (not isinstance(sample.get("memory_current_bytes"), int) or sample["memory_current_bytes"] < 0
                        or not isinstance(sample.get("memory_peak_bytes"), int) or sample["memory_peak_bytes"] < sample["memory_current_bytes"]
                        or not isinstance(sample.get("elapsed_sec"), (int, float)) or sample["elapsed_sec"] < 0
                        or not isinstance(sample.get("cpu_stat"), str) or not sample["cpu_stat"].strip()
                        or not isinstance(sample.get("cgroup"), str) or not sample["cgroup"].startswith("/sys/fs/cgroup/")):
                    raise ValueError("invalid container cgroup sample")
            for log in ("process.log", "container.log"):
                if not (directory / log).is_file():
                    raise ValueError("container/process log missing")
            evaluator = json.loads((directory / "evaluator.json").read_text())
            if not evaluator.get("all_reference_frames_exact") or not evaluator.get("developer_admissible") or not evaluator.get("gate_verdict", {}).get("admissible"):
                raise ValueError("evaluator admission evidence missing")
            checks.append({"path": str(path), "passed": True})
        except BaseException as exc:
            errors.append({"path": str(path), "reason": str(exc)})
    return {"checks": checks, "errors": errors, "passed": not errors}
