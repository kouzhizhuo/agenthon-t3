"""Extract the canonical Track 3 message trace from an ABIDES ``end_state``.

ABIDES logs per-agent events; ``abides_core.utils.parse_logs_df`` flattens them
into a DataFrame. This module maps the relevant ABIDES event types onto the
canonical 7-column ``trace.parquet`` schema defined in
``templates/trace_column_registry.json``:

    [t_ns, agent_id, msg_type, side, price, size, order_id]

ABIDES event type      -> canonical msg_type
    ORDER_SUBMITTED     -> ORDER_SUBMITTED
    ORDER_ACCEPTED      -> ORDER_ACCEPTED
    ORDER_EXECUTED      -> PARTIAL_FILL (non-final per order) / ORDER_FILLED (final)
    ORDER_CANCELLED     -> ORDER_CANCELLED
    ORDER_REPLACED      -> ORDER_REPLACED
    BEST_BID / BEST_ASK -> QUOTE_UPDATE (side BID / ASK)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from abides_core.utils import parse_logs_df
from abides_markets.orders import Side

TRACE_COLUMNS: list[str] = [
    "t_ns",
    "agent_id",
    "msg_type",
    "side",
    "price",
    "size",
    "order_id",
]

# ABIDES EventType -> canonical msg_type for order-lifecycle events whose price
# is the order's limit price. ORDER_EXECUTED is handled separately (fill price,
# and the PARTIAL_FILL / ORDER_FILLED split).
_ORDER_EVENT_MAP: dict[str, str] = {
    "ORDER_SUBMITTED": "ORDER_SUBMITTED",
    "ORDER_ACCEPTED": "ORDER_ACCEPTED",
    "ORDER_CANCELLED": "ORDER_CANCELLED",
    "ORDER_REPLACED": "ORDER_REPLACED",
}

_TRACE_DTYPES: dict[str, str] = {
    "t_ns": "int64",
    "agent_id": "int32",
    "msg_type": "string",
    "side": "string",
    "price": "int64",
    "size": "int64",
    "order_id": "int64",
}

# --- v2 enriched message-level trace (companion to the order-event trace) --------------
# One row per DELIVERED (sub)message from the kernel ledger, carrying the network + causal
# metadata the v2 latency / event-order / wakeup / reactive / protocol gates need. This is a
# SEPARATE table (message granularity != order-event granularity), so trace.parquet stays a
# byte-for-byte v1 superset and existing Tier-A/Tier-B/stylized checks are unaffected.
MESSAGE_TRACE_COLUMNS: list[str] = [
    "seq",
    "t_recv_ns",
    "t_send_ns",
    "latency_ns",
    "src_id",
    "dst_id",
    "message_id",
    "msg_type",
    "order_id",
    "causal_parent",
]

_MSG_DTYPES: dict[str, str] = {
    "seq": "int64",
    "t_recv_ns": "int64",
    "t_send_ns": "Int64",  # nullable: wakeups have no send time
    "latency_ns": "int64",
    "src_id": "int32",
    "dst_id": "int32",
    "message_id": "int64",
    "msg_type": "string",
    "order_id": "Int64",  # nullable: non-order messages
    "causal_parent": "Int64",  # nullable: root events
}


def _side_to_str(value: Any) -> str | None:
    """Normalize an ABIDES ``Side`` enum (or string) to ``"BID"`` / ``"ASK"``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    enum_val = getattr(value, "value", None)
    if enum_val in ("BID", "ASK"):
        return str(enum_val)
    text = str(value).upper()
    if "BID" in text:
        return "BID"
    if "ASK" in text:
        return "ASK"
    return None


_RAW_TRACE_FIELDS = ("EventTime", "EventType", "ScalarEventValue", "agent_id", "order_id", "side", "quantity", "limit_price", "fill_price")


def _parse_trace_logs(end_state):
    """Project unused log fields before pandas inference, retaining every row/index.

    Per-agent inference and concatenation stay identical to parse_logs_df. Keeping
    all rows preserves missing-value promotion and the original emission order.
    """
    frames = []
    for agent in end_state["agents"]:
        messages = []
        for event_time, event_type, event in agent.log:
            row = {"EventTime": event_time if isinstance(event_time, (int, np.int64)) else 0,
                   "EventType": event_type}
            if event == None:
                pass
            elif isinstance(event, dict):
                for key in _RAW_TRACE_FIELDS:
                    if key in event:
                        row[key] = event[key]
            else:
                row["ScalarEventValue"] = event
            if row.get("agent_id") == None:
                row["agent_id"] = agent.id
            messages.append(row)
        frames.append(pd.DataFrame(messages))
    return pd.concat(frames)


def _canonical_trace(end_state):
    """Materialize canonical pinned-engine events without an exploratory wide frame.

    Restrict this path to exact integral payloads representable by the original
    pandas float promotion. Noncanonical/custom log payloads retain the original
    extractor. Agent order, emission order and both stable sorts are preserved.
    """
    events = []
    quotes = {}
    final_exec = {}
    has_scalar_column = False
    integer_types = (int, np.int64, np.int32)
    def exact_integer(value):
        return type(value) in integer_types and -(1 << 53) <= value <= (1 << 53)
    for agent in end_state["agents"]:
        for timestamp, event_type, payload in agent.log:
            if isinstance(timestamp, (int, np.int64)) and not -(1 << 63) <= timestamp < (1 << 63):
                return None
            # parse_logs_df tests every payload, including diagnostics. Keep its
            # equality behavior (e.g. array truth-value errors), and defer unusual
            # objects that compare equal to None to the original extraction path.
            if payload == None and payload is not None:
                return None
            if payload is not None and (not isinstance(payload, dict) or "ScalarEventValue" in payload):
                has_scalar_column = True
            if isinstance(payload, dict) and ("EventTime" in payload or "EventType" in payload):
                return None
            if event_type in _ORDER_EVENT_MAP or event_type == "ORDER_EXECUTED":
                if type(payload) is not dict or "EventTime" in payload or "EventType" in payload:
                    return None
                oid = payload.get("order_id")
                if oid is None:
                    continue
                aid = payload.get("agent_id")
                if aid is None:
                    aid = agent.id
                quantity = payload.get("quantity")
                price = payload.get("fill_price" if event_type == "ORDER_EXECUTED" else "limit_price")
                if not exact_integer(oid) or not exact_integer(aid) or not -(1 << 31) <= aid < (1 << 31) or not exact_integer(quantity) or (price is not None and not exact_integer(price)) or "side" not in payload:
                    return None
                if not isinstance(timestamp, (int, np.int64)):
                    timestamp = 0
                if not -(1 << 63) <= timestamp < (1 << 63) or type(payload.get("side")) not in (Side, str, type(None)):
                    return None
                side = _side_to_str(payload.get("side"))
                events.append([int(timestamp), int(aid), event_type, side, 0 if price is None else int(price), int(quantity), int(oid)])
            elif event_type in ("BEST_BID", "BEST_ASK"):
                if type(payload) is not str:
                    return None
                fields = payload.split(",")
                if len(fields) != 3:
                    return None
                try:
                    price, quantity = int(fields[1]), int(fields[2])
                except ValueError:
                    return None
                if str(price) != fields[1] or str(quantity) != fields[2] or not exact_integer(price) or not exact_integer(quantity):
                    return None
                if not exact_integer(agent.id) or not -(1 << 31) <= agent.id < (1 << 31):
                    return None
                if not isinstance(timestamp, (int, np.int64)):
                    timestamp = 0
                if not -(1 << 63) <= timestamp < (1 << 63):
                    return None
                timestamp = int(timestamp)
                side = "BID" if event_type == "BEST_BID" else "ASK"
                key = (timestamp, side)
                # Updating a value retains dict's original first-insertion order.
                quotes[key] = [timestamp, int(agent.id), "QUOTE_UPDATE", side, price, quantity, -1]
    if not events or not has_scalar_column:
        return None
    events.sort(key=lambda row: row[0])
    for index, row in enumerate(events):
        if row[2] == "ORDER_EXECUTED":
            final_exec[row[6]] = index
    for index, row in enumerate(events):
        if row[2] == "ORDER_EXECUTED":
            row[2] = "ORDER_FILLED" if final_exec[row[6]] == index else "PARTIAL_FILL"
        else:
            row[2] = _ORDER_EVENT_MAP[row[2]]
    events.extend(quotes.values())
    events.sort(key=lambda row: (row[0], row[6]))
    columns = {}
    for index, name in enumerate(TRACE_COLUMNS):
        dtype = _TRACE_DTYPES[name]
        if dtype in ("int64", "int32"):
            columns[name] = np.fromiter((row[index] for row in events), dtype=dtype, count=len(events))
        else:
            columns[name] = pd.array([row[index] for row in events], dtype="string")
    return pd.DataFrame(columns, columns=TRACE_COLUMNS)


def extract_trace(end_state: dict[str, Any]) -> pd.DataFrame:
    """Build the canonical 7-column trace DataFrame from an ABIDES ``end_state``.

    Args:
        end_state: the dict returned by ``abides_core.abides.run``.

    Returns:
        A DataFrame with columns ``TRACE_COLUMNS`` and canonical dtypes, sorted by
        ``(t_ns, order_id)``.
    """
    canonical = _canonical_trace(end_state)
    if canonical is not None:
        return canonical
    raw = _parse_trace_logs(end_state)

    # --- order-lifecycle events (rows carrying an order_id), vectorized ---------
    # parse_logs_df returns a non-unique index (per-agent row numbers); sort by
    # EventTime and reset so the final-execution lookup is positionally unambiguous
    # and the post-sort tie order is the causal (processing) order.
    orders = (
        raw[raw["order_id"].notna()]
        .sort_values("EventTime", kind="stable")
        .reset_index(drop=True)
    )
    keep = orders["EventType"].isin(_ORDER_EVENT_MAP.keys()) | (
        orders["EventType"] == "ORDER_EXECUTED"
    )
    o = orders[keep].reset_index(drop=True)
    is_exec = o["EventType"] == "ORDER_EXECUTED"
    # The final ORDER_EXECUTED per order_id is the ORDER_FILLED; earlier ones are
    # PARTIAL_FILL ("final" = last occurrence per order_id in EventTime order).
    final_pos = o[is_exec].drop_duplicates("order_id", keep="last").index
    is_final = o.index.isin(final_pos)
    msg_type = (
        o["EventType"]
        .map(_ORDER_EVENT_MAP)
        .where(
            ~is_exec,
            pd.Series(
                np.where(is_final, "ORDER_FILLED", "PARTIAL_FILL"), index=o.index
            ),
        )
    )
    # ORDER_EXECUTED rows carry the fill price; lifecycle rows carry the limit price.
    # Reference the columns lazily so a fills-only / no-fills trace cannot KeyError.
    limit_price = (
        o["limit_price"]
        if "limit_price" in o.columns
        else pd.Series(np.nan, index=o.index)
    )
    fill_price = (
        o["fill_price"]
        if "fill_price" in o.columns
        else pd.Series(np.nan, index=o.index)
    )
    price = limit_price.where(~is_exec, fill_price)
    # Normalize the Side enum once per distinct value, then map (C-level) — much
    # cheaper than calling _side_to_str on every row at F6 scale.
    side_map = {v: _side_to_str(v) for v in o["side"].dropna().unique()}
    order_df = pd.DataFrame(
        {
            "t_ns": o["EventTime"],
            "agent_id": o["agent_id"],
            "msg_type": msg_type,
            "side": o["side"].map(side_map),
            "price": price,
            "size": o["quantity"],
            "order_id": o["order_id"],
        }
    )

    # --- quote events: BEST_BID / BEST_ASK -> QUOTE_UPDATE (vectorized) ---------
    # ABIDES emits a best-bid/ask event per book change, so several land on the same
    # nanosecond as an agent posts a price ladder. Keep only the final quote per
    # (t_ns, side): the resting best price at that instant. This keeps quote timestamps
    # unique per side (the scorer's mid-price series reindexes on them and cannot
    # tolerate duplicate labels). "Final" = last occurrence in emission order; the
    # surviving rows are ordered by each (t_ns, side)'s first appearance.
    quotes = raw[raw["EventType"].isin(["BEST_BID", "BEST_ASK"])]
    qparts = quotes["ScalarEventValue"].astype(str).str.split(",", expand=True)
    if qparts.shape[1] >= 3:
        # ScalarEventValue is "SYMBOL,price,volume" -> exactly two commas, int fields.
        q_price = pd.to_numeric(qparts[1], errors="coerce")
        q_size = pd.to_numeric(qparts[2], errors="coerce")
        valid = (
            (quotes["ScalarEventValue"].astype(str).str.count(",") == 2)
            & q_price.notna()
            & q_size.notna()
        )
    else:
        valid = pd.Series(False, index=quotes.index)
    qv = quotes[valid].reset_index(drop=True)
    if qv.empty:
        quote_df = pd.DataFrame(columns=TRACE_COLUMNS)
    else:
        side = pd.Series(
            np.where(qv["EventType"] == "BEST_BID", "BID", "ASK"), index=qv.index
        )
        # factorize gives each (t_ns, side) a rank by first appearance == the order a
        # dict keyed on first insertion would yield.
        key = qv["EventTime"].astype("int64").astype(str) + "|" + side
        quote_df = pd.DataFrame(
            {
                "t_ns": qv["EventTime"],
                "agent_id": qv["agent_id"],
                "msg_type": "QUOTE_UPDATE",
                "side": side,
                "price": q_price[valid].to_numpy(),
                "size": q_size[valid].to_numpy(),
                "order_id": -1,
                "_rank": pd.factorize(key)[0],
            }
        )
        quote_df = (
            quote_df.drop_duplicates(["t_ns", "side"], keep="last")
            .sort_values("_rank", kind="stable")
            .drop(columns="_rank")
        )

    # --- combine, fill missing numerics, sort canonically ----------------------
    trace = pd.concat([order_df, quote_df], ignore_index=True)
    if trace.empty:
        return trace.astype(_TRACE_DTYPES)
    trace["price"] = trace["price"].fillna(0)
    trace["size"] = trace["size"].fillna(0)
    trace["order_id"] = trace["order_id"].fillna(-1)
    trace = trace.sort_values(["t_ns", "order_id"], kind="stable").reset_index(
        drop=True
    )
    return trace.astype(_TRACE_DTYPES)


def _extract_message_trace_original(end_state: dict[str, Any]) -> pd.DataFrame:
    """Build the v2 message-level enriched trace from the kernel ledger in ``end_state``.

    Companion to the order-lifecycle ``trace.parquet``: one row per DELIVERED (sub)message,
    ordered by the faithful kernel processing order (``seq``). Requires the
    ``kernel_message_ledger`` patch (``end_state["message_ledger"]`` +
    ``end_state["deliver_seq_by_key"]``); returns an empty typed frame if absent.

    Args:
        end_state: the dict returned by ``abides_core.abides.run``.

    Returns:
        A DataFrame with columns ``MESSAGE_TRACE_COLUMNS`` and canonical dtypes.
    """
    ledger = end_state.get("message_ledger") or []
    seqmap = end_state.get("deliver_seq_by_key") or {}
    empty = pd.DataFrame({c: [] for c in MESSAGE_TRACE_COLUMNS}).astype(_MSG_DTYPES)
    if not ledger:
        return empty

    # Attach the faithful delivery seq (keyed by (message_id, recipient) — a broadcast message
    # carries one id but N deliveries) and keep only DELIVERED rows (undelivered sends past
    # stop_time have no seq). Sort by processing order.
    rows = [
        (seq, r)
        for r in ledger
        if (seq := seqmap.get((int(r["message_id"]), int(r["dst_id"])))) is not None
    ]
    if not rows:
        return empty
    rows.sort(key=lambda sr: sr[0])
    led = [r for _, r in rows]

    # The nullable-int columns (t_send_ns, order_id, causal_parent) MUST be built as Int64
    # directly: routing None+int through pandas' float64 inference silently rounds the ~1.6e18 ns
    # timestamps (float64 has ~15-16 sig figs), breaking t_recv - t_send == latency_ns. The
    # remaining columns have no nulls, so plain lists infer exact int64/string before astype.
    df = pd.DataFrame(
        {
            "seq": [s for s, _ in rows],
            "t_recv_ns": [r["t_recv_ns"] for r in led],
            "t_send_ns": pd.array([r["t_send_ns"] for r in led], dtype="Int64"),
            "latency_ns": [r["latency_ns"] for r in led],
            "src_id": [r["src_id"] for r in led],
            "dst_id": [r["dst_id"] for r in led],
            "message_id": [r["message_id"] for r in led],
            "msg_type": [r["msg_type"] for r in led],
            "order_id": pd.array([r["order_id"] for r in led], dtype="Int64"),
            "causal_parent": pd.array([r["causal_parent"] for r in led], dtype="Int64"),
        }
    ).astype(_MSG_DTYPES)
    return df[MESSAGE_TRACE_COLUMNS]


def extract_message_trace(end_state: dict[str, Any]) -> pd.DataFrame:
    """Bulk exact integer projection of the original filtered/sorted ledger.

    NumPy integer inference never passes nanosecond values through floats.
    Other inference domains retain the unchanged original extractor. Nullable
    arrays use the same explicit Pandas construction as the original.
    """
    ledger = end_state.get("message_ledger") or []
    seqmap = end_state.get("deliver_seq_by_key") or {}
    if type(ledger) is not list or type(seqmap) is not dict or not ledger:
        return _extract_message_trace_original(end_state)
    try:
        rows = [(seq, row) for row in ledger
            if (seq := seqmap.get((int(row["message_id"]), int(row["dst_id"])))) is not None]
        if not rows:
            return _extract_message_trace_original(end_state)
        rows.sort(key=lambda sr: sr[0])
        led = [row for _, row in rows]
        columns = {}
        for name, dtype in _MSG_DTYPES.items():
            values = [seq for seq, _ in rows] if name == "seq" else [row[name] for row in led]
            if dtype in ("string", "Int64"):
                columns[name] = pd.array(values, dtype=dtype)
            else:
                numbers = np.asarray(values)
                if numbers.dtype.kind not in ("b", "i"):
                    return _extract_message_trace_original(end_state)
                lower, upper = (-(1 << 31), 1 << 31) if dtype == "int32" else (-(1 << 63), 1 << 63)
                if np.any(numbers < lower) or np.any(numbers >= upper):
                    return _extract_message_trace_original(end_state)
                columns[name] = numbers.astype(dtype, copy=False)
        return pd.DataFrame(columns, columns=MESSAGE_TRACE_COLUMNS)
    except (TypeError, ValueError, KeyError, OverflowError):
        return _extract_message_trace_original(end_state)
