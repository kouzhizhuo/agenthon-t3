#!/usr/bin/env python3
"""Run the pinned ABIDES engine; public reference material is never loaded here."""
from bootstrap import activate
activate()

import argparse
import json
from pathlib import Path
import resource
import sys
import time

from abides_core import abides
from abides_core.kernel import Kernel
from abides_fork.config import build_config
from abides_fork.simulate import reset_abides_counters
from abides_fork.trace import extract_trace, extract_message_trace
from contracts import sha256, validate_scenario, validate_frames
from optimizations import enabled


def simulate(config_path, out_path, mode="optimized"):
    t0 = time.perf_counter()
    scenario = json.loads(Path(config_path).read_text())
    validate_scenario(scenario)
    reset_abides_counters()
    config = build_config(scenario)
    # Upstream write_summary_log ignores skip_log and writes ./log even with
    # a read-only container root. It is not a competition output and does not
    # modify end_state, so both comparison modes suppress that diagnostic IO.
    summary_writer = Kernel.write_summary_log
    Kernel.write_summary_log = lambda self: None
    try:
        with enabled(mode == "optimized"):
            end_state = abides.run(config)
    finally:
        Kernel.write_summary_log = summary_writer
    trace = extract_trace(end_state)
    messages = extract_message_trace(end_state)
    validate_frames(trace, messages)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    trace.to_parquet(out, compression="snappy", index=False)
    messages.to_parquet(out.parent / "message_trace.parquet", compression="snappy", index=False)
    trace_digest = sha256(out)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    wall = time.perf_counter() - t0
    events = {"scenario_id": str(scenario["scenario_id"]), "seed": int(scenario["seed"]),
              "n_events": len(trace), "wall_clock_sec": wall,
              "events_per_sec": len(trace) / wall, "trace_sha256": trace_digest,
              "peak_memory_bytes": int(rss) if sys.platform == "darwin" else int(rss) * 1024,
              "gpu_seconds": 0.0}
    (out.parent / "events.json").write_text(json.dumps(events, indent=2) + "\n")
    return events


def simulate_batch(batch_dir, out_dir, mode="optimized"):
    paths = sorted(p for p in Path(batch_dir).glob("*.json") if not p.name.startswith("._"))
    if not paths:
        raise ValueError("batch-dir contains no scenario JSON files")
    t0 = time.perf_counter()
    per_scenario = []
    for path in paths:
        events = simulate(path, Path(out_dir) / path.stem / "trace.parquet", mode)
        per_scenario.append({"sub": path.stem, "n_events": events["n_events"],
                             "scenario_id": events["scenario_id"], "seed": events["seed"]})
    wall = time.perf_counter() - t0
    total = sum(row["n_events"] for row in per_scenario)
    result = {"total_events": total, "wall_clock_sec": wall, "events_per_sec": total / wall,
              "per_scenario": per_scenario}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "batch_events.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="verb", required=True)
    single = sub.add_parser("simulate")
    single.add_argument("--config", required=True)
    single.add_argument("--out", required=True)
    batch = sub.add_parser("simulate-batch")
    batch.add_argument("--batch-dir", required=True)
    batch.add_argument("--out-dir", required=True)
    for command in (single, batch):
        command.add_argument("--mode", choices=["baseline", "optimized"], default="optimized")
    args = parser.parse_args()
    if args.verb == "simulate":
        result = simulate(args.config, args.out, args.mode)
    else:
        result = simulate_batch(args.batch_dir, args.out_dir, args.mode)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
