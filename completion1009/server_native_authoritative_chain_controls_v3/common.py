"""Stdlib source inventories for one honest authoritative-chain JSON control."""
import hashlib
import json
from pathlib import Path
import stat

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1.json"
CANDIDATE_SHA256 = "6e31d82ff0dbdfba0283abf6e29b36e71e28ffb4ca66e9e2cbba2dd2618da695"
CANDIDATE_FILE_COUNT = 25
MAX_FILES, MAX_BYTES = 256, 32 * 1024 * 1024
ENTRYPOINT = ["/usr/local/bin/python", "-B", "/opt/authoritative-chain/control/entry.py"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def safe_name(value):
    if (type(value) is not str or not value or "\\" in value or "\x00" in value
            or "//" in value or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("unambiguous ordinary relative source path required")
    path = Path(value)
    if (not value or path.is_absolute() or path.as_posix() != value
            or any(part in (".", "..", "__pycache__") or part.startswith("._") for part in path.parts)):
        raise ValueError("clean ordinary relative source path required")
    return path


def inventory(root):
    result = []
    for path in sorted(Path(root).rglob("*")):
        if any(part.startswith("._") or part == "__pycache__" for part in path.parts):
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
            or sha(root / "candidate" / CANDIDATE_RECEIPT) != CANDIDATE_SHA256
            or plan.get("native_builds") != 1 or plan.get("real_JSON_scenarios") != 1
            or plan.get("arms") != ["original", "native1", "native2"]):
        raise ValueError("exact single-build/source/three-arm plan required")
    receipt = json.loads((root / "candidate" / CANDIDATE_RECEIPT).read_bytes())
    if len(receipt["files"]) != CANDIDATE_FILE_COUNT or receipt["frozen_build_input"] is not True:
        raise ValueError("exact frozen V3 candidate source roster required")
    verify_rows(root / "candidate", receipt["files"])
    runtime = json.loads((root / "candidate/RUNTIME_PINS.json").read_bytes())
    if len(runtime["files"]) != 64:
        raise ValueError("exact original 64-file runtime required")
    verify_rows(root / "runtime", runtime["files"])
    rules = json.loads((root / "candidate/RULE_SOURCE_PINS_v1.json").read_bytes())
    verify_rows(root / "rules", rules["files"])
    audit = root / "source_review/INDEPENDENT_BODY_AUDIT.json"
    if sha(audit) != plan["independent_body_audit_sha256"]:
        raise ValueError("independent finite business-body audit differs")
    if sha(root / "source_review/INDEPENDENT_V3_REPAIR_REVIEW.json") != plan["independent_v3_repair_review_sha256"]:
        raise ValueError("independent V3 typed-comprehension repair review differs")
    return plan
