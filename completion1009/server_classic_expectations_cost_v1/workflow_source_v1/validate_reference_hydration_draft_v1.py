"""Validate complete official input/reference bytes after frozen public fetch."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
PLAN_PIN = {'bytes': 103740, 'sha256': '4ed54fc6ef706b614f221a7af6b3f09a7d21c490d54260e2d75fe2a31607ca68'}
CAP = 64 * 1024**2


def require(value, message):
    if not value:raise ValueError(message)


def pin(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= CAP, 'bounded ordinary reference/input')
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024**2), b''):
            count += len(data);require(count <= CAP, 'reference stream hard bound');digest.update(data)
    require(count == path.stat().st_size, 'complete stable reference/input byte count')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def validate(root, original):
    require(pin(original) == PLAN_PIN and root.is_absolute() and root.is_dir()
        and all(not item.is_symlink() for item in (root, *root.parents)), 'exact original full71 plan and ordinary root')
    plan = json.loads(original.read_bytes())
    require(len(plan['units']) == plan['all_roster_units'] == plan['selected_units'] == 71
        and plan['reference_frame_count'] == 190, 'complete organizer full71 reference authority')
    units = {item['unit']: item for item in plan['units']}
    entries = list(root.iterdir())
    require(len(units) == 71 and all(path.is_dir() and not path.is_symlink() for path in entries)
        and {path.name for path in entries} == set(units), 'only the71 ordinary official unit directories at reference root')
    scenarios, references, rows = 0, 0, []
    for unit, item in units.items():
        folder = root / unit
        require(not folder.is_symlink(), 'ordinary official unit directory')
        for group in ('input_sha256', 'reference_sha256'):
            for relative, digest in item[group].items():
                path = PurePosixPath(relative)
                require(not path.is_absolute() and '..' not in path.parts and path.as_posix() == relative, 'safe original reference path')
                target = folder / relative
                require(all(not parent.is_symlink() for parent in (target, *target.parents)), 'no reference path symlinks')
                actual = pin(target);require(actual['sha256'] == digest, 'full original reference/input hash equality')
                if group == 'reference_sha256':
                    references += 1
                    with target.open('rb') as source:require(source.read(4) == b'PAR1', 'real LFS Parquet byte header')
                else:scenarios += 1
                rows.append({'unit': unit, 'group': group, 'path': relative, **actual})
    require(scenarios == 95 and references == 190, 'exact95market190reference hashes')
    return {'schema': 't3-cost-exact-reference-hydration-v1', 'original_plan': PLAN_PIN, 'unit_count': 71,
        'scenario_count': scenarios, 'reference_count': references, 'files': rows,
        'participant_imported': False, 'native_compiled': False, 'market_executed': False, 'reference_mounted_into_runtime': False}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--references', type=Path, required=True);parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'fresh reference receipt')
    result = validate(args.references, HERE / 'bound_data/ORIGINAL_REFERENCE_PLAN.json')
    with args.out.open('x') as output:output.write(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('FULL71/95INPUT/190REFERENCE COMPLETE SHA VERIFIED')


if __name__ == '__main__':main()
