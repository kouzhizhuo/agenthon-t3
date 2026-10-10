"""Official exact-option CLI; internal argparse abbreviations cannot escape."""
import argparse
from pathlib import Path
import runpy
import sys

SOURCE = Path('/opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1/production_cli.py')


def public_options(options):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest='verb', required=True)
    single = sub.add_parser('simulate', allow_abbrev=False)
    single.add_argument('--config', required=True)
    single.add_argument('--out', required=True)
    batch = sub.add_parser('simulate-batch', allow_abbrev=False)
    batch.add_argument('--batch-dir', required=True)
    batch.add_argument('--out-dir', required=True)
    parsed = parser.parse_args(options)
    if parsed.verb == 'simulate':
        return ['simulate', '--config', parsed.config, '--out', parsed.out]
    return ['simulate-batch', '--batch-dir', parsed.batch_dir, '--out-dir', parsed.out_dir]


def main():
    options = public_options(sys.argv[1:])
    sys.path.insert(0, str(SOURCE.parent))
    sys.argv = [str(SOURCE), *options, '--arm', 'light_dynamic']
    runpy.run_path(str(SOURCE), run_name='__main__')


if __name__ == '__main__':
    main()
