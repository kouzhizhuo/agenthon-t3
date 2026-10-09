"""Frozen V4 + actual V4.1 fixture binding; finite market/daemon diagnostics only."""
import hashlib
import json
from pathlib import Path, PurePosixPath
BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/lightweight_canonical_buffers_v4"
BASELINE = "completion1009/candidates/lean_production_native_projection_v1/runtime"
SOURCE_RECEIPT_SHA256 = "5a7efb13de2aa4dd888480d235250e5f2b894a60a16900b29724ec8e3553fbf0"
CANDIDATE_REVIEW_SHA256 = "2574f48eaedab59e6143658e0c89e528fee74d875458cfbeff328ecd4539d21c"
FIXTURE_ACTUAL_AUDIT_SHA256 = "b5f76b247ca992fba34729266de65b6d06c189569f5da5e94c5a09a437682a11"
FIXTURE_ARTIFACT_ZIP_SHA256 = "cb973eea0ab9933a308e02ca9ff7fdf361c3644a9bf022fa562bbdc378fda440"
FIXTURE_AUDITOR_SHA256 = "6584309ae7d4d385bc2ae25f8e75fd2099eb4a782963a741a350e5c7f9c2dbd2"
FIXTURE_SPEC_SHA256 = "e2d998b234a77f1893407140ba4b96a115ac10e8feba7655b65bd90c1a38c1b4"
FIXTURE_PAYLOAD_SHA256 = "5808c02995f5cdac8aab3f5ffef29a1d735da9270053adc56bb7b49133a2dbec"
FIXTURE_MANIFEST_PIN = {"bytes": 34337, "sha256": "b3e1640fdafb7d6d08e891789c04c7eaaa5aac17ea993156487a65f2d7c59a22"}
FIXTURE_PLAN_PIN = {"bytes": 26108, "sha256": "eecec9ec371ae4946dcca784c6369c5338a6556fdd398ef83a0adcf8370201d2"}
FIXTURE_RECEIPT_PIN = {"bytes": 15029, "sha256": SOURCE_RECEIPT_SHA256}
FIXTURE_WRAPPER_REVIEW_SHA256 = "11e3cdaa479323bb353d73910d82c2d9d55c5deb4aee59257eedd9262525a9ac"
FIXTURE_AUDITOR = "completion1009/research/pandas_free_output_route_v1/saved_fixture_audit_v4_1/audit.py"
FIXTURE_SPEC = "completion1009/research/pandas_free_output_route_v1/saved_fixture_audit_v4_1/PREPARATION_SPEC_v1.json"
GENERATOR = "completion1009/research/pandas_free_output_route_v1/prepare_schema_metadata_source_v1.py"
GENERATOR_SHA256 = "aa60cd24b919446e881a6b849a4039b363c14e684ccd58bbd0cf9ad55cffeafe"
IMAGE_ROOT = "/opt/lightweight-canonical-market-v4-1"
ENTRYPOINT = ["/usr/local/bin/python", "-B", IMAGE_ROOT + "/control/entry.py"]
ARMS = ("baseline", "new")
SEMANTIC_ARMS = ("baseline", "new", "new-repeat")
PHASE_ARMS = ("diagnostic-baseline", "diagnostic-new")
COLD_EMPTY = {"pandas_loaded": False, "pandas_modules": [], "scipy_loaded": False, "scipy_modules": [],
              "unused_stock_modules_loaded": [], "stock_cli_loaded": False}
SEEDS = (81009, 82009, 83009, 84009)
SINGLES = ("t3-s001-price-time-priority", "t3-as06-throughput-fast", "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid")
BATCH = "t3-gbatch-hetero-mix"
MAX_FILES = 512
MAX_BYTES = 32 * 1024 ** 2

def arm_order(unit_index, repeat):
    return list(ARMS if (unit_index + repeat) % 2 == 0 else reversed(ARMS))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)

def safe_name(value):
    name = PurePosixPath(value)
    if (not value or name.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")) or "\\" in value or "\x00" in value):
        raise ValueError("unsafe relative source path")
    return name.as_posix()

def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.name.startswith("._") or "__pycache__" in path.parts: continue
        if path.is_symlink(): raise ValueError("source symlink refused")
        if path.is_file(): result[path.relative_to(root).as_posix()] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return result

def require_fixture_actual_audit(actual):
    # The source-only preparation cannot invent this receipt. Root supplies an
    # actual saved-data audit after checking the downloaded artifact envelope.
    if (actual.get("schema") != "t3-lightweight-canonical-fixture-data-only-actual-audit-v4-1"
            or actual.get("all_passed") is not True or "failure" in actual
            or any(actual.get(key) is not False for key in ("rankable", "official_gate", "market_executed", "participant_imported"))
            or actual.get("source_auditor_sha256") != FIXTURE_AUDITOR_SHA256
            or actual.get("spec_sha256") != FIXTURE_SPEC_SHA256):
        raise ValueError("exact actual fixtureV4.1 data-only audit PASS required")
    retained = actual.get("retained_archive_inventory", {})
    expected = {"payload/PAYLOAD_MANIFEST.json": FIXTURE_MANIFEST_PIN,
                "payload/FIXTURE_PLAN.json": FIXTURE_PLAN_PIN,
                "payload/" + CANDIDATE + "/SOURCE_PREPARATION_RECEIPT_v4.json": FIXTURE_RECEIPT_PIN}
    if any(retained.get(name) != pin for name, pin in expected.items()):
        raise ValueError("actual fixture archive manifest/plan/frozenV4 binding differs")
    commands = actual.get("commands", {})
    if commands.get("resources_verified") is not True or commands.get("both_cleanup_returncodes_zero") is not True or commands.get("commands") != 12:
        raise ValueError("actual fixture resource/build/cleanup checks absent")
    fixture = actual.get("fixtures", {})
    if (fixture.get("public_time_cases") != 16 or fixture.get("normal_return_cases") != 8
            or fixture.get("sentinel_throw_cases") != 3 or fixture.get("general_fallback_cases") != 4
            or fixture.get("full_serializer_group_calls") != 12
            or fixture.get("primary_API_equal") is not True
            or fixture.get("cold_final_attempt_lists_empty") is not True
            or fixture.get("actual12_stable_sort_tie_rows_checked") is not True):
        raise ValueError("actual fixtureV4.1 signed64/NaT/cold/serializer controls absent")
    decoded = fixture.get("decoded_retained_parquets", [])
    if (len(decoded) != 9 or {(row.get("arm"), row.get("table")) for row in decoded}
            != {(arm, name) for arm in ("baseline", "new", "cold-new") for name in ("trace", "message_trace", "trace_sort_ties")}):
        raise ValueError("actual nine retained fixture Parquet decode roster absent")


def verify_payload(root):
    root = Path(root); manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
    actual = inventory(root); actual.pop("PAYLOAD_MANIFEST.json", None); actual.pop("MATERIALIZATION.json", None)
    if actual != manifest["files"]: raise ValueError("source payload differs")
    plan = json.loads((root / "SCREEN_PLAN.json").read_text())
    if (plan.get("schema") != "t3-lightweight-canonical-market-source-plan-v4-1"
            or plan.get("prototype_only") is not False or plan.get("independent_wrapper_review_sha256") is None
            or plan.get("fixture_actual_audit_sha256") is None):
        raise ValueError("actual fixture audit and independent wrapper review required before execution")
    if (plan.get("candidate") != CANDIDATE or plan.get("candidate_source_receipt_sha256") != SOURCE_RECEIPT_SHA256
            or plan.get("candidate_review_sha256") != CANDIDATE_REVIEW_SHA256
            or plan.get("fixture_auditor_sha256") != FIXTURE_AUDITOR_SHA256
            or plan.get("fixture_spec_sha256") != FIXTURE_SPEC_SHA256
            or plan.get("fixture_payload_sha256") != FIXTURE_PAYLOAD_SHA256
            or plan.get("fixture_manifest_sha256") != FIXTURE_MANIFEST_PIN["sha256"]
            or plan.get("fixture_wrapper_review_sha256") != FIXTURE_WRAPPER_REVIEW_SHA256
            or plan.get("fixture_actual_audit_sha256") != FIXTURE_ACTUAL_AUDIT_SHA256
            or plan.get("fixture_artifact_zip_sha256") != FIXTURE_ARTIFACT_ZIP_SHA256):
        raise ValueError("frozenV4/corrected fixtureV4.1 required pins differ")
    evidence = root / "control/ACTUAL_FIXTURE_AUDIT.json"
    if sha(evidence) != FIXTURE_ACTUAL_AUDIT_SHA256:
        raise ValueError("actual fixture audit receipt bytes changed")
    if (sha(root / "control/FIXTURE_DATA_AUDITOR_v4_1.py") != FIXTURE_AUDITOR_SHA256
            or sha(root / "control/FIXTURE_DATA_AUDIT_SPEC_v4_1.json") != FIXTURE_SPEC_SHA256
            or sha(root / "control/INDEPENDENT_WRAPPER_SOURCE_REVIEW.json") != plan["independent_wrapper_review_sha256"]
            or sha(root / "control/INDEPENDENT_CANDIDATE_SOURCE_REVIEW.json") != CANDIDATE_REVIEW_SHA256):
        raise ValueError("required exact independent sources/receipts changed")
    require_fixture_actual_audit(json.loads(evidence.read_text()))
    return plan
