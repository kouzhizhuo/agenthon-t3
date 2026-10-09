"""Source-only archive helpers and the fixed native projection screen contract."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_canonical_projection_v2"
PARENT = "completion1009/candidates/observer_mixed_v2_authcache"
ARMS = ["observer_parent", "native_projection"]
ARM_CANDIDATES = {"observer_parent": PARENT, "native_projection": CANDIDATE}
IMAGE_CANDIDATE = "/opt/projection-screen/" + CANDIDATE
SOURCE_RECEIPT_SHA256 = "5b4c73f7fdc20df050cad77613eec674cce7a10adfb28a238b15557203c161ac"
PARENT_MANIFEST_SHA256 = "0803830c3fdd1977e6decc6cc89f1390a40fa2513a8f2c57814a737469ab17bf"
SINGLES = ["t3-s001-price-time-priority", "t3-as06-throughput-fast",
           "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid"]
BATCH = "t3-gbatch-hetero-mix"
MARKER = "T3_NATIVE_PROJECTION_SCREEN="
TIMING_SCOPE = "CLI ENTRY_STARTED through Parquet/hash; unchanged sidecar cutoff; marker serialization outside CLI timer"
MAX_FILES = 2048
MAX_BYTES = 128 * 1024 ** 2


def finite_names():
    return ['basic_lifecycle', 'unsorted_max_time_and_tied_final', 'equal_time_cross_agent_final_emission', 'negative_order_id_quote_collision', 'quote_last_write_first_insertion_tie', 'duplicate_quote_across_agents', 'mixed_all_order_kinds', 'missing_order_id_skips', 'agent_id_none_fallback', 'market_missing_limit_price', 'missing_fill_price_zero', 'nullable_side_string_array', 'side_bid_precedence', 'numpy_integral_types', 'int64_timestamp_extremes', 'timestamp_npint32_original_zero', 'bool_timestamp_original_integer', 'noninteger_timestamp_original_zero', 'integer53_edges', 'agent_int32_edges', 'rehash_many_fill_and_quote_keys', 'many_equal_keys_stable', 'large_negative_sort_keys', 'single_row_sort_zero_passes', 'raw_field_override_replay', 'raw_array_original_exception', 'out_of_integer53_replay', 'out_of_int32_agent_replay', 'float_quantity_replay', 'boolean_quantity_replay', 'quote_comma_symbol_replay', 'quote_float_price_replay', 'absent_scalar_inference_replay', 'empty_contract_replay', 'quotes_only_replay', 'huge_timestamp_replay', 'integer_timestamp_callback_replay', 'large_uint64_timestamp_original_zero', 'admission_compiled_export_replacement_refused', 'admission_mutable_dtype_constant_refused', 'helper_callable_replacement', 'helper_code_mutation', 'helper_default_mutation', 'helper_kwdefault_mutation', 'helper_global_import_alias', 'helper_proof_roster_mutation', 'cli_imported_projection_alias', 'numpy_empty_callable_replacement', 'numpy_int64_alias_replacement', 'pandas_array_callable_replacement', 'pandas_array_default_mutation', 'pandas_dataframe_alias_replacement', 'side_member_value_mutation', 'native_numpy_import_alias', 'compiled_projector_default_mutation', 'whole_episode_preprojection_numeric_mutation']


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
