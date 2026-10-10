"""Exact cold native output source and independent review binding for finite real screen."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_inline_exact_latency_v1"
BASELINE = "completion1009/candidates/lean_production_native_projection_v1/runtime"
SOURCE_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1.json"
SOURCE_RECEIPT_SHA256 = "cb931ce44fe91ca0a1f820000e11f7d864e079b6d9a2f24ea3a93299dc8363be"
CANDIDATE_REVIEW_SHA256 = "db499da7aadff916dc70ecaaf24f0011ae02cd77a240cb9d305b547893c908c7"
BASELINE_PINS_SHA256 = "ad2084b3097e0bc482e68388f4b7b8f946e2668529aa606a1ba94abeeeeb8a11"
GENERATOR = "completion1009/research/pandas_free_output_route_v1/prepare_schema_metadata_source_v1.py"
GENERATOR_SHA256 = "aa60cd24b919446e881a6b849a4039b363c14e684ccd58bbd0cf9ad55cffeafe"
SCHEMA_DRIVER_SHA256 = "b10e31efc42d93ef7afb6ab99fe2ec85b40c9a2ad6a1738050c58efb9619d3df"
IMAGE_ROOT = "/opt/native-inline-exact-latency-v1"
ENTRYPOINT = ["/usr/local/bin/python", "-B", IMAGE_ROOT + "/control/entry.py"]
ARMS = ("baseline", "light_canonical", "light_dynamic")
COLD_EMPTY = {"pandas_loaded": False, "pandas_modules": [], "scipy_loaded": False, "scipy_modules": [],
              "unused_stock_modules_loaded": [], "stock_cli_loaded": False}
SINGLES = ("t3-s001-price-time-priority", "t3-as06-throughput-fast", "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid")
BATCH = "t3-gbatch-hetero-mix"
CONTROL_ARMS = ("original", "light_canonical", "light_dynamic", "light_dynamic_repeat", "decline_trace", "decline_message_trace")
MAX_FILES = 512
MAX_BYTES = 32 * 1024 ** 2


def arm_order(unit_index, repeat):
    offset = unit_index % len(ARMS)
    rotated = ARMS[offset:] + ARMS[:offset]
    return list(reversed(rotated)) if repeat == 1 else list(rotated)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def safe_name(value):
    name = PurePosixPath(value)
    if (type(value) is not str or not value or name.is_absolute() or name.as_posix() != value
            or any(p in ("", ".", "..", "__pycache__", "__MACOSX") or p.startswith("._") for p in value.split("/"))
            or "\\" in value or "\x00" in value):
        raise ValueError("unsafe relative source path")
    return name.as_posix()


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if any(part.startswith("._") or part in ("__pycache__", "__MACOSX") for part in path.parts): continue
        if path.is_symlink(): raise ValueError("source symlink refused")
        if path.is_file(): result[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return result


def require_review(path, expected_receipt_sha256, expected_files, status="PASS_SOURCE_ONLY"):
    review = json.loads(Path(path).read_bytes())
    if (review.get("status") != status or review.get("unresolved_source_blockers") != []
            or review.get("reviewed_source_receipt_sha256") != expected_receipt_sha256
            or review.get("reviewed_files") != expected_files):
        raise ValueError("independent exact source PASS and complete roster required")
    return review


def verify_payload(root):
    root = Path(root); manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_bytes())
    actual = inventory(root); actual.pop("PAYLOAD_MANIFEST.json", None); actual.pop("MATERIALIZATION.json", None)
    if actual != manifest["files"]: raise ValueError("source payload differs")
    plan = json.loads((root / "SCREEN_PLAN.json").read_bytes())
    if (plan.get("schema") != "t3-cold-native-projection-buffers-market-source-plan-v1"
            or plan.get("prototype_only") is not False or plan.get("candidate") != CANDIDATE
            or plan.get("candidate_source_receipt_sha256") != SOURCE_RECEIPT_SHA256
            or plan.get("candidate_review_sha256") != CANDIDATE_REVIEW_SHA256
            or plan.get("base") != BASE or plan.get("arms") != list(ARMS)
            or plan.get("baseline_pins_sha256") != BASELINE_PINS_SHA256
            or plan.get("generator_sha256") != GENERATOR_SHA256
            or plan.get("execution_containers") != 61 or plan.get("measured_runs") != 30
            or plan.get("ordinary_runs") != 60 or plan.get("phase_runs") != 0
            or plan.get("native_output_fixture_children") != 2
            or plan.get("require_translation_C_equal_build_C") is not True):
        raise ValueError("exact independently reviewed finite cold native output plan required")
    receipt_path = root / CANDIDATE / SOURCE_RECEIPT
    if sha(receipt_path) != SOURCE_RECEIPT_SHA256: raise ValueError("frozen cold native output receipt changed")
    candidate = json.loads(receipt_path.read_bytes())
    if candidate["files"] != plan["candidate_sources"]: raise ValueError("candidate roster changed")
    for row in candidate["files"]:
        path = root / CANDIDATE / safe_name(row["path"])
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("frozen candidate actual bytes changed")
    wrapper_receipt = root / "source_review/WRAPPER_SOURCE_PREPARATION_RECEIPT_v1.json"
    wrapper = json.loads(wrapper_receipt.read_bytes())
    if sha(wrapper_receipt) != plan["wrapper_source_receipt_sha256"]:
        raise ValueError("frozen wrapper receipt changed")
    for label, digest, receipt_digest, files in (("CANDIDATE", plan["candidate_review_sha256"], SOURCE_RECEIPT_SHA256, candidate["files"]),
            ("WRAPPER", plan["wrapper_review_sha256"], plan["wrapper_source_receipt_sha256"], wrapper["files"])):
        path = root / ("source_review/INDEPENDENT_" + label + "_SOURCE_REVIEW.json")
        if sha(path) != digest: raise ValueError("independent source review changed")
        require_review(path, receipt_digest, files,
            "PASS_SOURCE_ONLY" if label == "CANDIDATE" else "PASS_SOURCE_ONLY")
    for row in wrapper["files"]:
        path = root / "wrapper_source" / safe_name(row["path"])
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("reviewed complete wrapper source bytes changed")
    for name, expected in plan["control_sources"].items():
        if inventory(root / "control").get(name) != expected:
            raise ValueError("reviewed actual execution control source changed")
    if inventory(root / "host") != plan["host_sources"]:
        raise ValueError("reviewed actual host evaluator source changed")
    return plan
