"""
silmaril.portfolios.move_attribution — Alpha 6.3 P3 measurable move attribution.

WHAT THIS IS
------------
For each trade, decomposes the REALISED price move into weighted contributions
from the signals the TradeCaseFile already unifies — regime, sector pressure,
catalyst, narrative, technical (momentum / relative strength), volatility,
agent conviction, and execution quality.

It replaces narrative-only commentary ("it moved because of AI optimism") with
a deterministic, confidence-weighted decomposition that flags, per factor,
whether the link is CAUSATION (the catalyst names this ticker) or merely
CORRELATION (a market/sector-level signal that happens to align).

DESIGN CONTRACT — projection, not a new pipeline
------------------------------------------------
  * Pure function of an already-assembled TradeCaseFile case dict plus the
    cycle's sector-pressure map. Introduces no new state file and no new
    collector. Output is embedded into the canonical `attribution` section
    (attribution.move_attribution). One schema.
  * It is HONEST about its limits: it does not claim causal proof. It measures
    directional ALIGNMENT between each factor and the realised move, weighted
    by how specific/reliable that factor is, and reports an explained_fraction
    and an attribution_confidence rather than fabricating exact PnL shares.

FEEDS
-----
  * TradeCaseFile.attribution.move_attribution  (this cycle)
  * an `edge_source` label naming the subsystem that most added or destroyed
    edge — the hook P4 uses to credit/debit responsible subsystems.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _f(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None:
            return default
        v = float(x)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def build_move_attribution(
    case: Dict[str, Any],
    sector_pressure_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Decompose one case's realised move into confidence-weighted factors."""
    sector_pressure_map = sector_pressure_map or {}
    execu = case.get("execution") or {}
    regime = case.get("regime_state") or {}
    narrative = case.get("narrative_state") or {}
    catalyst = case.get("catalyst_state") or {}
    health = case.get("health") or {}
    reasoning = case.get("reasoning") or {}
    sector = case.get("sector") or "Unknown"

    move = _f(execu.get("unrealized_pl_pct"))
    if move is None:
        return {
            "realised_move_pct": None,
            "factors": [],
            "dominant_factor": None,
            "edge_source": None,
            "explained_fraction": 0.0,
            "attribution_confidence": 0.0,
            "method": "no realised move available",
        }
    move_sign = _sign(move)

    factors: List[Dict[str, Any]] = []

    def add(name, alignment, confidence, basis, causation):
        """alignment in [-1,1] (direction vs move); confidence in [0,1]."""
        alignment = max(-1.0, min(1.0, alignment))
        confidence = max(0.0, min(1.0, confidence))
        factors.append({
            "factor": name,
            "alignment": round(alignment, 3),
            "confidence": round(confidence, 3),
            "weight": round(abs(alignment) * confidence, 4),
            "directional": "with_move" if alignment * move_sign > 0
                            else ("against_move" if alignment * move_sign < 0 else "neutral"),
            "basis": basis,
            "causation": causation,   # "causation" | "correlation"
        })

    # ── 1. regime alignment (market-level → correlation) ──────────
    regime_label = (regime.get("regime") or "").upper()
    if regime_label:
        # long book assumed; RISK_ON aligns with up-move, RISK_OFF with down
        regime_dir = 1 if "ON" in regime_label else (-1 if "OFF" in regime_label else 0)
        align = regime_dir * (1 if move_sign >= 0 else -1) if move_sign else 0
        add("regime_alignment", float(align), 0.45,
            f"regime={regime_label}", "correlation")

    # ── 2. sector pressure (market-level → correlation) ───────────
    sp = narrative.get("sector_pressure")
    if sp is None:
        sp = sector_pressure_map.get(sector)
    sp = _f(sp)
    if sp is not None and sp != 0:
        add("sector_pressure",
            _sign(sp) * (1 if move_sign >= 0 else -1) * min(1.0, abs(sp) * 2),
            min(0.6, 0.3 + abs(sp)), f"sector={sector} pressure={sp:+.2f}",
            "correlation")

    # ── 3. catalyst (ticker-named → CAUSATION candidate) ──────────
    cats = catalyst.get("catalysts") or []
    if cats:
        # a catalyst attached to THIS case already references the ticker
        add("catalyst", float(move_sign or 1), 0.7,
            f"{len(cats)} catalyst(s) reference this ticker", "causation")

    # ── 4. narrative drift (trade-specific signal) ────────────────
    nd = _f(health.get("narrative_drift"))
    if nd is not None and nd != 0:
        # positive drift = narrative strengthening (supports up-move)
        add("narrative", _sign(nd) * (1 if move_sign >= 0 else -1) * min(1.0, abs(nd)),
            0.4, f"narrative_drift={nd:+.2f}", "correlation")

    # ── 5. technical momentum (trade-specific) ────────────────────
    mom = _f(health.get("momentum_score"))
    if mom is not None:
        # momentum is 0..1; >0.5 supports up-move
        m_align = ((mom - 0.5) * 2) * (1 if move_sign >= 0 else -1)
        add("technical_momentum", m_align, 0.55,
            f"momentum_score={mom:.2f}", "correlation")

    # ── 6. relative strength (trade-specific) ─────────────────────
    rs = _f(health.get("relative_strength"))
    if rs is not None and rs != 0:
        add("relative_strength", _sign(rs) * (1 if move_sign >= 0 else -1) * min(1.0, abs(rs)),
            0.5, f"relative_strength={rs:+.2f}", "correlation")

    # ── 7. volatility (context, low directional confidence) ───────
    vix = _f(regime.get("vix"))
    if vix is not None:
        # high vix amplifies move magnitude; not directional — low confidence
        add("volatility", 0.0, min(0.4, vix / 50.0) if vix else 0.0,
            f"vix={vix}", "correlation")

    # ── 8. agent conviction (who wanted it) ───────────────────────
    backers = reasoning.get("backers") or []
    if backers:
        convs = [_f(b.get("conviction")) for b in backers if _f(b.get("conviction")) is not None]
        avg_conv = sum(convs) / len(convs) if convs else None
        if avg_conv is not None:
            # high conviction "predicts" an up-move; alignment = move direction
            add("agent_conviction", float(move_sign or 1) * min(1.0, avg_conv),
                min(0.6, avg_conv), f"{len(backers)} backer(s), avg conviction {avg_conv:.2f}",
                "causation")

    # ── 9. execution quality (cost drag) ──────────────────────────
    fx = (execu.get("forensics") or {})
    ec = _f(fx.get("execution_confidence"))
    if ec is not None:
        # degraded execution is a drag (against a positive move / worsens a loss)
        drag = -(1.0 - ec)
        add("execution_quality", drag, 0.5,
            f"execution_confidence={ec:.2f} ({fx.get('execution_confidence_label')})",
            "causation")

    # ── normalise into explained shares ───────────────────────────
    total_w = sum(f["weight"] for f in factors) or 1.0
    for f in factors:
        f["share"] = round(f["weight"] / total_w, 4)

    # dominant factor = highest weight aligned WITH the move
    with_move = [f for f in factors if f["directional"] == "with_move"]
    dominant = max(with_move, key=lambda f: f["weight"], default=None)
    # edge destroyer = strongest factor AGAINST the move
    against = [f for f in factors if f["directional"] == "against_move"]
    destroyer = max(against, key=lambda f: f["weight"], default=None)

    # explained fraction: how much of the |move| the aligned factors plausibly
    # account for (capped at 1.0); attribution confidence = mean factor conf.
    aligned_w = sum(f["weight"] for f in with_move)
    explained_fraction = round(min(1.0, aligned_w / (total_w or 1.0)), 4)
    attribution_confidence = round(
        sum(f["confidence"] for f in factors) / len(factors), 4) if factors else 0.0

    edge_source = None
    if dominant:
        edge_source = dominant["factor"]
    elif destroyer:
        edge_source = f"-{destroyer['factor']}"

    return {
        "realised_move_pct": round(move, 6),
        "factors": sorted(factors, key=lambda f: f["weight"], reverse=True),
        "dominant_factor": dominant["factor"] if dominant else None,
        "edge_destroyer": destroyer["factor"] if destroyer else None,
        "edge_source": edge_source,
        "explained_fraction": explained_fraction,
        "attribution_confidence": attribution_confidence,
        "method": ("alignment-weighted deterministic decomposition; "
                   "causation flag = factor references this ticker; "
                   "not a causal proof"),
    }


__all__ = ["build_move_attribution"]
