"""Source-only archive helpers and the fixed native book screen contract."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_book_owner_v2"
PARENT = CANDIDATE
ARMS = ["canonical_book", "native_book"]
ARM_CANDIDATES = {"canonical_book": PARENT, "native_book": CANDIDATE}
IMAGE_CANDIDATE = "/opt/book-screen/" + CANDIDATE
SOURCE_RECEIPT_SHA256 = "c3cf3e889c10cf380ddf1952090667911c841427974175720991afb116065604"
SINGLES = ["t3-s001-price-time-priority", "t3-as06-throughput-fast",
           "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid"]
BATCH = "t3-gbatch-hetero-mix"
MARKER = "T3_NATIVE_BOOK_SCREEN="
COUNTER_KEYS = ("match", "cancel", "insert", "read")
TIMING_SCOPE = "CLI ENTRY_STARTED through Parquet/hash/events wall; both-arm proof serialization after single wall; batch wall includes member proof serialization"
MAX_FILES = 2048
MAX_BYTES = 128 * 1024 ** 2


def finite_names():
    # Filled from an independent literal source-only roster audit after freeze.
    return FINITE_NAMES

FINITE_NAMES = [
    'level_fifo_hidden_duplicate_alias',
    'raw_queue_structural_alias',
    'level_comparison_BID',
    'level_comparison_ASK',
    'exact_sum_builtin_big',
    'exact_sum_numpy_int64_overflow',
    'exact_sum_numpy_uint64',
    'exact_sum_numpy_int32',
    'exact_sum_numpy_float32',
    'exact_sum_mixed_numpy_builtin',
    'exact_sum_builtin_float',
    'exact_sum_bool',
    'limit_multilevel_stp_BID_None',
    'limit_multilevel_stp_BID_cancel_oldest',
    'limit_multilevel_stp_BID_cancel_newest',
    'limit_multilevel_stp_BID_unknown_truthy',
    'limit_accept_quiet_BID_False',
    'limit_accept_quiet_BID_True',
    'market_multilevel_stp_BID_None',
    'market_multilevel_stp_BID_cancel_oldest',
    'market_multilevel_stp_BID_cancel_newest',
    'MR_post_only_BID_MR_preprocess_ADD',
    'MR_post_only_BID_MR_preprocess_REPLACE',
    'PTC_fill_BID_False',
    'PTC_fill_BID_True',
    'PTC_cancel_BID',
    'hidden_post_only_BID',
    'PTC_visible_execution_exception_residue_BID',
    'limit_multilevel_stp_ASK_None',
    'limit_multilevel_stp_ASK_cancel_oldest',
    'limit_multilevel_stp_ASK_cancel_newest',
    'limit_multilevel_stp_ASK_unknown_truthy',
    'limit_accept_quiet_ASK_False',
    'limit_accept_quiet_ASK_True',
    'market_multilevel_stp_ASK_None',
    'market_multilevel_stp_ASK_cancel_oldest',
    'market_multilevel_stp_ASK_cancel_newest',
    'MR_post_only_ASK_MR_preprocess_ADD',
    'MR_post_only_ASK_MR_preprocess_REPLACE',
    'PTC_fill_ASK_False',
    'PTC_fill_ASK_True',
    'PTC_cancel_ASK',
    'hidden_post_only_ASK',
    'PTC_visible_execution_exception_residue_ASK',
    'validation_handle_limit_order_zero',
    'validation_handle_limit_order_negative',
    'validation_handle_limit_order_fraction',
    'validation_handle_limit_order_numpy',
    'validation_handle_limit_order_price_negative',
    'validation_handle_limit_order_price_fraction',
    'validation_handle_limit_order_wrong_symbol',
    'validation_handle_limit_order_nan',
    'validation_handle_limit_order_huge',
    'validation_handle_market_order_zero',
    'validation_handle_market_order_negative',
    'validation_handle_market_order_fraction',
    'validation_handle_market_order_numpy',
    'validation_handle_market_order_price_negative',
    'validation_handle_market_order_price_fraction',
    'validation_handle_market_order_wrong_symbol',
    'validation_handle_market_order_nan',
    'validation_handle_market_order_huge',
    'read_depth_BID',
    'L1_hidden_only_BID',
    'L1_hidden_best_visible_next_BID',
    'read_depth_ASK',
    'L1_hidden_only_ASK',
    'L1_hidden_best_visible_next_ASK',
    'modify_partial_replace_False',
    'modify_partial_replace_True',
    'modify_partial_replace_None',
    'modify_partial_replace_1',
    'volume_windows',
    'padding_pretty_print_rng',
    'owner_witness_all_four',
]


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
