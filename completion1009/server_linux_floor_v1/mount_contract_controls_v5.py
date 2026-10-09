"""Pure-source Docker representation/adversarial fixtures; never run a market."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


def load(path):
    spec = importlib.util.spec_from_file_location("floor_mount_fixture_controller", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    controller = load(HERE / "controller.py")
    diagnostic = Path("/fixture/diagnostic")
    image = "sha256:" + "a" * 64
    create = ["docker", "create", "--name", "fixture", "--entrypoint", "/usr/local/bin/python",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--mount", "type=bind,src=/fixture/input,dst=/input,readonly",
        "--mount", "type=bind,src=/fixture/output,dst=/output",
        "--mount", "type=bind,src=/fixture/diagnostic,dst=/diagnostic,readonly",
        image, "-B", "/diagnostic/entry_probe.py", "simulate", "--config", "/input/scenario.json",
        "--out", "/output/trace.parquet", "--mode", "optimized"]
    info = {"Image": image, "State": {"Status": "created"}, "HostConfig": {
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=64m"},
        "Ulimits": [{"Name": name, "Soft": value, "Hard": value}
                   for name, value in (("nofile", 1024), ("nproc", 256), ("fsize", 268435456))],
        "NanoCpus": 4000000000, "Memory": 17179869184, "MemorySwap": 17179869184,
        "PidsLimit": 256, "ReadonlyRootfs": True, "NetworkMode": "none", "Runtime": "runc",
        "Privileged": False, "CapDrop": ["ALL"], "CapAdd": None,
        "SecurityOpt": ["no-new-privileges"], "OomKillDisable": None},
        "Config": {"Entrypoint": ["/usr/local/bin/python"], "Cmd": create[create.index(image) + 1:],
            "Env": ["PYTHONDONTWRITEBYTECODE=1"], "User": "65534:65534", "WorkingDir": "/output"},
        "Mounts": [{"Type": "bind", "Source": "/fixture" + destination, "Destination": destination,
                    "RW": destination == "/output", "Mode": "", "Propagation": "rprivate"}
                   for destination in ("/input", "/output", "/diagnostic")]}
    rows = []
    def accepted(name, value, argv=None, profiling=False):
        controller.diagnostic_contract(value, argv or create, diagnostic, profiling)
        rows.append({"name": name, "passed": True, "expected": "accept"})
    def rejected(name, change=None, argv=None):
        value = copy.deepcopy(info)
        if change is not None:
            change(value)
        try:
            controller.diagnostic_contract(value, argv or create, diagnostic, False)
        except (ValueError, KeyError, TypeError):
            rows.append({"name": name, "passed": True, "expected": "reject"})
        else:
            raise AssertionError("malicious fixture accepted: " + name)
    accepted("created_no_top_level_tmpfs", info)
    settled = copy.deepcopy(info)
    settled["State"]["Status"] = "exited"
    settled["HostConfig"]["OomKillDisable"] = False
    settled["Mounts"].reverse()
    accepted("exited_no_top_level_tmpfs_reversed_binds_oom_false", settled)
    base = controller.diagnostic_contract(info, create, diagnostic, False)
    assert controller.diagnostic_contract(settled, create, diagnostic, False) == base
    rows.append({"name": "created_settled_full_configuration_normalization", "passed": True, "expected": "equal"})
    enumerated = copy.deepcopy(settled)
    enumerated["Mounts"].append({"Type": "tmpfs", "Destination": "/tmp", "RW": True})
    accepted("exited_optional_top_level_tmpfs", enumerated)
    assert controller.diagnostic_contract(enumerated, create, diagnostic, False) == base
    profiled = copy.deepcopy(info)
    profiled["Config"]["Env"].append("PYTHONPROFILEIMPORTTIME=1")
    accepted("explicit_profile_mode", profiled, profiling=True)
    for key, value in (("Tmpfs", {}), ("Tmpfs", {"/tmp": "rw,noexec,nosuid,nodev,size=640m"}),
        ("Tmpfs", {"/tmp": "rw,noexec,nosuid,nodev,size=64m", "/extra": "size=1m"}),
        ("OomKillDisable", True), ("OomKillDisable", 0), ("NanoCpus", 5000000000),
        ("Memory", 8589934592), ("MemorySwap", 34359738368), ("PidsLimit", 512),
        ("ReadonlyRootfs", False), ("NetworkMode", "bridge"), ("Runtime", "other"),
        ("Privileged", True), ("CapAdd", ["SYS_ADMIN"]), ("CapDrop", []),
        ("SecurityOpt", []), ("Ulimits", info["HostConfig"]["Ulimits"][:2])):
        rejected("host_" + key + "_" + str(len(rows)), lambda x, k=key, v=value: x["HostConfig"].__setitem__(k, v))
    for destination in ("/input", "/output", "/diagnostic"):
        def mount(x):
            return next(row for row in x["Mounts"] if row["Destination"] == destination)
        rejected(destination + "_foreign_source", lambda x: mount(x).__setitem__("Source", "/foreign"))
        rejected(destination + "_wrong_rw", lambda x: mount(x).__setitem__("RW", not mount(x)["RW"]))
        rejected(destination + "_integer_rw", lambda x: mount(x).__setitem__("RW", int(mount(x)["RW"])))
        rejected(destination + "_wrong_type", lambda x: mount(x).__setitem__("Type", "volume"))
    rejected("extra_bind", lambda x: x["Mounts"].append({"Type": "bind", "Destination": "/extra"}))
    rejected("duplicate_bind", lambda x: x["Mounts"].append(copy.deepcopy(x["Mounts"][0])))
    rejected("tmp_bind", lambda x: x["Mounts"].append({"Type": "bind", "Destination": "/tmp"}))
    rejected("duplicate_optional_tmp", lambda x: x["Mounts"].extend([
        {"Type": "tmpfs", "Destination": "/tmp"}, {"Type": "tmpfs", "Destination": "/tmp"}]))
    rejected("entrypoint_changed", lambda x: x["Config"].__setitem__("Entrypoint", ["/bin/sh"]))
    rejected("full_command_changed", lambda x: x["Config"]["Cmd"].append("--foreign"))
    rejected("profile_enabled_in_phases", lambda x: x["Config"]["Env"].append("PYTHONPROFILEIMPORTTIME=1"))
    rejected("wrong_user", lambda x: x["Config"].__setitem__("User", "0"))
    rejected("wrong_workdir", lambda x: x["Config"].__setitem__("WorkingDir", "/tmp"))
    rejected("wrong_image", lambda x: x.__setitem__("Image", "sha256:" + "b" * 64))
    wrong = list(create)
    wrong[wrong.index("--tmpfs") + 1] = "/tmp:rw,size=64m"
    rejected("raw_create_tmpfs_changed", argv=wrong)
    wrong = list(create)
    wrong.extend(["--mount", "type=bind,src=/extra,dst=/extra"])
    rejected("raw_create_extra_mount", argv=wrong)
    wrong = [value.replace("dst=/diagnostic,readonly", "dst=/diagnostic") for value in create]
    rejected("raw_create_diagnostic_writable", argv=wrong)

    # Real command_class runs against a fake base; no Docker/process/participant import.
    class Raw:
        def inspect(self, name, cleanup=False, seconds=30):
            return self.fixture, {"fixture_only": True}
    class Original(Raw):
        def call(self, arguments, label, seconds=30, cleanup=False):
            row = {"argv": ["docker"] + arguments, "succeeded": True}
            self.rows.append(row)
            return row
    screen = SimpleNamespace(StrictCommands=Original, linux=SimpleNamespace())
    cls = controller.command_class(screen, diagnostic, False)
    instance = cls()
    instance.rows = [{"argv": create, "succeeded": True}]
    instance.fixture = copy.deepcopy(info)
    instance.inspect("fixture")
    instance.fixture = copy.deepcopy(enumerated)
    instance.inspect("fixture")
    rows.append({"name": "actual_commands_prestart_then_settled_compatible", "passed": True, "expected": "accept"})
    for name, change in (("settled_other_host_field", lambda x: x["HostConfig"].__setitem__("RestartPolicy", {"Name": "always"})),
        ("settled_full_config_extra", lambda x: x["Config"].__setitem__("Unexpected", True)),
        ("settled_bind_propagation", lambda x: x["Mounts"][0].__setitem__("Propagation", "rshared"))):
        instance.fixture = copy.deepcopy(settled)
        change(instance.fixture)
        try:
            instance.inspect("fixture")
        except ValueError:
            rows.append({"name": name, "passed": True, "expected": "reject"})
        else:
            raise AssertionError("settled fixture accepted: " + name)
    instance.fixture = {}
    instance.inspect("fixture", cleanup=True)
    rows.append({"name": "cleanup_contract_skips_preserve_owned_cleanup", "passed": True, "expected": "accept"})
    instance.fixture = copy.deepcopy(info)
    instance.rows.append({"argv": create, "succeeded": True})
    try:
        instance.inspect("fixture")
    except ValueError:
        rows.append({"name": "duplicate_successful_raw_create", "passed": True, "expected": "reject"})
    else:
        raise AssertionError("duplicate create accepted")
    result = {"schema": "t3-floor-mount-contract-controls-v5", "passed": True, "source_only": True,
        "controller_sha256": hashlib.sha256((HERE / "controller.py").read_bytes()).hexdigest(),
        "fixtures": rows, "fixture_count": len(rows), "market_execution": False, "docker_execution": False,
        "participant_or_native_import": False, "compiler_execution": False}
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: value for k, value in result.items() if k != "fixtures"}, sort_keys=True))


if __name__ == "__main__":
    main()
