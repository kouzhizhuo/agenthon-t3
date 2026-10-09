"""Source-prepared two-arm diagnostic contract; no actual runtime claim."""
import hashlib
import json
from pathlib import Path, PurePosixPath
BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/pandas_free_canonical_outputs_v3"
BASELINE = "completion1009/candidates/lean_production_native_projection_v1/runtime"
SOURCE_RECEIPT_SHA256 = "96dd6883cdce8d9e6ff6703944cb16a8a0c99360c69810b3c1a7c6ed6b31bef1"
CANDIDATE_REVIEW_SHA256 = "0a49a943568b40dbe9414c40198cf25a2c9d767a1b95038142424af088a48997"
FIXTURE_ACTUAL_AUDIT_SHA256 = "0c9673c11158dec7faf5253da5bd9bfa5647841dd39ee748ab0a550f6b87e835"
FIXTURE_ARTIFACT_ZIP_SHA256 = "27dba5b9cff78e6f6505e87f649a9065da78a911574535ca0d3e1110bd9791e9"
FIXTURE_AUDITOR_SHA256 = "d8fa3962297a9beabc1abe64a7a29e38b014c3a230fa96757643911ab48bb6c2"
FIXTURE_SPEC_SHA256 = "1656104846dc4b249b64778611f53b88d86f184a740bb69bd4cae4638e46e006"
FIXTURE_PAYLOAD_SHA256 = "b2e3d18d2e3bb9287a0a1de546779bb33742b96aeec987313ffacf18cb6c4717"
FIXTURE_MANIFEST_PIN = {"bytes": 32985, "sha256": "ed5a9441425fa110e48406a4bf7da32516434d700ed679310f13455d3a802b08"}
FIXTURE_PLAN_PIN = {"bytes": 25343, "sha256": "5f900c16e8beafff1ff2fa67b00f91e70e5ea7d9c259085ddb1991f936b4f751"}
FIXTURE_RECEIPT_PIN = {"bytes": 16018, "sha256": SOURCE_RECEIPT_SHA256}
FIXTURE_WRAPPER_REVIEW_SHA256 = "89fbe6d18ee113dc5857e6fee3cf72eb21e1644cea66a1c4ebf2c96ba9926db5"
FIXTURE_AUDITOR = "completion1009/research/pandas_free_output_route_v1/saved_fixture_audit_v2/audit.py"
FIXTURE_SPEC = "completion1009/research/pandas_free_output_route_v1/saved_fixture_audit_v2/PREPARATION_SPEC_v2.json"
GENERATOR = "completion1009/research/pandas_free_output_route_v1/prepare_schema_metadata_source_v1.py"
GENERATOR_SHA256 = "aa60cd24b919446e881a6b849a4039b363c14e684ccd58bbd0cf9ad55cffeafe"
IMAGE_ROOT = "/opt/pandas-free-market-screen"
ENTRYPOINT = ["/usr/local/bin/python", "-B", IMAGE_ROOT + "/control/entry.py"]
ARMS = ("baseline", "new")
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
    if (actual.get("schema") != "t3-pandas-free-fixture-data-only-actual-audit-v2"
            or actual.get("all_passed") is not True or "failure" in actual
            or any(actual.get(key) is not False for key in ("rankable", "official_gate", "market_executed", "participant_imported"))
            or actual.get("source_auditor_sha256") != FIXTURE_AUDITOR_SHA256
            or actual.get("spec_sha256") != FIXTURE_SPEC_SHA256):
        raise ValueError("exact actual fixtureV2 data-only audit PASS required")
    retained = actual.get("retained_archive_inventory", {})
    expected = {"payload/PAYLOAD_MANIFEST.json": FIXTURE_MANIFEST_PIN,
                "payload/FIXTURE_PLAN.json": FIXTURE_PLAN_PIN,
                "payload/" + CANDIDATE + "/SOURCE_PREPARATION_RECEIPT_v3.json": FIXTURE_RECEIPT_PIN}
    if any(retained.get(name) != pin for name, pin in expected.items()):
        raise ValueError("actual fixture archive manifest/plan/frozenV3 binding differs")
    commands = actual.get("commands", {})
    if commands.get("resources_verified") is not True or commands.get("both_cleanup_returncodes_zero") is not True or commands.get("commands") != 12:
        raise ValueError("actual fixture resource/build/cleanup checks absent")
    fixture = actual.get("fixtures", {})
    if (fixture.get("public_time_cases") != 16 or fixture.get("normal_return_cases") != 8
            or fixture.get("sentinel_throw_cases") != 3 or fixture.get("general_fallback_cases") != 4
            or fixture.get("full_serializer_group_calls") != 12
            or fixture.get("primary_API_equal") is not True
            or fixture.get("cold_final_attempt_lists_empty") is not True):
        raise ValueError("actual fixtureV2 signed64/NaT/cold/serializer controls absent")
    decoded = fixture.get("decoded_retained_parquets", [])
    if (len(decoded) != 6 or {(row.get("arm"), row.get("table")) for row in decoded}
            != {(arm, name) for arm in ("baseline", "new", "cold-new") for name in ("trace", "message_trace")}):
        raise ValueError("actual six retained fixture Parquet decode roster absent")


def verify_payload(root):
    root = Path(root); manifest = json.loads((root / "PAYLOAD_MANIFEST.json").read_text())
    actual = inventory(root); actual.pop("PAYLOAD_MANIFEST.json", None); actual.pop("MATERIALIZATION.json", None)
    if actual != manifest["files"]: raise ValueError("source payload differs")
    plan = json.loads((root / "SCREEN_PLAN.json").read_text())
    if (plan.get("schema") != "t3-pandas-free-market-screen-source-plan-v2"
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
        raise ValueError("frozenV3/corrected fixtureV2 required pins differ")
    evidence = root / "control/ACTUAL_FIXTURE_AUDIT.json"
    if sha(evidence) != FIXTURE_ACTUAL_AUDIT_SHA256:
        raise ValueError("actual fixture audit receipt bytes changed")
    if (sha(root / "control/FIXTURE_DATA_AUDITOR_v2.py") != FIXTURE_AUDITOR_SHA256
            or sha(root / "control/FIXTURE_DATA_AUDIT_SPEC_v2.json") != FIXTURE_SPEC_SHA256
            or sha(root / "control/INDEPENDENT_WRAPPER_SOURCE_REVIEW.json") != plan["independent_wrapper_review_sha256"]
            or sha(root / "control/INDEPENDENT_CANDIDATE_SOURCE_REVIEW.json") != CANDIDATE_REVIEW_SHA256):
        raise ValueError("required exact independent sources/receipts changed")
    require_fixture_actual_audit(json.loads(evidence.read_text()))
    return plan
