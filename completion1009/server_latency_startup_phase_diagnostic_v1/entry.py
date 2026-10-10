"""Untimed marker-only clone of the frozen actual CLI."""
import argparse
from pathlib import Path
import sys
from phase_entry import main
ROOT = Path("/opt/light-typed-noise-latency-market-controls-v1")
SOURCE = ROOT / "completion1009/candidates/light_typed_noise_latency_market_v1_2/production_cli.py"

def entry():
    parser = argparse.ArgumentParser()
    parser.add_argument("verb", choices=("simulate", "simulate-batch"))
    parser.add_argument("--config"); parser.add_argument("--out")
    parser.add_argument("--batch-dir"); parser.add_argument("--out-dir")
    parser.add_argument("--mode", choices=("light_canonical", "light_dynamic"), required=True)
    args = parser.parse_args()
    if args.verb == "simulate":
        if args.config != "/input/scenario.json" or args.out != "/output/trace.parquet" or args.batch_dir or args.out_dir:
            raise ValueError("fixed single paths required")
        options = ["--config", args.config, "--out", args.out]
    else:
        if args.batch_dir != "/input/scenarios" or args.out_dir != "/output" or args.config or args.out:
            raise ValueError("fixed batch paths required")
        options = ["--batch-dir", args.batch_dir, "--out-dir", args.out_dir]
    sys.path.insert(0, str(SOURCE.parent))
    main(SOURCE, [str(SOURCE), args.verb, *options, "--arm", args.mode], args.mode)

if __name__ == "__main__": entry()
