"""Linux-only host worker reuses each frozen controller in a fresh process."""
import argparse
import json
from pathlib import Path
import platform
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("build", "controls", "one", "metadata"))
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--gate-kit", type=Path, required=True)
    parser.add_argument("--gate-python", required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise ValueError("real Linux amd64 only")
    args.payload = args.payload.resolve()
    sys.path.insert(0, str(args.payload / "control"))
    sys.path.insert(0, str(args.payload / "host"))
    import controller as ctl
    import common
    args.evidence = args.evidence.resolve()
    args.docker = "docker"
    args.log_cap_bytes = 16 * 1024 ** 2
    args.timeout = 300
    plan = common.verify_payload(args.payload)
    if args.stage == "build":
        ctl.build(args, plan)
        result = common.inventory(args.evidence / "installed")
    else:
        request = json.loads(args.request.read_bytes())
        ready = json.loads((args.evidence / "BUILD_READY.json").read_bytes())
        image = ready["image_id"]
        if args.stage == "metadata":
            result = ctl.linux.image_metadata(args, image, Path(request["folder"]))
        elif args.stage == "one":
            args.owner = request["owner"]
            result = ctl.run_one(args, image, "light_dynamic", request["item"],
                Path(request["folder"]), request["suffix"])
            if not result["passed"]:
                raise ValueError("actual direct run failed")
        else:
            args.owner = request["owner"]
            roster = ctl.public.collect_plan(args.reference_root, list(common.SINGLES) + [common.BATCH])
            admissions = []
            for item in roster["units"]:
                for original_path in item["scenario_paths"]:
                    original = Path(original_path)
                    admissions.append({"unit": item["unit"] + ("/" + original.stem if item["shape"] == "batch" else ""),
                        "scenario_sha256": common.sha(original), "scenario": ctl.public.read_json(original)})
            if len(admissions) != 9:
                raise ValueError("nine source admission inputs required")
            bundle = {"proof_command": "cold-native-projection-buffers-six-children-and-fixtures-v1",
                "scenario": ctl.public.read_json(args.payload / "control/control_scenario.json"),
                "admission_scenarios": admissions}
            config = args.evidence / "direct-control-input.json"
            common.write(config, bundle)
            args.timeout = 3600
            execution, output = ctl.linux.run_container(args, image, "controls",
                {"shape": "single", "scenario_paths": [str(config)]}, args.evidence / "controls",
                args.owner, "controls")
            if not execution["succeeded"]:
                raise ValueError("actual original full control container failed")
            result = {"execution": execution, **ctl.validate_controls(output / "controls", plan, bundle)}
    common.write(args.result, result)


if __name__ == "__main__":
    main()
