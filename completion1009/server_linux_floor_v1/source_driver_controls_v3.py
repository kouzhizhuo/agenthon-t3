"""Pure-source driver construction/parser controls; simulate is never invoked."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import types

HERE = Path(__file__).resolve().parent


def check_driver():
    source = (HERE / "prepare_phases_v3.py").read_text()
    helper = next(n.value.value for n in ast.parse(source).body if isinstance(n, ast.Assign)
        and any(isinstance(v, ast.Name) and v.id == "HELPERS" for v in n.targets))
    node = next(n for n in ast.parse(helper).body if isinstance(n, ast.FunctionDef) and n.name == "floor_driver")
    namespace = {"ast": ast, "Path": Path, "floor_tick": lambda *a: None}
    exec(compile(ast.Module([node], []), "<source-only-control>", "exec"), namespace)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.py"
        # No participant imports. Source sites mirror the original function's
        # layout, and the function must never execute in these controls.
        path.write_text('''def simulate(config_path, out_path, mode="optimized", started=None):
    """Preserved diagnostic fixture docstring."""
    t0 = time.perf_counter()
    observer.begin_episode(scenario, authenticate_loaded())
    config = build_config(scenario)
    try:
        with enabled(True) as message_extractor:
            end_state = abides.run(config)
    finally:
        pass
    try:
        trace = extract_trace(end_state)
    finally:
        pass
    messages = message_extractor(end_state)
    validate_frames(trace, messages)
    trace.to_parquet(out)
    messages.to_parquet(out)
    trace_digest = sha256(out)
    wall = time.perf_counter() - t0
    events = {"wall": wall}
    return events
''')
        entry = types.ModuleType("_source_only_fixture")
        entry.__file__ = str(path)
        exec(compile(path.read_text(), str(path), "exec"), vars(entry))
        entry.simulate.__annotations__ = {"mode": str, "return": dict}
        before = entry.simulate
        driver = namespace["floor_driver"](entry)
        if (driver.__doc__ != before.__doc__ or driver.__annotations__ != before.__annotations__
                or driver.__defaults__ != before.__defaults__ or driver.__kwdefaults__ != before.__kwdefaults__
                or driver.__globals__ is not vars(entry)):
            raise ValueError("metadata differs")
        if driver.__doc__ is None:
            raise ValueError("driver lost docstring")
        return {"driver_constructed": True, "metadata_preserved": True, "non_marker_AST_equal": True,
                "simulator_imported": False, "simulate_called": False}


def check_parser():
    spec = importlib.util.spec_from_file_location("floor_source_controller", HERE / "controller.py")
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    labels = ["simulate_begin", "admission_begin", "config_begin", "simulation_begin", "simulation_end_projection_begin",
        "projection_end_validation_begin", "parquet_begin", "parquet_end_hash_begin", "sidecar_begin_after_original_wall", "simulate_exit"]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = []
        ticks = []
        for i, name in enumerate(("a.json", "b.json")):
            path = root / name
            path.write_text(json.dumps({"scenario_id": name, "seed": i + 1}))
            paths.append(str(path))
            ticks += [{"phase": label, "perf_counter": 10.0 + i + j / 20,
                "config_path": "/input/scenarios/" + name if j == 0 else None} for j,label in enumerate(labels)]
        row = {"schema": "t3-floor-ten-point-driver-v3", "ticks": ticks, "original_entry_started": 1.0,
            "trace_hook_used": False, "non_marker_ast_equal": True, "diagnostic_simulate_alias_installed_during_main": True,
            "original_simulate_alias_restored_before_post_auth": True,
            "rankable": False, "ten_points_per_episode": True, "probe_overhead_included": True,
            "line_numbers_differ_but_all_non_marker_AST_equal": True,
            "milestones": [{"phase": n, "perf_counter": t} for n,t in zip(
                ("real_entry_import_begin","real_entry_import_end","main_begin","main_end","post_auth_begin","post_auth_end"),
                (0.5,2.0,3.0,14.0,15.0,16.0))]}
        log = root / "stderr.txt"
        item = {"shape": "batch", "scenario_paths": paths}
        def run(value):
            log.write_text("T3_FLOOR_PHASES=" + json.dumps(value) + "\n")
            return controller.parse_phases(log,item)
        valid = run(row)
        if len(valid["actual_input_scenario_roster"]) != 2:
            raise ValueError("batch roster not bound")
        rejected = 0
        for field, new in (("phase", "wrong"), ("perf_counter", float("nan")), ("config_path", "/input/wrong.json")):
            changed = json.loads(json.dumps(row));changed["ticks"][0][field] = new
            try: run(changed)
            except ValueError: rejected += 1
            else: raise ValueError("bad parser case accepted")
        return {"valid_batch_roster_passed": True, "invalid_controls_rejected": rejected}


if __name__ == "__main__":
    result = {"schema": "t3-floor-pure-source-controls-v3", "driver": check_driver(), "parser": check_parser(),
        "native_or_simulator_loaded": False, "simulate_executed": False, "compilation_executed": False}
    (HERE / "SOURCE_DRIVER_CONTROLS_v3.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
