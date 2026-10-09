"""Source-only helpers for pinned T3 screening; no participant references."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
SMOKE = ["t3-s001-price-time-priority", "t3-as06-throughput-fast", "t3-mp01-stp-newest-baseline"]
UNITS = SMOKE + ["t3-ra01-fundamental-shock-mid", "t3-gbatch-hetero-mix"]
STRESS = ["t3-mr-deep-book-state-size", "t3-gb-mega-throughput"]
MAX_FILES = 2048
MAX_BYTES = 128 * 1024 ** 2


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_name(value):
    name = PurePosixPath(value)
    if not value or name.is_absolute() or any(p in ("", ".", "..") for p in name.parts) or "\\" in value:
        raise ValueError("unsafe relative path: " + repr(value))
    return name.as_posix()


def inventory(root):
    rows = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("source symlink prohibited: " + str(path))
        if path.is_file() and "__pycache__" not in path.parts and not path.name.startswith("._"):
            rows[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return rows


def verify_inventory(root, expected):
    if inventory(root) != expected:
        raise ValueError("complete pinned source inventory differs: " + str(root))


def get_field(value, field):
    for part in field.split("."):
        value = value[part]
    return value
