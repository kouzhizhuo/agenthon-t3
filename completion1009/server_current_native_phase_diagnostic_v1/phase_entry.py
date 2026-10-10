"""Finite untimed phases: the actual CLI simulate AST plus constant clock markers."""
import time
DRIVER_STARTED = time.perf_counter()
import ast
import copy
import hashlib
import importlib.util
import json
import sys

TICKS = []
MILESTONES = []
CURRENT_CONFIG = None


def mark(label, config_path=None):
    global CURRENT_CONFIG
    if config_path is not None:
        CURRENT_CONFIG = str(config_path)
    TICKS.append({"phase": label, "perf_counter": time.perf_counter(), "config_path": CURRENT_CONFIG})


def milestone(label):
    MILESTONES.append({"phase": label, "perf_counter": time.perf_counter()})


def instrument(namespace, source, source_path, arm):
    tree = ast.parse(source)
    original = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "simulate")
    target = copy.deepcopy(original)
    labels = []

    def clock(label, config=False):
        labels.append(label)
        args = [ast.Constant(label)]
        if config:
            args.append(ast.Name(id="config_path", ctx=ast.Load()))
        return ast.Expr(value=ast.Call(func=ast.Name(id="_t3_phase_mark", ctx=ast.Load()), args=args, keywords=[]))

    class Insert(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            self.generic_visit(node)
            node.body.insert(0, clock("simulate_enter", config=True))
            return node

        def visit_Assign(self, node):
            self.generic_visit(node)
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            labels_by_name = {"runtime": "runtime_setup_enter", "scenario": "scenario_read_enter", "authenticated": "source_auth_enter",
                              "admitted_episode": "observer_begin_enter", "config": "build_config_enter",
                              "summary_writer": "summary_override_enter", "engine": "native_load_prepare_enter", "trace": "trace_projection_enter",
                              "messages": "message_projection_enter", "out": "output_prepare_enter",
                              "trace_digest": "hash_enter", "result": "hash_and_sidecar_prepare_enter"}
            if names == ["end_state"]:
                return [clock("simulation_enter"), node, clock("simulation_exit")]
            if len(names) == 1 and names[0] in labels_by_name:
                return [clock(labels_by_name[names[0]]), node]
            return node

        def visit_Expr(self, node):
            self.generic_visit(node)
            prefix = ast.unparse(node)
            labels_by_prefix = {"verify_sources(": "verify_sources_enter", "verify_runtime(": "verify_runtime_enter", "authenticate_runtime(": "noise_auth_enter", "authenticate_latency_runtime(": "latency_auth_enter", "validate_scenario(": "scenario_validate_enter",
                                "observer.begin_episode(": "source_auth_and_observer_enter",
                                "reset_abides_counters(": "counters_reset_enter",
                                "validate_frames(": "frame_validation_enter",
                                "validate_admitted_columns(": "column_validation_enter",
                                "observer.finish_episode(": "observer_finish_enter",
                                "trace.to_parquet(": "trace_write_enter",
                                "messages.to_parquet(": "message_write_enter",
                                "write_outputs(": "joint_output_write_enter",
                                "(out.parent / 'events.json').write_text(": "sidecar_write_enter"}
            for text, label in labels_by_prefix.items():
                if prefix.startswith(text):
                    return [clock(label), node, clock(label + "_exit")]
            return node

        def visit_Return(self, node):
            return [clock("simulate_exit"), node]

    transformed = Insert().visit(target)
    ast.fix_missing_locations(transformed)

    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "_t3_phase_mark"):
                return None
            return self.generic_visit(node)

    stripped = Remove().visit(copy.deepcopy(transformed))
    if ast.dump(stripped, include_attributes=False) != ast.dump(original, include_attributes=False):
        raise ValueError("diagnostic non-marker business AST differs")
    required = {"simulate_enter", "scenario_read_enter", "scenario_validate_enter", "build_config_enter",
                "simulation_enter", "simulation_exit", "trace_projection_enter", "message_projection_enter",
                "observer_finish_enter", "output_prepare_enter", "hash_and_sidecar_prepare_enter", "sidecar_write_enter", "simulate_exit"}
    if not required <= set(labels):
        raise ValueError("fixed actual simulate phase locations absent")
    module = ast.Module(body=[transformed], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace["_t3_phase_mark"] = mark
    exec(compile(module, str(source_path), "exec"), namespace)
    return {"non_marker_AST_equal": True, "static_labels": labels,
            "original_simulate_AST_sha256": hashlib.sha256(ast.dump(original, include_attributes=False).encode()).hexdigest()}


def main(source_path, official_argv, arm):
    source = source_path.read_bytes()
    milestone("actual_entry_import_enter")
    spec = importlib.util.spec_from_file_location("production_cli", source_path)
    actual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(actual)
    milestone("actual_entry_import_exit")
    original, old_argv = actual.simulate, list(sys.argv)
    prepared = instrument(vars(actual), source, source_path, arm)
    failure = None
    try:
        sys.argv = official_argv
        milestone("actual_main_enter")
        actual.main()
        milestone("actual_main_exit")
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        actual.simulate = original
        actual.__dict__.pop("_t3_phase_mark", None)
        sys.argv = old_argv
        milestone("diagnostic_exit")
        report = {"schema": "t3-current-native-untimed-production-phases-v1", "arm": arm,
                  "official_argv": official_argv, "driver_started": DRIVER_STARTED,
                  "original_entry_started": actual.ENTRY_STARTED, "ticks": TICKS, "milestones": MILESTONES,
                  **prepared, "simulate_alias_restored": actual.simulate is original,
                  "phase_global_removed": "_t3_phase_mark" not in vars(actual),
                  "source_sha256": hashlib.sha256(source).hexdigest(), "failure": failure,
                  "trace_hook_used": False, "diagnostic_overhead_included": True,
                  "timing_included": False, "rankable": False}
        print("T3_CONTINUOUS_NATIVE_UNTIMED_PHASES=" + json.dumps(report, sort_keys=True, allow_nan=False))
