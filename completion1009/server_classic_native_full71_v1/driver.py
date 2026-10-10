"""Full71 single-pass Linux coverage with original gates and daemon timing."""
import argparse
import calendar
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ARMS = ("scalar",)


def pin(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if any(part.startswith("._") or part in ("__MACOSX", "__pycache__") for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError("saved symlink refused")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = pin(path)
    return result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("fresh receipt path required")
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def read(path):
    return json.loads(path.read_bytes())


def duration(state):
    def ns(value):
        base, fraction = value.rstrip("Z").split(".")
        return calendar.timegm(datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").timetuple()) * 10**9 + int(fraction.ljust(9, "0"))
    return (ns(state["FinishedAt"]) - ns(state["StartedAt"])) / 10**9


def worker(args, arm, stage, label, request=None, seconds=600):
    result = args.evidence / "worker-results" / (label + ".json")
    command = [sys.executable, "-B", str(HERE / "worker.py"), stage, "--payload", str(args.payloads[arm]),
        "--evidence", str(args.evidence / arm), "--reference-root", str(args.reference_root),
        "--gate-kit", str(args.gate_kit), "--gate-python", sys.executable, "--result", str(result)]
    if request is not None:
        req = args.evidence / "requests" / (label + ".json")
        write(req, request)
        command.extend(["--request", str(req)])
    log = args.evidence / "worker-logs" / (label + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("xb") as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=seconds)
    write(log.with_suffix(".json"), {"command": command, "returncode": process.returncode, "log": pin(log)})
    if process.returncode:
        raise ValueError("original controller worker failed: " + label)
    return read(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("build", "screen", "artifact"))
    parser.add_argument("--scalar-payload", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--gate-kit", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("real Linux amd64 only")
    args.evidence = args.evidence.resolve()
    args.payloads = {"scalar": args.scalar_payload.resolve()}
    args.reference_root = args.reference_root.resolve()
    args.gate_kit = args.gate_kit.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.stage == "artifact":
        if args.artifact.exists():
            raise ValueError("fresh archive folder required")
        shutil.copytree(args.evidence, args.artifact / "evidence", ignore=shutil.ignore_patterns("anonymous-docker-config"))
        for arm in ARMS:
            shutil.copytree(args.payloads[arm], args.artifact / "payloads" / arm)
        for name in ("driver.py", "worker.py", "README.md", "SOURCE_REVIEW.json"):
            shutil.copyfile(HERE / name, args.artifact / name)
        write(args.artifact / "ARTIFACT.json", {"files": inventory(args.artifact), "rankable": False})
        return
    if args.stage == "build":
        for arm in ARMS:
            worker(args, arm, "build", arm + "-build", seconds=3000)
        return
    sys.path.insert(0, str(args.payloads["scalar"] / "host"))
    import verify_public as public
    plan = public.collect_plan(args.reference_root, None)
    items = {item["unit"]: item for item in plan["units"]}
    if len(items)!=71 or plan["reference_frame_count"]!=190:
        raise ValueError("complete71units/95markets required")
    units=tuple(sorted(items))
    write(args.evidence / "REFERENCE_PLAN.json", plan)
    rows, controls, before, after, failure = [], {}, {}, {}, None
    owners = {arm: uuid.uuid4().hex for arm in ARMS}
    try:
        for arm in ARMS:
            before[arm] = worker(args, arm, "metadata", arm + "-before",
                {"folder": str(args.evidence / arm / "before")})
            controls[arm] = worker(args, arm, "controls", arm + "-controls",
                {"owner": owners[arm]}, seconds=3900)
        # One fresh container per unit. This establishes full public coverage,
        # not Final repeated timing. All original source, gates and limits stay.
        for index,unit in enumerate(units):
            arm="scalar"
            label="%02d-%s" % (index,arm)
            folder=args.evidence / arm / "full71" / unit
            row=worker(args,arm,"one",label,{"owner":owners[arm],"item":items[unit],
                "folder":str(folder),"suffix":label})
            row.update(direct_arm=arm,repeat=0,warmup=False,timing_included=True)
            rows.append(row)
            write(args.evidence / "raw-progress" / (label+".json"),row)
            print(label,unit,"PASS",flush=True)
        for arm in ARMS:
            after[arm] = worker(args, arm, "metadata", arm + "-after",
                {"folder": str(args.evidence / arm / "after")})
            if before[arm]["inspection"] != after[arm]["inspection"]:
                raise ValueError("actual immutable image changed")
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    unchanged = all(public.sha256(args.reference_root / item["unit"] / name) == digest
        for item in plan["units"] for mapping in (item["input_sha256"], item["reference_sha256"])
        for name, digest in mapping.items())
    write(args.evidence / "RAW_RESULTS.json", rows)
    write(args.evidence / "CONTROLS.json", controls)
    rates=[]
    for row in rows:
        t=duration(row["execution"]["state"])
        if t!=row["settled_container_runtime_sec"] or t<=0:
            raise ValueError("actual daemon timing differs")
        rates.append({"unit":row["unit"],"N":row["actual_events"],"T":t,"EPS":row["actual_events"]/t})
    gate_count=sum(g["passed"] is True for row in rows for g in row["developer_verifier"]["verdict"]["gate_results"].values())
    executions=[value["execution"] for value in controls.values()]+[row["execution"] for row in rows]
    intervals=sorted((ex["state"]["StartedAt"],ex["state"]["FinishedAt"],ex["name"]) for ex in executions)
    serial=len(intervals)==len({value[2] for value in intervals}) and all(a[1]<b[0] for a,b in zip(intervals,intervals[1:]))
    settled=all(ex["succeeded"] is True and ex["exit_code"]==0 and ex["OOMKilled"] is False
        and ex["cleanup"]["settled"] is True and ex["cleanup"]["removed"] is True
        and ex["cleanup"]["final_absent"] is True and ex["cleanup"]["errors"]==[] for ex in executions)
    passed=(failure is None and len(rows)==71 and gate_count==284 and unchanged and len(after)==1 and serial and settled)
    write(args.evidence / "SUMMARY.json",{"all_passed":passed,"failure":failure,
        "ordinary_runs":len(rows),"official_gate_passes":gate_count,"controls_containers":len(controls),
        "source_and_references_unchanged":unchanged,"actual_market_containers":len(executions),
        "actual_serial_intervals":serial,"all_settled_removed":settled,"per_unit":rates,
        "full71_single_run_mean_EPS":statistics.mean(row["EPS"] for row in rates) if len(rates)==71 else None,
        "rankable":False,"full71":len(rows)==71,"formal_repeats":False,"official_submission":False,
        "target_verified_met":False,"timing_policy":"one full public validation pass; no Final median claim"})
    if not passed:
        raise ValueError("actual full71 public validation failed")



if __name__ == "__main__":
    main()
