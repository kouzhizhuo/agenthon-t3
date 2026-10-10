#!/usr/bin/env python3
"""Bounded local verification of the production T3 agent against public references.

This is strict local differential evidence, not official ranking or a resource-certified run.
It preserves organizer inputs, launches the real agent in fresh processes, compares exact
reference values and dtypes, checks sidecar arithmetic and hashes, and reruns batch markets
in isolation. Each process has a 300-second deadline and bounded stdout/stderr retention.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import stat
import subprocess
import sys
import threading
import time

import pandas as pd
import pyarrow


HERE = Path(__file__).resolve().parent
T3 = HERE.parent
EXCLUDED_UNIT = "t3-EXAMPLE-vectorized-matching"
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
CORE_EVENTS = ("scenario_id", "seed", "n_events", "wall_clock_sec", "events_per_sec", "trace_sha256")
SUB_FILES = ("trace.parquet", "message_trace.parquet", "events.json", "profile.json")


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(json_safe(value), indent=2, sort_keys=True, default=str, allow_nan=False) + "\n")
    temporary.replace(path)


def json_safe(value):
    """Preserve malformed nonfinite sidecars as diagnostic strings, not invalid result JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def read_json(path):
    return json.loads(Path(path).read_text())


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require(condition, message, breaches):
    if not condition:
        breaches.append(message)


def collect_plan(reference_root, selected):
    all_units = sorted(p for p in reference_root.iterdir() if p.is_dir() and not p.name.startswith("._") and p.name != EXCLUDED_UNIT)
    if len(all_units) != 71:
        raise ValueError("expected exactly 71 reference units after excluding the historical exemplar, found %d" % len(all_units))
    chosen = set(selected) if selected else {p.name for p in all_units}
    unknown = chosen - {p.name for p in all_units}
    if unknown:
        raise ValueError("unknown units: " + repr(sorted(unknown)))
    units = []
    for unit in all_units:
        if unit.name not in chosen:
            continue
        if (unit / "batch.json").exists():
            batch = read_json(unit / "batch.json")
            subs = batch["subs"]
            names = [entry["sub"] for entry in subs]
            if not names or len(set(names)) != len(names):
                raise ValueError("invalid organizer batch roster: " + unit.name)
            scenarios = [unit / entry["scenario_file"] for entry in subs]
            if sorted(p.stem for p in (unit / "scenarios").glob("*.json") if not p.name.startswith("._")) != sorted(names):
                raise ValueError("organizer scenario files differ from batch roster: " + unit.name)
            frames = [unit / "checks/reference_data" / name / filename for name in names for filename in SUB_FILES[:2]]
            shape = "batch"
        else:
            subs = []
            scenarios = [unit / "scenario.json"]
            frames = [unit / filename for filename in SUB_FILES[:2]]
            shape = "single"
        for path in scenarios + frames + [unit / "card.toml"]:
            if not path.is_file():
                raise ValueError("missing public input/reference: " + str(path))
        units.append({"unit": unit.name, "shape": shape, "subs": subs,
                      "scenario_paths": [str(p) for p in scenarios],
                      "reference_frames": [str(p) for p in frames],
                      "input_sha256": {str(p.relative_to(unit)): sha256(p) for p in scenarios + [unit / "card.toml"] + ([unit / "batch.json"] if subs else [])},
                      "reference_sha256": {str(p.relative_to(unit)): sha256(p) for p in frames}})
    frame_count = sum(len(unit["reference_frames"]) for unit in units)
    if not selected and frame_count != 190:
        raise ValueError("full71 must contain exactly 190 reference Parquet frames, found %d" % frame_count)
    return {"all_roster_units": 71, "selected_units": len(units), "reference_frame_count": frame_count,
            "isolated_process_count": sum(len(unit["subs"]) for unit in units), "units": units}


def retained_pipe(pipe, path, cap, metadata):
    total = 0
    kept = 0
    with path.open("wb") as stream:
        for chunk in iter(lambda: pipe.read(64 * 1024), b""):
            total += len(chunk)
            if kept < cap:
                data = chunk[:cap - kept]
                stream.write(data)
                kept += len(data)
    pipe.close()
    metadata.update(total_bytes=total, retained_bytes=kept, truncated=total > kept)


def run_process(command, workdir, env, output_prefix, timeout, log_cap):
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    result = {"command": command, "cwd": str(workdir), "timeout_sec": timeout,
              "rankable": False, "stdout": {}, "stderr": {}}
    started = time.perf_counter()
    try:
        process = subprocess.Popen(command, cwd=workdir, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        result.update(returncode=None, timed_out=False, succeeded=False,
                      host_wall_sec=time.perf_counter() - started,
                      error=type(exc).__name__ + ": " + str(exc))
        for label in ("stdout", "stderr"):
            path = output_prefix.with_name(output_prefix.name + "." + label + ".txt")
            path.write_text(result["error"] if label == "stderr" else "")
            result[label].update(path=str(path), total_bytes=path.stat().st_size,
                                 retained_bytes=path.stat().st_size, truncated=False)
        return result
    threads = []
    for label, pipe in [("stdout", process.stdout), ("stderr", process.stderr)]:
        path = output_prefix.with_name(output_prefix.name + "." + label + ".txt")
        result[label]["path"] = str(path)
        thread = threading.Thread(target=retained_pipe, args=(pipe, path, log_cap, result[label]), daemon=True)
        thread.start()
        threads.append(thread)
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
    elapsed = time.perf_counter() - started
    for thread in threads:
        thread.join(timeout=5)
    result.update(returncode=process.returncode, timed_out=timed_out, host_wall_sec=elapsed,
                  succeeded=not timed_out and process.returncode == 0)
    return result


def compare_frame(candidate, reference):
    result = {"candidate": str(candidate), "reference": str(reference), "passed": False}
    try:
        c, r = pd.read_parquet(candidate), pd.read_parquet(reference)
        result.update(candidate_sha256=sha256(candidate), reference_sha256=sha256(reference),
                      candidate_rows=len(c), reference_rows=len(r),
                      candidate_dtypes={k: str(v) for k, v in c.dtypes.items()},
                      reference_dtypes={k: str(v) for k, v in r.dtypes.items()})
        pd.testing.assert_frame_equal(c, r, check_dtype=True, check_exact=True,
                                      check_names=True, check_like=False, rtol=0, atol=0)
        result["passed"] = True
        result["byte_equal"] = result["candidate_sha256"] == result["reference_sha256"]
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:2500]
    return result


def verify_events(output, scenario, count):
    breaches = []
    result = {"passed": False, "breaches": breaches}
    try:
        event = read_json(output / "events.json")
        require(isinstance(event, dict), "events.json must be an object", breaches)
        if not isinstance(event, dict):
            return result
        require(set(CORE_EVENTS).issubset(event), "missing required events.json fields", breaches)
        for name in ("scenario_id", "seed"):
            require(event.get(name) == scenario.get(name), name + " does not match organizer input", breaches)
        require(isinstance(event.get("seed"), int) and not isinstance(event.get("seed"), bool), "seed must be an integer", breaches)
        require(isinstance(event.get("n_events"), int) and not isinstance(event.get("n_events"), bool) and event.get("n_events") == count,
                "n_events does not equal actual Parquet rows", breaches)
        wall, rate = event.get("wall_clock_sec"), event.get("events_per_sec")
        ok = finite_number(wall) and wall > 0 and finite_number(rate) and rate >= 0 and count > 0
        require(ok, "timing/rate/count must be finite and valid", breaches)
        if ok:
            computed = count / wall
            require(abs(rate - computed) / computed <= .05, "rate arithmetic differs by more than 5%", breaches)
        actual_hash = sha256(output / "trace.parquet")
        require(event.get("trace_sha256") == actual_hash, "trace_sha256 does not hash emitted trace", breaches)
        result.update(events=event, actual_trace_sha256=actual_hash)
    except Exception as exc:
        breaches.append(type(exc).__name__ + ": " + str(exc)[:1500])
    result["passed"] = not breaches
    return result


def check_tree(output, allowed):
    breaches = []
    files = []
    host_metadata = []
    total = 0
    if output.exists():
        for path in output.rglob("*"):
            if sys.platform == "darwin" and path.name.startswith("._"):
                # The shared Mac volume materializes extended attributes as AppleDouble files.
                # Record this host artifact; it is not emitted by a Linux participant process.
                host_metadata.append(str(path.relative_to(output)))
                continue
            info = path.lstat()
            if path.is_dir() and not path.is_symlink():
                continue
            rel = str(path.relative_to(output))
            files.append(rel)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "not a single regular file: " + rel, breaches)
            require(rel in allowed, "outside local output allowlist: " + rel, breaches)
            require(info.st_size <= MAX_OUTPUT_BYTES, "oversized output file: " + rel, breaches)
            total += info.st_size
    require(bool(files), "empty output tree", breaches)
    require(len(files) <= 256 and total <= MAX_OUTPUT_BYTES, "output tree exceeds file/byte budget", breaches)
    return {"passed": not breaches, "breaches": breaches, "files": sorted(files), "total_bytes": total,
            "ignored_native_mac_appledouble": sorted(host_metadata)}


def verify_outputs(unit, output, item):
    frames, events, counts = [], [], {}
    if item["shape"] == "single":
        frames = [compare_frame(output / name, unit / name) for name in SUB_FILES[:2]]
        count = frames[0].get("candidate_rows", 0)
        events = [verify_events(output, read_json(unit / "scenario.json"), count)]
        allowed = set(SUB_FILES)
        aggregate = None
    else:
        allowed = {"batch_events.json"}
        for entry in item["subs"]:
            sub = entry["sub"]
            allowed.update(sub + "/" + name for name in SUB_FILES)
            for name in SUB_FILES[:2]:
                frames.append(compare_frame(output / sub / name, unit / "checks/reference_data" / sub / name))
            counts[sub] = frames[-2].get("candidate_rows", 0)
            events.append(verify_events(output / sub, read_json(unit / entry["scenario_file"]), counts[sub]))
        breaches = []
        aggregate = {"passed": False, "breaches": breaches}
        try:
            meta = read_json(output / "batch_events.json")
            aggregate["events"] = meta
            require(meta.get("n_scenarios") == len(item["subs"]), "n_scenarios differs from input roster", breaches)
            require(isinstance(meta.get("total_events"), int) and not isinstance(meta.get("total_events"), bool) and meta.get("total_events") == sum(counts.values()),
                    "total_events differs from emitted subs", breaches)
            rows = meta.get("per_scenario", [])
            names = [row.get("sub") for row in rows]
            require(len(names) == len(counts) and len(set(names)) == len(names) and set(names) == set(counts), "per_scenario must exactly cover subs", breaches)
            for row in rows:
                require(isinstance(row.get("n_events"), int) and not isinstance(row.get("n_events"), bool) and row.get("n_events") == counts.get(row.get("sub")),
                        "per_scenario n_events mismatch", breaches)
            wall, rate = meta.get("wall_clock_sec"), meta.get("events_per_sec")
            ok = finite_number(wall) and wall > 0 and finite_number(rate) and rate >= 0 and sum(counts.values()) > 0
            require(ok, "invalid batch timing arithmetic", breaches)
            if ok:
                computed = sum(counts.values()) / wall
                require(abs(rate - computed) / computed <= .05, "batch rate arithmetic differs by more than 5%", breaches)
        except Exception as exc:
            breaches.append(type(exc).__name__ + ": " + str(exc)[:1500])
        aggregate["passed"] = not breaches
    tree = check_tree(output, allowed)
    passed = tree["passed"] and all(row["passed"] for row in frames + events) and (aggregate is None or aggregate["passed"])
    return {"passed": passed, "frames": frames, "sidecars": events, "aggregate": aggregate, "output_tree": tree,
            "actual_events": sum(counts.values()) if counts else frames[0].get("candidate_rows", 0)}


def candidate_command(args, item, unit, output, scenario=None):
    command = [args.run_python, str(args.agent), "simulate" if scenario is not None or item["shape"] == "single" else "simulate-batch"]
    if scenario is not None or item["shape"] == "single":
        command += ["--config", str(scenario or unit / "scenario.json"), "--out", str(output / "trace.parquet")]
    else:
        command += ["--batch-dir", str(unit / "scenarios"), "--out-dir", str(output)]
    command += ["--mode", args.mode]
    return command


def gate_main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True)
    parser.add_argument("--gate-kit", type=Path, required=True)
    args = parser.parse_args(sys.argv[2:])
    sys.path.insert(0, str(args.gate_kit))
    from qfbench2_track_simulation.scoring import build_developer_verifier
    ctx = {"unit_dir": str(args.unit), "output_dir": str(args.output)}
    verdict = asdict(build_developer_verifier(ctx).run(ctx))
    verdict.update(rankable=False, verification_scope="official unchanged developer verifier, local process output only")
    write_json(args.save, verdict)
    print(json.dumps(verdict, default=str))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=T3 / "evaluation_references")
    parser.add_argument("--agent", type=Path, default=HERE / "runtime/agent.py")
    parser.add_argument("--run-python", default="/usr/bin/python3")
    parser.add_argument("--runtime-pythonpath", type=Path, default=T3 / ".runtime")
    parser.add_argument("--out-dir", type=Path, default=HERE / "verification/full71")
    parser.add_argument("--units", nargs="+")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--log-cap-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--mode", choices=("optimized", "baseline"), default="optimized")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--gate-python")
    parser.add_argument("--gate-kit", type=Path)
    parser.add_argument("--require-gate", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true", help="retain the first failed unit and stop the sweep")
    args = parser.parse_args()
    if args.timeout <= 0 or args.timeout > 300 or args.log_cap_bytes <= 0:
        parser.error("timeout must be in (0,300] and log cap positive")
    if bool(args.gate_python) != bool(args.gate_kit):
        parser.error("--gate-python and --gate-kit must be supplied together")
    if args.require_gate and not args.gate_python:
        parser.error("--require-gate requires a configured current official scorer")
    plan = collect_plan(args.reference_root.resolve(), args.units)
    plan.update(rankable=False, verification_scope="native Mac bounded exact public differential checks; no enforced container CPU/memory caps or C1/C2/C7 evidence",
                host=platform.platform(), verifier_python=sys.version, pandas=pd.__version__, pyarrow=pyarrow.__version__,
                agent=str(args.agent), agent_sha256=sha256(args.agent), verifier_sha256=sha256(__file__),
                run_python=args.run_python, runtime_pythonpath=str(args.runtime_pythonpath), timeout_sec=args.timeout,
                developer_verifier="configured" if args.gate_python else "unavailable: configure Python 3.13, toolkit v2.5.1 and current --gate-kit")
    if args.plan_only:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    args.out_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.out_dir / "PLAN.json", plan)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(args.runtime_pythonpath.resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    records = []
    for item in plan["units"]:
        unit = args.reference_root.resolve() / item["unit"]
        work = args.out_dir / item["unit"]
        output = work / "output"
        output.mkdir(parents=True)
        row = {"unit": item["unit"], "shape": item["shape"], "rankable": False}
        row["execution"] = run_process(candidate_command(args, item, unit, output), args.agent.parent, env, work / "run", args.timeout, args.log_cap_bytes)
        row["checks"] = verify_outputs(unit, output, item)
        row["isolated"] = []
        for entry in item["subs"]:
            sub = entry["sub"]
            iso = work / "isolated" / sub
            iso.mkdir(parents=True)
            execution = run_process(candidate_command(args, item, unit, iso, unit / entry["scenario_file"]), args.agent.parent, env, work / "isolated" / (sub + "-run"), args.timeout, args.log_cap_bytes)
            frames = [compare_frame(iso / name, output / sub / name) for name in SUB_FILES[:2]]
            sidecar = verify_events(iso, read_json(unit / entry["scenario_file"]), frames[0].get("candidate_rows", 0))
            passed = execution["succeeded"] and sidecar["passed"] and all(frame["passed"] and frame.get("byte_equal") for frame in frames)
            row["isolated"].append({"sub": sub, "execution": execution, "frames": frames, "sidecar": sidecar, "passed": passed})
        row["developer_verifier"] = {"status": "unavailable", "admissible": None}
        if args.gate_python:
            save = work / "developer_verdict.json"
            command = [args.gate_python, str(Path(__file__).resolve()), "_gate", "--unit", str(unit), "--output", str(output), "--save", str(save), "--gate-kit", str(args.gate_kit)]
            gate_env = os.environ.copy()
            gate_env.pop("PYTHONPATH", None)
            execution = run_process(command, args.gate_kit, gate_env, work / "developer-gate", 300, args.log_cap_bytes)
            verdict = read_json(save) if save.is_file() else None
            row["developer_verifier"] = {"status": "completed" if execution["succeeded"] and verdict else "error", "execution": execution,
                                          "admissible": verdict.get("admissible") if verdict else None, "verdict": verdict}
        row["passed"] = row["execution"]["succeeded"] and row["checks"]["passed"] and all(iso["passed"] for iso in row["isolated"])
        if args.require_gate:
            row["passed"] = row["passed"] and row["developer_verifier"]["admissible"] is True
        row["host_events_per_sec"] = row["checks"]["actual_events"] / row["execution"]["host_wall_sec"] if row["passed"] else 0.0
        records.append(row)
        write_json(work / "RAW_RESULT.json", row)
        write_json(args.out_dir / "RAW_RESULTS.json", records)
        print("%s %s frames=%d isolated=%d host_wall=%.3fs" % (item["unit"], "PASS" if row["passed"] else "FAIL", len(row["checks"]["frames"]), len(row["isolated"]), row["execution"]["host_wall_sec"]), flush=True)
        if args.stop_on_failure and not row["passed"]:
            break
    input_unchanged = all(sha256(args.reference_root / item["unit"] / relative) == value for item in plan["units"] for relative, value in item["input_sha256"].items())
    frames = [frame for row in records for frame in row["checks"]["frames"]]
    summary = {"rankable": False, "scope": plan["verification_scope"], "selected_units": len(records),
               "planned_units": len(plan["units"]), "complete_roster": len(records) == len(plan["units"]),
               "passed_units": sum(row["passed"] for row in records), "all_passed": all(row["passed"] for row in records) and input_unchanged,
               "reference_frames": len(frames), "exact_reference_frames_passed": sum(frame["passed"] for frame in frames),
               "isolated_markets": sum(len(row["isolated"]) for row in records),
               "isolated_markets_passed": sum(iso["passed"] for row in records for iso in row["isolated"]),
               "input_files_unchanged": input_unchanged, "agent_unchanged": sha256(args.agent) == plan["agent_sha256"],
               "developer_verifier_configured": bool(args.gate_python), "developer_admissible_units": sum(row["developer_verifier"]["admissible"] is True for row in records),
               "local_mean_rate_with_failed_units_zero": sum(row["host_events_per_sec"] for row in records) / len(records),
               "failure_units": [row["unit"] for row in records if not row["passed"]]}
    summary["all_passed"] = summary["all_passed"] and summary["agent_unchanged"] and summary["complete_roster"]
    write_json(args.out_dir / "SUMMARY.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_gate":
        gate_main()
    else:
        raise SystemExit(main())
