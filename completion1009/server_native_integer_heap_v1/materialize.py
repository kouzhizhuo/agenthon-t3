"""Materialize only bounded, ordinary members from an exact reviewed archive."""
import argparse
from pathlib import Path
import tarfile
from common import MAX_BYTES, MAX_FILES, safe_name, sha, verify_payload, write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if len(args.expected_sha256) != 64 or sha(args.archive) != args.expected_sha256:
        raise ValueError("exact reviewed archive SHA256 required")
    if args.out.exists() or args.out.is_symlink():
        raise ValueError("new materialization destination required")
    with tarfile.open(args.archive, "r:xz") as archive:
        members = archive.getmembers()
        names = [safe_name(member.name) for member in members]
        if (len(members) > MAX_FILES or sum(member.size for member in members) > MAX_BYTES
                or len(set(names)) != len(names) or any(not member.isfile() for member in members)):
            raise ValueError("bounded unique ordinary source members required")
        types = set(names)
        for name in names:
            if any(parent.as_posix() in types for parent in Path(name).parents if parent.as_posix() != "."):
                raise ValueError("archive file used as a parent directory")
        args.out.mkdir(parents=True)
        for member, name in zip(members, names):
            target = args.out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("truncated source archive")
                    output.write(chunk)
                    remaining -= len(chunk)
            target.chmod(0o644)
    verify_payload(args.out)
    write(args.out / "MATERIALIZATION.json", {"archive_sha256": sha(args.archive),
        "files": len(members), "expanded_bytes": sum(member.size for member in members),
        "inventory_passed": True, "source_only": True})


if __name__ == "__main__":
    main()
