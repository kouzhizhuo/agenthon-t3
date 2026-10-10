"""Same-run direct native comparison with original gates and daemon timing."""
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
ARMS = ("incumbent", "scalar")
UNITS = ("t3-s001-price-time-priority", "t3-as06-throughput-fast",
    "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid", "t3-gbatch-hetero-mix")
VOLATILE = {"wall_clock_sec", "events_per_sec", "peak_memory_bytes", "gpu_seconds"}


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


def pair(a, b):
    ia, ib = inventory(a), inventory(b)
    if set(ia) != set(ib):
        raise ValueError("output file roster differs")
    records = []
    for name in ia:
        if name.endswith(".parquet"):
            if (a / name).read_bytes() != (b / name).read_bytes():
                raise ValueError("actual full Parquet pair differs")
        else:
            x, y = read(a / name), read(b / name)
            if {k: v for k, v in x.items() if k not in VOLATILE} != {k: v for k, v in y.items() if k not in VOLATILE}:
                raise ValueError("stable sidecar pair differs")
        records.append({"path": name, "full_parquet_or_stable_sidecar_equal": True})
    return records


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
    parser.add_argument("--incumbent-payload", type=Path, required=True)
    parser.add_argument("--scalar-payload", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--gate-kit", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("real Linux amd64 only")
    args.evidence = args.evidence.resolve()
    args.payloads = {"incumbent": args.incumbent_payload.resolve(), "scalar": args.scalar_payload.resolve()}
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
    plan = public.collect_plan(args.reference_root, list(UNITS))
    items = {item["unit"]: item for item in plan["units"]}
    if set(items) != set(UNITS):
        raise ValueError("exact five diagnostic units required")
    write(args.evidence / "REFERENCE_PLAN.json", plan)
    rows, controls, before, after, pairs, failure = [], {}, {}, {}, [], None
    owners = {arm: uuid.uuid4().hex for arm in ARMS}
    try:
        for arm in ARMS:
            before[arm] = worker(args, arm, "metadata", arm + "-before",
                {"folder": str(args.evidence / arm / "before")})
            controls[arm] = worker(args, arm, "controls", arm + "-controls",
                {"owner": owners[arm]}, seconds=3900)
        # Original controls include fixture pairs, six full state graphs and
        # two forced output fallbacks. Require cross-version state equality too.
        for name in ("trace.parquet", "message_trace.parquet", "STATE.json"):
            a = args.evidence / "incumbent/controls/output/controls/children/light_dynamic" / name
            b = args.evidence / "scalar/controls/output/controls/children/light_dynamic" / name
            if a.read_bytes() != b.read_bytes():
                raise ValueError("cross-version actual control state/output differs")
        first = {}
        for repeat in range(5):
            for index, unit in enumerate(UNITS):
                order = list(ARMS if (repeat + index) % 2 == 0 else reversed(ARMS))
                group = {}
                for arm in order:
                    label = "%02d-%02d-%s" % (repeat, index, arm)
                    folder = args.evidence / arm / "direct" / str(repeat) / unit
                    row = worker(args, arm, "one", label, {"owner": owners[arm], "item": items[unit],
                        "folder": str(folder), "suffix": label})
                    row.update(direct_arm=arm, repeat=repeat, warmup=repeat == 0,
                        timing_included=repeat > 0, order=order)
                    rows.append(row)
                    group[arm] = row
                    write(args.evidence / "raw-progress" / (label + ".json"), row)
                    print(label, "PASS", flush=True)
                for arm in ARMS:
                    current = Path(group[arm]["output"])
                    previous = first.setdefault((unit, arm), current)
                    pairs.append({"unit": unit, "arm": arm, "repeat": repeat,
                        "same_round": pair(current, Path(group["incumbent"]["output"])),
                        "same_arm_repeat": pair(current, previous)})
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
    write(args.evidence / "PAIRS.json", pairs)
    rates = []
    for unit in UNITS:
        values = {}
        for arm in ARMS:
            samples = []
            for row in rows:
                if row["unit"] == unit and row["direct_arm"] == arm and row["timing_included"]:
                    t = duration(row["execution"]["state"])
                    if t != row["settled_container_runtime_sec"] or t <= 0:
                        raise ValueError("actual daemon timing differs")
                    samples.append({"repeat": row["repeat"], "N": row["actual_events"], "T": t,
                        "EPS": row["actual_events"] / t})
            if len(samples) == 4:
                values[arm] = {"samples": samples, "median_EPS": statistics.median(s["EPS"] for s in samples)}
        if len(values) == 2:
            rates.append({"unit": unit, "arms": values,
                "integer_heap_vs_classic_parent_ratio": values["scalar"]["median_EPS"] / values["incumbent"]["median_EPS"]})
    means = {arm: statistics.mean(row["arms"][arm]["median_EPS"] for row in rates) for arm in ARMS} if len(rates) == 5 else None
    gate_count = sum(g["passed"] is True for row in rows for g in row["developer_verifier"]["verdict"]["gate_results"].values())
    executions = [value["execution"] for value in controls.values()] + [row["execution"] for row in rows]
    intervals = sorted((ex["state"]["StartedAt"], ex["state"]["FinishedAt"], ex["name"]) for ex in executions)
    serial = len(intervals) == len({value[2] for value in intervals}) and all(a[1] < b[0] for a, b in zip(intervals, intervals[1:]))
    settled = all(ex["succeeded"] is True and ex["exit_code"] == 0 and ex["OOMKilled"] is False
        and ex["cleanup"]["settled"] is True and ex["cleanup"]["removed"] is True
        and ex["cleanup"]["final_absent"] is True and ex["cleanup"]["errors"] == [] for ex in executions)
    write(args.evidence / "SUMMARY.json", {"all_passed": failure is None and len(rows) == 50 and len(pairs) == 50
        and gate_count == 200 and unchanged and len(after) == 2 and serial and settled, "failure": failure, "ordinary_runs": len(rows),
        "measured_runs": sum(row["timing_included"] for row in rows), "official_gate_passes": gate_count,
        "controls_containers": len(controls), "source_and_references_unchanged": unchanged,
        "actual_market_containers": len(executions), "actual_serial_intervals": serial, "all_settled_removed": settled,
        "per_unit": rates, "five_unit_mean_of_median_EPS": means,
        "integer_heap_vs_classic_parent_ratio": None if means is None else means["scalar"] / means["incumbent"],
        "rankable": False, "full71": False, "official_submission": False,
        "prescribed_fixture_repeat_shape_only": "5 runs with first warmup excluded; five selected units only"})
    if failure or len(rows) != 50 or gate_count != 200 or not unchanged or not serial or not settled:
        raise ValueError("actual direct comparison failed")


if __name__ == "__main__":
    main()
