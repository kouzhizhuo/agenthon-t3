#!/usr/bin/env python3
"""Finite Linux Docker verification and paired, unrankable local timing.

The host imports the unchanged completion1009/verify_public.py validators. Only
scenario JSON is staged into /input; no validator, scorer or reference enters
the participant image. The default roster is all 71 units plus 30 isolated
batch markets. --units and --repeats support a fixed pilot on two local images.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import signal
import statistics
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verify_public as public

OWNER_LABEL = "qfbench2.t3.verifier_owner"
MEMORY_BYTES = 16 * 1024 ** 3
_cancelled = None


def cancellation(signum, _frame):
    global _cancelled
    if _cancelled is None:
        _cancelled = signum


def check_cancelled():
    if _cancelled is not None:
        raise InterruptedError("verification received signal %d" % _cancelled)


def child_limits(cap):
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT, signal.SIGTERM})


def run_command(argv, prefix, seconds, cap, cleanup=False):
    """Retain real logs directly in hard-bounded files and reap the creator handle."""
    prefix.parent.mkdir(parents=True, exist_ok=True)
    paths = {name: prefix.with_name(prefix.name + "." + name + ".txt")
             for name in ("stdout", "stderr")}
    started = time.perf_counter()
    row = {"argv": argv, "timeout_sec": seconds, "rankable": False,
           "per_log_file_hard_bytes": cap, "creator_reaped": False,
           "timed_out": False, "cancelled": False, "error": None}
    process = None
    with paths["stdout"].open("xb") as stdout, paths["stderr"].open("xb") as stderr:
        try:
            if seconds <= 0:
                raise TimeoutError("command budget exhausted before launch")
            if not cleanup:
                check_cancelled()
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
            try:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr, start_new_session=True,
                    preexec_fn=lambda: child_limits(cap))
                row["pid"] = process.pid
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            deadline = started + seconds
            while True:
                if not cleanup:
                    check_cancelled()
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    row["timed_out"] = True
                    raise TimeoutError("owned command deadline")
                try:
                    process.wait(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            row["error"] = type(error).__name__ + ": " + str(error)
            row["cancelled"] = isinstance(error, (InterruptedError, KeyboardInterrupt))
            if process is not None and process.returncode is None:
                # An unreaped leader still anchors this exact owned process group.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    row["owned_group_kill_sent"] = True
                except ProcessLookupError:
                    row["owned_group_already_absent"] = True
                except BaseException as kill_error:
                    row["kill_error"] = repr(kill_error)
                try:
                    process.wait(timeout=5)
                except BaseException as wait_error:
                    row["reap_error"] = repr(wait_error)
        finally:
            row["returncode"] = process.returncode if process is not None else None
            row["creator_reaped"] = process is not None and process.returncode is not None
    row["host_wall_sec"] = time.perf_counter() - started
    for name, path in paths.items():
        row[name] = {"path": str(path), "bytes": path.stat().st_size,
                     "sha256": public.sha256(path),
                     "hard_limit_reached": path.stat().st_size >= cap}
    row["succeeded"] = (row["error"] is None and row["returncode"] == 0
                        and row["creator_reaped"]
                        and not any(row[name]["hard_limit_reached"] for name in paths))
    return row


class DockerCommands:
    def __init__(self, docker, folder, cap):
        self.docker, self.folder, self.cap = docker, folder, cap
        self.rows = []

    def call(self, arguments, label, seconds=30, cleanup=False):
        prefix = self.folder / ("%03d-%s" % (len(self.rows), label))
        row = run_command([self.docker] + arguments, prefix, seconds,
                          self.cap, cleanup=cleanup)
        self.rows.append(row)
        return row

    def text(self, row, stream="stdout"):
        return Path(row[stream]["path"]).read_text(errors="replace")

    def inspect(self, name, cleanup=False, seconds=30):
        row = self.call(["inspect", name], "inspect", seconds, cleanup)
        if row["succeeded"]:
            values = json.loads(self.text(row))
            if len(values) != 1 or values[0].get("Name") != "/" + name:
                raise ValueError("exact container inspect identity required")
            return values[0], row
        error = self.text(row, "stderr")
        if (row["returncode"] == 1 and row["error"] is None
                and ("No such object: " + name in error
                     or "No such container: " + name in error)):
            return None, row
        raise RuntimeError("container inspect did not establish presence or absence")


def require_owned(inspect, name, token, image_id):
    if (inspect.get("Name") != "/" + name
            or inspect.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != token
            or inspect.get("Image") != image_id):
        raise ValueError("container exact name, owner label and immutable image differ")


def settle_container(commands, name, token, image_id, creation_uncertain=False):
    """Inspect ownership, kill a live owned container, wait, then remove and prove absence."""
    deadline = time.perf_counter() + 60
    row = {"name": name, "owner": token, "settled": False, "removed": False,
           "final_absent": False, "errors": [], "state_before_remove": None}
    def remaining():
        return min(20, max(0, deadline - time.perf_counter()))
    try:
        info, _ = commands.inspect(name, cleanup=True, seconds=remaining())
        if info is None and creation_uncertain:
            # A cancelled Docker create client may have already reached the
            # daemon. Screen the exact random-owned name through a finite grace.
            grace = min(deadline, time.perf_counter() + 3)
            while info is None and time.perf_counter() < grace:
                time.sleep(min(.2, max(0, grace - time.perf_counter())))
                info, _ = commands.inspect(name, cleanup=True, seconds=remaining())
            row["cancelled_create_absence_grace_sec"] = 3
        if info is None:
            row.update(settled=True, final_absent=True, never_present_or_already_absent=True)
            return row
        require_owned(info, name, token, image_id)
        row["container_id"] = info["Id"]
        if info["State"].get("Running") or info["State"].get("Restarting"):
            killed = commands.call(["kill", "--signal", "KILL", name], "cleanup-kill", remaining(), True)
            if not killed["succeeded"]:
                row["errors"].append("kill command failed; inspect/wait still attempted")
        if info["State"].get("Status") != "created":
            waited = commands.call(["wait", name], "cleanup-wait", remaining(), True)
            if not waited["succeeded"]:
                row["errors"].append("wait command failed")
        info, _ = commands.inspect(name, cleanup=True, seconds=remaining())
        if info is None:
            raise RuntimeError("owned container disappeared before retained terminal state")
        require_owned(info, name, token, image_id)
        row["state_before_remove"] = info["State"]
        row["settled"] = (not info["State"].get("Running")
                          and not info["State"].get("Restarting")
                          and info["State"].get("Pid") == 0)
        if not row["settled"]:
            raise RuntimeError("owned container has not settled; removal refused")
        removed = commands.call(["rm", name], "cleanup-remove", remaining(), True)
        row["removed"] = removed["succeeded"]
        info, _ = commands.inspect(name, cleanup=True, seconds=remaining())
        row["final_absent"] = info is None
        if not row["removed"] or not row["final_absent"]:
            row["errors"].append("exact owned removal or final absence not established")
    except BaseException as error:
        row["errors"].append(type(error).__name__ + ": " + str(error))
    return row


def stage_input(item, folder, scenario=None):
    folder.mkdir(parents=True)
    paths = [Path(scenario)] if scenario is not None else [Path(p) for p in item["scenario_paths"]]
    staged = []
    batch_shape = scenario is None and item["shape"] == "batch"
    if batch_shape:
        destination = folder / "scenarios"
        destination.mkdir()
    else:
        destination = folder
    for source in paths:
        if source.is_symlink() or not source.is_file():
            raise ValueError("ordinary original input JSON required")
        target = destination / (source.name if batch_shape else "scenario.json")
        shutil.copyfile(source, target)
        target.chmod(0o644)
        if public.sha256(target) != public.sha256(source):
            raise ValueError("staged input bytes differ")
        staged.append({"source": str(source), "staged": str(target), "sha256": public.sha256(target)})
    for directory in [folder] + [p for p in folder.rglob("*") if p.is_dir()]:
        directory.chmod(0o755)
    return staged


def run_container(args, image_id, mode, item, folder, token, suffix, scenario=None):
    folder.mkdir(parents=True)
    output, input_dir = folder / "output", folder / "input"
    output.mkdir()
    output.chmod(0o777)
    staged = stage_input(item, input_dir, scenario)
    name = "t3v-%s-%s" % (token[:12], suffix)
    commands = DockerCommands(args.docker, folder / "commands", args.log_cap_bytes)
    verb = "simulate" if scenario is not None or item["shape"] == "single" else "simulate-batch"
    arguments = (["--config", "/input/scenario.json", "--out", "/output/trace.parquet"]
                 if verb == "simulate" else ["--batch-dir", "/input/scenarios", "--out-dir", "/output"])
    if mode != "original":
        arguments += ["--mode", mode]
    create = ["create", "--name", name, "--label", OWNER_LABEL + "=" + token,
              "--pull", "never", "--platform", "linux/amd64", "--runtime", "runc",
              "--network", "none", "--cpus", "4", "--memory", str(MEMORY_BYTES),
              "--memory-swap", str(MEMORY_BYTES), "--pids-limit", "256",
              "--ulimit", "nofile=1024:1024", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", "--read-only", "--user", "65534:65534",
              "--workdir", "/output", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
              "--mount", "type=bind,src=" + str(input_dir.resolve()) + ",dst=/input,readonly",
              "--mount", "type=bind,src=" + str(output.resolve()) + ",dst=/output"]
    for key in ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        create += ["--env", key + "=1"]
    create += ["--env", "PYTHONDONTWRITEBYTECODE=1", image_id, verb] + arguments
    row = {"name": name, "owner": token, "image_id": image_id, "mode": mode,
           "rankable": False, "staged_inputs": staged, "succeeded": False,
           "state": None, "error": None}
    started = time.perf_counter()
    deadline = started + args.timeout
    try:
        made = commands.call(create, "create", min(30, deadline - time.perf_counter()))
        if not made["succeeded"]:
            raise RuntimeError("docker create failed")
        info, _ = commands.inspect(name, seconds=min(30, deadline - time.perf_counter()))
        if info is None:
            raise RuntimeError("created container absent")
        require_owned(info, name, token, image_id)
        row["container_id"] = info["Id"]
        row["effective_config"] = {"HostConfig":info["HostConfig"],"Config":info["Config"],"Mounts":info["Mounts"]}
        host = info["HostConfig"]
        if (host.get("NanoCpus") != 4 * 10 ** 9 or host.get("Memory") != MEMORY_BYTES
                or host.get("MemorySwap") != MEMORY_BYTES or host.get("PidsLimit") != 256
                or not host.get("ReadonlyRootfs") or host.get("NetworkMode") != "none"
                or host.get("Runtime") != "runc" or info["Config"].get("User") != "65534:65534"
                or "ALL" not in host.get("CapDrop", [])
                or not any(value.startswith("no-new-privileges") for value in host.get("SecurityOpt", []))
                or not all(flag in host.get("Tmpfs", {}).get("/tmp", "")
                           for flag in ("noexec", "nosuid", "nodev", "size=64m"))
                or not any(row.get("Name")=="nofile" and row.get("Soft")==1024 and row.get("Hard")==1024
                           for row in host.get("Ulimits", []))
                or not any(row.get("Destination")=="/input" and row.get("RW") is False for row in info["Mounts"])
                or not any(row.get("Destination")=="/output" and row.get("RW") is True for row in info["Mounts"])):
            raise ValueError("actual Docker resource or mount configuration differs from fixed contract")
        attached = commands.call(["start", "--attach", name], "start-attach", deadline - time.perf_counter())
        row["attach"] = attached
        info, _ = commands.inspect(name, seconds=min(30, deadline - time.perf_counter()))
        if info is None:
            raise RuntimeError("started container absent")
        require_owned(info, name, token, image_id)
        row["state"] = info["State"]
        row["host_wall_sec"] = time.perf_counter() - started
        row["succeeded"] = (attached["succeeded"] and info["State"].get("ExitCode") == 0
                            and not info["State"].get("OOMKilled")
                            and not info["State"].get("Running")
                            and not info["State"].get("Restarting"))
    except BaseException as error:
        row["error"] = type(error).__name__ + ": " + str(error)
    finally:
        row.setdefault("host_wall_sec", time.perf_counter() - started)
        row["cleanup"] = settle_container(commands, name, token, image_id,
            creation_uncertain=not row.get("container_id"))
        row["state"] = row["state"] or row["cleanup"].get("state_before_remove")
        row["exit_code"] = row["state"].get("ExitCode") if row["state"] else None
        row["OOMKilled"] = row["state"].get("OOMKilled") if row["state"] else None
        row["succeeded"] = (row["succeeded"] and row["cleanup"]["settled"]
                            and row["cleanup"]["final_absent"] and not row["cleanup"]["errors"])
        row["total_with_cleanup_wall_sec"] = time.perf_counter() - started
        row["commands"] = commands.rows
        public.write_json(folder / "EXECUTION.json", row)
    return row, output


def image_metadata(args, requested, folder):
    commands = DockerCommands(args.docker, folder, args.log_cap_bytes)
    row = commands.call(["image", "inspect", requested], "image-inspect")
    if not row["succeeded"]:
        raise RuntimeError("local image unavailable; verifier never pulls images")
    values = json.loads(commands.text(row))
    if len(values) != 1:
        raise ValueError("exact local image required")
    image = values[0]
    if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
        raise ValueError("Linux amd64 image required")
    if image.get("Config", {}).get("Volumes"):
        raise ValueError("Docker VOLUME is prohibited, including inherited volumes")
    if image.get("Config", {}).get("Labels", {}).get("qfbench2.interface_version") != "2.0":
        raise ValueError("interface_version=2.0 image label required")
    public.write_json(folder / "IMAGE.json", image)
    return {"requested": requested, "id": image["Id"], "inspection": image, "commands": commands.rows}


def gate(args, unit, output, folder):
    if not args.gate_python:
        return {"status": "unavailable", "admissible": None}
    save = folder / "developer_verdict.json"
    command = [args.gate_python, str(HERE / "verify_public.py"), "_gate",
               "--unit", str(unit), "--output", str(output), "--save", str(save),
               "--gate-kit", str(args.gate_kit.resolve())]
    execution = run_command(command, folder / "developer-gate", 300, args.log_cap_bytes)
    verdict = public.read_json(save) if save.is_file() else None
    return {"status": "completed" if execution["succeeded"] and verdict else "error",
            "admissible": verdict.get("admissible") if verdict else None,
            "execution": execution, "verdict": verdict, "rankable": False}


def output_pair(output, prior, item):
    names = ([name for name in public.SUB_FILES[:2]] if item["shape"] == "single"
             else [entry["sub"] + "/" + name for entry in item["subs"] for name in public.SUB_FILES[:2]])
    frames = [public.compare_frame(output / name, prior / name) for name in names]
    return {"passed": all(row["passed"] and row.get("byte_equal") for row in frames), "frames": frames}


def main():
    global _cancelled
    _cancelled = None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="local tag, image ID or digest; resolved once to immutable ID")
    parser.add_argument("--baseline-image", help="optional paired local comparison image")
    parser.add_argument("--mode", choices=("original", "baseline", "optimized"), default="optimized")
    parser.add_argument("--baseline-mode", choices=("original", "baseline", "optimized"), default="optimized")
    parser.add_argument("--reference-root", type=Path, default=HERE.parent / "evaluation_references")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--docker", default="/usr/bin/docker")
    parser.add_argument("--units", "--unit", nargs="+")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--log-cap-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--gate-python")
    parser.add_argument("--gate-kit", type=Path)
    parser.add_argument("--require-gate", action="store_true")
    parser.add_argument("--require-byte-reference", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if not 0 < args.timeout <= 300 or not 0 < args.log_cap_bytes <= 16 * 1024 * 1024:
        parser.error("timeout must be (0,300]; log cap must be (0,16MiB]")
    if not 1 <= args.repeats <= 5 or not 0 <= args.warmups <= 1:
        parser.error("repeats must be 1..5 and warmups 0..1")
    if not args.units and args.mode != "optimized":
        parser.error("full71 runs use optimized mode; filter units for original/baseline pilots")
    if bool(args.gate_python) != bool(args.gate_kit) or args.require_gate and not args.gate_python:
        parser.error("configure both --gate-python/--gate-kit; --require-gate requires them")
    reference_root = args.reference_root.resolve()
    plan = public.collect_plan(reference_root, args.units)
    plan.update(schema="t3-linux-docker-public-verification-v1", rankable=False,
        verification_scope="finite runc Linux local-image exact public checks and unrankable host wall timing",
        host=platform.platform(), verifier_python=sys.version, verifier_sha256=public.sha256(__file__),
        validator_source=str(HERE / "verify_public.py"), validator_sha256=public.sha256(HERE / "verify_public.py"),
        selected_image=args.image, baseline_image=args.baseline_image, mode=args.mode,
        baseline_mode=args.baseline_mode, repeats=args.repeats, warmups=args.warmups,
        per_container_timeout_sec=args.timeout, cleanup_reserve_sec=60,
        limits={"cpus":4,"memory_bytes":MEMORY_BYTES,"swap_total_bytes":MEMORY_BYTES,
                "nonroot":"65534:65534","readonly_root":True,"network":"none","runtime":"runc",
                "cap_drop":"ALL","no_new_privileges":True,"pids":256,"nofile":1024,
                "tmp_bytes":64*1024**2,"tmp_noexec":True,"log_hard_bytes_each":args.log_cap_bytes},
        host_wall_scope="docker create through settled execution inspect, including container setup/start/exit and process logs; exact cleanup saved separately",
        reference_byte_equality_required=args.require_byte_reference,
        official_developer_gate_required=args.require_gate)
    if args.plan_only:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    if sys.platform != "linux":
        parser.error("execution requires a Linux host; use --plan-only for source planning elsewhere")
    args.out_dir = args.out_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    original_handlers = {sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
    for sig in original_handlers:
        signal.signal(sig, cancellation)
    token = uuid.uuid4().hex
    plan["owner_token"] = token
    public.write_json(args.out_dir / "PLAN.json", plan)
    records, failure = [], None
    try:
        candidate = image_metadata(args, args.image, args.out_dir / "candidate-image")
        arms = [("candidate", candidate["id"], args.mode)]
        if args.baseline_image:
            baseline = image_metadata(args, args.baseline_image, args.out_dir / "baseline-image")
            arms.append(("baseline", baseline["id"], args.baseline_mode))
        plan["immutable_arms"] = [{"name":name,"image_id":image,"mode":mode} for name,image,mode in arms]
        public.write_json(args.out_dir / "PLAN.json", plan)
        for unit_index, item in enumerate(plan["units"]):
            unit = reference_root / item["unit"]
            first_outputs, last_outputs = {}, {}
            unit_rows = []
            for repeat in range(-args.warmups, args.repeats):
                for arm, image_id, mode in (arms if repeat % 2 == 0 else list(reversed(arms))):
                    check_cancelled()
                    label = "warmup-%d" % (-repeat) if repeat < 0 else "repeat-%02d" % repeat
                    folder = args.out_dir / item["unit"] / arm / label
                    execution, output = run_container(args,image_id,mode,item,folder,token,
                        "%03d-%s-%s" % (unit_index,arm,label))
                    checks = public.verify_outputs(unit,output,item)
                    verdict = gate(args,unit,output,folder)
                    byte_ok = all(frame.get("byte_equal") for frame in checks["frames"])
                    repeated = output_pair(output,first_outputs[arm],item) if repeat >= 0 and arm in first_outputs else None
                    row = {"unit":item["unit"],"shape":item["shape"],"arm":arm,"repeat":repeat,
                           "warmup":repeat<0,"rankable":False,"execution":execution,"checks":checks,
                           "developer_verifier":verdict,"repeat_parquet_equality":repeated,
                           "reference_parquet_byte_equal":byte_ok,"output":str(output)}
                    row["passed"] = (execution["succeeded"] and checks["passed"]
                        and (not args.require_byte_reference or byte_ok)
                        and (not args.require_gate or verdict["admissible"] is True)
                        and (repeated is None or repeated["passed"]))
                    row["host_events_per_sec"] = checks["actual_events"] / execution["host_wall_sec"] if row["passed"] else 0.
                    if repeat >= 0:
                        first_outputs.setdefault(arm,output)
                        last_outputs[arm] = output
                    records.append(row);unit_rows.append(row)
                    public.write_json(folder / "RAW_RESULT.json",row)
                    public.write_json(args.out_dir / "RAW_RESULTS.json",records)
                    print("%s %s %s %s host_wall=%.3fs" % (item["unit"],arm,label,
                        "PASS" if row["passed"] else "FAIL",execution["host_wall_sec"]),flush=True)
                    if args.stop_on_failure and not row["passed"]:
                        raise RuntimeError("stop on first failed unit")
            isolation = []
            for arm,image_id,mode in arms:
                for index,entry in enumerate(item["subs"]):
                    check_cancelled()
                    scenario = unit / entry["scenario_file"]
                    folder = args.out_dir/item["unit"]/arm/"isolated"/entry["sub"]
                    execution,output = run_container(args,image_id,mode,item,folder,token,
                        "%03d-%s-iso-%02d" % (unit_index,arm,index),scenario)
                    frames = [public.compare_frame(output/name,last_outputs[arm]/entry["sub"]/name)
                              for name in public.SUB_FILES[:2]]
                    sidecar = public.verify_events(output,public.read_json(scenario),frames[0].get("candidate_rows",0))
                    tree = public.check_tree(output,set(public.SUB_FILES))
                    iso = {"unit":item["unit"],"arm":arm,"sub":entry["sub"],"execution":execution,
                           "frames":frames,"sidecar":sidecar,"output_tree":tree,"rankable":False}
                    iso["passed"] = (execution["succeeded"] and sidecar["passed"] and tree["passed"]
                                     and all(f["passed"] and f.get("byte_equal") for f in frames))
                    isolation.append(iso)
                    public.write_json(folder/"RAW_RESULT.json",iso)
                    print("%s %s isolated %s %s" % (item["unit"],arm,entry["sub"],"PASS" if iso["passed"] else "FAIL"),flush=True)
                    if args.stop_on_failure and not iso["passed"]:
                        raise RuntimeError("stop on first isolated failure")
            paired = output_pair(last_outputs["candidate"],last_outputs["baseline"],item) if args.baseline_image else None
            unit_result = {"unit":item["unit"],"records":unit_rows,"isolated":isolation,
                           "paired_image_parquet_equality":paired,"rankable":False}
            unit_result["passed"] = (all(r["passed"] for r in unit_rows) and all(r["passed"] for r in isolation)
                                     and (paired is None or paired["passed"]))
            public.write_json(args.out_dir/item["unit"] / "UNIT_RESULT.json",unit_result)
            if args.stop_on_failure and not unit_result["passed"]:
                raise RuntimeError("stop on paired image output failure")
    except BaseException as error:
        failure = {"type":type(error).__name__,"text":str(error)}
    finally:
        unit_results = [public.read_json(p) for p in sorted(args.out_dir.glob("*/UNIT_RESULT.json"))]
        inputs_unchanged = all(public.sha256(reference_root/item["unit"]/rel)==digest
            for item in plan["units"] for rel,digest in item["input_sha256"].items())
        references_unchanged = all(public.sha256(reference_root/item["unit"]/rel)==digest
            for item in plan["units"] for rel,digest in item["reference_sha256"].items())
        measured = [r for r in records if not r["warmup"]]
        executions = [public.read_json(p) for p in sorted(args.out_dir.rglob("EXECUTION.json"))]
        timings = []
        for item in plan["units"]:
            groups = {arm:[r for r in measured if r["unit"]==item["unit"] and r["arm"]==arm]
                      for arm in ("candidate","baseline")}
            timing = {"unit":item["unit"],"rankable":False,
                "candidate_measured_runs":len(groups["candidate"]),
                "candidate_median_host_wall_sec":statistics.median(r["execution"]["host_wall_sec"] for r in groups["candidate"])
                    if groups["candidate"] else None}
            if groups["baseline"] and groups["candidate"]:
                timing["baseline_median_host_wall_sec"] = statistics.median(r["execution"]["host_wall_sec"] for r in groups["baseline"])
                timing["baseline_over_candidate_median_wall_ratio"] = timing["baseline_median_host_wall_sec"] / timing["candidate_median_host_wall_sec"]
                candidate_pairs = {r["repeat"]:r for r in groups["candidate"]}
                baseline_pairs = {r["repeat"]:r for r in groups["baseline"]}
                timing["paired_wall_ratios"] = [{"repeat":i,
                    "baseline_over_candidate":baseline_pairs[i]["execution"]["host_wall_sec"]/candidate_pairs[i]["execution"]["host_wall_sec"],
                    "both_passed":candidate_pairs[i]["passed"] and baseline_pairs[i]["passed"]}
                    for i in sorted(set(candidate_pairs)&set(baseline_pairs))]
            timings.append(timing)
        summary = {"schema":"t3-linux-docker-verification-summary-v1","rankable":False,
            "scope":plan["verification_scope"],"planned_units":len(plan["units"]),
            "completed_units":len(unit_results),"complete_roster":len(unit_results)==len(plan["units"]),
            "passed_units":sum(r["passed"] for r in unit_results),"records":len(records),
            "measured_records":len(measured),"failure":failure,"cancelled_signal":_cancelled,
            "input_files_unchanged":inputs_unchanged,"reference_files_unchanged":references_unchanged,
            "validator_unchanged":public.sha256(HERE/"verify_public.py")==plan["validator_sha256"],
            "verifier_unchanged":public.sha256(__file__)==plan["verifier_sha256"],
            "isolated_markets":sum(len(r["isolated"]) for r in unit_results),
            "isolated_markets_passed":sum(iso["passed"] for r in unit_results for iso in r["isolated"]),
            "all_container_cleanup_passed":all(r["cleanup"]["final_absent"]
                and r["cleanup"]["settled"] and not r["cleanup"]["errors"] for r in executions),
            "container_executions":len(executions),"timings":timings}
        summary["all_passed"] = (failure is None and summary["complete_roster"]
            and all(r["passed"] for r in unit_results) and inputs_unchanged and references_unchanged
            and summary["validator_unchanged"] and summary["verifier_unchanged"]
            and summary["all_container_cleanup_passed"])
        public.write_json(args.out_dir/"SUMMARY.json",summary)
        for sig,handler in original_handlers.items():
            signal.signal(sig,handler)
        print(json.dumps(summary,indent=2),flush=True)
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
