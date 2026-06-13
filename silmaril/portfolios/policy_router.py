"""silmaril.portfolios.policy_router — Alpha 3.3 / 4.0 central execution authority.

What it does
────────────
This is the module the Alpha 3.2 review document specifically called
out as missing. It is the single source of truth that consumes every
intelligence sidecar (market_state, conviction_ranking, profit_at_risk,
operational_alerts, opportunity_urgency, elite_mode,
preservation_intelligence, three_month signals, deployment_pressure)
and produces ONE ExecutionPolicy dict that the executor reads.

Alpha 4.0 changes:
  - Computes deployment_pressure (idle cash + SGOV exposure + elite
    pipeline + market_mode bias) and writes it alongside the policy.
  - Emits DEPLOYMENT_URGENCY directives when score >= threshold.
  - Escalates `sizing.base_multiplier` and `sizing.deployment_pressure`
    in ATTACK when pressure is high.
  - Widens `concentration_limits.max_per_sector` by +1 when pressure
    crosses 0.60 in ATTACK or BALANCED.
  - Reduces `min_conviction_floor` by 0.05 when pressure >= 0.70 and
    mode is ATTACK (never below market_state's baseline floor of 0.35).
  - Surfaces SGOV redeployment actions for sweep_protection to consume.

After Alpha 3.3, the executor in alpaca_paper.py no longer makes
independent decisions about position sizing, conviction floors, sweep
aggressiveness, or new-open permissions. It reads policy.* and acts.

ExecutionPolicy shape (also written to docs/data/execution_policy.json)
──────────────────────────────────────────────────────────────────────
{
  "version": "4.0",
  "generated_at": "...",
  "market_mode": "ATTACK" | "BALANCED" | "DEFENSIVE" | "PRESERVATION",
  "winner_engine": "preservation_intelligence",  // who wins precedence
  "winner_action": "preservation_halt",

  "deployment_pressure": {
    "score":  0.71,
    "high":   true,
    "actions": [{"action": "RELAX_SUPPRESSION", "rationale": "..."}, ...]
  },

  "halt_opens":            bool,    // executor refuses to open ANY new position
  "halt_opens_reasons":    [str],
  "force_close":           {"AAPL": {"engine":"...","rationale":"..."}},
  "elite_tickers":         ["NVDA", "AMD"],
  "urgency_tickers":       ["MSFT", "GOOGL"],   // Alpha 4.0
  "blocked_tickers":       {"ABNB": "3m downtrend; no catalyst"},

  "sizing": {
    "base_multiplier":         0.7..1.5,
    "min_conviction_floor":    0.35..0.75,
    "max_position_pct":        0.08,
    "elite_multiplier":        1.5,
    "elite_concentration_cap": 0.20,
    "deployment_pressure":     0.0..1.0,        // Alpha 4.0
    "concentration_limits":    {"max_per_sector": 3, ...},
  },

  "close_loop": {
    "trail_tightness":      1.0,
    "bleed_exit_enabled":   true,
    "stale_close_enabled":  true,
    "stale_close_age_days": 3,                   // Alpha 4.0: scales with mode
    "force_close_vulnerable_critical": true,
  },

  "sweep": {
    "aggression_multiplier": 1.0,
    "instant_sweep_usd":     300.0,
    "instant_sweep_pct":     0.05,
    "force_sweep_floor":     10500.0,            // Alpha 4.0: principal+5% buffer
    "redeploy_sgov":         {"recommended": bool, "amount_hint": float},
  },

  "urgency_priority_order": ["NVDA","AMD","MSFT",...]
  "rationale": "...",
  "directives": [Directive.to_dict(), ...]
}

The executor reads it like:
  policy = load_policy(out_dir)
  if policy["halt_opens"]: skip OPEN loop entirely
  for ticker, reason in policy["force_close"]: close()
  for plan: notional = dynamic_sizer.size_position(plan, policy, ...)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


POLICY_FILENAME = "execution_policy.json"
POLICY_VERSION  = "4.0"


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _stale_close_age_days(mode: str, pressure_score: float) -> int:
    """Alpha 4.0: relax stale-close age in offensive modes.

    DEFENSIVE / PRESERVATION → 3d (default 3.3 behaviour).
    BALANCED                 → 4d (give one extra trading day).
    ATTACK + low pressure    → 5d (let trends develop).
    ATTACK + high pressure   → 5d (consistent — no over-shortening).
    """
    if mode == "ATTACK":
        return 5
    if mode == "BALANCED":
        return 4
    return 3


def _concentration_limits(mode: str, pressure_high: bool) -> Dict[str, Any]:
    """Alpha 4.0: widen by +1 per_sector when pressure is high in
    ATTACK/BALANCED; preserve 3.3 defaults otherwise.
    """
    if mode == "ATTACK":
        return {
            "max_per_sector":     5 if pressure_high else 4,
            "max_per_asset_class": 12 if pressure_high else 10,
            "max_sector_book_pct": 0.45 if pressure_high else 0.40,
        }
    if mode == "BALANCED":
        return {
            "max_per_sector":     4 if pressure_high else 3,
            "max_per_asset_class": 9 if pressure_high else 8,
            "max_sector_book_pct": 0.35 if pressure_high else 0.30,
        }
    if mode == "DEFENSIVE":
        return {"max_per_sector": 2, "max_per_asset_class": 5,
                "max_sector_book_pct": 0.20}
    # PRESERVATION
    return {"max_per_sector": 1, "max_per_asset_class": 3,
            "max_sector_book_pct": 0.10}


def _adjust_conviction_floor(
    mode: str, base_floor: float, pressure_score: float,
) -> float:
    """Alpha 4.0: shave the min_conviction_floor by up to 0.05 in ATTACK
    when pressure is high. Never below 0.35 in any mode.
    """
    floor = float(base_floor)
    if mode == "ATTACK" and pressure_score >= 0.70:
        floor = max(0.35, floor - 0.05)
    elif mode == "ATTACK" and pressure_score >= 0.60:
        floor = max(0.35, floor - 0.03)
    return round(floor, 4)


def _adjust_base_multiplier(
    mode: str, base_mult: float, pressure_score: float, vulnerable_count: int,
) -> float:
    """Alpha 4.0: nudge base sizing multiplier up to +0.10 in ATTACK with
    high pressure; clamp down a touch when vulnerability is elevated.
    """
    m = float(base_mult)
    if mode == "ATTACK" and pressure_score >= 0.60:
        m += min(0.10, (pressure_score - 0.60) * 0.50)
    if vulnerable_count >= 2:
        m -= min(0.10, (vulnerable_count - 1) * 0.05)
    return round(max(0.40, min(1.50, m)), 4)


def compute_policy(
    *,
    data_dir: Path,
    plans: List[Dict[str, Any]],
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    market_state: Optional[Dict[str, Any]] = None,
    profit_at_risk: Optional[Dict[str, Any]] = None,
    catalysts_by_ticker: Optional[Dict[str, List[str]]] = None,
    catalysts_raw: Optional[List[Dict[str, Any]]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the ExecutionPolicy. Reads sidecars from `data_dir` for any
    field not passed explicitly. Returns the policy dict.

    Side effect: writes `execution_policy.json` AND
    `deployment_pressure.json` to data_dir.
    """
    multi_account_results = multi_account_results or {}
    contexts_by_ticker = contexts_by_ticker or {}
    n = now or datetime.now(timezone.utc)

    # ── 1. Resolve market_state (passed-in wins, else file, else default)
    if market_state is None:
        market_state = _load_json(data_dir / "market_state.json") or {}
    mode = (market_state.get("mode") or "BALANCED").upper()
    knobs = market_state.get("knobs") or {}

    # ── 2. Profit-at-risk (for vulnerability triage)
    if profit_at_risk is None:
        profit_at_risk = _load_json(data_dir / "profit_at_risk.json") or {}
    par_positions = profit_at_risk.get("positions") or []
    vulnerable_tickers = {
        (p.get("ticker") or "").upper(): p
        for p in par_positions if p.get("vulnerable")
    }
    vulnerable_count = len(vulnerable_tickers)

    # ── 3. Opportunity urgency
    try:
        from . import opportunity_urgency as ou
        urgency_by_ticker = ou.score_plans(plans, contexts_by_ticker, now=n,
                                            data_dir=data_dir)
    except TypeError:
        # Back-compat: score_plans without data_dir kwarg
        try:
            from . import opportunity_urgency as ou
            urgency_by_ticker = ou.score_plans(plans, contexts_by_ticker, now=n)
        except Exception as e:
            print(f"[policy_router] urgency scoring failed: {e}")
            urgency_by_ticker = {}
    except Exception as e:
        print(f"[policy_router] urgency scoring failed: {e}")
        urgency_by_ticker = {}

    # ── 4. Elite mode selection
    try:
        from . import elite_mode as elt
        elite_result = elt.select_elite_plans(
            plans, urgency_by_ticker,
            market_state_mode=mode,
            profit_at_risk_vulnerable_count=vulnerable_count,
        )
        elite_tickers = elite_result["elite_tickers"]
    except Exception as e:
        print(f"[policy_router] elite_mode failed: {e}")
        elite_result = {"elite_tickers": [], "candidates": [], "suppressed": True,
                        "suppression_reason": str(e)}
        elite_tickers = []

    # ── 5. Deployment pressure (Alpha 4.0)
    try:
        from . import deployment_pressure as dp
        pressure = dp.compute_pressure(
            market_state=market_state,
            multi_account_results=multi_account_results,
            elite_tickers=elite_tickers,
            profit_at_risk=profit_at_risk,
            now=n,
        )
        dp.write_pressure(data_dir, pressure)
    except Exception as e:
        print(f"[policy_router] deployment_pressure failed: {e}")
        pressure = {
            "score": 0.0, "high": False, "components": {},
            "totals": {}, "actions": [], "rationale": f"failed: {e}",
        }
    pressure_score = float(pressure.get("score") or 0.0)
    pressure_high  = bool(pressure.get("high"))

    # ── 5b. Alpha 5.0: Narrative tracker + sector rotation reads ─────
    # Both are sidecars written by cli.py earlier in the cycle. We read
    # them defensively; missing files yield empty rotation/narrative
    # dicts (back-compat — no behaviour change).
    narrative_payload = _load_json(data_dir / "narrative_tracker.json") or {}
    rotation_payload  = _load_json(data_dir / "sector_rotation.json") or {}
    sector_pressure_map = (narrative_payload.get("sector_pressure") or {})
    rotation_sectors    = (rotation_payload.get("sectors") or {})
    regime_shift        = (narrative_payload.get("regime_shift") or "NEUTRAL")
    regime_shift_conf   = _safe_f(narrative_payload.get("regime_shift_confidence"))

    # ── 5c. Alpha 5.1: Deployment floor + orchestrator reads ─────────
    # Both are sidecars written by cli.py earlier in the cycle. We read
    # them defensively so the policy is back-compat when the files don't
    # yet exist.
    floor_payload   = _load_json(data_dir / "deployment_floor.json") or {}
    orch_payload    = _load_json(data_dir / "orchestrator.json") or {}
    setup_payload   = _load_json(data_dir / "setup_classifications.json") or {}
    capeff_payload  = _load_json(data_dir / "capital_efficiency.json") or {}
    posdir_payload  = _load_json(data_dir / "position_directives.json") or {}
    floor_contracts = (floor_payload.get("contracts") or {})
    orch_directive  = (orch_payload.get("directive") or {})

    # ── 6. Preservation intelligence (per-position critical triggers)
    forced_closes: Dict[str, Dict[str, Any]] = {}
    pi_directives: List[Dict[str, Any]] = []
    try:
        from . import preservation_intelligence as pi
        positions_by_owner: Dict[str, List[Dict[str, Any]]] = {}
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict) or not astate.get("enabled"):
                continue
            snap = astate.get("positions_snapshot") or []
            if snap:
                positions_by_owner[aid] = snap
                continue
            meta = astate.get("position_meta") or {}
            positions_by_owner[aid] = [
                {"symbol": sym, "qty": m.get("qty", 0),
                 "current_price": m.get("entry_price")}
                for sym, m in (meta.items() if isinstance(meta, dict) else [])
            ]
        # Alpha 4.0: pass market_mode + urgency so preservation can discount
        # non-critical warnings during ATTACK.
        try:
            pi_directives = pi.build_preservation_directives(
                positions_by_owner,
                contexts_by_ticker=contexts_by_ticker,
                catalysts=catalysts_raw,
                now=n,
                market_mode=mode,
                urgency_by_ticker=urgency_by_ticker,
                elite_tickers=set(elite_tickers),
            )
        except TypeError:
            # Back-compat with 3.3 signature
            pi_directives = pi.build_preservation_directives(
                positions_by_owner,
                contexts_by_ticker=contexts_by_ticker,
                catalysts=catalysts_raw,
                now=n,
            )
        for d in pi_directives:
            if d["should_force_close"]:
                forced_closes[d["ticker"]] = {
                    "engine":    "preservation_intelligence",
                    "rationale": "; ".join(
                        t["rationale"] for t in d["triggers"]),
                    "severity":  d["max_severity"],
                }
    except Exception as e:
        print(f"[policy_router] preservation_intelligence failed: {e}")
        pi_directives = []

    # ── 7. Decision authority — build directives + arbitrate
    directives: List[Any] = []
    try:
        from . import decision_authority as da

        # Halt opens directive from market_state preservation
        if not knobs.get("new_opens_allowed", True):
            directives.append(da.Directive(
                precedence=da.P1_PRESERVATION,
                engine="market_state",
                action="preservation_halt",
                rationale=(f"market_state={mode}: "
                            + (market_state.get("rationale") or "")),
            ))

        # Halt-on-safe-mode from risk engine
        risk_state = _load_json(data_dir / "risk_state.json") or {}
        if risk_state.get("system", {}).get("safe_mode"):
            directives.append(da.Directive(
                precedence=da.P0_SAFETY_HALT,
                engine="risk_engine",
                action="safe_mode_halt",
                rationale=risk_state["system"].get("safe_mode_reason", "safe mode"),
            ))

        # Per-position preservation triggers
        for d in pi_directives:
            if d["should_force_close"]:
                directives.append(da.Directive(
                    precedence=da.P1_PRESERVATION,
                    engine="preservation_intelligence",
                    action="force_close",
                    ticker=d["ticker"],
                    rationale="; ".join(t["rationale"] for t in d["triggers"]),
                    payload={"severity": d["max_severity"]},
                ))

        # Elite opportunities
        for t in elite_tickers:
            directives.append(da.Directive(
                precedence=da.P5_ELITE_OPPORTUNITY,
                engine="elite_mode",
                action="elite_opportunity",
                ticker=t,
                rationale=f"elite: all gates cleared in {mode} mode",
            ))

        # Alpha 4.0: deployment-urgency directives.
        # Portfolio-wide directive when pressure is high.
        if pressure_high and mode != "PRESERVATION":
            for act in (pressure.get("actions") or []):
                # Surface RELAX_SUPPRESSION / WIDEN_CONCENTRATION / ESCALATE_OPENS
                # as portfolio-wide directives at P5_DEPLOYMENT_URGENCY.
                directives.append(da.Directive(
                    precedence=da.P5_DEPLOYMENT_URGENCY,
                    engine="deployment_pressure",
                    action="deployment_urgency",
                    rationale=f"{act.get('action')}: {act.get('rationale','')}",
                    payload={
                        "score":  pressure_score,
                        "action": act.get("action"),
                    },
                ))
                if act.get("action") == "REDEPLOY_SGOV":
                    directives.append(da.Directive(
                        precedence=da.P5_DEPLOYMENT_URGENCY,
                        engine="deployment_pressure",
                        action="redeploy_sgov",
                        rationale=act.get("rationale", ""),
                        payload={
                            "score":       pressure_score,
                            "amount_hint": _safe_f(act.get("amount_hint")),
                        },
                    ))
        # Per-ticker urgency for top urgency-scored plans (caps at 5).
        # These are NOT elite (those got their own directive); they're
        # high-urgency-but-normal that the global_allocator should prefer.
        if pressure_high and mode in ("ATTACK", "BALANCED"):
            urgent_ranked = sorted(
                ((t, sc.get("score", 0.0)) for t, sc in urgency_by_ticker.items()
                 if sc.get("score", 0.0) >= 0.65 and t not in set(elite_tickers)),
                key=lambda kv: kv[1], reverse=True)[:5]
            for t, sc in urgent_ranked:
                directives.append(da.Directive(
                    precedence=da.P5_DEPLOYMENT_URGENCY,
                    engine="deployment_pressure",
                    action="deployment_urgency",
                    ticker=t,
                    rationale=(f"high urgency {sc:.2f} + pressure "
                                f"{pressure_score:.2f} in {mode}"),
                ))

        # Vulnerable but not critical → P3 profit-protection signal (advisory)
        for tkr, par in vulnerable_tickers.items():
            if tkr not in forced_closes:
                directives.append(da.Directive(
                    precedence=da.P3_PROFIT_PROTECTION,
                    engine="profit_protection",
                    action="protect",
                    ticker=tkr,
                    rationale=f"profit-at-risk score {par.get('score', 0):.2f}",
                ))

        arb = da.arbitrate(directives)
    except Exception as e:
        print(f"[policy_router] arbitration failed: {e}")
        arb = {
            "winner_engine": "unknown", "winner_action": "NORMAL",
            "halt_opens": False, "halt_reasons": [], "forced_closes": [],
            "elite_tickers": elite_tickers, "urgency_tickers": [],
            "global_directives": [], "blocked_tickers": {},
            "all_directives": [],
        }

    # Merge forced_closes from preservation_intelligence directly
    # (they're already in the directive list but we also store the dict form)
    halt_opens = bool(arb.get("halt_opens"))
    halt_reasons = list(arb.get("halt_reasons") or [])

    # Concentration limits — mode + pressure aware (Alpha 4.0)
    concentration_limits = _concentration_limits(mode, pressure_high)

    # Stale-close age (Alpha 4.0)
    stale_age_days = _stale_close_age_days(mode, pressure_score)

    # SGOV redeployment hint (Alpha 4.0)
    redeploy_action: Optional[Dict[str, Any]] = None
    for act in (pressure.get("actions") or []):
        if act.get("action") == "REDEPLOY_SGOV":
            redeploy_action = act
            break

    # ── 8. Urgency-driven plan re-ordering
    def _urgency_for(p):
        t = (p.get("ticker") or "").upper()
        u = urgency_by_ticker.get(t, {})
        return (u.get("score", 0.0), _safe_f(p.get("consensus_conviction")))
    urgency_priority_order = [
        (p.get("ticker") or "").upper()
        for p in sorted(plans, key=_urgency_for, reverse=True)
    ]

    # ── 9. Sizing knobs (Alpha 4.0: pressure-adjusted)
    base_mult = _adjust_base_multiplier(
        mode,
        float(knobs.get("position_sizing_multiplier", 1.0)),
        pressure_score, vulnerable_count,
    )
    conviction_floor = _adjust_conviction_floor(
        mode,
        float(knobs.get("min_conviction_floor", 0.40)),
        pressure_score,
    )

    # ── 10. Force-sweep floor (Alpha 4.0)
    # The 3.3 sweep_protection hard-codes BIG_WINNER_SHIELD_USD = $10,000
    # which triggers EVERY day for accounts that start at $10k. The
    # policy now publishes a floor = principal_target * 1.05 by default
    # which sweep_protection consumes. Accounts that haven't run yet
    # (no multi_account_results) get a safe $10,500 default.
    principal_targets = [
        _safe_f(astate.get("principal_target"))
        for astate in (multi_account_results or {}).values()
        if isinstance(astate, dict) and astate.get("enabled")
    ]
    median_principal = (sorted(principal_targets)[len(principal_targets)//2]
                        if principal_targets else 10_000.0)
    force_sweep_floor = round(max(median_principal * 1.05, 10_500.0), 2)

    # ── 11. Build final policy
    policy: Dict[str, Any] = {
        "version":      POLICY_VERSION,
        "generated_at": n.isoformat(),
        "market_mode":  mode,
        "winner_engine": arb.get("winner_engine"),
        "winner_action": arb.get("winner_action"),
        "winner_precedence_name": arb.get("winner_precedence_name"),
        "halt_opens":   halt_opens,
        "halt_opens_reasons": halt_reasons,
        "force_close":  forced_closes,
        "elite_tickers": elite_tickers,
        "urgency_tickers": arb.get("urgency_tickers") or [],
        "elite_suppressed":       elite_result.get("suppressed", False),
        "elite_suppression_reason": elite_result.get("suppression_reason", ""),
        "blocked_tickers": arb.get("blocked_tickers") or {},
        "vulnerable_tickers": list(vulnerable_tickers.keys()),
        "deployment_pressure": {
            "score":      pressure_score,
            "high":       pressure_high,
            "actions":    pressure.get("actions") or [],
            "components": pressure.get("components") or {},
            "totals":     pressure.get("totals") or {},
            "rationale":  pressure.get("rationale", ""),
        },
        "sizing": {
            "base_multiplier":          base_mult,
            "min_conviction_floor":     conviction_floor,
            "elite_multiplier":         1.50,
            "elite_concentration_cap":  0.20,
            "normal_concentration_cap": 0.12,
            "deployment_pressure":      pressure_score,
            "concentration_limits":     concentration_limits,
        },
        "close_loop": {
            "trail_tightness":      float(knobs.get("trailing_stop_tightness", 1.0)),
            "bleed_exit_enabled":   True,
            "stale_close_enabled":  True,
            "stale_close_age_days": stale_age_days,
            "force_close_vulnerable_critical": True,
        },
        "sweep": {
            "aggression_multiplier": float(knobs.get("sweep_aggression", 1.0)),
            "instant_sweep_usd":     300.0,
            "instant_sweep_pct":     0.05,
            "news_boost_multiplier": float(knobs.get("news_boost_multiplier", 1.0)),
            "force_sweep_floor":     force_sweep_floor,
            "redeploy_sgov": (
                {"recommended": True,
                 "amount_hint": _safe_f(redeploy_action.get("amount_hint"))
                                  if redeploy_action else 0.0,
                 "rationale":   redeploy_action.get("rationale", "")
                                  if redeploy_action else ""}
                if redeploy_action else
                {"recommended": False, "amount_hint": 0.0, "rationale": ""}
            ),
        },
        "urgency_priority_order": urgency_priority_order,
        "urgency_by_ticker":      urgency_by_ticker,
        # Alpha 5.0: narrative tracker + sector rotation read-throughs.
        # Downstream consumers (conviction_engine, dashboard) read these
        # directly without re-fetching the source sidecars.
        "narrative": {
            "dominant":     narrative_payload.get("dominant_narrative", ""),
            "regime_shift": regime_shift,
            "confidence":   regime_shift_conf,
        },
        "sector_rotation": {
            "rationale":    rotation_payload.get("rationale", ""),
            "top_pairs":    (rotation_payload.get("top_pairs") or [])[:5],
            "sector_lift": {
                s: float((info or {}).get("rotation_lift", 1.0) or 1.0)
                for s, info in rotation_sectors.items()
            },
            "sector_tag": {
                s: (info or {}).get("tag", "neutral")
                for s, info in rotation_sectors.items()
            },
        },
        # Alpha 5.1: deployment-floor contracts + orchestrator directive
        # are surfaced here so every downstream consumer (the executor,
        # the dashboard, future automation) reads ONE policy file.
        "deployment_floor": {
            aid: {
                "deployment_base":           _safe_f(c.get("deployment_base")),
                "harvest_threshold":         _safe_f(c.get("harvest_threshold")),
                "max_sweep_today":           _safe_f(c.get("max_sweep_today")),
                "redeploy_from_sgov_amount": _safe_f(c.get("redeploy_from_sgov_amount")),
                "is_underdeployed":          bool(c.get("is_underdeployed")),
                "must_redeploy_today":       bool(c.get("must_redeploy_today")),
                "objective_today":           c.get("objective_today", "STEADY_STATE"),
                "violation_flags":           list(c.get("violation_flags") or []),
            }
            for aid, c in floor_contracts.items()
        },
        "orchestrator": {
            "system_objective_today":         orch_directive.get("system_objective_today", ""),
            "posture":                        orch_directive.get("posture", ""),
            "target_market_exposure_pct":     _safe_f(orch_directive.get("target_market_exposure_pct")),
            "max_sector_concentration_pct":   _safe_f(orch_directive.get("max_sector_concentration_pct")),
            "max_position_concentration_pct": _safe_f(orch_directive.get("max_position_concentration_pct")),
            "deployment_pacing":              orch_directive.get("deployment_pacing", ""),
            "account_priority_order":         list(orch_directive.get("account_priority_order") or []),
        },
        "setup_classifications": {
            "per_ticker": {
                (c.get("ticker") or "").upper(): {
                    "archetype":  c.get("archetype"),
                    "setup_lift": _safe_f(c.get("setup_lift"), 1.0),
                }
                for c in (setup_payload.get("classifications") or [])
                if (c.get("ticker") or "").upper()
            },
        },
        "capital_efficiency": {
            "deployment_efficiency_score": _safe_f((capeff_payload.get("summary") or {})
                                                        .get("deployment_efficiency_score")),
            "stale_holding_drag":          _safe_f((capeff_payload.get("summary") or {})
                                                        .get("stale_holding_drag")),
            "idle_capital_drag":           _safe_f((capeff_payload.get("summary") or {})
                                                        .get("idle_capital_drag")),
            "rotation_recommendations":    (capeff_payload.get("summary") or {})
                                                .get("rotation_recommendations") or {},
        },
        "position_directives": list(posdir_payload.get("directives") or []),
        "rationale":              _summarize(arb, mode, elite_tickers,
                                              forced_closes, pressure),
        "directives":             arb.get("all_directives") or [],
        "global_directives":      arb.get("global_directives") or [],
    }

    # Persist
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / POLICY_FILENAME).write_text(
            json.dumps(policy, indent=2, default=str))
    except Exception as e:
        print(f"[policy_router] write failed: {e}")

    return policy


def _summarize(arb: Dict[str, Any], mode: str,
                elite: List[str], forced: Dict[str, Any],
                pressure: Optional[Dict[str, Any]] = None) -> str:
    bits = [f"mode={mode}"]
    if arb.get("halt_opens"):
        bits.append("HALT_OPENS")
    if elite:
        bits.append(f"elite={','.join(elite)}")
    if forced:
        bits.append(f"force_close={','.join(forced.keys())}")
    if pressure and pressure.get("high"):
        bits.append(f"pressure={pressure.get('score', 0):.2f}↑")
    return " | ".join(bits)


def load_policy(data_dir: Path) -> Dict[str, Any]:
    """Read execution_policy.json. Returns a safe default if missing."""
    p = data_dir / POLICY_FILENAME
    if not p.exists():
        return _default_policy()
    try:
        return json.loads(p.read_text())
    except Exception:
        return _default_policy()


def _default_policy() -> Dict[str, Any]:
    """Permissive defaults for back-compat / when the policy file is missing."""
    return {
        "version":     POLICY_VERSION,
        "market_mode": "BALANCED",
        "winner_engine": "default",
        "winner_action": "NORMAL",
        "halt_opens":  False,
        "halt_opens_reasons": [],
        "force_close": {},
        "elite_tickers": [],
        "urgency_tickers": [],
        "blocked_tickers": {},
        "vulnerable_tickers": [],
        "deployment_pressure": {
            "score": 0.0, "high": False, "actions": [],
            "components": {}, "totals": {}, "rationale": "",
        },
        "sizing": {
            "base_multiplier":          1.0,
            "min_conviction_floor":     0.40,
            "elite_multiplier":         1.50,
            "elite_concentration_cap":  0.20,
            "normal_concentration_cap": 0.12,
            "deployment_pressure":      0.0,
            "concentration_limits": {
                "max_per_sector": 3,
                "max_per_asset_class": 8,
                "max_sector_book_pct": 0.30,
            },
        },
        "close_loop": {
            "trail_tightness":      1.0,
            "bleed_exit_enabled":   True,
            "stale_close_enabled":  True,
            "stale_close_age_days": 3,
            "force_close_vulnerable_critical": True,
        },
        "sweep": {
            "aggression_multiplier": 1.0,
            "instant_sweep_usd":     300.0,
            "instant_sweep_pct":     0.05,
            "news_boost_multiplier": 1.0,
            "force_sweep_floor":     10500.0,
            "redeploy_sgov":         {"recommended": False, "amount_hint": 0.0,
                                       "rationale": ""},
        },
        "urgency_priority_order": [],
        "urgency_by_ticker": {},
        "rationale":         "default (no policy file)",
        "directives":        [],
        "global_directives": [],
    }


__all__ = [
    "compute_policy",
    "load_policy",
    "POLICY_FILENAME",
    "POLICY_VERSION",
]
