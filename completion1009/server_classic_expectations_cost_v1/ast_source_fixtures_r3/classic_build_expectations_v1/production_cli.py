#!/usr/bin/env python3
"""Official single/batch entry for finite light canonical + continuous native owners."""
import time
ENTRY_STARTED = time.perf_counter()
import argparse
import json
from pathlib import Path
import resource
import sys

HERE = Path(__file__).resolve().parent


def activate_paths(runtime):
    runtime = Path(runtime).resolve()
    sys.path.insert(0, str(runtime))
    from bootstrap import activate
    activate()
    return runtime


def simulate(config_path, out_path, build_dir=None, runtime=None, arm="light_dynamic", started=None, witness_path=None):
    if arm not in ("light_canonical", "light_dynamic"):
        raise ValueError("unknown coherent composite arm")
    t0 = time.perf_counter() if started is None else started
    runtime = (HERE / "runtime" if runtime is None else Path(runtime)).resolve()
    build_dir = HERE / "build" if build_dir is None else Path(build_dir).resolve()
    from source_provenance import verify_sources, verify_runtime
    verify_sources(); verify_runtime(runtime)
    runtime = activate_paths(runtime)
    if "trader_probe" in sys.modules:
        raise ValueError("production loaded control-only probe")
    from abides_core import abides
    from abides_core.kernel import Kernel
    from abides_fork.config import build_config
    from counters import reset_abides_counters
    from abides_fork.trace import extract_trace, extract_message_trace, MESSAGE_TRACE_COLUMNS, _MSG_DTYPES, _side_to_str
    from contracts import sha256, validate_scenario, validate_frames
    from canonical_buffers import Declined, project_trace, project_messages, validate_admitted_columns, write_outputs, import_witness
    from abides_markets.orders import Side
    import observer
    from observer_domain import authenticate_loaded, configure_expectations
    from arena_admission import admit
    from optimizations import enabled
    scenario = json.loads(Path(config_path).read_bytes())
    validate_scenario(scenario)
    configure_expectations(build_dir, runtime)
    authenticated = authenticate_loaded()
    native_admitted = arm == "light_dynamic" and authenticated and admit(scenario, runtime)
    engine, chosen = None, Kernel
    if native_admitted:
        from native_loader import load
        engine = load(build_dir, runtime)["dynamic_arena_chain"]
        from native_owner_kernel import NativeOwnerKernel
        chosen = NativeOwnerKernel
    original_kernel, summary_writer = abides.Kernel, Kernel.write_summary_log
    if observer.STATE is not None:
        raise ValueError("previous observer episode active")
    before = import_witness() if witness_path is not None else None
    admitted_episode = observer.begin_episode(scenario, authenticated)
    declines = {}
    try:
        reset_abides_counters()
        config = build_config(scenario)
        # Same diagnostic summary IO suppression in each control arm.
        Kernel.write_summary_log = lambda self: None
        if native_admitted:
            abides.Kernel = chosen
            end_state = abides.run(config)
            kernel = end_state["agents"][0].kernel
            if type(kernel) is not chosen or kernel.agents is not end_state["agents"]:
                raise ValueError("actual native selected kernel/roster differs")
            kernel._chain_migration.assert_authority()
            ledger_type = engine.ColumnLedger
            from ledger_writer import extract as ledger_extract
            message_extractor = lambda state: ledger_extract(state, MESSAGE_TRACE_COLUMNS, _MSG_DTYPES)
        else:
            # A refused whole-episode native domain stays in a complete original
            # kernel/ledger pair. Light canonical control uses its existing pair.
            with enabled(arm == "light_canonical") as message_extractor:
                end_state = abides.run(config)
            ledger_type = getattr(message_extractor, "ledger_type", None)
        trace = (project_trace(end_state, observer.STATE, Side, _side_to_str, engine) if admitted_episode
                 else Declined("unauthenticated-episode"))
        messages = (project_messages(end_state, ledger_type) if admitted_episode and isinstance(ledger_type, type)
                    else Declined("legacy-extractor-pair"))
        declines = {name: value.reason for name, value in (("trace", trace), ("message_trace", messages)) if type(value) is Declined}
        if declines:
            # Both fallbacks refer to this single finished market and its actual
            # ledger owner. No original object state is revived and no rerun occurs.
            trace = extract_trace(end_state)
            messages = message_extractor(end_state)
            validate_frames(trace, messages)
        else:
            validate_admitted_columns(trace, messages)
    finally:
        abides.Kernel, Kernel.write_summary_log = original_kernel, summary_writer
        observer.finish_episode()
    out = Path(out_path); out.parent.mkdir(parents=True, exist_ok=True)
    if declines:
        trace.to_parquet(out, compression="snappy", index=False)
        messages.to_parquet(out.parent / "message_trace.parquet", compression="snappy", index=False)
        n_events = len(trace)
    else:
        write_outputs(trace, messages, out)
        n_events = trace.n_rows
    wall = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {"scenario_id": str(scenario["scenario_id"]), "seed": int(scenario["seed"]), "n_events": n_events,
        "wall_clock_sec": wall, "events_per_sec": n_events / wall, "trace_sha256": sha256(out),
        "peak_memory_bytes": int(rss) if sys.platform == "darwin" else int(rss) * 1024, "gpu_seconds": 0.0}
    (out.parent / "events.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    if witness_path is not None:
        native_output = not declines and engine is not None and type(trace) is engine.NativeColumns and type(messages) is engine.NativeColumns
        witness = {"schema": "t3-cold-native-projection-buffers-output-witness-v1", "requested_arm": arm,
            "source_authenticated": authenticated, "observer_admitted": admitted_episode, "native_admitted": native_admitted,
            "selected_kernel": type(end_state["agents"][0].kernel).__name__, "projectors_admitted": not bool(declines),
            "declines": declines, "output_mode": "legacy-pandas" if declines else "native-canonical-arrow-buffers" if native_output else "canonical-arrow-buffers",
            "native_output_pair": native_output,
            "before": before, "after": import_witness(), "actual_trace_rows": n_events,
            "actual_trace_sha256": result["trace_sha256"], "market_rerun": False, "rankable": False}
        path = Path(witness_path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(witness, sort_keys=True, indent=2) + "\n")
    return result


def simulate_batch(batch_dir, out_dir, build_dir=None, runtime=None, arm="light_dynamic", started=None, witness_path=None):
    t0 = time.perf_counter() if started is None else started
    paths = sorted(path for path in Path(batch_dir).glob("*.json") if not path.name.startswith("._"))
    if not paths:
        raise ValueError("batch directory has no scenario JSON")
    rows = []
    for path in paths:
        value = simulate(path, Path(out_dir) / path.stem / "trace.parquet", build_dir, runtime, arm,
            witness_path=None if witness_path is None else Path(witness_path) / (path.stem + ".json"))
        rows.append({"sub": path.stem, "n_events": value["n_events"], "scenario_id": value["scenario_id"], "seed": value["seed"]})
    wall = time.perf_counter() - t0; total = sum(row["n_events"] for row in rows)
    result = {"n_scenarios": len(rows), "total_events": total, "wall_clock_sec": wall, "events_per_sec": total / wall, "per_scenario": rows}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "batch_events.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="verb", required=True)
    single = sub.add_parser("simulate"); single.add_argument("--config", required=True); single.add_argument("--out", required=True)
    batch = sub.add_parser("simulate-batch"); batch.add_argument("--batch-dir", required=True); batch.add_argument("--out-dir", required=True)
    for command in (single, batch):
        command.add_argument("--runtime", type=Path, default=HERE / "runtime")
        command.add_argument("--build", type=Path, default=HERE / "build")
        command.add_argument("--arm", choices=("light_canonical", "light_dynamic"), default="light_dynamic")
        command.add_argument("--output-witness", type=Path)
    args = parser.parse_args()
    value = (simulate(args.config, args.out, args.build, args.runtime, args.arm, ENTRY_STARTED, args.output_witness)
        if args.verb == "simulate" else simulate_batch(args.batch_dir, args.out_dir, args.build, args.runtime, args.arm, ENTRY_STARTED, args.output_witness))
    print(json.dumps(value))


if __name__ == "__main__":
    main()
