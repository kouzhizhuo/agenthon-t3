#!/usr/bin/env python3
"""Unpack a reviewed bounded payload into a new directory without links."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import tarfile

MAX_MEMBERS = 512
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def unpack(archive_path, expected_sha256, output):
    archive_path, output = Path(archive_path), Path(output)
    if not re.fullmatch("[0-9a-f]{64}", expected_sha256):
        raise ValueError("payload SHA256 malformed")
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("reviewed payload bytes differ")
    if output.exists():
        raise ValueError("payload destination must be new")
    with tarfile.open(archive_path, "r:xz") as archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_MEMBERS:
            raise ValueError("payload member count outside bound")
        seen, total = set(), 0
        for member in members:
            name = member.name
            total += member.size
            if (not member.isfile() or name.startswith("/") or "\\" in name
                    or any(p in ("", ".", "..") or p.startswith("._") for p in name.split("/"))
                    or "__pycache__" in name.split("/") or name in seen
                    or member.size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES):
                raise ValueError("unsafe or oversized frozen payload member")
            seen.add(name)
        output.mkdir(parents=True)
        try:
            for member in members:
                path = output / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                data = archive.extractfile(member).read()
                if len(data) != member.size:
                    raise ValueError("truncated frozen payload member")
                path.write_bytes(data)
                path.chmod(0o644)
        except Exception:
            shutil.rmtree(output)
            raise
    return {"payload_sha256": expected_sha256, "member_count": len(members), "uncompressed_bytes": total}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    unpack(args.archive, args.expected_sha256, args.out)


if __name__ == "__main__":
    main()
