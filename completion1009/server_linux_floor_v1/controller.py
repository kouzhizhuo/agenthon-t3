"""Two fresh real-market import diagnostics; explicit execution, no score claim."""
import argparse
import copy
import importlib.util
import json
import math
from pathlib import Path
import platform
import signal
import sys
import uuid

HERE = Path(__file__).resolve().parent
UNIT = "t3-s001-price-time-priority"
PHASE_UNITS = [UNIT, "t3-as06-throughput-fast", "t3-mp01-stp-newest-baseline",
    "t3-ra01-fundamental-shock-mid", "t3-gbatch-hetero-mix"]
PHASE_MARKER = "T3_FLOOR_PHASE="


def load_screen(payload):
    sys.path.insert(0, str(payload / "control"))
    spec = importlib.util.spec_from_file_location("floor_frozen_screen", payload / "control/controller.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def parse_imports(path):
    """Retain actual row depth; cumulative descendants are never added."""
    phase, rows, markers = "wrapper_pre_entry", [], []
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if line.startswith(PHASE_MARKER):
            row = json.loads(line[len(PHASE_MARKER):])
            phase = row["phase"]
            markers.append({**row, "stderr_line": number})
        elif line.startswith("import time:") and "self [us]" not in line:
            parts = line[len("import time:"):].split("|", 2)
            if len(parts) == 3:
                try:
                    self_us, cumulative_us = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                raw = parts[2]
                rows.append({"module": raw.strip(), "self_us": self_us, "cumulative_us": cumulative_us,
                    "indent_spaces": len(raw) - len(raw.lstrip()), "phase": phase, "stderr_line": number})
    required = {"real_entry_import_begin", "real_entry_import_end", "cold_visibility_checked", "main_begin",
                "main_end", "post_auth_begin", "post_auth_end", "simulation_begin", "trace_output_begin", "message_output_begin"}
    if not required <= {row["phase"] for row in markers}:
        raise ValueError("diagnostic phase roster incomplete")
    return {"schema": "t3-floor-import-tree-v1", "rankable": False, "rows": rows, "phase_markers": markers,
        "cumulative_rows_summed": False, "note": "rows include instrumentation and nested children; not removable uninstrumented time"}

def parse_phases(path, item):
    values = [json.loads(line[len("T3_FLOOR_PHASES="):]) for line in path.read_text(errors="replace").splitlines()
              if line.startswith("T3_FLOOR_PHASES=")]
    if len(values) != 1:
        raise ValueError("one ten-point external driver receipt required")
    value = values[0]
    ticks = value.get("ticks", [])
    paths = sorted(Path(p) for p in item["scenario_paths"])
    episodes = len(paths)
    labels = ["simulate_begin", "admission_begin", "config_begin", "simulation_begin",
        "simulation_end_projection_begin", "projection_end_validation_begin", "parquet_begin",
        "parquet_end_hash_begin", "sidecar_begin_after_original_wall", "simulate_exit"]
    if (value.get("schema") != "t3-floor-ten-point-driver-v3" or value.get("trace_hook_used") is not False
            or value.get("non_marker_ast_equal") is not True or len(ticks) != 10 * episodes
            or value.get("diagnostic_simulate_alias_installed_during_main") is not True
            or value.get("original_simulate_alias_restored_before_post_auth") is not True
            or value.get("rankable") is not False or value.get("ten_points_per_episode") is not True
            or value.get("probe_overhead_included") is not True
            or value.get("line_numbers_differ_but_all_non_marker_AST_equal") is not True):
        raise ValueError("actual fixed per-episode driver points/AST proof differ")
    def finite(x):
        return type(x) in (float, int) and math.isfinite(x) and x > 0
    clocks = [t.get("perf_counter") for t in ticks]
    started = value.get("original_entry_started")
    if (not finite(started) or not all(finite(c) for c in clocks)
            or any(a > b for a, b in zip(clocks, clocks[1:])) or clocks[0] < started):
        raise ValueError("diagnostic ticks must be positive finite monotonic clocks")
    roster = []
    for ordinal, scenario_path in enumerate(paths):
        group = ticks[ordinal * 10:(ordinal + 1) * 10]
        expected_config = "/input/scenarios/" + scenario_path.name if item["shape"] == "batch" else "/input/scenario.json"
        if ([t.get("phase") for t in group] != labels or group[0].get("config_path") != expected_config
                or any(t.get("config_path") is not None for t in group[1:])):
            raise ValueError("actual phase labels/order/scenario input path differ")
        scenario = json.loads(scenario_path.read_text())
        roster.append({"config_path": expected_config, "scenario_id": str(scenario["scenario_id"]), "seed": int(scenario["seed"]),
            "intervals": [{"from": a["phase"], "to": b["phase"], "seconds": b["perf_counter"] - a["perf_counter"]}
                          for a,b in zip(group,group[1:])]})
    milestones = value.get("milestones", [])
    required = ["real_entry_import_begin", "real_entry_import_end", "main_begin", "main_end", "post_auth_begin", "post_auth_end"]
    if [m.get("phase") for m in milestones] != required:
        raise ValueError("post-auth complete milestone roster differs")
    mc = [m.get("perf_counter") for m in milestones]
    if not all(finite(c) for c in mc) or any(a > b for a,b in zip(mc,mc[1:])):
        raise ValueError("milestone clocks not finite monotonic")
    if not (mc[0] <= started <= mc[1] <= mc[2] <= clocks[0] <= clocks[-1] <= mc[3] <= mc[4] <= mc[5]):
        raise ValueError("entry/ticks/main/auth milestone nesting differs")
    value["actual_input_scenario_roster"] = roster
    return value

def diagnostic_contract(info, create_argv, diagnostic, importtime):
    """Bind inspect to raw create; Docker may omit --tmpfs from Mounts."""
    def options(flag):
        return [create_argv[i + 1] for i, value in enumerate(create_argv[:-1]) if value == flag]
    images = [i for i, value in enumerate(create_argv) if value.startswith("sha256:")]
    if (len(images) != 1 or info.get("Image") != create_argv[images[0]]
            or options("--entrypoint") != ["/usr/local/bin/python"]
            or options("--tmpfs") != ["/tmp:rw,noexec,nosuid,nodev,size=64m"]):
        raise ValueError("raw diagnostic create image/entrypoint/tmpfs differs")
    expected = {}
    for specification in options("--mount"):
        fields = specification.split(",")
        values = dict(part.split("=", 1) for part in fields if "=" in part)
        if (len(values) != 3 or set(values) != {"type", "src", "dst"}
                or values["type"] != "bind" or values["dst"] in expected
                or any(part != "readonly" for part in fields if "=" not in part)
                or len(fields) != 3 + fields.count("readonly") or fields.count("readonly") > 1):
            raise ValueError("raw diagnostic exact bind declaration differs")
        expected[values["dst"]] = (str(Path(values["src"]).resolve()), "readonly" not in fields)
    if (set(expected) != {"/input", "/output", "/diagnostic"}
            or expected["/input"][1] is not False or expected["/output"][1] is not True
            or expected["/diagnostic"] != (str(diagnostic), False)):
        raise ValueError("raw diagnostic exact source/permissions differ")
    mounts = info.get("Mounts", [])
    binds = [row for row in mounts if row.get("Destination") != "/tmp"]
    temporary = [row for row in mounts if row.get("Destination") == "/tmp"]
    if (len(binds) != 3 or {row.get("Destination") for row in binds} != set(expected)
            or any(row.get("Type") != "bind" or not isinstance(row.get("Source"), str)
                   or (str(Path(row["Source"]).resolve()), row.get("RW")) != expected[row["Destination"]]
                   or type(row.get("RW")) is not bool for row in binds)
            or len(temporary) > 1 or any(row.get("Type") != "tmpfs" for row in temporary)):
        raise ValueError("diagnostic exact three bind mounts or optional tmpfs enumeration differ")
    host, config = info["HostConfig"], info["Config"]
    if host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,nodev,size=64m"}:
        raise ValueError("exact isolated tmp64MiB mount/options required")
    limits = host.get("Ulimits", [])
    expected_limits = {"nofile": (1024, 1024), "nproc": (256, 256), "fsize": (268435456, 268435456)}
    if (len(limits) != 3 or {row.get("Name") for row in limits} != set(expected_limits)
            or any((row.get("Soft"), row.get("Hard")) != expected_limits[row["Name"]] for row in limits)):
        raise ValueError("actual diagnostic ulimits differ")
    if (host.get("NanoCpus") != 4 * 10 ** 9 or host.get("Memory") != 16 * 1024 ** 3
            or host.get("MemorySwap") != 16 * 1024 ** 3 or host.get("PidsLimit") != 256
            or host.get("ReadonlyRootfs") is not True or host.get("NetworkMode") != "none"
            or host.get("Runtime") != "runc" or host.get("Privileged") is not False
            or host.get("CapDrop") != ["ALL"] or host.get("CapAdd") not in (None, [])
            or host.get("SecurityOpt") != ["no-new-privileges"]
            or (host.get("OomKillDisable") is not None and host.get("OomKillDisable") is not False)
            or config.get("User") != "65534:65534" or config.get("WorkingDir") != "/output"):
        raise ValueError("actual diagnostic resource/security configuration differs")
    if (config.get("Entrypoint") != ["/usr/local/bin/python"]
            or config.get("Cmd") != create_argv[images[0] + 1:]
            or config.get("Cmd", [])[:2] != ["-B", "/diagnostic/entry_probe.py"]
            or (importtime and "PYTHONPROFILEIMPORTTIME=1" not in config.get("Env", []))
            or (not importtime and any(e.startswith("PYTHONPROFILEIMPORTTIME=") for e in config.get("Env", [])))):
        raise ValueError("actual diagnostic profile environment/argv differs")
    normalized_host = copy.deepcopy(host)
    # Docker's created null may settle to false; both keep the OOM killer enabled.
    normalized_host["OomKillDisable"] = False
    return {"HostConfig": normalized_host, "Config": copy.deepcopy(config),
            "binds": sorted((copy.deepcopy(row) for row in binds), key=lambda row: row["Destination"])}


def command_class(screen, diagnostic, importtime=True):
    original = screen.StrictCommands
    raw = original.__mro__[1]
    linux = screen.linux
    class FloorCommands(original):
        def call(self, arguments, label, seconds=30, cleanup=False):
            if arguments and arguments[0] == "create":
                profiling = ["--env", "PYTHONPROFILEIMPORTTIME=1"] if importtime else []
                arguments = [arguments[0], *profiling,
                    "--entrypoint", "/usr/local/bin/python", "--mount",
                    "type=bind,src=" + str(diagnostic) + ",dst=/diagnostic,readonly", *arguments[1:]]
                positions = [i for i, value in enumerate(arguments) if value.startswith("sha256:")]
                if len(positions) != 1:
                    raise ValueError("one immutable image ID in diagnostic create required")
                index = positions[0]
                arguments[index + 1:index + 1] = ["-B", "/diagnostic/entry_probe.py"]
            return super().call(arguments, label, seconds, cleanup)

        def inspect(self, name, cleanup=False, seconds=30):
            info, command = raw.inspect(self, name, cleanup, seconds)
            if info is not None and not cleanup:
                creates = [row for row in self.rows if row.get("succeeded") is True
                           and row.get("argv", [])[1:2] == ["create"]]
                if len(creates) != 1:
                    raise ValueError("one successful raw diagnostic create required")
                current = diagnostic_contract(info, creates[0]["argv"], diagnostic, importtime)
                if hasattr(self, "_floor_created_contract") and current != self._floor_created_contract:
                    raise ValueError("diagnostic settled configuration differs from prestart contract")
                self._floor_created_contract = current
            return info, command
    linux.DockerCommands = FloorCommands
    return FloorCommands


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True, help="exact observer-startup materialized payload")
    parser.add_argument("--images", type=Path, required=True, help="same-run IMAGES.json; image IDs must exist locally")
    parser.add_argument("--build-evidence", type=Path, required=True)
    parser.add_argument("--diagnostic-source", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--gate-kit", type=Path, required=True)
    parser.add_argument("--gate-python", default=sys.executable)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--mode", choices=("importtime-s001", "phases-five"), default="phases-five")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    selected = [UNIT] if args.mode == "importtime-s001" else PHASE_UNITS
    plan = {"schema": "t3-linux-floor-plan-v2", "rankable": False, "units": selected, "runs": 2 * len(selected),
        "mode": args.mode, "trace_hook_used": args.mode == "importtime-s001",
        "source_only_preparation": not args.execute, "build_performed_by_controller": False,
        "immutable_images_required_local": True, "profile_results_used_for_selection": False,
        "optional_default_latency_pair": "separate explicit protocol only if initial SciPy branch remains unresolved"}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise ValueError("diagnostic execution requires Linux amd64 host")
    if args.evidence.exists():
        raise ValueError("new diagnostic evidence directory required")
    args.evidence.mkdir(parents=True)
    payload, diagnostic = args.payload.resolve(), args.diagnostic_source.resolve()
    screen = load_screen(payload)
    public, linux = screen.public, screen.linux
    prep = public.read_json(diagnostic / "PREPARATION.json")
    if (screen.sha(payload / "control/entry_probe.py") != prep["base_probe_sha256"]
            or screen.sha(diagnostic / "entry_probe.py") != prep["probe_sha256"]
            or screen.sha(diagnostic / "common.py") != prep["common_sha256"]):
        raise ValueError("source-copy marker preparation not bound to exact frozen probe")
    images = public.read_json(args.images.resolve())
    if set(images) != set(screen.ARMS):
        raise ValueError("exact observer parent/lazy two-arm image roster required")
    args.timeout, args.log_cap_bytes, args.owner = 300, 4 * 1024 ** 2, uuid.uuid4().hex
    # Inspect only: never pull a retired runner's image ID or silently rebuild.
    for name in screen.ARMS:
        current = screen.inspect_image(args, images[name]["id"], args.evidence / "image-inspect" / name)
        if current["inspection"]["Config"] != images[name]["inspection"]["Config"]:
            raise ValueError("existing image config differs from bound image receipt")
    command_class(screen, diagnostic, args.mode == "importtime-s001")
    args.reference_root, args.gate_kit = args.reference_root.resolve(), args.gate_kit.resolve()
    signal.signal(signal.SIGINT, linux.cancellation)
    signal.signal(signal.SIGTERM, linux.cancellation)
    roster = public.collect_plan(args.reference_root, selected)
    original_evidence = args.evidence
    # Existing run_one also requires exact build-generated receipt files.
    args.evidence = args.build_evidence.resolve()
    rows, pairs, failure = [], [], None
    try:
        index = 0
        for item in roster["units"]:
            paired = []
            for name in screen.ARMS:
                folder = original_evidence / "runs" / item["unit"] / name
                row = screen.run_one(args, images, name, item, folder, args.owner, "floor-%d" % index)
                index += 1
                rows.append(row); paired.append(row)
                if not row["passed"]:
                    raise ValueError("real original output/resource/ABI/source/official gate failed")
                log = Path(row["execution"]["attach"]["stderr"]["path"])
                tree = parse_imports(log) if args.mode == "importtime-s001" else parse_phases(log, item)
                screen.write(folder / "PHASE_EVIDENCE.json", tree)
                row["phase_evidence"] = str(folder / "PHASE_EVIDENCE.json")
            pair = screen.pair_outputs(Path(paired[1]["output"]), Path(paired[0]["output"]), item)
            pairs.append({"unit": item["unit"], **pair})
            if not pair["passed"]:
                raise ValueError("diagnostic exact cross-arm frames/dtypes/bytes/sidecars differ")
    except BaseException as error:
        failure = type(error).__name__ + ": " + str(error)
        raise
    finally:
        args.evidence = original_evidence
        screen.write(original_evidence / "SUMMARY.json", {**plan, "rows": rows, "failure": failure,
            "passed": failure is None and len(rows) == plan["runs"] and all(r["passed"] for r in rows),
            "source_copy": prep, "reference_plan": roster,
            "cross_arm_pairs": pairs,
            "phase_note": "O(10) driver timestamps with unprofiled actual execution; diagnostic overhead included" if args.mode == "phases-five" else "traced importtime prototype includes global trace overhead",
            "floor_bound": "Measured component attribution only; no proven unavoidable residual or official throughput bound"})


if __name__ == "__main__":
    main()
