"""silmaril.portfolios.conviction_engine — Alpha 4.0 opportunity ranker.

What changed in 4.0
───────────────────
3.2 was advisory-only: it ranked, but the recommendations never made it
into the execution authority pipeline. Alpha 4.0 promotes strong rotation
calls to P5_DEPLOYMENT_URGENCY directives so the policy router can act on
them when the market regime allows, while preserving the original
explainability output for the dashboard.

Three additional Alpha 4.0 changes:
  1. Empirical catalyst lift — plan scores receive a bounded multiplier
     based on signal_validation.json win-rate/expectancy buckets. No
     synthetic confidence; pure historical attribution.
  2. Tuned thresholds — ROTATE_SCORE_DELTA and PRUNE_HOLDING_SCORE are
     read through parameter_tuning.get_tuned_value when available, so the
     bounded-optimization loop can adapt them safely.
  3. Strong idle-cash signal — when the policy router has flagged
     deployment pressure HIGH, the idle-cash recommendation escalates so
     the executor will not let cash sit through a regime that wants it
     working.

Output: docs/data/conviction_ranking.json (same shape as 3.2 + new
        "forced_rotation_directives" array and "deployment_pressure" echo).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Base scoring weights ─────────────────────────────────────────────────────
SCORE_CONVICTION_WEIGHT  = 0.50
SCORE_THREE_MONTH_WEIGHT = 0.25
SCORE_CATALYST_WEIGHT    = 0.15
SCORE_BACKERS_WEIGHT     = 0.10

# ── Default rotation thresholds (parameter_tuning may override) ──────────────
ROTATE_SCORE_DELTA      = 0.20    # advisory rotate
FORCED_ROTATE_DELTA     = 0.30    # promotes to P5_DEPLOYMENT_URGENCY directive
PRUNE_HOLDING_SCORE     = 0.25    # holdings below this are obvious prunes
IDLE_CASH_PCT           = 0.05    # 5% of trading capital still in cash = idle

# Empirical-lift bounds (signal_validation supplies the multiplier within these)
CATALYST_LIFT_MIN = 0.85
CATALYST_LIFT_MAX = 1.20


def _safe_f(x, default: float = 0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _tuned(name: str, default: float) -> float:
    """Read a tuned threshold from parameter_tuning if the helper exists."""
    try:
        from ..learning.parameter_tuning import get_tuned_value  # type: ignore
        val = get_tuned_value("conviction_engine", name, default)
        if isinstance(val, (int, float)) and val == val:
            return float(val)
    except Exception:
        pass
    return float(default)


# ── Empirical catalyst lift via signal_validation ────────────────────────────
def _empirical_lift(plan: Dict[str, Any], data_dir: Optional[Path]) -> float:
    """Bounded multiplier from signal_validation.json. 1.0 = no lift."""
    if data_dir is None:
        return 1.0
    try:
        from . import signal_validation  # type: ignore
        regime = (plan.get("regime") or plan.get("market_state") or "BALANCED")
        lift = signal_validation.get_catalyst_lift(
            data_dir,
            signal       = plan.get("consensus_signal") or plan.get("signal"),
            regime       = regime,
            catalyst_lab = plan.get("catalyst_strength_label"),
            elite        = bool(plan.get("is_elite")),
        )
        if isinstance(lift, (int, float)) and lift == lift:
            return max(CATALYST_LIFT_MIN, min(CATALYST_LIFT_MAX, float(lift)))
    except Exception:
        pass
    return 1.0


# ── Alpha 5.0: sector rotation lift ──────────────────────────────────────────
# Bounded multiplier read from execution_policy.json's sector_rotation block
# (originally produced by silmaril.portfolios.sector_rotation). 1.0 = neutral.
_SECTOR_LIFT_CACHE: Dict[str, Dict[str, float]] = {}


def _sector_lift(plan: Dict[str, Any], data_dir: Optional[Path]) -> float:
    """Bounded sector_rotation multiplier. 1.0 when sector unknown or files missing."""
    if data_dir is None:
        return 1.0
    sector = plan.get("sector") or plan.get("asset_class") or None
    if not sector:
        return 1.0
    cache_key = str(data_dir)
    cached = _SECTOR_LIFT_CACHE.get(cache_key)
    if cached is None:
        cached = {}
        try:
            # Prefer policy's roll-up (single source of truth).
            p = data_dir / "execution_policy.json"
            if p.exists():
                doc = json.loads(p.read_text())
                cached = ((doc.get("sector_rotation") or {})
                           .get("sector_lift") or {})
        except Exception:
            cached = {}
        if not cached:
            try:
                from . import sector_rotation as _sr  # type: ignore
                payload = _sr.load_sector_rotation(data_dir)
                for s, info in (payload.get("sectors") or {}).items():
                    cached[s] = float((info or {}).get("rotation_lift", 1.0) or 1.0)
            except Exception:
                cached = {}
        _SECTOR_LIFT_CACHE[cache_key] = cached
    try:
        v = float(cached.get(sector, 1.0) or 1.0)
        # Hard clamp matching sector_rotation.LIFT_MIN/MAX
        return max(0.75, min(1.30, v))
    except Exception:
        return 1.0


def reset_sector_lift_cache() -> None:
    """Test hook — force reload of the sector_lift cache."""
    _SECTOR_LIFT_CACHE.clear()


# ── Alpha 5.1: setup classifier lift ─────────────────────────────────
# Each plan carries `setup_archetype` (assigned by setup_classifier).
# We read the per-archetype empirical lift from setup_classifications.json.
_SETUP_LIFT_CACHE: Dict[str, Dict[str, float]] = {}


def _setup_lift(plan: Dict[str, Any], data_dir: Optional[Path]) -> float:
    """Bounded per-archetype lift. 1.0 when archetype/file missing."""
    if data_dir is None:
        return 1.0
    archetype = plan.get("setup_archetype")
    if not archetype or archetype == "GENERIC":
        return 1.0
    cache_key = str(data_dir)
    cached = _SETUP_LIFT_CACHE.get(cache_key)
    if cached is None:
        cached = {}
        try:
            p = data_dir / "setup_classifications.json"
            if p.exists():
                doc = json.loads(p.read_text())
                stats = (doc.get("archetype_stats") or {})
                for k, info in stats.items():
                    cached[k] = float((info or {}).get("setup_lift", 1.0) or 1.0)
        except Exception:
            cached = {}
        _SETUP_LIFT_CACHE[cache_key] = cached
    try:
        v = float(cached.get(archetype, 1.0) or 1.0)
        return max(0.85, min(1.25, v))
    except Exception:
        return 1.0


def reset_setup_lift_cache() -> None:
    _SETUP_LIFT_CACHE.clear()


# ── Alpha 5.1: capital efficiency lift (HOLDINGS ONLY) ───────────────
# For ranked OPPORTUNITIES we ignore this (capital_efficiency is per
# currently-held position). But for the holdings_review pass we apply
# it so a position with low efficiency_score gets a lower rotation_score
# and is more likely to be flagged for forced rotation.
_CAPEFF_LIFT_CACHE: Dict[str, Dict[str, float]] = {}


def _capeff_lift_for_held(
    plan: Dict[str, Any], data_dir: Optional[Path], owner: Optional[str] = None,
) -> float:
    """Per-held-position lift; 1.0 when ticker is not currently held."""
    if data_dir is None:
        return 1.0
    t = (plan.get("ticker") or "").upper()
    if not t:
        return 1.0
    cache_key = str(data_dir)
    cached = _CAPEFF_LIFT_CACHE.get(cache_key)
    if cached is None:
        cached = {}
        try:
            p = data_dir / "capital_efficiency.json"
            if p.exists():
                doc = json.loads(p.read_text())
                for r in (doc.get("positions") or []):
                    key = f"{r.get('owner','')}::{(r.get('ticker') or '').upper()}"
                    cached[key] = float(r.get("lift", 1.0) or 1.0)
                    # Also cache an "any-owner" entry for back-compat lookups
                    bare = (r.get("ticker") or "").upper()
                    if bare and bare not in cached:
                        cached[bare] = float(r.get("lift", 1.0) or 1.0)
        except Exception:
            cached = {}
        _CAPEFF_LIFT_CACHE[cache_key] = cached
    if owner:
        v = cached.get(f"{owner}::{t}")
        if v is not None:
            return max(0.85, min(1.05, float(v)))
    v = cached.get(t, 1.0)
    return max(0.85, min(1.05, float(v)))


def reset_capeff_lift_cache() -> None:
    _CAPEFF_LIFT_CACHE.clear()


# ── Core scoring ─────────────────────────────────────────────────────────────
def _score_plan(plan: Dict[str, Any], data_dir: Optional[Path] = None) -> float:
    """Score a plan on a 0..1 scale combining conviction, trend, catalyst,
    agent agreement, and an empirical-lift multiplier from signal_validation."""
    conv = _safe_f(plan.get("consensus_conviction")
                    or plan.get("conviction")
                    or plan.get("avg_conviction"))
    tm_ret = plan.get("three_month_return")
    tm_score = 0.5
    if isinstance(tm_ret, (int, float)):
        # Map -10%..+20% to 0..1 saturating
        tm_score = max(0.0, min(1.0, (float(tm_ret) + 0.10) / 0.30))
    cat_score = _safe_f(plan.get("catalyst_strength"))
    backers = plan.get("backers") or []
    backer_score = min(1.0, len(backers) / 6.0)  # 6+ backers caps the bonus

    base = (
        SCORE_CONVICTION_WEIGHT  * conv
        + SCORE_THREE_MONTH_WEIGHT * tm_score
        + SCORE_CATALYST_WEIGHT    * cat_score
        + SCORE_BACKERS_WEIGHT     * backer_score
    )
    lift = _empirical_lift(plan, data_dir)
    # Alpha 5.0: apply bounded sector_rotation lift so plans in
    # strengthening sectors score modestly higher and plans in
    # weakening sectors score modestly lower. Bounded [0.75, 1.30].
    sector_mult = _sector_lift(plan, data_dir)
    # Alpha 5.1: apply bounded setup_classifier lift so trade-type
    # expectancy (earnings momentum, breakout continuation, etc.)
    # modulates the score in addition to raw signals. Bounded [0.85, 1.25].
    setup_mult = _setup_lift(plan, data_dir)
    score = base * lift * sector_mult * setup_mult
    return round(max(0.0, min(1.0, score)), 4)


def _score_holding(
    pos: Dict[str, Any],
    plan_by_ticker: Dict[str, Dict[str, Any]],
    data_dir: Optional[Path] = None,
) -> float:
    """Score an open position with the same 0..1 scale we use for plans.

    Alpha 5.1: apply the capital_efficiency lift so held positions with
    deteriorating efficiency_score get a lower rotation score (which makes
    forced-rotation logic flag them earlier).
    """
    sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
    plan = plan_by_ticker.get(sym)
    owner = pos.get("owner") or pos.get("account_id")
    if plan:
        base_score = _score_plan(plan, data_dir)
    else:
        # No fresh plan — score on the position's own data
        upl_pct = _safe_f(pos.get("unrealized_plpc"), 0.0)
        cur = _safe_f(pos.get("current_price"))
        peak = _safe_f(pos.get("peak_price") or pos.get("current_price"))
        peak_drop = 0.0
        if peak > 0 and cur > 0:
            peak_drop = (cur - peak) / peak  # negative when below peak
        upl_score = max(0.0, min(1.0, (upl_pct + 0.05) / 0.10))
        peak_score = max(0.0, min(1.0, 1.0 + peak_drop / 0.05))
        base_score = 0.6 * upl_score + 0.4 * peak_score
    # Apply capital_efficiency lift (bounded 0.85..1.05)
    capeff = _capeff_lift_for_held({"ticker": sym}, data_dir, owner=owner)
    return round(max(0.0, min(1.0, base_score * capeff)), 4)


def build_ranked_opportunities(
    plans: List[Dict[str, Any]],
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Score and sort plans high → low."""
    out: List[Dict[str, Any]] = []
    for p in plans:
        ticker = (p.get("ticker") or "").upper()
        if not ticker:
            continue
        score = _score_plan(p, data_dir)
        out.append({
            "ticker":               ticker,
            "score":                score,
            "signal":               p.get("consensus_signal") or p.get("signal"),
            "conviction":           _safe_f(p.get("consensus_conviction")
                                              or p.get("conviction")
                                              or p.get("avg_conviction")),
            "three_month_return":   p.get("three_month_return"),
            "three_month_signal":   p.get("three_month_signal"),
            "catalyst_strength":    p.get("catalyst_strength"),
            "catalyst_label":       p.get("catalyst_strength_label"),
            "backers":              len(p.get("backers") or []),
            "override_applied":     bool(p.get("override_applied")),
            "is_elite":             bool(p.get("is_elite")),
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def review_holdings(
    positions_by_owner: Dict[str, List[Dict[str, Any]]],
    plans: List[Dict[str, Any]],
    *,
    ranked_opportunities: Optional[List[Dict[str, Any]]] = None,
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """For each holding across every account, emit HOLD/ROTATE/PRUNE."""
    ranked = ranked_opportunities or build_ranked_opportunities(plans, data_dir)
    plan_by_ticker = {p.get("ticker", "").upper(): p for p in plans if p.get("ticker")}
    out: List[Dict[str, Any]] = []

    rotate_delta = _tuned("ROTATE_SCORE_DELTA", ROTATE_SCORE_DELTA)
    prune_score  = _tuned("PRUNE_HOLDING_SCORE", PRUNE_HOLDING_SCORE)

    top_alternatives = [r for r in ranked if r["score"] >= 0.55]

    for owner, positions in positions_by_owner.items():
        held_tickers = {
            (p.get("symbol") or p.get("ticker") or "").upper()
            for p in (positions or [])
        }
        for pos in (positions or []):
            sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
            if not sym:
                continue
            # SGOV-style vault tickers are not actionable here (sweep handles them)
            try:
                from .sweep_protection import _is_vault
                if _is_vault(sym):
                    continue
            except Exception:
                if sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                    continue

            holding_score = _score_holding(pos, plan_by_ticker, data_dir)
            best_alt = None
            for alt in top_alternatives:
                if alt["ticker"] in held_tickers:
                    continue
                if alt["score"] >= holding_score + rotate_delta:
                    best_alt = alt
                    break

            if holding_score < prune_score and best_alt is not None:
                rec = "PRUNE"
                rationale = (
                    f"Holding score {holding_score:.2f} below prune threshold "
                    f"{prune_score:.2f}; alternative {best_alt['ticker']} "
                    f"scores {best_alt['score']:.2f}."
                )
            elif best_alt is not None:
                rec = "ROTATE"
                rationale = (
                    f"Holding {holding_score:.2f} vs alternative "
                    f"{best_alt['ticker']} {best_alt['score']:.2f} "
                    f"(Δ {best_alt['score']-holding_score:+.2f})."
                )
            else:
                rec = "HOLD"
                rationale = (
                    f"Holding score {holding_score:.2f}; no alternative "
                    f"clears the rotate threshold ({rotate_delta:.2f})."
                )
            out.append({
                "owner":          owner,
                "ticker":         sym,
                "holding_score":  holding_score,
                "recommendation": rec,
                "rationale":      rationale,
                "alternative":    best_alt["ticker"] if best_alt else None,
                "alt_score":      best_alt["score"] if best_alt else None,
                "advisory_only":  True,  # may be flipped to False below for forced rotation
            })
    return out


def build_forced_rotation_directives(
    holdings_review: List[Dict[str, Any]],
    market_mode: str,
    deployment_pressure_score: float,
) -> List[Dict[str, Any]]:
    """Promote strong ROTATE candidates to P5_DEPLOYMENT_URGENCY directives.

    A holdings_review entry becomes a forced-rotation directive when:
      • recommendation is ROTATE or PRUNE,
      • alt_score - holding_score >= FORCED_ROTATE_DELTA (tunable),
      • market_mode is ATTACK or BALANCED,
      • deployment_pressure_score >= 0.50 (cash is not deployed enough).

    The directive carries the precedence=P5_DEPLOYMENT_URGENCY hint so the
    decision_authority arbiter routes it correctly. It does NOT auto-execute
    in PRESERVATION/DEFENSIVE; the router will downgrade to advisory there.
    """
    out: List[Dict[str, Any]] = []
    if market_mode not in ("ATTACK", "BALANCED"):
        return out
    if _safe_f(deployment_pressure_score) < 0.50:
        return out

    forced_delta = _tuned("FORCED_ROTATE_DELTA", FORCED_ROTATE_DELTA)
    for h in holdings_review:
        if h.get("recommendation") not in ("ROTATE", "PRUNE"):
            continue
        alt = h.get("alternative")
        alt_score = _safe_f(h.get("alt_score"))
        hold_score = _safe_f(h.get("holding_score"))
        if not alt or (alt_score - hold_score) < forced_delta:
            continue
        out.append({
            "action":           "forced_rotate",
            "owner":            h.get("owner"),
            "sell_ticker":      h.get("ticker"),
            "buy_ticker":       alt,
            "score_delta":      round(alt_score - hold_score, 4),
            "holding_score":    hold_score,
            "alternative_score": alt_score,
            "precedence":       "P5_DEPLOYMENT_URGENCY",
            "rationale": (
                f"{h.get('ticker')} ({hold_score:.2f}) → {alt} ({alt_score:.2f}) "
                f"Δ {(alt_score-hold_score):+.2f} in {market_mode} "
                f"@ pressure {deployment_pressure_score:.2f}"
            ),
        })
        # Flip the advisory flag on the corresponding review entry
        h["advisory_only"] = False
    return out


def compute_idle_cash_signal(
    account_state: Dict[str, Any],
    ranked: List[Dict[str, Any]],
    *,
    deployment_pressure_score: float = 0.0,
    market_mode: str = "BALANCED",
) -> Dict[str, Any]:
    """Detect idle cash on an account and recommend deployment.

    Escalates the recommendation when deployment_pressure is HIGH so the
    executor will not let the cash sit through an ATTACK regime.
    """
    if not account_state or not account_state.get("enabled"):
        return {}
    acct = account_state.get("account") or {}
    cash = _safe_f(acct.get("cash"))
    trading_capital = _safe_f(account_state.get("trading_capital"))
    if trading_capital <= 0:
        return {}
    idle_pct = cash / trading_capital if trading_capital else 0.0
    idle_floor = _tuned("IDLE_CASH_PCT", IDLE_CASH_PCT)
    if idle_pct < idle_floor:
        return {}

    # Floor relaxes in ATTACK + high pressure (any plan ≥ 0.50 becomes deployable)
    conv_floor = 0.40
    score_floor = 0.55
    escalated = (deployment_pressure_score >= 0.60 and market_mode in ("ATTACK", "BALANCED"))
    if escalated:
        conv_floor = 0.35
        score_floor = 0.50

    top = next((r for r in ranked
                if r["score"] >= score_floor and r.get("conviction", 0) >= conv_floor), None)

    if escalated and top is not None:
        rec_str = (
            f"DEPLOY NOW — {market_mode} regime, pressure "
            f"{deployment_pressure_score:.2f}, idle {idle_pct:.1%}"
        )
    elif top is not None:
        rec_str = f"DEPLOY into top-ranked plan (score ≥ {score_floor:.2f})"
    else:
        rec_str = f"No plan currently clears score {score_floor:.2f}"

    return {
        "owner":           account_state.get("account_id") or "UNKNOWN",
        "idle_usd":        round(cash, 2),
        "idle_pct":        round(idle_pct, 4),
        "trading_capital": round(trading_capital, 2),
        "recommendation":  rec_str,
        "escalated":       bool(escalated),
        "top_plan":        top["ticker"] if top else None,
        "top_plan_score":  top["score"] if top else None,
        "top_plan_conviction": top.get("conviction") if top else None,
    }


def _load_policy_context(data_dir: Path) -> Tuple[str, float]:
    """Read market_mode + deployment_pressure score from sidecar JSONs.
    Falls back to ('BALANCED', 0.0) on any error."""
    market_mode = "BALANCED"
    pressure    = 0.0
    try:
        p = data_dir / "execution_policy.json"
        if p.exists():
            doc = json.loads(p.read_text())
            market_mode = (doc.get("market_mode") or
                            (doc.get("market_state") or {}).get("mode") or
                            "BALANCED")
            dp = doc.get("deployment_pressure") or {}
            pressure = _safe_f(dp.get("score"), 0.0)
    except Exception:
        pass
    if pressure == 0.0:
        try:
            p = data_dir / "deployment_pressure.json"
            if p.exists():
                doc = json.loads(p.read_text())
                pressure = _safe_f(doc.get("score"), 0.0)
        except Exception:
            pass
    return market_mode, pressure


def write_conviction_ranking(
    data_dir: Path,
    plans: List[Dict[str, Any]],
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compute everything + write docs/data/conviction_ranking.json."""
    ranked = build_ranked_opportunities(plans, data_dir)
    multi_account_results = multi_account_results or {}
    market_mode, pressure = _load_policy_context(data_dir)

    positions_by_owner: Dict[str, List[Dict[str, Any]]] = {}
    for owner, astate in multi_account_results.items():
        if not isinstance(astate, dict) or not astate.get("enabled"):
            continue
        snap_positions = (astate.get("positions_snapshot") or [])
        if snap_positions:
            positions_by_owner[owner] = snap_positions
            continue
        meta = astate.get("position_meta") or {}
        positions = []
        for sym, m in (meta.items() if isinstance(meta, dict) else []):
            positions.append({
                "symbol": sym,
                "current_price": m.get("entry_price"),
                "avg_entry_price": m.get("entry_price"),
                "peak_price": m.get("peak_price"),
                "qty": m.get("qty", 0),
                "unrealized_plpc": 0.0,
            })
        positions_by_owner[owner] = positions

    holdings_review = review_holdings(
        positions_by_owner, plans,
        ranked_opportunities=ranked, data_dir=data_dir,
    )

    forced_rotations = build_forced_rotation_directives(
        holdings_review, market_mode, pressure,
    )

    idle_signals: List[Dict[str, Any]] = []
    for owner, astate in multi_account_results.items():
        sig = compute_idle_cash_signal(
            astate, ranked,
            deployment_pressure_score=pressure,
            market_mode=market_mode,
        )
        if sig:
            idle_signals.append(sig)

    payload = {
        "version":                "4.0",
        "generated_at":           datetime.now(timezone.utc).isoformat(),
        "market_mode":            market_mode,
        "deployment_pressure":    round(pressure, 4),
        "ranked_opportunities":   ranked[:20],
        "holdings_review":        holdings_review,
        "forced_rotation_directives": forced_rotations,
        "idle_cash_signals":      idle_signals,
        "advisory_only":          len(forced_rotations) == 0,
        "thresholds": {
            "ROTATE_SCORE_DELTA":  _tuned("ROTATE_SCORE_DELTA", ROTATE_SCORE_DELTA),
            "FORCED_ROTATE_DELTA": _tuned("FORCED_ROTATE_DELTA", FORCED_ROTATE_DELTA),
            "PRUNE_HOLDING_SCORE": _tuned("PRUNE_HOLDING_SCORE", PRUNE_HOLDING_SCORE),
            "IDLE_CASH_PCT":       _tuned("IDLE_CASH_PCT", IDLE_CASH_PCT),
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "conviction_ranking.json").write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[conviction] write failed: {e}")
    return payload


__all__ = [
    "build_ranked_opportunities",
    "review_holdings",
    "build_forced_rotation_directives",
    "compute_idle_cash_signal",
    "write_conviction_ranking",
]
