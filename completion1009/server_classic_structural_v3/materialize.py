"""Materialize exact, bounded ordinary source overlay; no participant imports."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from prepare import inventory, safe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if hashlib.sha256(args.archive.read_bytes()).hexdigest() != args.expected_sha256 or args.out.exists():
        raise ValueError('exact source archive and fresh output required')
    with tarfile.open(args.archive, 'r:xz') as archive:
        members = archive.getmembers()
        names = [safe(member.name) for member in members]
        if len(members) > 768 or sum(member.size for member in members) > 48 * 1024**2 or len(names) != len(set(names)) or any(not member.isfile() for member in members):
            raise ValueError('bounded unique ordinary archive members required')
        roster = set(names)
        if any(any(parent.as_posix() in roster for parent in Path(name).parents if parent.as_posix() != '.') for name in names):
            raise ValueError('file member cannot be a parent directory')
        args.out.mkdir(parents=True)
        for member, name in zip(members, names):
            target = args.out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ValueError('truncated source member')
                    output.write(chunk)
                    remaining -= len(chunk)
            target.chmod(0o644)
    expected = json.loads((args.out / 'STRUCTURAL_MANIFEST.json').read_bytes())['files']
    actual = inventory(args.out)
    actual.pop('STRUCTURAL_MANIFEST.json')
    if actual != expected:
        raise ValueError('materialized structural source differs')
    print('EXACT STRUCTURAL SOURCE MATERIALIZATION PASS')


if __name__ == '__main__':
    main()
