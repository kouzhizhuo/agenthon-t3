"""Exact source-only scheduler screen contract with immutable owner receipts."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_canonical_scheduler_ledger_v3"
RUNTIME_OWNER = "completion1009/candidates/lean_production_native_projection_v1/runtime"
ARMS = ["original_canonical", "matching_python", "actual_native"]
IMAGE_CANDIDATE = "/opt/scheduler-screen/" + CANDIDATE
IMAGE_RUNTIME = "/opt/scheduler-screen/" + RUNTIME_OWNER
SOURCE_RECEIPT_SHA256 = "7ec1d795d020f35bd5ea5d3b0bda175aa6455575f6323e55286e77aaf208d680"
RUNTIME_PINS_SHA256 = "18399adef0041fda36441c5735beb8f9108876b5d84a5933c3adb529f3bde1fb"
CONTROL_SOURCE_RECEIPT_SHA256 = "cbcb7b613dca7ca8e617357420a6dd4ae60025b3830eb99840eae4e6d7cd3b6a"
SINGLES = ["t3-s001-price-time-priority", "t3-as06-throughput-fast",
           "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid"]
BATCH = "t3-gbatch-hetero-mix"
MARKER = "T3_NATIVE_CANONICAL_SCHEDULER_V3_SCREEN="
TIMING_SCOPE = "CLI ENTRY_STARTED through Parquet/hash; unchanged sidecar cutoff; marker serialization outside CLI timer"
MAX_FILES = 2048
MAX_BYTES = 128 * 1024 ** 2
BUILD_SCHEMA = "t3-native-canonical-scheduler-ledger-build-v3"
DEPLOYMENT_SCHEMA = "t3-native-canonical-scheduler-ledger-deployment-v3"
ENTRY_SCHEMA = "t3-native-canonical-scheduler-v3-entry"
SCREEN_SCHEMA = "t3-native-canonical-scheduler-v3-screen-result"
BOUNDARY_CASES = 41
SCHEDULER_VARIANTS = 33
MARKET_CASES = 4
MARKET_RECORDS = 12
CONTROL_PARQUETS = 24
MARKET_SEEDS = [81009, 82009, 83009, 84009]

def arm_order(unit_index, repeat):
    # Each measured repeat rotates every arm through each position; units
    # alternate orientation. Every round uses three fresh serial processes.
    order = list(ARMS if unit_index % 2 == 0 else reversed(ARMS))
    offset = repeat % 3
    return order[offset:] + order[:offset]

def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()

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
        raise ValueError("unsafe relative path: " + repr(value))
    return name.as_posix()

def inventory(root):
    values = {}
    for path in sorted(Path(root).rglob("*")):
        if path.name.startswith("._") or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("source symlink prohibited: " + str(path))
        if path.is_file():
            values[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return values

def verify_payload(root):
    expected = json.loads((Path(root) / "PAYLOAD_MANIFEST.json").read_text())["files"]
    actual = inventory(root)
    actual.pop("PAYLOAD_MANIFEST.json", None)
    actual.pop("MATERIALIZATION.json", None)
    if actual != expected:
        raise ValueError("complete reviewed payload inventory differs")
    return expected
