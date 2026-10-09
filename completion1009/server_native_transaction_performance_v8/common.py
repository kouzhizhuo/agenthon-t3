"""Source-only native V8 five-unit actual CLI performance protocol."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_canonical_transaction_v8"
BASELINE = "completion1009/candidates/lean_production_native_projection_v1/runtime"
SOURCE_RECEIPT_SHA256 = "8e065cb145d48f1ec7425484d047849102820a921a927bb7d5e38668414b7f6c"
MAX_FILES = 512
MAX_BYTES = 32 * 1024 ** 2
IMAGE_ROOT = "/opt/native-transaction-performance"
ENTRYPOINT = ["/usr/local/bin/python", "-B", IMAGE_ROOT + "/control/entry.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_name(value):
    name = PurePosixPath(value)
    if (not value or name.is_absolute() or any(p in ("", ".", "..") for p in value.split("/"))
            or "\\" in value or "\x00" in value):
        raise ValueError("unsafe relative path")
    return name.as_posix()


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.name.startswith("._") or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("source symlink prohibited")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return result


def verify_payload(root):
    root = Path(root)
    manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
    actual = inventory(root)
    actual.pop("PAYLOAD_MANIFEST.json", None)
    actual.pop("MATERIALIZATION.json", None)
    if actual != manifest["files"]:
        raise ValueError("exact transaction controls payload inventory differs")
    return actual

ARMS = ("original_canonical", "actual_native")
SINGLES = ("t3-s001-price-time-priority", "t3-as06-throughput-fast", "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid")
BATCH = "t3-gbatch-hetero-mix"
WARMUPS = 1
MEASURED_REPEATS = 5

def arm_order(unit_index, repeat):
    return list(ARMS if (unit_index + repeat) % 2 == 0 else reversed(ARMS))
