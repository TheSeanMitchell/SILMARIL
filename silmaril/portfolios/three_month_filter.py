"""silmaril.portfolios.three_month_filter — Alpha 4.0 downtrend gate.

What's new in 4.0
─────────────────
1. ATTACK-mode override loosening — in ATTACK + high deployment pressure,
   the rescue gate accepts `conv ≥ 0.50 AND catalyst ≥ 0.40` (down from
   the rigid 0.55 / 0.55 combo). Reversals during strong tape are
   genuine opportunities; the old gate stranded too many of them.

2. Catalyst hysteresis — once we've rescued a ticker out of downtrend
   AND it failed (closed at a loss), we require a *higher* catalyst score
   than the prior rescue's score before rescuing the same ticker again
   within a 30-day window. Prevents the same death spiral from getting
   re-rescued by the same headline cluster on consecutive cycles.
   The hysteresis state is persisted in
   docs/data/three_month_rescue_state.json.

3. Three regimes of behavior:
        DEFENSIVE / PRESERVATION → strict gate (0.55 / 0.55)
        BALANCED               → strict gate (0.55 / 0.55)
        ATTACK                 → loosened gate (0.50 / 0.40) AND
                                 a "fresh-uptrend" hook: a downtrend
                                 name where the LAST 10 bars are
                                 themselves uptrending +5% can pass
                                 with conv ≥ 0.50 + soft catalyst.

4. Reads regime from execution_policy.json. Falls back to BALANCED if
   no policy file present (3.3 back-compat).

Output shape unchanged from 3.2 — plans still get the same diagnostic
fields, only the rescue logic differs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Trigger: anything worse than -5% over ~3 months is "in a downtrend
# bad enough that we don't want to provide bag-holder exit liquidity".
DOWNTREND_THRESHOLD: float = -0.05

# Rescue thresholds by regime
STRICT_CONVICTION_FLOOR  = 0.55
STRICT_CATALYST_FLOOR    = 0.55   # via catalyst score; "strong" label = >= 0.55
ATTACK_CONVICTION_FLOOR  = 0.50
ATTACK_CATALYST_FLOOR    = 0.40
ATTACK_FRESH_UPTREND_PCT = 0.05   # last-10-bar return >= +5% counts as a turn

# Hysteresis — re-rescuing the same failed ticker requires a higher
# catalyst score than the prior rescue's score by this much.
HYSTERESIS_DAYS         = 30
HYSTERESIS_BUMP         = 0.10   # catalyst must clear prior + 0.10

# State file
_RESCUE_STATE_FILENAME = "three_month_rescue_state.json"


# Strong-catalyst keywords (case-insensitive substring match).
STRONG_CATALYST_KEYWORDS: Tuple[str, ...] = (
    "blowout", "smashed estimates", "beats estimates",
    "raised guidance", "raises guidance", "guidance raised",
    "upgrade to buy", "upgraded to buy", "raised target",
    "fda approval", "fda approves", "phase 3",
    "index inclusion", "added to s&p", "added to nasdaq-100",
    "all-time high", "record revenue", "record earnings",
    "buyback", "share repurchase", "spinoff", "spin-off",
    "merger", "acquires", "to acquire", "acquisition",
    "breakout", "surge", "surges", "surging",
    "strong demand", "strong guidance", "raises outlook",
)


def _safe_float(x, default: Optional[float] = None) -> Optional[float]:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _load_market_mode(data_dir: Optional[Path]) -> str:
    """Read market_mode from execution_policy.json; default BALANCED."""
    if data_dir is None:
        return "BALANCED"
    try:
        p = Path(data_dir) / "execution_policy.json"
        if p.exists():
            doc = json.loads(p.read_text())
            mode = (doc.get("market_mode") or
                    (doc.get("market_state") or {}).get("mode") or "BALANCED")
            return str(mode).upper()
    except Exception:
        pass
    return "BALANCED"


def _load_deployment_pressure(data_dir: Optional[Path]) -> float:
    if data_dir is None:
        return 0.0
    try:
        p = Path(data_dir) / "execution_policy.json"
        if p.exists():
            doc = json.loads(p.read_text())
            dp = doc.get("deployment_pressure") or {}
            v = _safe_float(dp.get("score"), 0.0)
            if v is not None:
                return float(v)
    except Exception:
        pass
    try:
        p = Path(data_dir) / "deployment_pressure.json"
        if p.exists():
            doc = json.loads(p.read_text())
            v = _safe_float(doc.get("score"), 0.0)
            if v is not None:
                return float(v)
    except Exception:
        pass
    return 0.0


# ── Rescue-state persistence ────────────────────────────────────────────────
def _load_rescue_state(data_dir: Optional[Path]) -> Dict[str, Any]:
    if data_dir is None:
        return {}
    try:
        p = Path(data_dir) / _RESCUE_STATE_FILENAME
        if p.exists():
            doc = json.loads(p.read_text())
            if isinstance(doc, dict):
                return doc
    except Exception:
        pass
    return {}


def _save_rescue_state(data_dir: Optional[Path], state: Dict[str, Any]) -> None:
    if data_dir is None:
        return
    try:
        p = Path(data_dir)
        p.mkdir(parents=True, exist_ok=True)
        (p / _RESCUE_STATE_FILENAME).write_text(
            json.dumps(state, indent=2, default=str))
    except Exception:
        pass


def _hysteresis_floor(
    ticker: str,
    state: Dict[str, Any],
    now: datetime,
    base_floor: float,
) -> Tuple[float, Optional[str]]:
    """Compute the effective catalyst floor for `ticker` given prior failed
    rescues. Returns (floor, reason_text_or_None)."""
    entry = (state or {}).get((ticker or "").upper())
    if not isinstance(entry, dict):
        return base_floor, None
    last_attempt_iso = entry.get("last_attempt_at")
    last_outcome     = entry.get("last_outcome")  # "win" | "loss" | None
    prior_score      = _safe_float(entry.get("last_catalyst_score"), 0.0) or 0.0
    if last_outcome != "loss" or not last_attempt_iso:
        return base_floor, None
    try:
        d = datetime.fromisoformat(str(last_attempt_iso).replace("Z", "+00:00"))
        age_days = (now - d).total_seconds() / 86400.0
    except Exception:
        return base_floor, None
    if age_days > HYSTERESIS_DAYS:
        return base_floor, None
    bumped = max(base_floor, prior_score + HYSTERESIS_BUMP)
    return bumped, (
        f"hysteresis: prior rescue lost; need catalyst ≥ {bumped:.2f} "
        f"(was {prior_score:.2f}, ageing {age_days:.0f}d)"
    )


def record_rescue_attempt(
    data_dir: Path,
    ticker: str,
    catalyst_score: float,
    now: Optional[datetime] = None,
) -> None:
    """Called when a rescue is APPLIED (override fires). Stores the
    catalyst score so a future re-rescue must clear a higher bar."""
    n = now or datetime.now(timezone.utc)
    state = _load_rescue_state(data_dir)
    key = (ticker or "").upper()
    entry = state.get(key) or {}
    entry["last_attempt_at"]      = n.isoformat()
    entry["last_catalyst_score"]  = round(float(catalyst_score), 4)
    # Outcome defaults to "pending" until close_outcome updates it.
    entry.setdefault("last_outcome", "pending")
    state[key] = entry
    _save_rescue_state(data_dir, state)


def record_rescue_outcome(
    data_dir: Path,
    ticker: str,
    outcome: str,
    now: Optional[datetime] = None,
) -> None:
    """Called by the close path: outcome = "win" | "loss" | "flat".
    Only "loss" triggers hysteresis on the next rescue attempt."""
    n = now or datetime.now(timezone.utc)
    state = _load_rescue_state(data_dir)
    key = (ticker or "").upper()
    entry = state.get(key)
    if not isinstance(entry, dict):
        return
    entry["last_outcome"]   = outcome
    entry["last_outcome_at"] = n.isoformat()
    state[key] = entry
    _save_rescue_state(data_dir, state)


# ── Original-shape signal scoring ───────────────────────────────────────────
def compute_three_month_signal(price_history: Optional[List[float]]) -> Dict[str, Any]:
    """Returns {"three_month_return": float|None, "label": str}."""
    try:
        from ..analytics.technicals import three_month_return as _3m
    except Exception:
        _3m = None
    if _3m is None or not price_history:
        return {"three_month_return": None, "label": "unknown"}
    ret = _3m(price_history)
    if ret is None:
        return {"three_month_return": None, "label": "unknown"}
    if ret <= DOWNTREND_THRESHOLD:
        label = "downtrend"
    elif ret >= 0.05:
        label = "uptrend"
    else:
        label = "flat"
    return {"three_month_return": round(ret, 4), "label": label}


def _recent_uptrend(price_history: Optional[List[float]],
                     bars: int = 10) -> Optional[float]:
    """Return pct change over the last `bars` bars; None if too short."""
    if not price_history or len(price_history) < bars + 1:
        return None
    try:
        end   = float(price_history[-1])
        start = float(price_history[-bars])
        if start <= 0:
            return None
        return (end - start) / start
    except Exception:
        return None


def score_catalyst_strength(
    debate: Dict[str, Any],
    catalysts_by_ticker: Optional[Dict[str, List[str]]] = None,
) -> Tuple[float, str, Optional[str]]:
    """Score the strength of any near-term catalyst on this name."""
    catalysts_by_ticker = catalysts_by_ticker or {}
    ticker = (debate.get("ticker") or "").upper()

    headlines: List[str] = []
    for h in (debate.get("recent_headlines") or [])[:6]:
        if isinstance(h, dict):
            t = h.get("title") or h.get("headline") or ""
            if t:
                headlines.append(str(t).lower())
        elif isinstance(h, str):
            headlines.append(h.lower())
    for t in catalysts_by_ticker.get(ticker, [])[:5]:
        headlines.append(str(t).lower())

    matched_kw: Optional[str] = None
    for line in headlines:
        for kw in STRONG_CATALYST_KEYWORDS:
            if kw in line:
                matched_kw = kw
                break
        if matched_kw:
            break

    sent = _safe_float(debate.get("sentiment_score"), 0.0) or 0.0
    src = int(debate.get("source_count") or 0)
    arts = int(debate.get("article_count") or 0)

    score = 0.0
    if matched_kw:
        score += 0.6
    score += max(0.0, min(0.30, max(0.0, sent) * 0.6))
    if src >= 3 or arts >= 5:
        score += 0.15
    elif src >= 2 or arts >= 3:
        score += 0.08
    score = max(0.0, min(1.0, score))

    if score >= 0.55:
        label = "strong"
    elif score >= 0.25:
        label = "soft"
    else:
        label = "none"
    return round(score, 3), label, matched_kw


# ── Core gate evaluation ────────────────────────────────────────────────────
def evaluate_three_month_gate(
    plan: Dict[str, Any],
    debate: Optional[Dict[str, Any]] = None,
    ctx_price_history: Optional[List[float]] = None,
    catalysts_by_ticker: Optional[Dict[str, List[str]]] = None,
    *,
    market_mode: str = "BALANCED",
    deployment_pressure: float = 0.0,
    data_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Decide whether the 3-month downtrend gate blocks this plan."""
    debate = debate or {}
    n = now or datetime.now(timezone.utc)
    sig_info = compute_three_month_signal(ctx_price_history)
    cat_score, cat_label, cat_kw = score_catalyst_strength(
        debate, catalysts_by_ticker)

    out: Dict[str, Any] = {
        "three_month_return": sig_info["three_month_return"],
        "three_month_signal": sig_info["label"],
        "catalyst_strength": cat_score,
        "catalyst_strength_label": cat_label,
        "catalyst_matched_keyword": cat_kw,
        "rejection_reason": None,
        "override_applied": False,
        "override_reason": "",
        "regime_at_gate": market_mode,
    }

    label = sig_info["label"]
    if label != "downtrend":
        return out

    consensus_signal = (plan.get("consensus_signal")
                        or plan.get("signal") or "").upper()
    conviction = _safe_float(plan.get("consensus_conviction")
                              or plan.get("conviction")
                              or plan.get("avg_conviction"), 0.0) or 0.0
    ticker = (plan.get("ticker") or "").upper()

    # Choose regime thresholds
    is_attack = (market_mode == "ATTACK")
    is_pressed = (deployment_pressure >= 0.50)
    use_loose = is_attack and is_pressed

    if use_loose:
        conv_floor = ATTACK_CONVICTION_FLOOR
        cat_floor  = ATTACK_CATALYST_FLOOR
        regime_tag = f"ATTACK+pressure {deployment_pressure:.2f}"
    else:
        conv_floor = STRICT_CONVICTION_FLOOR
        cat_floor  = STRICT_CATALYST_FLOOR
        regime_tag = market_mode

    # Apply hysteresis: re-rescuing a failed name needs a higher catalyst score
    state = _load_rescue_state(data_dir)
    eff_cat_floor, hyst_note = _hysteresis_floor(ticker, state, n, cat_floor)
    if hyst_note:
        out["hysteresis_note"] = hyst_note

    rescue_paths: List[Tuple[bool, str]] = []

    # Path A — STRONG catalyst rescue (loose or strict variant)
    cat_ok = (cat_score >= eff_cat_floor) or (cat_label == "strong")
    conv_ok = (conviction >= conv_floor)
    strong_signal = consensus_signal in ("STRONG_BUY", "BUY") if use_loose \
                    else (consensus_signal == "STRONG_BUY")
    if cat_ok and conv_ok and strong_signal:
        rescue_paths.append((True,
            f"catalyst rescue ({regime_tag}): conv {conviction:.2f}≥{conv_floor:.2f}, "
            f"catalyst {cat_score:.2f}≥{eff_cat_floor:.2f}"
            + (f", '{cat_kw}'" if cat_kw else "")
        ))

    # Path B — ATTACK fresh-uptrend hook: recent 10-bar uptrend overrides
    # a 3-month downtrend if there's at least a soft catalyst and decent conv.
    if use_loose and not rescue_paths:
        recent = _recent_uptrend(ctx_price_history, 10)
        if (recent is not None
            and recent >= ATTACK_FRESH_UPTREND_PCT
            and conviction >= ATTACK_CONVICTION_FLOOR
            and cat_label in ("soft", "strong")):
            # Hysteresis still applies — the catalyst must clear bumped floor
            # OR the recent uptrend must be very strong (>= 8%) to bypass.
            if cat_score >= eff_cat_floor or recent >= 0.08:
                rescue_paths.append((True,
                    f"ATTACK fresh-uptrend: last-10-bar {recent*100:+.1f}%, "
                    f"conv {conviction:.2f}, catalyst {cat_label}"
                ))

    if rescue_paths and rescue_paths[0][0]:
        out["override_applied"] = True
        out["override_reason"] = (
            f"3-month {sig_info['three_month_return']*100:+.1f}% downtrend "
            f"overridden — {rescue_paths[0][1]}"
        )
        # Persist rescue attempt so a future failure triggers hysteresis next time
        try:
            if data_dir is not None and ticker:
                record_rescue_attempt(data_dir, ticker, cat_score, now=n)
        except Exception:
            pass
        return out

    # Block.
    ret_str = (f"{sig_info['three_month_return']*100:+.1f}%"
               if sig_info["three_month_return"] is not None else "?")
    extra = f" [{hyst_note}]" if hyst_note else ""
    out["rejection_reason"] = (
        f"3-month downtrend ({ret_str}) in {regime_tag} — catalyst {cat_label} "
        f"(score {cat_score:.2f}, floor {eff_cat_floor:.2f}); requires "
        f"conv≥{conv_floor:.2f} + catalyst≥floor"
        f" + {'BUY/STRONG_BUY' if use_loose else 'STRONG_BUY'} to override "
        f"(had {consensus_signal or 'HOLD'} / {conviction:.2f}).{extra}"
    )
    return out


def filter_plans_by_trend(
    plans: List[Dict[str, Any]],
    debates_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    catalysts_by_ticker: Optional[Dict[str, List[str]]] = None,
    *,
    market_mode: Optional[str] = None,
    deployment_pressure: Optional[float] = None,
    data_dir: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply the 3-month downtrend gate to every plan. Returns (kept, rejected).

    `market_mode` and `deployment_pressure` may be passed explicitly; if
    omitted, they're read from execution_policy.json in `data_dir`.
    """
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    debates_by_ticker = debates_by_ticker or {}
    contexts_by_ticker = contexts_by_ticker or {}
    catalysts_by_ticker = catalysts_by_ticker or {}

    if market_mode is None:
        market_mode = _load_market_mode(data_dir)
    if deployment_pressure is None:
        deployment_pressure = _load_deployment_pressure(data_dir)

    for plan in plans:
        ticker = (plan.get("ticker") or "").upper()
        if not ticker:
            kept.append(plan)
            continue
        debate = debates_by_ticker.get(ticker) or {}
        ctx = contexts_by_ticker.get(ticker)
        ph: Optional[List[float]] = None
        if ctx is not None:
            ph = getattr(ctx, "price_history", None)
            if ph is None and isinstance(ctx, dict):
                ph = ctx.get("price_history")
        result = evaluate_three_month_gate(
            plan, debate=debate,
            ctx_price_history=ph,
            catalysts_by_ticker=catalysts_by_ticker,
            market_mode=market_mode,
            deployment_pressure=float(deployment_pressure or 0.0),
            data_dir=data_dir,
        )
        plan.update({k: v for k, v in result.items() if k != "rejection_reason"})
        if result.get("rejection_reason"):
            plan["rejected_reason"] = result["rejection_reason"]
            plan["rejected_by"] = "three_month_filter"
            rejected.append(plan)
        else:
            kept.append(plan)
    return kept, rejected


__all__ = [
    "DOWNTREND_THRESHOLD",
    "STRONG_CATALYST_KEYWORDS",
    "compute_three_month_signal",
    "score_catalyst_strength",
    "evaluate_three_month_gate",
    "filter_plans_by_trend",
    "record_rescue_attempt",
    "record_rescue_outcome",
]
