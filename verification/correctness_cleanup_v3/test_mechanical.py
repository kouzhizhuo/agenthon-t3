"""Finite fake-Docker/mechanical controls; no real Docker, network or simulator."""
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import tempfile
import time
from unittest.mock import patch

import cleanup
import execute_correctness


def null_id_finalization_case(directory):
    """Run the actual controller with fake process/daemon/host, not a simulator."""
    root = directory / "null-id-controller"
    output = root / "evidence"
    protocol_path = root / "t3/research1008v5b/linux_verification/PROTOCOL.json"
    protocol_path.parent.mkdir(parents=True)
    frozen = Path(__file__).resolve().parents[3] / "t3/research1008v5b/linux_verification/PROTOCOL.json"
    protocol_path.write_bytes(frozen.read_bytes())
    protocol = json.loads(protocol_path.read_text())
    output.mkdir()
    (output / "cpuset.txt").write_text("0")
    for version, python in (("311", "3.11.17"), ("313", "3.13.7")):
        controls = output / ("controls" + version)
        controls.mkdir()
        (controls / ("controls_py" + version + ".json")).write_text(json.dumps({
            "passed": True, "cases": 566, "python": python,
            "source_sha256": "b7cea49f0b992d60bbde435374d47e8558b2198ed9cb5d164d6c868b0c5aa141",
            "baseline_sha256": "ac4a28892f903f1c5790f54e25833188efa7e57e32fab8e651092a9b329733e7"}))
    current, daemon_calls, cleanup_checks = {}, [], []

    class FakeHarness:
        pid = 99999999
        returncode = 0

        def __init__(self, *arguments, **kwargs):
            correctness = output / "correctness"
            correctness.mkdir()
            raw = []
            for index, unit in enumerate(protocol["correctness_units"]):
                for variant in (("v3", "v5b") if index % 2 == 0 else ("v5b", "v3")):
                    raw.append({"unit": unit, "variant": variant, "pair": 0})
            (correctness / "raw_runs.json").write_text(json.dumps(raw))
            (correctness / "summary.json").write_text(json.dumps({"processes": 142,
                "all_output_bytes_counts_reference_frames_and_developer_gates_exact": True}))
            state = output / "cleanup_v3"
            expected = json.loads((state / "PLAN.json").read_text())
            valid_journals = [{"name": planned["name"], "arguments": ["run" if planned["probe"] else "create"],
                               "state": "settled", "returncode": 0,
                               **({} if planned["probe"] else {"created_id": format(index + 1, "064x")})}
                              for index, planned in enumerate(expected["containers"])]
            assert execute_correctness.journal_admission(expected, valid_journals)["passed"]
            row = expected["containers"][0]
            (state / "operation-1.json").write_text(json.dumps({"name": row["name"],
                "arguments": ["create", "--name", row["name"]], "state": "settled",
                "returncode": 0, "created_id": None}))
            other = expected["containers"][1]
            (state / "operation-2.json").write_text(json.dumps({"name": other["name"],
                "arguments": ["create", "--name", other["name"]], "state": "settled",
                "returncode": 0, "created_id": "b" * 64}))
            for planned, identifier in ((row, "a" * 64), (other, "b" * 64)):
                current[planned["name"]] = {"Id": identifier, "Name": "/" + planned["name"],
                    "Config": {"Image": expected["image"], "Cmd": planned["cmd"], "User": "65534:65534"},
                    "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none"},
                    "Mounts": [{"Type": "bind", "Source": s, "Destination": d, "RW": rw} for s, d, rw in planned["mounts"]]}

        def poll(self):
            return 0

    def fake_daemon(docker, arguments):
        daemon_calls.append(arguments)
        if arguments[:1] == ["logs"]:
            assert arguments[1] == "b" * 64, "null journal must not authorize logs"
            return {"returncode": 0, "stdout": "preserved own log", "stderr": ""}
        if arguments[:3] == ["container", "rm", "--force"]:
            assert arguments[3] == "b" * 64, "null journal must not authorize removal"
            name = next(name for name, obj in current.items() if obj["Id"] == arguments[3])
            del current[name]
            return {"returncode": 0, "stdout": arguments[3], "stderr": ""}
        assert arguments[:2] == ["container", "inspect"]
        name = arguments[2]
        if name in current:
            return {"returncode": 0, "stdout": json.dumps([current[name]]), "stderr": ""}
        return {"returncode": 1, "stdout": "[]\n", "stderr": "Error response from daemon: No such container: " + name + "\n"}

    def fake_cleanup(expected):
        cleanup_checks.append(True)
        return {"passed": True, "checks": [], "errors": []}

    read_text = Path.read_text

    def fake_host_read(path, *arguments, **kwargs):
        values = {"/proc/meminfo": "MemAvailable: 8388608 kB\n", "/proc/stat": "cpu 1 2 3 4\n",
                  "/sys/fs/cgroup/cpu.stat": "usage_usec 1\n"}
        return values[str(path)] if str(path) in values else read_text(path, *arguments, **kwargs)

    previous_directory = Path.cwd()
    try:
        os.chdir(root)
        with patch.object(sys, "argv", ["execute_correctness.py", "--out", str(output)]), \
                patch.object(execute_correctness.shutil, "which", return_value="fake-docker"), \
                patch.object(execute_correctness.subprocess, "Popen", FakeHarness), \
                patch.object(cleanup, "command", fake_daemon), \
                patch.object(execute_correctness, "cleanup_receipts", fake_cleanup), \
                patch.object(Path, "read_text", fake_host_read), \
                patch.object(execute_correctness.signal, "signal"):
            try:
                execute_correctness.main()
            except RuntimeError as exc:
                assert str(exc) == "correctness/cleanup admission failed; preserved without rerun"
            else:
                raise AssertionError("malformed null-ID journal must reject admission")
    finally:
        os.chdir(previous_directory)
    state = output / "cleanup_v3"
    for name in ("DOCKER_OPERATIONS.json", "JOURNAL_ADMISSION.json", "ORIGINAL_CLEANUP_CHECKS.json",
                 "RECONCILIATION.json", "FINAL_ABSENCE.json", "HOST_MONITOR_SAMPLES.json",
                 "HOST_MONITOR_ERRORS.json", "FINAL.json"):
        assert (state / name).is_file(), name
    final = json.loads((state / "FINAL.json").read_text())
    operations = json.loads((state / "DOCKER_OPERATIONS.json").read_text())
    admission = json.loads((state / "JOURNAL_ADMISSION.json").read_text())
    reconciliation = json.loads((state / "RECONCILIATION.json").read_text())
    assert operations[0]["state"] == "unresolved" and "invalid proxy-created ID" in operations[0]["error"]
    assert not final["admitted"] and not final["operations_settled"] and not final["journal_roster_pass"]
    assert not admission["passed"] and list(admission["created_ids"].values()) == ["b" * 64]
    assert cleanup_checks and reconciliation["found"] and reconciliation["errors"]
    assert not (output / "CORRECTNESS_ONLY_RECEIPT.json").exists()
    removals = [command for command in daemon_calls if command[:2] == ["container", "rm"]]
    assert removals == [["container", "rm", "--force", "b" * 64]]
    assert len(current) == 1 and next(iter(current.values()))["Id"] == "a" * 64


def main():
    cases = []
    expected = {"image": "image@sha256:" + "1" * 64, "containers": [{"name": "t3verify-test", "probe": False,
                "cmd": ["simulate"], "mounts": [("/source", "/opt/t3", False), ("/input", "/input/scenario.json", False), ("/output", "/output", True)]}]}
    row = expected["containers"][0]
    obj = {"Id": "a" * 64, "Name": "/t3verify-test", "Config": {"Image": expected["image"], "Cmd": ["simulate"], "User": "65534:65534"},
           "HostConfig": {"ReadonlyRootfs": True, "NetworkMode": "none"},
           "Mounts": [{"Type": "bind", "Source": s, "Destination": d, "RW": rw} for s, d, rw in row["mounts"]], "State": {"Running": False}}
    assert cleanup.owned(row, obj, expected["image"])
    cases.append("exact full owner admission")
    for field in ("image", "name", "user", "command", "RW", "extra_mount"):
        changed = copy.deepcopy(obj)
        if field == "image": changed["Config"]["Image"] = "other"
        elif field == "name": changed["Name"] = "/other"
        elif field == "user": changed["Config"]["User"] = "0"
        elif field == "command": changed["Config"]["Cmd"] = ["other"]
        elif field == "RW": changed["Mounts"][0]["RW"] = True
        else: changed["Mounts"].append({"Type": "bind", "Source": "/foreign", "Destination": "/foreign", "RW": True})
        assert not cleanup.owned(row, changed, expected["image"])
        cases.append("ownership refusal " + field)
    original_command = cleanup.command
    calls, objects = [], {row["name"]: copy.deepcopy(obj)}

    def fake(docker, args):
        calls.append(args)
        if args[:2] == ["container", "inspect"]:
            if args[2] in objects:
                return {"arguments": args, "returncode": 0, "stdout": json.dumps([objects[args[2]]]), "stderr": ""}
            return {"arguments": args, "returncode": 1, "stdout": "[]\n", "stderr": "Error response from daemon: No such container: " + args[2] + "\n"}
        if args[:3] == ["container", "rm", "--force"]:
            objects.clear()
            return {"arguments": args, "returncode": 0, "stdout": args[3], "stderr": ""}
        return {"arguments": args, "returncode": 0, "stdout": "log", "stderr": ""}

    cleanup.command = fake
    try:
        result = cleanup.sweep("fake", expected, remove=True, created_ids={row["name"]: "b" * 64})
        assert result["errors"] and not any(x[:2] == ["container", "rm"] for x in calls)
        cases.append("journal ID mismatch never removes")
        calls.clear()
        result = cleanup.sweep("fake", expected, remove=True, created_ids={row["name"]: "a" * 64})
        assert not result["errors"] and result["found"] == [row["name"]] and calls[-1][:2] == ["container", "inspect"]
        assert any(x == ["container", "rm", "--force", "a" * 64] for x in calls)
        cases.append("exact journal ID removal and absence")
        cleanup.command = lambda docker, args: {"arguments": args, "returncode": 1, "stdout": "", "stderr": "Cannot connect to Docker daemon"}
        assert cleanup.inspect("fake", "name")[0] == "error"
        cases.append("daemon unavailable never proves absence")
    finally:
        cleanup.command = original_command
    with tempfile.TemporaryDirectory(prefix="t3-cleanup-mechanical-") as temporary:
        directory = Path(temporary)
        process = directory / "process"
        process.mkdir()
        local = {"containers": [{"probe": False, "output": str(process)}]}
        (process / "cleanup.json").write_text(json.dumps([{"action": "rm_own_ephemeral_container", "returncode": 1}]))
        assert not cleanup.cleanup_receipts(local)["passed"]
        cases.append("original nonzero removal rejects")
        (process / "cleanup.json").write_text(json.dumps([{"action": "rm_own_ephemeral_container", "returncode": 0}]))
        (process / "container_state.json").write_text(json.dumps({"Running": False, "ExitCode": 0, "OOMKilled": False}))
        (process / "cgroup_samples.json").write_text(json.dumps([{"memory_current_bytes": 1, "memory_peak_bytes": 2, "elapsed_sec": 0.5, "cpu_stat": "usage_usec 1\n", "cgroup": "/sys/fs/cgroup/example"}]))
        (process / "process.log").write_text("")
        (process / "container.log").write_text("")
        (process / "evaluator.json").write_text(json.dumps({"all_reference_frames_exact": True, "developer_admissible": True, "gate_verdict": {"admissible": True}}))
        assert cleanup.cleanup_receipts(local)["passed"]
        cases.append("complete original process evidence accepted")
        (process / "cgroup_samples.json").unlink()
        assert not cleanup.cleanup_receipts(local)["passed"]
        cases.append("missing cgroup evidence rejects")
        (directory / "operation-1.json").write_text('{"state":"settled","arguments":[]}')
        rows = execute_correctness.operations(directory)
        assert rows[0]["state"] == "unresolved" and not execute_correctness.settle(directory, timeout=0)[1]
        cases.append("malformed journal cannot bypass final cleanup")
        proxy_state = directory / "proxy"
        proxy_state.mkdir()
        (proxy_state / "PLAN.json").write_text(json.dumps({"containers": [{"name": "t3verify-fake"}, {"name": "t3probe-fake"}], "probe_name": "t3probe-fake"}))
        fake_cli = directory / "fake-docker"
        fake_cli.write_text("#!" + sys.executable + "\nimport pathlib,sys,time\npathlib.Path(" + repr(str(directory / "fake-called")) + ").write_text('called')\ntime.sleep(0.3)\nif '--cidfile' in sys.argv:pathlib.Path(sys.argv[sys.argv.index('--cidfile')+1]).write_text('a'*64)\nprint('a'*64 if sys.argv[1]=='create' else '{}')\n")
        fake_cli.chmod(0o755)
        environment = dict(os.environ, T3_PROXY_STATE=str(proxy_state), T3_REAL_DOCKER=str(fake_cli))
        child = subprocess.Popen([sys.executable, str(Path(__file__).parent / "docker_proxy.py"), "create", "--name", "t3verify-fake"], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while not list(proxy_state.glob("operation-*.json")) and time.monotonic() < deadline:
            time.sleep(0.01)
        os.kill(child.pid, signal.SIGINT)
        stdout, stderr = child.communicate(timeout=5)
        journal = execute_correctness.operations(proxy_state)
        assert child.returncode == 0 and stdout.strip() == b"a" * 64 and journal[0]["state"] == "settled" and journal[0]["created_id"] == "a" * 64
        cases.append("fake CLI creation settles and journals ID through proxy SIGINT")
        (proxy_state / "CANCEL").write_text("cancel")
        (directory / "fake-called").unlink()
        denied = subprocess.run([sys.executable, str(Path(__file__).parent / "docker_proxy.py"), "create", "--name", "t3verify-fake"], env=environment, capture_output=True, timeout=5)
        assert denied.returncode == 125 and not (directory / "fake-called").exists()
        cases.append("cancel marker denies fake CLI new creation")
        null_id_finalization_case(directory)
        cases.append("null-ID journal rejects while final receipts and other journal-owned cleanup complete")
    for name in ("cleanup.py", "docker_proxy.py", "execute_correctness.py", "prepare_host.py"):
        ast.parse((Path(__file__).parent / name).read_text())
    report = {"passed": True, "cases": cases, "case_count": len(cases), "real_docker_calls": 0, "network_calls": 0,
              "simulator_or_forecast_runs": 0, "scope": "fake command receipts / pure data / fake CLI proxy SIGINT / actual controller with fake host, harness and daemon / AST; no real Docker daemon"}
    (Path(__file__).parent / "MECHANICAL_RECEIPT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
