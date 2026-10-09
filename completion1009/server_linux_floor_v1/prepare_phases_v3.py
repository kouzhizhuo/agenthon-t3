"""Prepare ten-point external CLI driver; no tracing or market execution."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from prepare import BASE, replace_once

HELPERS = '''
import time as _floor_time
_floor_ticks = []
_floor_milestones = []

def floor_mark(name, entry=None):
    row = {"phase": name, "perf_counter": _floor_time.perf_counter(), "rankable": False}
    if entry is not None:
        row["entry_started"] = entry.ENTRY_STARTED
        row["since_entry_sec"] = row["perf_counter"] - entry.ENTRY_STARTED
    _floor_milestones.append(row)

def floor_tick(name, config_path=None):
    # Exactly ten O(1) timestamp appends per real simulate call, no per-event hook.
    _floor_ticks.append((name, _floor_time.perf_counter(), str(config_path) if config_path is not None else None))

def floor_driver(entry):
    tree = ast.parse(Path(entry.__file__).read_bytes())
    original = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "simulate")
    fn = next(n for n in ast.parse(ast.unparse(original)).body if isinstance(n, ast.FunctionDef))
    docstring = fn.body[0] if (fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant)
        and isinstance(fn.body[0].value.value, str)) else None
    first = fn.body[1] if docstring is not None else fn.body[0]
    labels = {id(first): "simulate_begin"}
    def text(node):
        return ast.unparse(node)
    for node in fn.body:
        value = text(node)
        label = None
        if value.startswith("observer.begin_episode("): label = "admission_begin"
        elif value.startswith("config = build_config("): label = "config_begin"
        elif isinstance(node, ast.Try) and "with enabled(" in value: label = "simulation_begin"
        elif isinstance(node, ast.Try) and "trace = extract_trace(" in value: label = "simulation_end_projection_begin"
        elif value.startswith("validate_frames("): label = "projection_end_validation_begin"
        elif value.startswith("trace.to_parquet("): label = "parquet_begin"
        elif value.startswith("trace_digest = sha256("): label = "parquet_end_hash_begin"
        elif value.startswith("events = {"): label = "sidecar_begin_after_original_wall"
        elif isinstance(node, ast.Return): label = "simulate_exit"
        if label:
            labels[id(node)] = label
    if len(labels) != 10 or len(set(labels.values())) != 10:
        raise ValueError("original exact ten phase source sites differ")
    body = []
    for node in fn.body:
        label = labels.get(id(node))
        if label:
            args = [ast.Constant(label)] + ([ast.Name("config_path", ast.Load())] if label == "simulate_begin" else [])
            tick = ast.Expr(ast.Call(ast.Name("_t3_floor_tick", ast.Load()), args, []))
            ast.copy_location(tick, node)
            body.append(tick)
        body.append(node)
    fn.body = body
    # Remove only injected nodes and verify every other AST operation is exact.
    clean = ast.parse(ast.unparse(fn)).body[0]
    clean.body = [n for n in clean.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name) and n.value.func.id == "_t3_floor_tick")]
    if ast.dump(clean, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("diagnostic driver altered non-marker CLI AST")
    if "_t3_floor_tick" in vars(entry):
        raise ValueError("diagnostic global collision")
    namespace = {}
    module = ast.Module([fn], [])
    ast.fix_missing_locations(module)
    exec(compile(module, entry.__file__, "exec", dont_inherit=True), vars(entry), namespace)
    driver = namespace["simulate"]
    if driver.__defaults__ != entry.simulate.__defaults__ or driver.__globals__ is not vars(entry):
        raise ValueError("diagnostic driver defaults/globals differ")
    driver.__doc__ = entry.simulate.__doc__
    driver.__annotations__ = dict(entry.simulate.__annotations__)
    driver.__kwdefaults__ = entry.simulate.__kwdefaults__
    if (driver.__doc__ != entry.simulate.__doc__ or driver.__annotations__ != entry.simulate.__annotations__
            or driver.__kwdefaults__ != entry.simulate.__kwdefaults__):
        raise ValueError("diagnostic driver doc/annotations/kwdefaults differ")
    vars(entry)["_t3_floor_tick"] = floor_tick
    return driver

def floor_dump(entry):
    targets = ("numpy", "pandas", "pyarrow", "scipy", "scipy.spatial", "scipy.spatial.distance",
        "scipy.sparse", "scipy.linalg", "scipy.special", "scipy.stats", "abides_markets.agents",
        "abides_markets.oracles.mean_reverting_oracle", "abides_markets.oracles.sparse_mean_reverting_oracle",
        "observer", "observer_domain")
    modules = {}
    for name in targets:
        module = sys.modules.get(name)
        state = vars(module) if module is not None else {}
        modules[name] = {"present": module is not None, "origin": state.get("__file__"), "version": state.get("__version__")}
    phases = [{"phase": n, "perf_counter": t, "since_entry_sec": t - entry.ENTRY_STARTED, "config_path": c} for n, t, c in _floor_ticks]
    print("T3_FLOOR_PHASES=" + json.dumps({"schema": "t3-floor-ten-point-driver-v3", "rankable": False,
        "ticks": phases, "milestones": _floor_milestones, "modules": modules, "original_entry_started": entry.ENTRY_STARTED,
        "ten_points_per_episode": True, "trace_hook_used": False, "non_marker_ast_equal": True,
        "probe_overhead_included": True, "diagnostic_simulate_alias_installed_during_main": True,
        "original_simulate_alias_restored_before_post_auth": True,
        "line_numbers_differ_but_all_non_marker_AST_equal": True}, sort_keys=True), file=sys.stderr, flush=True)
'''


def prepare(out, base=BASE):
    if out.exists():
        raise ValueError("new diagnostic source output required")
    out.mkdir(parents=True)
    original = base.read_text()
    source = replace_once(original, 'PROBE_SCHEMA = "t3-screen-entry-probe-v2"',
        'PROBE_SCHEMA = "t3-screen-entry-probe-v2"\n' + HELPERS)
    source = replace_once(source, "    module_spec.loader.exec_module(entry)",
        "    floor_mark('real_entry_import_begin')\n    module_spec.loader.exec_module(entry)\n    floor_mark('real_entry_import_end', entry)")
    source = replace_once(source, "    try:\n        entry.main()", "    original_simulate = entry.simulate\n    entry.simulate = floor_driver(entry)\n    floor_mark('main_begin', entry)\n    try:\n        entry.main()")
    source = replace_once(source, "    finally:\n        entry.enabled, abides.run = original_enabled, original_run",
        "    finally:\n        floor_mark('main_end', entry)\n        entry.simulate = original_simulate\n        vars(entry).pop('_t3_floor_tick', None)\n        entry.enabled, abides.run = original_enabled, original_run")
    source = replace_once(source, '            receipt["authentication"] = authenticate(entry)',
        '            floor_mark("post_auth_begin", entry)\n            receipt["authentication"] = authenticate(entry)')
    source = replace_once(source, '            receipt["passed"] = error is None',
        '            floor_mark("post_auth_end", entry)\n            floor_dump(entry)\n            receipt["floor_driver_schema"] = "t3-floor-ten-point-driver-v3"\n            receipt["floor_milestones"] = _floor_milestones\n            receipt["passed"] = error is None')
    ast.parse(source)
    common = base.with_name("common.py").read_bytes()
    (out / "entry_probe.py").write_text(source)
    (out / "common.py").write_bytes(common)
    data = {"schema": "t3-floor-source-copy-v3", "source_only": True, "simulation_executed": False,
        "candidate_source_changed": False, "base_probe_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "probe_sha256": hashlib.sha256(source.encode()).hexdigest(), "common_sha256": hashlib.sha256(common).hexdigest(),
        "trace_hook_used": False, "points_per_episode": 10, "non_marker_ast_runtime_checked": True,
        "timing_claim": False}
    (out / "PREPARATION.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--base-probe", type=Path, default=BASE)
    args = p.parse_args()
    print(json.dumps(prepare(args.out, args.base_probe), indent=2))
