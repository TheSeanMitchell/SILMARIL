"""
silmaril.execution.forensics — Alpha 6.3 P2 execution-quality forensics.

WHAT THIS IS
------------
A deterministic JOIN that turns the order/fill records the broker bridge
already writes (alpaca_*_state.json: `orders`, `positions_snapshot`,
`errors`) plus the INTENDED levels from the trade plan into a per-trade
execution-quality forensic. It answers, for one (account, ticker):

    • what did we intend         (intended entry/stop/target from the plan)
    • what actually happened       (order timeline, real fill prices, qty)
    • why quality differed          (realized vs modeled slippage, spread)
    • what damaged/improved it      (limit vs market, partial scaling)
    • broker vs internal cause      (submitted flag + broker error stream)

DESIGN CONTRACT — extends, does not fork
----------------------------------------
  * Introduces NO new state file and NO new pipeline. It reads emitters the
    running cycle already writes and returns a dict that is embedded into the
    `execution` section of the canonical TradeCaseFile. One schema.
  * Operationalises silmaril.learning.slippage (previously an orphan with no
    caller) by using it to compute the EXPECTED slippage band that realised
    fill slippage is measured against.

HONESTY (observational by nature)
---------------------------------
Execution forensics MEASURES quality; it does not itself change decisions.
The systems that change execution behaviour (order_quality → limit/defer,
hard_stops → trail tighten/halt, correlation_book → block) are already
operational in the executor; this module measures their EFFECT.

Two values are explicitly NOT fabricated:
  * latency — order records carry a single timestamp (no submit→ack→fill
    pair), so true latency is reported as not measurable, with the reason.
  * spread  — modeled per ticker (no live bid/ask is stored), labeled modeled.

PHASE-3 CONFIDENCE SPLIT (canonical contract — read before consuming)
---------------------------------------------------------------------
`execution_confidence` (+ `_label`) is DEPRECATED and observational. It mixes
fill-derived signal with non-execution state and is retained byte-identically
ONLY for compatibility with its one existing consumer
(`portfolios/move_attribution.py`). It is NOT a policy candidate.

1. `fill_quality_confidence` (policy-eligible LATER; strictly fill-derived)
   • Derived ONLY from realized executed-fill quality.
   • Executed evidence in THIS architecture = a broker-reported HELD position
     (`positions_snapshot.avg_entry_price`). `submitted`/accepted orders are
     submission/intent artifacts, NOT fill evidence, and are never used here.
   • `fill_quality_basis` ∈ {"held_snapshot_avg_entry", "none"} records the
     provenance. "submitted_open_order" is intentionally absent; a future
     "confirmed_fill"/"filled_avg_price" basis may be added ONLY if the broker
     layer later persists real fill-price evidence.
   • NULL SEMANTICS: with no executed-fill evidence (basis="none") OR no
     intended reference to grade against, the value is JSON `null` and the
     label is "not_measurable". `null` means "not measurable due to lack of
     executed-fill evidence" and is SEMANTICALLY DISTINCT from 0, "degraded",
     a missing key, NaN, and empty string. Absence of execution evidence is
     NOT evidence of bad execution quality. Serializers MUST NOT coerce
     null → 0 or a default.
   • HOLD-NEUTRAL invariant (future P4.5 consumers): when null/not_measurable,
     a consumer MUST hold neutral — no adjustment, never infer degradation.
   • CERTAINTY LIMIT: `held_snapshot_avg_entry` is evidence of a held executed
     position ONLY. It does NOT imply execution-timing precision, exact fill
     path, fill completeness, experienced spread, or slippage-causality
     certainty. It is not a perfect execution ledger; future work MUST NOT
     over-ascribe certainty to snapshot-derived evidence.

2. `non_execution_state` (observational only; transport/provenance, NOT a
   causal diagnosis). Never feeds policy/weight/freeze/allocation/suppression.
   `broker_submission_failures` counts ONLY orders with `submitted is False`
   EXPLICITLY. Missing/absent `submitted`, accepted-but-unfilled opens, and
   no-fill cycles are NOT counted. It means "explicitly observed failed
   submission state" — NOT "probably failed"/"not filled"/"not executed".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _f(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def _parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _asset_class_for(ticker: str) -> str:
    t = (ticker or "").upper()
    if t.endswith("-USD") or t.endswith("USD") and "-" in t:
        return "crypto"
    return "equity"


def build_execution_forensics(
    orders: List[Dict[str, Any]],
    snapshot_row: Optional[Dict[str, Any]],
    intended: Optional[Dict[str, Any]] = None,
    broker_errors: Optional[List[Dict[str, Any]]] = None,
    ticker: str = "",
    asset_class: Optional[str] = None,
    realized_vol: Optional[float] = None,
    now: Optional[datetime] = None,
    intended_entry_epoch_match: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return the execution-quality forensic for one (account, ticker).

    Never raises. With no order records it returns a populated, honest
    'no execution recorded' forensic rather than a fake one.
    """
    n_now = now or _now()
    orders = orders or []
    intended = intended or {}
    broker_errors = broker_errors or []
    asset_class = asset_class or _asset_class_for(ticker)

    # ── order timeline (chronological, real fields only) ──────────
    timeline: List[Dict[str, Any]] = []
    for o in sorted(orders, key=lambda r: str(r.get("time") or r.get("timestamp") or "")):
        timeline.append({
            "action": o.get("action"),
            "side": o.get("side"),
            "price": _f(o.get("entry_price")) if o.get("action") == "OPEN" else _f(o.get("exit_price")),
            "qty": _f(o.get("qty")),
            "notional": _f(o.get("notional")),
            "submitted": bool(o.get("submitted")),
            "use_limit": bool(o.get("use_limit")),
            "limit_buffer_bps": _f(o.get("limit_buffer_bps")),
            "realized_pnl": _f(o.get("realized_pnl")),
            "trigger_reason": o.get("trigger_reason") or o.get("directive"),
            "synthetic_from_rotation": bool(o.get("synthetic_from_rotation")),
            "time": o.get("time") or o.get("timestamp"),
        })

    opens = [t for t in timeline if t["action"] == "OPEN"]
    closes = [t for t in timeline if t["action"] == "CLOSE"]
    stop_adjusts = [t for t in timeline if t["action"] == "STOP_ADJUST"]

    # ── fill quality: intended vs actual ──────────────────────────
    intended_entry = _f(intended.get("intended_entry"))
    actual_entry = None
    # prefer actual fill from first OPEN order; fall back to snapshot avg
    for t in opens:
        if t["price"]:
            actual_entry = t["price"]
            break
    if actual_entry is None and snapshot_row:
        actual_entry = _f(snapshot_row.get("avg_entry_price"))

    fill_diff_pct = None
    slippage_bps_realized = None
    if intended_entry and actual_entry and intended_entry > 0:
        fill_diff_pct = round((actual_entry - intended_entry) / intended_entry, 6)
        slippage_bps_realized = round(abs(fill_diff_pct) * 10_000, 2)

    # expected slippage band — OPERATIONALISES learning.slippage
    slippage_bps_expected = None
    try:
        from ..learning.slippage import estimate_slippage_bps
        slippage_bps_expected = round(estimate_slippage_bps(
            asset_class=asset_class,
            realized_vol=realized_vol,
            is_small_cap=False,
        ), 2)
    except Exception:
        slippage_bps_expected = None

    slippage_verdict = "not_measurable"
    if slippage_bps_realized is not None and slippage_bps_expected is not None:
        if slippage_bps_realized <= slippage_bps_expected * 1.0:
            slippage_verdict = "better_than_modeled"
        elif slippage_bps_realized <= slippage_bps_expected * 2.0:
            slippage_verdict = "within_tolerance"
        else:
            slippage_verdict = "worse_than_modeled"

    # ── spread (modeled, labeled) ─────────────────────────────────
    spread_modeled_bps = None
    try:
        from .detail import _spread_bps
        spread_modeled_bps = _spread_bps(ticker, asset_class)
    except Exception:
        spread_modeled_bps = None

    # ── order-type mix (limit vs market) — order_quality's effect ──
    limit_orders = sum(1 for t in timeline if t["use_limit"])
    market_orders = sum(1 for t in timeline if not t["use_limit"])

    # ── partial-fill / scaling detection ──────────────────────────
    scale_out_hist = (snapshot_row or {}).get("scale_out_history") or {}
    partial_exits = len(closes)
    scaled = (len(opens) > 1) or (partial_exits > 1) or bool(scale_out_hist)

    # ── aging ──────────────────────────────────────────────────────
    first_seen = (snapshot_row or {}).get("first_seen")
    if not first_seen and opens:
        first_seen = opens[0]["time"]
    days_held = None
    fs_dt = _parse_ts(first_seen)
    if fs_dt:
        days_held = round((n_now - fs_dt).total_seconds() / 86400.0, 3)

    # ── broker vs internal degradation ─────────────────────────────
    submitted_count = sum(1 for t in timeline if t["submitted"])
    not_submitted_count = sum(1 for t in timeline if not t["submitted"])
    # broker errors don't carry a symbol; expose the recent count as a
    # cohort-level signal (honest: not ticker-attributable)
    recent_broker_errors = len(broker_errors)

    if not_submitted_count > 0:
        # The order did not reach a fill. Broker errors lack a symbol, so we
        # cannot prove per-ticker whether the cause was an internal hold or a
        # broker rejection — report the unfilled state plus cohort context.
        degradation_source = "unfilled_orders"
    elif recent_broker_errors > 0 and submitted_count > 0:
        degradation_source = "broker_cohort"   # broker rejected somewhere this cycle
    else:
        degradation_source = "none"

    # ── latency: explicitly not measurable (no submit/fill pair) ───
    latency = {
        "measurable": False,
        "reason": "order records store a single timestamp; no submit→ack→fill pair is persisted",
    }

    # ── execution confidence score (0..1) ──────────────────────────
    confidence = 1.0
    notes: List[str] = []
    if slippage_verdict == "worse_than_modeled":
        confidence -= 0.35; notes.append("fill slippage worse than modeled")
    elif slippage_verdict == "within_tolerance":
        confidence -= 0.10
    if degradation_source == "unfilled_orders":
        confidence -= 0.20
        if recent_broker_errors > 0:
            notes.append(f"unfilled order(s) present alongside {recent_broker_errors} "
                         "cohort broker error(s) (e.g. limit-price rejections); "
                         "cause not per-ticker attributable (broker errors lack symbols)")
        else:
            notes.append("unfilled order(s) present (internal hold)")
    elif degradation_source == "broker_cohort":
        confidence -= 0.15; notes.append("broker rejection(s) this cycle (cohort-level)")
    if not opens and not snapshot_row:
        confidence = 0.0; notes.append("no execution recorded")
    confidence = round(max(0.0, min(1.0, confidence)), 3)
    if confidence >= 0.85:
        confidence_label = "clean"
    elif confidence >= 0.6:
        confidence_label = "acceptable"
    elif confidence > 0.0:
        confidence_label = "degraded"
    else:
        confidence_label = "none"

    # ── Phase-3: CLEAN, fill-derived confidence (separate concept) ────────
    # Executed evidence = a broker-reported HELD position ONLY. Submitted/
    # accepted orders are intent artifacts and are NOT used here.
    executed_entry = None
    fill_quality_basis = "none"
    _held_qty = _f((snapshot_row or {}).get("qty"), 0.0) or 0.0
    _snap_avg = _f((snapshot_row or {}).get("avg_entry_price"))
    if snapshot_row is not None and _held_qty != 0 and _snap_avg and _snap_avg > 0:
        executed_entry = _snap_avg
        fill_quality_basis = "held_snapshot_avg_entry"

    fill_quality_confidence = None          # JSON null = not measurable (NOT 0)
    fill_quality_confidence_label = "not_measurable"
    # P4.1 same-epoch gate: fill quality is measurable ONLY when the intended
    # reference is proven same-epoch as the executed (held) evidence. A None
    # flag (unknown) or False (cross-epoch/stale) forces not_measurable —
    # absence/uncertainty of same-epoch evidence is never degradation.
    _same_epoch = (intended_entry_epoch_match is True)
    if (fill_quality_basis == "held_snapshot_avg_entry"
            and intended_entry and intended_entry > 0
            and _same_epoch):
        # realized slippage of the EXECUTED held entry vs the intended entry
        _exec_diff = (executed_entry - intended_entry) / intended_entry
        _exec_slip_bps = abs(_exec_diff) * 10_000
        fqc = 1.0
        if slippage_bps_expected is not None:
            if _exec_slip_bps <= slippage_bps_expected:
                pass
            elif _exec_slip_bps <= slippage_bps_expected * 2.0:
                fqc -= 0.10
            elif _exec_slip_bps <= slippage_bps_expected * 4.0:
                fqc -= 0.35
            else:
                fqc -= 0.50          # severe realized slippage → degraded
        # (no expected band → treat measured fill as neutral 1.0)
        # A MEASURED fill stays in [0.5, 1.0]; "not measurable" is null, never 0 —
        # this keeps "bad fill" and "no evidence" permanently distinct.
        fill_quality_confidence = round(max(0.0, min(1.0, fqc)), 3)
        if fill_quality_confidence >= 0.85:
            fill_quality_confidence_label = "clean"
        elif fill_quality_confidence >= 0.6:
            fill_quality_confidence_label = "acceptable"
        else:
            fill_quality_confidence_label = "degraded"

    # ── Phase-3: non_execution_state (observational; provenance, not causal) ──
    # broker_submission_failures: ONLY orders with submitted EXPLICITLY False.
    explicit_submission_failures = sum(1 for o in orders if o.get("submitted") is False)
    non_execution_state = {
        "broker_submission_failures": explicit_submission_failures,
        "symbol_blind_broker_errors": recent_broker_errors,
        "no_executed_fill": fill_quality_basis == "none",
        "degradation_source": degradation_source,   # echoed; not a causal claim
        "observational_only": True,
    }

    return {
        "order_count": len(timeline),
        "opens": len(opens),
        "closes": len(closes),
        "stop_adjusts": len(stop_adjusts),
        "order_timeline": timeline[-12:],   # most recent 12 events
        "fill_quality": {
            "intended_entry": intended_entry,
            "actual_entry": actual_entry,
            "fill_diff_pct": fill_diff_pct,
            "slippage_bps_realized": slippage_bps_realized,
            "slippage_bps_expected": slippage_bps_expected,
            "slippage_verdict": slippage_verdict,
        },
        "spread_modeled_bps": spread_modeled_bps,
        "order_type_mix": {"limit": limit_orders, "market": market_orders},
        "partial_fills": {"scaled": scaled, "open_events": len(opens),
                           "close_events": partial_exits,
                           "scale_out_history": scale_out_hist},
        "aging": {"first_seen": first_seen, "days_held": days_held},
        "broker_response": {
            "submitted": submitted_count,
            "not_submitted": not_submitted_count,
            "recent_broker_errors_cohort": recent_broker_errors,
        },
        "degradation_source": degradation_source,
        "latency": latency,
        "execution_confidence": confidence,
        "execution_confidence_label": confidence_label,
        # ── Phase-3 split (additive) ──
        "fill_quality_confidence": fill_quality_confidence,        # float|null
        "fill_quality_confidence_label": fill_quality_confidence_label,
        "fill_quality_basis": fill_quality_basis,                  # held_snapshot_avg_entry|none
        "intended_entry_epoch_match": intended_entry_epoch_match,  # True|False|None (P4.1 same-epoch proof)
        "non_execution_state": non_execution_state,                # observational only
        "_deprecated": {
            "fields": ["execution_confidence", "execution_confidence_label"],
            "policy_candidate": "fill_quality_confidence",
            "reason": ("Phase-3 split; legacy fields retained byte-identical for "
                       "compatibility with move_attribution; NOT a policy candidate. "
                       "Observational marker only — no routing/aliasing."),
        },
        "notes": notes,
    }


__all__ = ["build_execution_forensics"]
