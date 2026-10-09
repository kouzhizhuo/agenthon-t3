"""Source-only archive helpers and the fixed native exchange screen contract."""
import hashlib
import json
from pathlib import Path, PurePosixPath

BASE = "ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb"
CANDIDATE = "completion1009/candidates/native_core_spine_exchange_v2"
PARENT = "completion1009/candidates/native_core_spine_counters_v2"
ARMS = ["native_reference", "native_exchange"]
ARM_CANDIDATES = {"native_reference": PARENT, "native_exchange": CANDIDATE}
IMAGE_CANDIDATE = "/opt/exchange-screen/" + CANDIDATE
SOURCE_RECEIPT_SHA256 = "90875ba3dff71cf24ad1f2b745c4fece5805c8a43b4346f2541c8a0e492fa250"
PARENT_SOURCE_RECEIPT_SHA256 = "85c0b984af7716c15b0e724c38f969e6100ee52183fb4aabb7bd284e173a4531"
SINGLES = ["t3-s001-price-time-priority", "t3-as06-throughput-fast",
           "t3-mp01-stp-newest-baseline", "t3-ra01-fundamental-shock-mid"]
BATCH = "t3-gbatch-hetero-mix"
MARKER = "T3_NATIVE_EXCHANGE_SCREEN="
COUNTER_KEYS = ("pop", "requeue", "wake", "receive", "act", "exchange_query",
    "exchange_book_bridge", "raw_strategy_bridge", "send", "oracle_bridge")
TIMING_SCOPE = "CLI ENTRY_STARTED through Parquet/hash; unchanged sidecar cutoff; marker serialization outside CLI timer"
MAX_FILES = 2048
MAX_BYTES = 128 * 1024 ** 2


def finite_names():
    names = ["calendar_builtin_huge_shared_raw_identity", "calendar_numpy_scalar_shared_raw_identity",
             "calendar_actual_dataclass_equality_sameuid_and_broadcast"]
    operations = ("wake_initial", "wake_open", "wake_closed", "spread_empty",
                  "spread_bid", "spread_ask", "spread_both", "spread_closed")
    names += ["strategy_" + str(kind) + "_" + operation for kind in (1, 2, 3, 4) for operation in operations]
    notifications = (("OrderAcceptedMsg", 7, True), ("OrderExecutedMsg", 2, True),
        ("OrderExecutedMsg", 7, True), ("OrderExecutedMsg", 9, False),
        ("OrderCancelledMsg", 7, True), ("OrderCancelledMsg", 7, False))
    names += ["strategy_" + str(kind) + "_" + cls + "_" + str(quantity) + "_" + str(owned)
              for kind in (1, 2, 3, 4) for cls, quantity, owned in notifications]
    names += ["runner_per_pop_" + label for label in ("batch_subuids", "previous_clock_stop", "busy_requeue")]
    names += ["runner_live_batch_bound_list_rebind_per_subcallback_delay_and_uid",
              "admission_original_default_mutation_refused", "admission_compiled_export_replacement_refused"]
    keys = COUNTER_KEYS
    names += ["counter_" + key + suffix for key in keys for suffix in
        ("_cross_uint64_real_operations", "_huge_pylong_real_operations")]
    names += ["counter_seed_invalid_inputs_atomic_and_unmarked",
        "counter_invalid_seed_preserves_existing_spill_and_mark",
        "counter_fresh_ordered_snapshot_and_sticky_seed_mark",
        "counter_two_slots_spill_through_shared_storage",
        "counter_pop_commit_before_debug_exception", "counter_requeue_commit_before_debug_exception",
        "counter_send_commit_before_test_only_ledger_exception",
        "counter_receive_commit_before_promoted_warning", "counter_seeded_production_capture_refused",
        "counter_seed_export_replacement_refused"]
    names += [
        'exchange_resting_default',
        'exchange_resting_log_none',
        'exchange_resting_order_logs',
        'exchange_resting_ack_owner_differs_sender',
        'exchange_resting_log_events_false',
        'exchange_preopen_allowed',
        'exchange_at_close_allowed',
        'exchange_after_close_rejected',
        'exchange_after_close_unknown_no_warning',
        'exchange_after_close_cancel_reply_sender',
        'exchange_after_close_limit_compute_without_pipeline_debug',
        'exchange_after_close_cancel_compute_without_pipeline',
        'exchange_cross_partial',
        'exchange_cross_full',
        'exchange_cross_residual',
        'exchange_cancel_bid',
        'exchange_cancel_ask',
        'exchange_cancel_missing',
        'exchange_cancel_wrong_price',
        'exchange_cancel_auction_metadata_live_alias',
        'exchange_unknown_limit',
        'exchange_unknown_cancel',
        'exchange_zero_quantity',
        'exchange_noninteger_quantity',
        'exchange_negative_price',
        'exchange_noninteger_price',
        'exchange_unknown_warning_exception_residue',
        'exchange_unknown_cancel_warning_exception_residue',
        'exchange_invalid_warning_exception_residue',
        'exchange_nan_quantity_conversion_exception_residue',
        'exchange_publish_exception_after_accepted_residue',
        'exchange_publish_exception_after_invalid_residue',
        'exchange_publish_exception_after_missing_cancel_residue',
        'exchange_stp_cancel_newest',
        'exchange_stp_cancel_oldest',
        'exchange_ack_compute_additional_batch_delay',
        'exchange_l1_publication_valid',
        'exchange_l1_publication_invalid',
        'exchange_l1_publication_missing_cancel',
        'exchange_hidden_limit',
        'exchange_price_to_comply_limit',
        'exchange_post_only_tag',
        'exchange_limit_subclass_original_handler',
        'exchange_cancel_subclass_original_handler',
        'exchange_market_original_handler',
        'exchange_modify_original_handler',
        'exchange_partial_cancel_original_handler',
        'exchange_replace_original_handler',
        'exchange_exchange_debug_retained',
        'exchange_base_debug_retained',
        'exchange_base_debug_argument_clock_retained',
        'exchange_cancel_logs_false',
        'exchange_cancel_log_events_false',
        'exchange_dynamic_order_attribute_copy_omission',
        'exchange_mutable_tag_copy_and_graph',
        'exchange_official_protocol_disabled_builder_knobs',
        'exchange_official_protocol_enabled_builder_knobs',
    ]
    return names


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
