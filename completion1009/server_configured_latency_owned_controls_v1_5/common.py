"""Stdlib pins for a finite configured-latency source experiment."""
import hashlib
import json
from pathlib import Path
import stat

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1_5.json"
CANDIDATE_SHA256 = "0efa23aab886f134b6eee109d72a689b3cf099da0b695650c8993d2b6641b5ef"
CANDIDATE_FILE_COUNT = 15
WRAPPER_RECEIPT = "SOURCE_PREPARATION_RECEIPT_v1_5.json"
WRAPPER_FILE_COUNT = 10
RUNTIME_RECEIPT = "RUNTIME_PINS.json"
RUNTIME_SHA256 = "ad2084b3097e0bc482e68388f4b7b8f946e2668529aa606a1ba94abeeeeb8a11"
MAX_FILES, MAX_BYTES = 256, 32 * 1024 * 1024
ENTRYPOINT = ["/usr/local/bin/python", "-B", "/opt/configured-latency-owned/control/entry.py"]
CASE_SPECS = [('uniform', {'model': 'uniform', 'params': {'min_ns': 0, 'max_ns': 2000}}, {}, {}, 700), ('lognormal', {'model': 'log_normal', 'params': {'mean_ns': 500, 'sigma': 1.2, 'max_ns': 2000}}, {}, {}, 700), ('pareto', {'model': 'pareto', 'params': {'min_ns': 1, 'max_ns': 2000, 'alpha': 1.5}}, {}, {}, 700), ('uniform_equal_still_draws', {'model': 'uniform', 'params': {'min_ns': 5, 'max_ns': 5}}, {}, {}, 20), ('lognormal_zero_sigma_still_draws', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': 0}}, {}, {}, 20), ('rollover622', {'model': 'uniform'}, {}, {'position': 622}, 700), ('rollover623', {'model': 'uniform'}, {}, {'position': 623}, 700), ('rollover624', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': 1.2}}, {}, {'position': 624}, 700), ('pending_positive_zero', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': 1.2}}, {}, {'has_gauss': 1, 'gauss': 0.0}, 20), ('pending_negative_zero', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': 1.2}}, {}, {'has_gauss': 1, 'gauss': -0.0}, 20), ('pending_nonzero', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': 1.2}}, {}, {'has_gauss': 1, 'gauss': -1.2345}, 20), ('lognormal_positive_overflow', {'model': 'log_normal', 'params': {'mean_ns': 1, 'sigma': 1}}, {'_mu': 710.0}, {}, 20), ('pareto_positive_overflow', {'model': 'pareto', 'params': {'alpha': 1e-300}}, {}, {}, 20), ('constant_unknown', {'model': 'source-unknown-constant', 'params': {'mean_ns': 1.5}}, {}, {}, 20), ('negativezero_sigma_fallback', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': -0.0}}, {}, {}, 5), ('negative_sigma_fallback', {'model': 'log_normal', 'params': {'mean_ns': 3, 'sigma': -1}}, {}, {}, 5), ('invalid_alpha_fallback', {'model': 'pareto', 'params': {'alpha': 0}}, {}, {}, 5), ('negative_bounds_fallback', {'model': 'uniform', 'params': {'min_ns': -3, 'max_ns': 3}}, {}, {}, 5), ('reversed_bounds_fallback', {'model': 'uniform', 'params': {'min_ns': 3, 'max_ns': 0}}, {}, {}, 5), ('nan_string_fallback', {'model': 'uniform', 'params': {'min_ns': 'nan', 'max_ns': 3}}, {}, {}, 5), ('infinity_string_fallback', {'model': 'uniform', 'params': {'min_ns': 0, 'max_ns': 'inf'}}, {}, {}, 5), ('nullfield_fallback', {'model': 'deterministic'}, {'_min_ns': None}, {}, 5), ('numpyfield_fallback', {'model': 'deterministic'}, {'_min_ns': 'NP_FLOAT64'}, {}, 5), ('arrayfield_fallback', {'model': 'deterministic'}, {'_min_ns': 'NP_ARRAY'}, {}, 5)]
CASE_COUNTS = {row[0]: row[4] for row in CASE_SPECS}
CALLS_PER_ARM = sum(CASE_COUNTS.values())


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
    if (receipt.get("schema") != "t3-configured-latency-owned-control-source-preparation-v1-5"
            or receipt.get("status") != "PREPARED_SOURCE_ONLY" or len(receipt["files"]) != CANDIDATE_FILE_COUNT):
        raise ValueError("exact frozen 15-file source roster required")
    verify_rows(root, receipt["files"])
    return receipt


def verify_runtime(root):
    root = Path(root)
    receipt_path = root / RUNTIME_RECEIPT
    if sha(receipt_path) != RUNTIME_SHA256:
        raise ValueError("exact original64 runtime receipt required")
    receipt = json.loads(receipt_path.read_bytes())
    if (receipt.get("schema") != "t3-lean-production-native-projection-runtime-pins-v1"
            or receipt.get("file_count") != 64 or len(receipt.get("files", [])) != 64
            or receipt.get("runtime_source_changes") != 0 or receipt.get("source_only") is not True):
        raise ValueError("exact unchanged original runtime roster required")
    verify_rows(root / "source", receipt["files"])
    expected = sorted(receipt["files"], key=lambda row: row["path"])
    if inventory(root / "source") != expected:
        raise ValueError("unmanifested original runtime source")
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
    if (plan.get("schema") != "t3-configured-latency-owned-finite-controls-plan-v1-5"
            or plan.get("frozen_source_inputs") is not True or plan.get("candidate_source_receipt_sha256") != CANDIDATE_SHA256
            or plan.get("runtime_source_receipt_sha256") != RUNTIME_SHA256
            or plan.get("native_builds") != 1 or plan.get("model_cases") != 24 or plan.get("calls_per_arm") != CALLS_PER_ARM
            or plan.get("arms") != ["original", "new", "new-repeat"] or plan.get("scalar_transforms") != 96
            or plan.get("market_controls") is not False or plan.get("minimum_host_free_bytes") != 4 * 1024**3
            or plan.get("controls_fsize_limit_bytes") != 1024**3):
        raise ValueError("exact finite latency single-build plan required")
    candidate = verify_candidate(root / "candidate")
    verify_runtime(root / "runtime")
    review_path = root / "source_review/INDEPENDENT_CANDIDATE_REVIEW.json"
    review = json.loads(review_path.read_bytes())
    if (sha(review_path) != plan.get("independent_candidate_review_sha256") or review.get("status") != "PASS_SOURCE_ONLY"
            or review.get("unresolved_source_blockers") != [] or review.get("reviewed_source_receipt_sha256") != CANDIDATE_SHA256
            or review.get("reviewed_files") != candidate["files"]):
        raise ValueError("exact independent candidate source PASS required")
    receipt_path = root / "source_review" / WRAPPER_RECEIPT
    wrapper = json.loads(receipt_path.read_bytes())
    if (sha(receipt_path) != plan.get("wrapper_source_receipt_sha256") or wrapper.get("source_frozen") is not True
            or wrapper.get("candidate_source_receipt_sha256") != CANDIDATE_SHA256
            or wrapper.get("runtime_source_receipt_sha256") != RUNTIME_SHA256 or len(wrapper["files"]) != WRAPPER_FILE_COUNT):
        raise ValueError("exact frozen ten-file wrapper receipt required")
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
