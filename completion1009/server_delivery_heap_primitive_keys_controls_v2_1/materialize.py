"""Stdlib materialization of one bounded exact source archive."""
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
        raise ValueError("exact root-reviewed source archive digest required")
    if args.out.exists() or args.out.is_symlink():
        raise ValueError("fresh materialization directory required")
    with tarfile.open(args.archive, "r:xz") as archive:
        members = archive.getmembers()
        names = [safe_name(member.name) for member in members]
        if (len(members) > MAX_FILES or sum(member.size for member in members) > MAX_BYTES
                or len(set(names)) != len(names) or any(not member.isfile() for member in members)):
            raise ValueError("bounded unique ordinary source members required")
        types = {name.as_posix() for name in names}
        if any(parent.as_posix() in types for name in names for parent in Path(name).parents if parent != Path(".")):
            raise ValueError("source file used as archive directory")
        args.out.mkdir(parents=True)
        for member, name in zip(members, names):
            path = args.out / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, path.open("xb") as output:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("truncated source archive")
                    output.write(chunk); remaining -= len(chunk)
            path.chmod(0o644)
    verify_payload(args.out)
    write(args.out.with_suffix(".materialization.json"), {"archive_sha256": sha(args.archive),
        "ordinary_files": len(members), "expanded_bytes": sum(member.size for member in members),
        "source_inventory_verified": True, "source_only": True})


if __name__ == "__main__":
    main()
