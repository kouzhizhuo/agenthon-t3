"""Deterministic input/output contracts; unknown semantics are not inferred."""
import hashlib
import math
from pathlib import Path

TRACE_TYPES = {"t_ns": "int64", "agent_id": "int32", "msg_type": "string",
               "side": "string", "price": "int64", "size": "int64", "order_id": "int64"}
MESSAGE_TYPES = {"seq": "int64", "t_recv_ns": "int64", "t_send_ns": "Int64",
                 "latency_ns": "int64", "src_id": "int32", "dst_id": "int32",
                 "message_id": "int64", "msg_type": "string", "order_id": "Int64",
                 "causal_parent": "Int64"}
EVENT_TYPES = {"ORDER_SUBMITTED", "ORDER_ACCEPTED", "ORDER_FILLED", "PARTIAL_FILL",
               "ORDER_CANCELLED", "ORDER_REPLACED", "QUOTE_UPDATE"}


def validate_scenario(scenario):
    required = {"scenario_id", "seed", "horizon_ns", "agent_configs", "exchange_config", "oracle_config"}
    missing = required - set(scenario)
    if missing:
        raise ValueError("missing stated scenario fields: " + ", ".join(sorted(missing)))
    if not isinstance(scenario["seed"], int) or isinstance(scenario["seed"], bool):
        raise ValueError("seed must be an integer")
    if not isinstance(scenario["horizon_ns"], int) or scenario["horizon_ns"] <= 0:
        raise ValueError("horizon_ns must be a positive integer")
    if not isinstance(scenario["agent_configs"], list) or not scenario["agent_configs"]:
        raise ValueError("agent_configs is authoritative and must be nonempty")
    for config in scenario["agent_configs"]:
        if config["agent_type"] not in {"NoiseTrader", "MarketMaker", "ValueTrader", "MomentumTrader"}:
            raise ValueError("unsupported baseline agent type: " + str(config["agent_type"]))
        if not isinstance(config["count"], int) or config["count"] < 0:
            raise ValueError("agent count must be a nonnegative integer")
    latency = scenario.get("latency_config", {}).get("params", {})
    for key, value in latency.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError("nonfinite latency parameter " + key)
    lo, hi = latency.get("min_ns", 0), latency.get("max_ns", 1e12)
    if lo > hi:
        raise ValueError("latency minimum exceeds maximum")


def validate_frames(trace, messages):
    for name, frame, types in [("trace", trace, TRACE_TYPES), ("message_trace", messages, MESSAGE_TYPES)]:
        if list(frame.columns) != list(types):
            raise ValueError(name + " column order differs from stated contract")
        wrong = {k: str(frame[k].dtype) for k, dtype in types.items() if str(frame[k].dtype) != dtype}
        if wrong:
            raise ValueError(name + " dtype violations: " + repr(wrong))
        if frame.empty:
            raise ValueError(name + " must demonstrate actual simulation events")
    if not set(trace["msg_type"]).issubset(EVENT_TYPES):
        raise ValueError("unknown canonical event type")
    if not trace["side"].dropna().isin(["BID", "ASK"]).all():
        raise ValueError("unknown side encoding")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
