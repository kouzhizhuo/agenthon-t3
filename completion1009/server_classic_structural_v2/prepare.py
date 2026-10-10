"""Source-only overlay of two reviewed candidates onto the exact frozen parent."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

HERE = Path(__file__).resolve().parent
COMPLETION = HERE.parent
ARMS = {'expectations': 'classic_build_expectations_v1', 'price_index': 'classic_price_index_v2'}
HARNESS = ('production_entry.py', 'controls_entry.py', 'diagnostic_entry.py', 'construction.py', 'Dockerfile')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if any(part.startswith('._') or part in ('__pycache__', '__MACOSX') for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError('ordinary source only')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return result


def safe(name):
    value = PurePosixPath(name)
    if not name or value.is_absolute() or value.as_posix() != name or '\\' in name or '\x00' in name or any(part in ('', '.', '..', '__MACOSX', '__pycache__') or part.startswith('._') for part in name.split('/')):
        raise ValueError('unsafe archive member')
    return name


def copy(source, target):
    data = source.read_bytes()
    if source.is_symlink():
        raise ValueError('ordinary source required')
    if source.suffix == '.py':
        ast.parse(data, filename=str(source))
        compile(data, str(source), 'exec', dont_inherit=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    target.chmod(0o644)


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-payload', type=Path, required=True)
    parser.add_argument('--candidate-lock', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.archive is not None and args.archive.exists():
        raise ValueError('fresh source-only payload required')
    parent = args.parent_payload.resolve()
    manifest = json.loads((parent / 'PAYLOAD_MANIFEST.json').read_bytes())
    actual = inventory(parent)
    actual.pop('PAYLOAD_MANIFEST.json', None)
    actual.pop('MATERIALIZATION.json', None)
    if actual != manifest['files']:
        raise ValueError('unchanged frozen parent host/control payload required')
    locks = json.loads(args.candidate_lock.read_bytes())
    if set(locks['arms']) != set(ARMS):
        raise ValueError('two independent reviewed structural candidate locks required')
    args.out.mkdir(parents=True)
    # Reuse exact original control oracle and host verifier sources, never patch them.
    for directory in ('host', 'control'):
        for name in inventory(parent / directory):
            copy(parent / directory / name, args.out / directory / name)
    baseline = 'completion1009/candidates/lean_production_native_projection_v1'
    for name in inventory(parent / baseline):
        copy(parent / baseline / name, args.out / baseline / name)
    for arm, directory in ARMS.items():
        lock = locks['arms'][arm]
        candidate = COMPLETION / 'candidates' / directory
        receipt = candidate / 'SOURCE_PREPARATION_RECEIPT_v1.json'
        if sha(receipt) != lock['source_receipt_sha256']:
            raise ValueError('candidate source receipt changed: ' + arm)
        definition = json.loads(receipt.read_bytes())
        rows = {row['path']: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in definition['files']}
        if definition.get('frozen_build_input') is not True or definition.get('unfrozen') is not False or rows != lock['source_files']:
            raise ValueError('complete frozen candidate source roster changed: ' + arm)
        review = COMPLETION / lock['review_path']
        if sha(review) != lock['review_sha256']:
            raise ValueError('independent candidate review source changed: ' + arm)
        reviewed = json.loads(review.read_bytes())
        if (reviewed.get('schema') != 't3-root-candidate-source-only-independent-review-v1'
                or reviewed.get('candidate') != directory or reviewed.get('source_receipt_sha256') != sha(receipt)
                or reviewed.get('frozen_file_count') != len(rows) or reviewed.get('all_pins_match') is not True
                or reviewed.get('AST_compile_python_only_passed') is not True
                or reviewed.get('participant_imported') is not False or reviewed.get('native_compiled') is not False
                or reviewed.get('market_executed') is not False):
            raise ValueError('independent candidate source review incomplete: ' + arm)
        destination = args.out / 'completion1009/candidates' / directory
        for name, expected in rows.items():
            source = candidate / safe(name)
            if source.stat().st_size != expected['bytes'] or sha(source) != expected['sha256']:
                raise ValueError('actual frozen candidate differs: ' + arm + '/' + name)
            if Path(name).parts[0] in ('build', 'translation') or name in ('runtime/schema_metadata_v1.json', 'runtime/schema_metadata_pin_v1.py'):
                raise ValueError('candidate source payload contains generated artifacts')
            copy(source, destination / name)
        copy(receipt, destination / receipt.name)
        copy(review, args.out / 'source-review' / (arm + '-review.json'))
    for name in HARNESS:
        copy(HERE / name, args.out / 'harness' / name)
    copy(HERE / 'census/PARENT_SOURCE_LOCK.json', args.out / 'PARENT_SOURCE_LOCK.json')
    copy(args.candidate_lock, args.out / 'CANDIDATE_SOURCE_LOCK.json')
    files = inventory(args.out)
    if len(files) > 768 or sum(row['bytes'] for row in files.values()) > 48 * 1024**2:
        raise ValueError('bounded ordinary structural source payload exceeded')
    write(args.out / 'STRUCTURAL_MANIFEST.json', {'schema': 't3-classic-structural-source-manifest-v2',
        'files': files, 'source_only': True, 'participant_imported': False, 'market_executed': False})
    if args.archive is not None:
        with tarfile.open(args.archive, 'w:xz', format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(inventory(args.out)):
                data = (args.out / name).read_bytes()
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(data), 0o644, 0
                member.uid = member.gid = 0
                archive.addfile(member, io.BytesIO(data))
    print(json.dumps({'prepared_files': len(files), 'source_only': True, 'actual_execution': False,
        'archive_sha256': None if args.archive is None else sha(args.archive)}))


if __name__ == '__main__':
    main()
