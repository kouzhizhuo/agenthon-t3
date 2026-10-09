"""Prepare diagnostic-only source copies; never build, compile or run a market."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPLETION = HERE.parent
BASE = COMPLETION / "server_observer_startup_v1/materialized_v1/control/entry_probe.py"
HELPERS = '''
import time as _floor_time
FLOOR_MARKER = "T3_FLOOR_PHASE="
FLOOR_TARGETS = ("numpy", "pandas", "pyarrow", "scipy", "scipy.spatial", "scipy.spatial.distance",
    "scipy.sparse", "scipy.linalg", "scipy.special", "scipy.stats", "abides_markets.agents",
    "abides_markets.agents.examples.momentum_agent", "abides_markets.agents.market_makers.adaptive_market_maker_agent",
    "abides_markets.agents.noise_agent", "abides_markets.agents.value_agent",
    "abides_markets.oracles.mean_reverting_oracle", "abides_markets.oracles.sparse_mean_reverting_oracle",
    "observer", "observer_domain")
_floor_rows = []

def floor_phase(name, entry=None):
    now = _floor_time.perf_counter()
    modules = {}
    for key in FLOOR_TARGETS:
        module = sys.modules.get(key)
        if module is None:
            modules[key] = {"present": False}
        else:
            state = vars(module)
            modules[key] = {"present": True, "origin": state.get("__file__"), "version": state.get("__version__")}
    row = {"phase": name, "perf_counter": now, "modules": modules, "rankable": False}
    if entry is not None:
        row["entry_started"] = entry.ENTRY_STARTED
        row["since_entry_sec"] = now - entry.ENTRY_STARTED
    _floor_rows.append(row)
    print(FLOOR_MARKER + json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)

def floor_source_evidence():
    # Read only already-loaded public source; never trigger an optional import.
    remaining = 1024 * 1024
    for name in ("scipy", "scipy.spatial", "scipy.spatial.distance", "pandas", "pandas.compat",
            "abides_markets.oracles.mean_reverting_oracle", "abides_markets.oracles.sparse_mean_reverting_oracle"):
        module = sys.modules.get(name)
        origin = vars(module).get("__file__") if module is not None else None
        row = {"module": name, "loaded": module is not None, "origin": origin, "rankable": False}
        if origin:
            path = Path(origin)
            if path.is_symlink() or not path.is_file():
                raise ValueError("loaded module source must be ordinary file")
            row.update(sha256=sha(path), bytes=path.stat().st_size)
            if path.suffix == ".py" and path.stat().st_size <= min(256 * 1024, remaining):
                data = path.read_text()
                row["source_text"] = data
                remaining -= path.stat().st_size
        print("T3_FLOOR_SOURCE=" + json.dumps(row, sort_keys=True), file=sys.stderr, flush=True)

def floor_trace(entry):
    # Diagnostic-only line tracing: no candidate alias or callback is replaced.
    # The global call hook has overhead, so intervals are never ranked timings.
    tree = ast.parse(Path(entry.__file__).read_bytes())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "simulate")
    starts = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            label = {"observer.begin_episode": "setup_admission_begin", "build_config": "config_build_begin",
                "abides.run": "simulation_begin", "extract_trace": "trace_projection_begin",
                "message_extractor": "message_projection_begin", "validate_frames": "frame_validation_begin",
                "trace.to_parquet": "trace_output_begin", "messages.to_parquet": "message_output_begin",
                "sha256": "trace_hash_begin", "resource.getrusage": "rss_lookup_begin"}.get(name)
            if label:
                if node.lineno in starts:
                    raise ValueError("ambiguous diagnostic marker line")
                starts[node.lineno] = label
    required = {"setup_admission_begin", "config_build_begin", "simulation_begin", "trace_projection_begin",
        "message_projection_begin", "frame_validation_begin", "trace_output_begin", "message_output_begin", "trace_hash_begin", "rss_lookup_begin"}
    if set(starts.values()) != required:
        raise ValueError("original CLI phase source layout differs")
    previous = None
    def local(frame, event, arg):
        nonlocal previous
        if event == "line":
            if previous is not None:
                floor_phase(previous + "_completed_next_line", entry)
                previous = None
            if frame.f_lineno in starts:
                previous = starts[frame.f_lineno]
                floor_phase(previous, entry)
        elif event in ("return", "exception"):
            floor_phase("simulate_" + event, entry)
        return local
    def global_trace(frame, event, arg):
        return local if event == "call" and frame.f_code is entry.simulate.__code__ else None
    return global_trace
'''


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("frozen wrapper splice differs: " + old[:80])
    return source.replace(old, new)


def prepare(out, base=BASE):
    if out.exists():
        raise ValueError("new diagnostic source directory required")
    out.mkdir(parents=True)
    original = base.read_text()
    source = replace_once(original, 'PROBE_SCHEMA = "t3-screen-entry-probe-v2"',
        'PROBE_SCHEMA = "t3-screen-entry-probe-v2"\n' + HELPERS)
    source = replace_once(source, "    module_spec.loader.exec_module(entry)",
        "    floor_phase('real_entry_import_begin')\n    module_spec.loader.exec_module(entry)\n    floor_phase('real_entry_import_end', entry)")
    source = replace_once(source, "    require_visibility(cold_stock)",
        "    require_visibility(cold_stock)\n    floor_phase('cold_visibility_checked', entry)")
    source = replace_once(source, "    try:\n        entry.main()", "    floor_phase('main_begin', entry)\n    previous_trace = sys.gettrace()\n    if previous_trace is not None:\n        raise ValueError('unexpected preexisting trace hook')\n    sys.settrace(floor_trace(entry))\n    try:\n        entry.main()")
    source = replace_once(source, "    finally:\n        entry.enabled, abides.run = original_enabled, original_run",
        "    finally:\n        sys.settrace(previous_trace)\n        floor_phase('main_end', entry)\n        entry.enabled, abides.run = original_enabled, original_run")
    source = replace_once(source, '            receipt["authentication"] = authenticate(entry)',
        '            floor_phase("post_auth_begin", entry)\n            receipt["authentication"] = authenticate(entry)')
    source = replace_once(source, '            receipt["passed"] = error is None',
        '            floor_phase("post_auth_end", entry)\n            floor_source_evidence()\n            receipt["floor_phases"] = _floor_rows\n            receipt["passed"] = error is None')
    ast.parse(source)
    (out / "entry_probe.py").write_text(source)
    common = base.with_name("common.py").read_bytes()
    (out / "common.py").write_bytes(common)
    data = {"schema": "t3-floor-source-copy-v1", "source_only": True, "simulation_executed": False,
        "candidate_source_changed": False, "base_probe_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "probe_sha256": hashlib.sha256(source.encode()).hexdigest(), "common_sha256": hashlib.sha256(common).hexdigest(),
        "phase_instrumentation": "external frozen wrapper markers plus original simulate line tracing; callback aliases preserved",
        "timing_claim": False}
    (out / "PREPARATION.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-probe", type=Path, default=BASE)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out, args.base_probe), indent=2))
