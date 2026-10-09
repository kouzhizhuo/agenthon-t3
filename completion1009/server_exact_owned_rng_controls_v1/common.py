"""Stdlib pins for a scalar-only owned-RNG experiment; no runtime preparation."""
import hashlib
import json
from pathlib import Path
import stat

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1.json"
CANDIDATE_SHA256 = "4b8539a2250a7f3928ebd97dfa930c871b3e877b87ee8148b649c687b75659bd"
CANDIDATE_FILE_COUNT = 13
CANDIDATE_REVIEW_SHA256 = "25d5467015abac983b7347ef53bc8535ac7aa4ecdf2ae43a246664065b3fac9b"
WRAPPER_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1.json"
MAX_FILES, MAX_BYTES = 256, 32 * 1024 * 1024
ENTRYPOINT = ["/usr/local/bin/python", "-B", "/opt/exact-owned-rng/control/entry.py"]
CASE_COUNTS = {
    "mixed-scalar-cache": 240, "normal-rollover": 400, "uniform-rollover": 400,
    "pending-positive-zero-cache": 18, "pending-negative-zero-cache": 18, "pending-nonzero-cache": 18,
    "negativezero-and-nonfinite-finite-transform": 24, "degenerate-and-invalid": 10,
    "small32-rejection-and-wide64": 840, "signed-bound-and-error": 5,
    "unsupported-NaN-original-handoff": 7, "unsupported-infinity-original-handoff": 7,
    "unsupported-bool-original-handoff": 7, "unsupported-numpy-scalar-handoff": 7,
    "unsupported-array-original-handoff": 7, "unsupported-size-original-handoff": 7,
    "unsupported-narrow-dtype-handoff": 7, "unsupported-other-method-handoff": 7,
    "real-NoiseTrader-act-order": 900, "real-uniform-latency": 700,
    "real-lognormal-latency": 700, "real-pareto-latency": 700,
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def safe_name(value):
    if (type(value) is not str or not value or "\\" in value or "\x00" in value
            or "//" in value or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("unambiguous ordinary relative source path required")
    path = Path(value)
    if (path.is_absolute() or path.as_posix() != value
            or any(part in (".", "..", "__pycache__", "__MACOSX") or part.startswith("._") for part in path.parts)):
        raise ValueError("clean ordinary relative source path required")
    return path


def inventory(root):
    result = []
    for path in sorted(Path(root).rglob("*")):
        if any(part.startswith("._") or part in ("__pycache__", "__MACOSX") for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError("source/output inventory contains a symlink")
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
            raise ValueError("source/output inventory contains a special file")
        if stat.S_ISREG(mode):
            result.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    return result


def verify_rows(root, rows):
    if len({row["path"] for row in rows}) != len(rows):
        raise ValueError("duplicate source pins")
    for row in rows:
        path = Path(root) / safe_name(row["path"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("source bytes differ: " + row["path"])


def verify_candidate(root):
    root = Path(root)
    if sha(root / CANDIDATE_RECEIPT) != CANDIDATE_SHA256:
        raise ValueError("exact frozen candidate receipt required")
    receipt = json.loads((root / CANDIDATE_RECEIPT).read_bytes())
    if (receipt.get("schema") != "t3-exact-owned-rng-control-source-preparation-v1"
            or receipt.get("status") != "PREPARED_SOURCE_ONLY" or len(receipt["files"]) != CANDIDATE_FILE_COUNT):
        raise ValueError("exact frozen 13-file source roster required")
    verify_rows(root, receipt["files"])
    return receipt


def verify_payload(root):
    root = Path(root)
    manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_bytes())
    verify_rows(root, manifest["files"])
    actual = inventory(root)
    expected = manifest["files"] + [row for row in actual if row["path"] == "PAYLOAD_MANIFEST.json"]
    if sorted(actual, key=lambda row: row["path"]) != sorted(expected, key=lambda row: row["path"]):
        raise ValueError("payload contains unmanifested/missing files")
    plan = json.loads((root / "CONTROL_PLAN.json").read_bytes())
    if (plan.get("frozen_source_inputs") is not True or plan.get("candidate_source_receipt_sha256") != CANDIDATE_SHA256
            or plan.get("native_builds") != 1 or plan.get("scalar_cases") != 22 or plan.get("calls_per_complete_arm") != 5029
            or plan.get("fixed_whole_arm_orders") != ["high-first", "low-first"] or plan.get("strategy_controls") is not False
            or plan.get("market_controls") is not False or plan.get("minimum_host_free_bytes") != 4 * 1024**3
            or plan.get("scalar_fsize_limit_bytes") != 1024**3):
        raise ValueError("exact scalar-only single-build plan required")
    candidate = verify_candidate(root / "candidate")
    review_path = root / "source_review/INDEPENDENT_CANDIDATE_REVIEW.json"
    review = json.loads(review_path.read_bytes())
    if (sha(review_path) != CANDIDATE_REVIEW_SHA256 or review.get("status") != "PASS_SOURCE_ONLY"
            or review.get("unresolved_source_blockers") != [] or review.get("reviewed_source_receipt_sha256") != CANDIDATE_SHA256
            or review.get("reviewed_files") != candidate["files"]):
        raise ValueError("exact independent candidate source PASS required")
    receipt_path = root / "source_review" / WRAPPER_RECEIPT
    wrapper = json.loads(receipt_path.read_bytes())
    if (sha(receipt_path) != plan.get("wrapper_source_receipt_sha256") or wrapper.get("source_frozen") is not True
            or wrapper.get("candidate_source_receipt_sha256") != CANDIDATE_SHA256 or len(wrapper["files"]) != 8):
        raise ValueError("exact frozen eight-file wrapper receipt required")
    verify_rows(root / "control", wrapper["files"])
    wrapper_review_path = root / "source_review/INDEPENDENT_WRAPPER_REVIEW.json"
    wrapper_review = json.loads(wrapper_review_path.read_bytes())
    if (sha(wrapper_review_path) != plan.get("independent_wrapper_review_sha256")
            or wrapper_review.get("status") != "PASS_SOURCE_ONLY" or wrapper_review.get("unresolved_source_blockers") != []
            or wrapper_review.get("wrapper_source_receipt_sha256") != sha(receipt_path)
            or wrapper_review.get("candidate_source_receipt_sha256") != CANDIDATE_SHA256
            or wrapper_review.get("reviewed_wrapper_files") != wrapper["files"]):
        raise ValueError("exact independent wrapper source PASS required")
    return plan
