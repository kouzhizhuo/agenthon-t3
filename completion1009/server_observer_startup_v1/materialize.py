"""Bounded exact-source payload materialization; no extraction of links."""
import argparse
import json
from pathlib import Path
import tarfile
from common import MAX_BYTES, MAX_FILES, safe_name, sha, verify_inventory, write


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if len(args.expected_sha256) != 64 or sha(args.archive) != args.expected_sha256:
        raise ValueError("reviewed archive SHA256 required")
    if args.out.exists():
        raise ValueError("materialization destination must be new")
    with tarfile.open(args.archive, "r:xz") as archive:
        members = archive.getmembers()
        names = [safe_name(item.name) for item in members]
        if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_BYTES or len(set(names)) != len(names):
            raise ValueError("bounded unique source archive required")
        if any(not m.isfile() for m in members):
            raise ValueError("only ordinary source files allowed")
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
    manifest = json.loads((args.out / "PAYLOAD_MANIFEST.json").read_text())
    actual = __import__("common").inventory(args.out)
    actual.pop("PAYLOAD_MANIFEST.json")
    if actual != manifest["files"]:
        raise ValueError("materialized payload file hashes differ")
    write(args.out / "MATERIALIZATION.json", {"archive_sha256": sha(args.archive), "files": len(members),
        "expanded_bytes": sum(m.size for m in members), "inventory_passed": True})


if __name__ == "__main__":
    main()
