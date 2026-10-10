"""Retain complete or partial startup bytes even if the diagnostic fails."""
import argparse
from pathlib import Path
import shutil

from common import HERE, inventory, read, require, write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    args = parser.parse_args()
    require(not args.artifact.exists(), 'fresh complete/partial startup artifact required')
    args.artifact.mkdir(parents=True)
    if args.evidence.is_dir():
        # Check source/evidence paths before copytree; no credential config or
        # filesystem link is followed into a diagnostic artifact.
        inventory(args.evidence)
        shutil.copytree(args.evidence, args.artifact / 'evidence', ignore=shutil.ignore_patterns(
            'anonymous-docker-config', '._*', '__MACOSX', '__pycache__'))
    pins = read(HERE / 'SOURCE_PINS.json')
    for name in list(pins['files']) + ['SOURCE_PINS.json']:
        destination = args.artifact / 'source' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / name, destination)
    write(args.artifact / 'ARTIFACT.json', {'schema': 't3-fixed-stock-startup-artifact-v2',
        'files': inventory(args.artifact), 'complete_or_partial_bytes_retained': True,
        'market_executed': False, 'participant_imported': False, 'native_compiled': False,
        'ordinary_performance_measured': False, 'rankable': False, 'official_submission': False,
        'startup_pins_updated': False, 'FIFO_domain_certified': False})


if __name__ == '__main__':
    main()
