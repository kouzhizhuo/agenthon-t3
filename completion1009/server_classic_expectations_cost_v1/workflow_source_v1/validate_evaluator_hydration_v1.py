"""Compare actual host evaluator freeze; normalize only two explicit file paths."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse

HERE = Path(__file__).resolve().parent
CAP = 64 * 1024**2
ORIGINAL_PIN = {'bytes': 465, 'sha256': '0740d368bb4d0107598096d052ff0677120e56ed5963e4cc387b632634cd5c38'}
LOCAL = {'qfbench2-common': 'toolkit/common', 'qfbench2-track-simulation': 'track3'}
OLD_ROOT = '/home/runner/work/agenthon-t3/agenthon-t3/expectations-delivery-evaluation'


def require(value, message):
    if not value:raise ValueError(message)


def ordinary(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and all(not item.is_symlink() for item in (path, *path.parents)),
        'absolute ordinary evaluator path')
    return path


def pin(path):
    path = ordinary(path)
    require(path.is_file() and path.stat().st_size <= CAP, 'bounded ordinary evaluator freeze')
    data = path.read_bytes()
    require(len(data) == path.stat().st_size <= CAP, 'complete stable evaluator freeze')
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def parse(data, local_paths):
    require(type(data) is bytes and len(data) <= CAP, 'finite actual freeze bytes')
    rows = data.decode('utf-8').splitlines();result = {}
    require(rows and all(row and row == row.strip() for row in rows), 'nonempty exact freeze lines')
    for row in rows:
        plain = re.fullmatch(r'([a-zA-Z0-9._-]+)==([a-zA-Z0-9.!+_-]+)', row)
        if plain:
            name, version = plain.groups();name = re.sub(r'[-_.]+', '-', name).lower()
            require(name not in LOCAL, 'local toolkit must bind explicit file source')
            value = {'version': version}
        else:
            direct = re.fullmatch(r'([a-zA-Z0-9._-]+) @ (\S+)', row)
            require(direct is not None, 'only strict version or two explicit local package lines')
            name, url = direct.groups();name = re.sub(r'[-_.]+', '-', name).lower()
            require(name in LOCAL, 'no unexpected direct-reference package')
            parsed = urllib.parse.urlsplit(url)
            require(parsed.scheme == 'file' and parsed.netloc == '' and parsed.query == parsed.fragment == ''
                and not re.search(r'%(?![0-9a-fA-F]{2})', parsed.path), 'ordinary file URL')
            path = urllib.parse.unquote(parsed.path)
            require(path == str(local_paths[name]), 'each local toolkit path explicitly maps to current evaluation root')
            value = {'local_source': LOCAL[name]}
        require(name not in result, 'no duplicate normalized evaluator package')
        result[name] = value
    return result


def validate(actual_path, evaluation, original_path):
    evaluation = ordinary(evaluation)
    require(evaluation.is_dir() and pin(original_path) == ORIGINAL_PIN, 'genuine evaluation root and original saved freeze bytes')
    actual_paths = {name: ordinary(evaluation / relative) for name, relative in LOCAL.items()}
    require(all(path.is_dir() for path in actual_paths.values()), 'both exact local evaluator directories')
    original = parse(original_path.read_bytes(), {name: Path(OLD_ROOT) / relative for name, relative in LOCAL.items()})
    actual = parse(actual_path.read_bytes(), actual_paths)
    require(actual == original and len(actual) == 15, 'all15 normalized evaluator packages exact; no extra or missing versions')
    fetch = evaluation / 'FETCH_RECEIPT.json'
    require(pin(fetch)['bytes'] > 0, 'actual original public fetch receipt')
    receipt = json.loads(fetch.read_bytes())
    require(receipt.get('track_ref') == 'bffb57227f796f9fa769a23d01fc364bee14a119'
        and receipt.get('toolkit_ref') == 'v2.5.1' and receipt.get('public_units') == 71
        and receipt.get('runtime_reference_access') is False and len(receipt['references']) == 190,
        'actual original fetch source/ref roster')
    return {'schema': 't3-cost-exact-evaluator-hydration-v1', 'all_passed': True, 'original_freeze': ORIGINAL_PIN,
        'actual_freeze': pin(actual_path), 'package_count': len(actual), 'normalized_packages': actual,
        'local_package_paths': {name: str(path) for name, path in actual_paths.items()}, 'fetch_receipt': pin(fetch),
        'only_two_explicit_local_paths_normalized': True, 'extra_packages_allowed': False,
        'participant_imported': False, 'native_compiled': False, 'market_executed': False, 'pip_executed_by_validator': False}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--freeze', type=Path, required=True);parser.add_argument('--evaluation', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True);args = parser.parse_args()
    require(not args.out.exists() and ordinary(args.out).parent.is_dir(), 'fresh evaluator version receipt')
    result = validate(args.freeze, args.evaluation, HERE / 'bound_data/V2_EVALUATOR_FREEZE.txt')
    with args.out.open('x') as output:output.write(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print('ALL15 EVALUATOR PACKAGE VERSIONS AND TWO EXPLICIT LOCAL SOURCE PATHS VERIFIED')


if __name__ == '__main__':main()
