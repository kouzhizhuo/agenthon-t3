"""Stdlib exact frozen heap/typed source and independent review binding."""
import hashlib
import json
from pathlib import Path
import stat

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1.json"
CANDIDATE_SHA256 = "052d8d2a5db0b2a40ecbe578a308f950d9cd72f0b1018152e2037a262a2382a2"
CANDIDATE_FILE_COUNT = 11
CANDIDATE_REVIEW_SHA256 = "985b577b6be70b454f4685f16df6f0e3a99197b3b58ba4daeda9be04b58e6733"
WRAPPER_FILE_COUNT = 13
MAX_FILES, MAX_BYTES = 256, 32 * 1024 * 1024
ENTRYPOINT = ["/usr/local/bin/python", "-B", "/opt/delivery-heap-primitive-v2-1/control/entry.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_name(value):
    if (type(value) is not str or not value or "\\" in value or "\x00" in value
            or any(part in ("", ".", "..", "__pycache__", "__MACOSX") or part.startswith("._") for part in value.split("/"))):
        raise ValueError("unambiguous ordinary relative source path required")
    path = Path(value)
    if path.is_absolute() or path.as_posix() != value:
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
    if type(rows) is not list or len({row["path"] for row in rows}) != len(rows):
        raise ValueError("unique complete source pins required")
    for row in rows:
        path = Path(root) / safe_name(row["path"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("source bytes differ: " + row["path"])


def require_review(path, receipt_sha256, files):
    review = json.loads(Path(path).read_bytes())
    if (review.get("status") != "PASS_SOURCE_ONLY" or review.get("unresolved_source_blockers") != []
            or review.get("reviewed_source_receipt_sha256") != receipt_sha256 or review.get("reviewed_files") != files):
        raise ValueError("independent complete frozen source PASS required")
    return review


def verify_payload(root):
    root = Path(root)
    manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_bytes())
    verify_rows(root, manifest["files"])
    actual = inventory(root)
    expected = manifest["files"] + [row for row in actual if row["path"] == "PAYLOAD_MANIFEST.json"]
    if sorted(actual, key=lambda row: row["path"]) != sorted(expected, key=lambda row: row["path"]):
        raise ValueError("payload contains unmanifested/missing files")
    plan = json.loads((root / "CONTROL_PLAN.json").read_bytes())
    expected_plan = {"schema": "t3-delivery-heap-primitive-v2-source-controls-plan-v1",
        "frozen_source_inputs": True, "prototype_only": False,
        "candidate_source_receipt_sha256": CANDIDATE_SHA256,
        "candidate_review_sha256": CANDIDATE_REVIEW_SHA256,
        "base": BASE, "native_builds": 1, "Cython_translation_only_preflights": 1,
        "translation_required_before_build": True, "translation_build_C_fullbytes_equal_required": True,
        "typed_handle_control_invocations": 1, "typed_handle_control_cases": 28,
        "heap_control_invocations": 1, "heap_control_cases": 13,
        "typed_controls_before_heap": True, "market_episodes": 0,
        "timing_runs": 0, "official_verifier_calls": 0, "runtime_containers": 2,
        "raw_controls_replay_required": True, "rankable": False, "speed_claim": False}
    if any(plan.get(key) != value for key, value in expected_plan.items()):
        raise ValueError("exact typed28/heap13/no-market reviewed source plan required")
    receipt_path = root / "candidate" / CANDIDATE_RECEIPT
    receipt = json.loads(receipt_path.read_bytes())
    if (sha(receipt_path) != CANDIDATE_SHA256 or len(receipt["files"]) != CANDIDATE_FILE_COUNT
            or receipt.get("frozen_build_input") is not True or receipt.get("unfrozen") is not False):
        raise ValueError("exact frozen11 heap candidate source roster required")
    verify_rows(root / "candidate", receipt["files"])
    if receipt["files"] != plan["candidate_sources"]:
        raise ValueError("candidate source roster plan differs")
    runtime = json.loads((root / "candidate/RUNTIME_PINS.json").read_bytes())
    if len(runtime["files"]) != 64 or sorted(runtime["files"], key=lambda row: row["path"]) != inventory(root / "runtime"):
        raise ValueError("complete exact original64 runtime required")
    verify_rows(root / "runtime", runtime["files"])
    candidate_review = root / "source_review/INDEPENDENT_CANDIDATE_SOURCE_REVIEW.json"
    if sha(candidate_review) != CANDIDATE_REVIEW_SHA256:
        raise ValueError("candidate independent source review differs")
    require_review(candidate_review, CANDIDATE_SHA256, receipt["files"])
    wrapper_receipt_path = root / "source_review/WRAPPER_SOURCE_PREPARATION_RECEIPT_v1.json"
    wrapper = json.loads(wrapper_receipt_path.read_bytes())
    if (sha(wrapper_receipt_path) != plan["wrapper_source_receipt_sha256"]
            or wrapper.get("source_frozen") is not True or len(wrapper["files"]) != WRAPPER_FILE_COUNT):
        raise ValueError("exact frozen wrapper full source receipt required")
    verify_rows(root / "wrapper_source", wrapper["files"])
    wrapper_review = root / "source_review/INDEPENDENT_WRAPPER_SOURCE_REVIEW.json"
    if sha(wrapper_review) != plan["wrapper_review_sha256"]:
        raise ValueError("wrapper independent source review differs")
    require_review(wrapper_review, sha(wrapper_receipt_path), wrapper["files"])
    if inventory(root / "control") != plan["control_sources"]:
        raise ValueError("actual control source roster differs")
    for row in plan["control_sources"]:
        if (root / "control" / row["path"]).read_bytes() != (root / "wrapper_source" / row["path"]).read_bytes():
            raise ValueError("actual controller differs from frozen wrapper source")
    return plan
