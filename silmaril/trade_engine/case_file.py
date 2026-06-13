"""
silmaril.trade_engine.case_file — THE canonical Trade Case File (Alpha 6.3, P1).

WHAT THIS IS
------------
A single, canonical, per-trade record that answers — for every trade —
the seven forensic questions the Alpha 6.3 directive demands:

    1. WHY does this trade exist?      (reasoning: consensus, backers, dissent, plan levels)
    2. WHO drove it?                   (attribution: driving agents, reconciliation status)
    3. WHAT was executed?              (execution: entry, qty, live price, unrealized PnL)
    4. WHAT conditions existed?        (regime + catalyst + narrative state at the trade)
    5. WHAT is the harvest intent?     (advisory recommendation + realized harvests)
    6. IS it healthy?                  (position-health metrics + status)
    7. WHAT was learned / blocked?     (decision-ledger events for this name)

DESIGN CONTRACT — READ BEFORE EXTENDING
---------------------------------------
This module is a **PROJECTION / JOIN layer, NOT a collector**.

  * It introduces NO new telemetry source and NO new state pipeline.
  * It READS the existing canonical emitters (already written each cycle by
    the running pipeline) and JOINS them by (account_id, ticker) into ONE
    record per trade.
  * The output `trade_case_files.json` is intended to become the single
    structure the UI consumes for trade reasoning / execution / attribution /
    harvest / regime / catalyst / learning. The UI must consume THIS — not a
    duplicated derivative.

If a future phase needs a new field, it must be SOURCED from an existing
emitter (or that emitter extended), then surfaced here. Do NOT fork this file
into a parallel "case file v2". One schema. One source of truth.

SOURCES JOINED (all under output_dir)
-------------------------------------
  position_health.json        -> execution snapshot + health metrics  (open trades)
  position_advisory.json      -> hold/trim/exit recommendation + rationale
  alpaca_attribution.json      -> driving agents + gold/orphan/phantom reconciliation
  verified_harvest_ledger.json -> realized harvests for the name
  decision_ledger.json         -> block/allow events for the name
  trade_plans.json             -> intended entry/stop/target/backers (this cycle's plans)
  conviction_ranking.json      -> conviction score / opportunity ranking
  market_state.json            -> regime label, VIX, session (global context)
  regime_memory.json           -> current regime detail
  narrative_tracker.json       -> dominant narrative + per-sector pressure
  catalysts.json               -> catalysts touching the name

Wired into the cycle from silmaril/cli.py (after attribution tagging, when all
sources are fresh) via build_case_files(out_dir, debate_dicts=...).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "6.3"
OUTPUT_FILE = "trade_case_files.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> Any:
    """Defensive JSON load. Missing/broken source -> None (never raises)."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except Exception:
        return None


def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────
# Canonical schema
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class TradeCaseFile:
    """One canonical record per (account_id, ticker) trade."""

    # ── identity ──────────────────────────────────────────────
    case_id: str
    account_id: str
    ticker: str
    name: str = ""
    sector: str = "Unknown"
    state: str = "OPEN"            # OPEN | PLANNED | HARVESTED
    generated_at: str = field(default_factory=_now)
    first_seen: str = field(default_factory=_now)
    # ── trade-epoch anchor (P4.1) ─────────────────────────────
    # Broker-truth per-trade epoch = positions_snapshot.first_seen, which
    # resets on a full close (position_meta.pop) and is re-stamped on reopen.
    # Observational/provenance ONLY this phase; never feeds policy/risk/exec.
    entry_epoch: str = ""

    # ── 1. reasoning (WHY) ────────────────────────────────────
    reasoning: Dict[str, Any] = field(default_factory=dict)
    # consensus_signal, conviction, backers[], dissenters[], invalidation,
    # intended_entry, intended_stop, intended_target, reward_risk,
    # intended_risk_pct

    # ── 2. attribution (WHO) ──────────────────────────────────
    attribution: Dict[str, Any] = field(default_factory=dict)
    # driving_agents[], reconciliation ("gold"|"orphan"|"phantom"|"unknown")

    # ── 3. execution (WHAT happened) ──────────────────────────
    execution: Dict[str, Any] = field(default_factory=dict)
    # qty, avg_entry, current_price, position_value, unrealized_pl,
    # unrealized_pl_pct, time_held_days

    # ── 4. regime state ───────────────────────────────────────
    regime_state: Dict[str, Any] = field(default_factory=dict)
    # regime, vix, session, current_regimes

    # ── 4b. catalyst state ────────────────────────────────────
    catalyst_state: Dict[str, Any] = field(default_factory=dict)
    # catalysts[] touching this ticker

    # ── 4c. narrative state ───────────────────────────────────
    narrative_state: Dict[str, Any] = field(default_factory=dict)
    # dominant_narrative, sector_pressure

    # ── 5. harvest ────────────────────────────────────────────
    harvest: Dict[str, Any] = field(default_factory=dict)
    # recommendation, rationale, realized_harvests[], realized_total

    # ── 6. health / status ────────────────────────────────────
    health: Dict[str, Any] = field(default_factory=dict)
    # momentum_score, narrative_drift, vulnerability_score, rotation_score,
    # relative_strength, status (healthy|watch|force_rotation)

    # ── 7. learning / ledger ──────────────────────────────────
    learning: Dict[str, Any] = field(default_factory=dict)
    # ledger_events[] (blocks/allows for this name)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────
# Builder
# ──────────────────────────────────────────────────────────────────────────
def build_case_files(
    out_dir: Path,
    debate_dicts: Optional[List[Dict[str, Any]]] = None,
    write: bool = True,
) -> Dict[str, Any]:
    """Join existing per-cycle emitters into canonical TradeCaseFiles.

    Returns the full payload dict (also written to trade_case_files.json
    when write=True). Never raises — missing sources degrade gracefully and
    are reported under `source_files`.
    """
    out = Path(out_dir)

    # ── prior case files: carry forward entry-time reasoning/attribution ─
    # The originating plan for a position lives in trade_plans.json ONLY on
    # the cycle it was created. To keep "every trade a forensic case file"
    # true across its whole life, we merge the prior canonical file: a case's
    # captured WHY/WHO is preserved even after the plan ages out. This keeps
    # ONE canonical structure (no parallel store) that accumulates over time.
    prior_payload = _load(out / OUTPUT_FILE)
    prior_by_id: Dict[str, Dict] = {}
    if isinstance(prior_payload, dict):
        for c in prior_payload.get("cases", []) or []:
            cid = c.get("case_id")
            if cid:
                prior_by_id[cid] = c

    # ── load all sources (None if absent) ─────────────────────
    health_doc      = _load(out / "position_health.json")
    advisory_doc    = _load(out / "position_advisory.json")
    attribution_doc = _load(out / "alpaca_attribution.json")
    harvest_doc     = _load(out / "verified_harvest_ledger.json")
    ledger_doc      = _load(out / "decision_ledger.json")
    plans_doc       = _load(out / "trade_plans.json")
    conviction_doc  = _load(out / "conviction_ranking.json")
    market_doc      = _load(out / "market_state.json")
    regime_doc      = _load(out / "regime_memory.json")
    narrative_doc   = _load(out / "narrative_tracker.json")
    catalyst_doc    = _load(out / "catalysts.json")
    # P4.3: live order_quality (read-only, for the observational dry-run diff)
    order_quality_doc = _load(out / "order_quality.json")
    oq_idx = {}
    if isinstance(order_quality_doc, dict):
        for t, row in (order_quality_doc.get("tickers") or {}).items():
            if isinstance(row, dict):
                oq_idx[str(t).upper()] = row

    source_files = {
        "position_health.json":        health_doc is not None,
        "position_advisory.json":      advisory_doc is not None,
        "alpaca_attribution.json":     attribution_doc is not None,
        "verified_harvest_ledger.json": harvest_doc is not None,
        "decision_ledger.json":        ledger_doc is not None,
        "trade_plans.json":            plans_doc is not None,
        "conviction_ranking.json":     conviction_doc is not None,
        "market_state.json":           market_doc is not None,
        "regime_memory.json":          regime_doc is not None,
        "narrative_tracker.json":      narrative_doc is not None,
        "catalysts.json":              catalyst_doc is not None,
    }

    # ── global regime context (same for every case this cycle) ─
    global_regime = _global_regime(market_doc, regime_doc)
    dominant_narrative = ((narrative_doc or {}).get("dominant_narrative")
                          if isinstance(narrative_doc, dict) else None)
    sector_pressure = ((narrative_doc or {}).get("sector_pressure") or {}
                       if isinstance(narrative_doc, dict) else {})

    # ── index the join sources by (owner, ticker) / ticker ─────
    advisory_idx = _index_advisory(advisory_doc)
    attribution_idx, recon_idx = _index_attribution(attribution_doc)
    harvest_idx = _index_harvest(harvest_doc)
    ledger_idx = _index_ledger(ledger_doc)
    plans_idx = _index_plans(plans_doc, debate_dicts)
    conviction_idx = _index_conviction(conviction_doc)
    catalyst_idx = _index_catalysts(catalyst_doc)
    # P2: real order/fill records from the broker state files (Alpaca accounts)
    exec_orders_idx, exec_snap_idx, exec_errors_by_acct = _index_execution_state(out)
    # P4: operational learning state (scoring weights + risk freeze) for the join
    learn_scoring_idx, learn_risk_idx, learn_system = _index_learning_state(out)

    cases: List[TradeCaseFile] = []
    seen: set = set()

    # ── 1) one case per OPEN position (position_health rows) ───
    health_rows = (health_doc or {}).get("rows", []) if isinstance(health_doc, dict) else []
    for row in health_rows:
        owner = str(row.get("owner", "")).upper()
        ticker = str(row.get("ticker", "")).upper()
        if not owner or not ticker:
            continue
        key = (owner, ticker)
        seen.add(key)
        sector = row.get("sector") or "Unknown"
        cf = TradeCaseFile(
            case_id=f"{owner}:{ticker}",
            account_id=owner,
            ticker=ticker,
            name=ticker,
            sector=sector,
            state="OPEN",
        )
        # execution
        cf.execution = {
            "qty": _num(row.get("qty")),
            "avg_entry": _num(row.get("avg_entry")),
            "current_price": _num(row.get("current_price")),
            "unrealized_pl": _num(row.get("unrealized_pl")),
            "unrealized_pl_pct": _num(row.get("unrealized_pl_pct")),
            "time_held_days": _num(row.get("time_held_days")),
        }
        # health
        cf.health = {
            "momentum_score": _num(row.get("momentum_score")),
            "narrative_drift": _num(row.get("narrative_drift")),
            "vulnerability_score": _num(row.get("vulnerability_score")),
            "rotation_score": _num(row.get("rotation_score")),
            "relative_strength": _num(row.get("relative_strength")),
            "status": _health_status(row, health_doc),
        }
        _attach_shared(cf, key, ticker, sector, global_regime, dominant_narrative,
                       sector_pressure, advisory_idx, attribution_idx, recon_idx,
                       harvest_idx, ledger_idx, plans_idx, conviction_idx, catalyst_idx)
        # P4.1: broker-truth trade-epoch anchor (resets on close→reopen)
        live_epoch = str((exec_snap_idx.get((owner, ticker)) or {}).get("first_seen") or "")
        _carry_forward(cf, prior_by_id, live_epoch)
        # P2: execution-quality forensics into the canonical execution section
        _attach_execution_forensics(cf, owner, ticker, exec_orders_idx,
                                    exec_snap_idx, exec_errors_by_acct)
        # P3: measurable move attribution into the canonical attribution section
        _attach_move_attribution(cf, sector_pressure)
        # P4: operational learning state of the responsible agents
        _attach_learning_state(cf, learn_scoring_idx, learn_risk_idx, learn_system)
        # P4.2/P4.3: observational shadow governor + dry-run diff (applied=false)
        _attach_fill_policy_shadow(cf, prior_by_id, oq_idx)
        cases.append(cf)

    # ── 2) PLANNED trades (this cycle's plans not yet open) ────
    for ticker, plan in plans_idx.items():
        # planned trades have no account yet -> PENDING owner
        key = ("PENDING", ticker)
        if any(k[1] == ticker for k in seen):
            continue  # already represented as an open position
        cf = TradeCaseFile(
            case_id=f"PENDING:{ticker}",
            account_id="PENDING",
            ticker=ticker,
            name=plan.get("name", ticker),
            sector=plan.get("sector", "Unknown"),
            state="PLANNED",
        )
        _attach_shared(cf, key, ticker, cf.sector, global_regime, dominant_narrative,
                       sector_pressure, advisory_idx, attribution_idx, recon_idx,
                       harvest_idx, ledger_idx, plans_idx, conviction_idx, catalyst_idx)
        _carry_forward(cf, prior_by_id)
        cases.append(cf)
        seen.add(key)

    # ── summary ────────────────────────────────────────────────
    open_n = sum(1 for c in cases if c.state == "OPEN")
    planned_n = sum(1 for c in cases if c.state == "PLANNED")
    with_harvest = sum(1 for c in cases if (c.harvest.get("realized_total") or 0) > 0)
    reconciled = sum(1 for c in cases if c.attribution.get("reconciliation") == "gold")

    # ── P4.3: observational cohort audit (telemetry / density / readiness) ──
    fill_policy_audit = None
    try:
        from ..execution.fill_policy_telemetry import build_audit
        open_dicts = [c.to_dict() for c in cases if c.state == "OPEN"]
        prior_audit = prior_payload.get("fill_policy_audit") if isinstance(prior_payload, dict) else None
        fill_policy_audit = build_audit(open_dicts, prior_audit)
    except Exception as _e:
        fill_policy_audit = {"error": f"audit build skipped: {_e}"}

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "doc": "Canonical per-trade forensic case files. Single source of "
               "truth for trade reasoning/execution/attribution/harvest/"
               "regime/catalyst/learning. Built by trade_engine.case_file "
               "(projection over existing emitters; not a parallel pipeline).",
        "source_files": source_files,
        "regime_context": global_regime,
        "summary": {
            "total": len(cases),
            "open": open_n,
            "planned": planned_n,
            "with_realized_harvest": with_harvest,
            "reconciled_gold": reconciled,
        },
        "fill_policy_audit": fill_policy_audit,   # P4.3 observational dashboard
        "cases": [c.to_dict() for c in cases],
    }

    if write:
        # P4.1 hardening: allow_nan=False so a non-finite (NaN/Inf) value FAILS
        # LOUDLY rather than emitting invalid JSON a reader might coerce. This
        # protects the null/HOLD-NEUTRAL guarantee end-to-end.
        try:
            text = json.dumps(payload, indent=2, default=str, allow_nan=False)
        except ValueError as e:
            raise ValueError(
                "trade_case_files serialization blocked a non-finite (NaN/Inf) "
                f"value — refusing to emit invalid JSON: {e}"
            ) from e
        (out / OUTPUT_FILE).write_text(text)

    return payload


# ──────────────────────────────────────────────────────────────────────────
# shared attachment (reasoning / attribution / regime / catalyst / narrative /
# harvest / learning) — applied to both OPEN and PLANNED cases
# ──────────────────────────────────────────────────────────────────────────
def _attach_shared(cf, key, ticker, sector, global_regime, dominant_narrative,
                   sector_pressure, advisory_idx, attribution_idx, recon_idx,
                   harvest_idx, ledger_idx, plans_idx, conviction_idx, catalyst_idx):
    # reasoning (plan levels + conviction)
    plan = plans_idx.get(ticker, {})
    conv = conviction_idx.get(ticker, {})
    cf.reasoning = {
        "consensus_signal": plan.get("consensus_signal") or conv.get("signal"),
        "conviction": _num(plan.get("conviction") if plan.get("conviction") is not None
                           else conv.get("conviction") or conv.get("score")),
        "backers": plan.get("backers", []),
        "dissenters": plan.get("dissenters", []),
        "invalidation": plan.get("invalidation"),
        "intended_entry": _num(plan.get("entry")),
        "intended_stop": _num(plan.get("stop")),
        "intended_target": _num(plan.get("target")),
        "reward_risk": _num(plan.get("reward_risk_ratio")),
        "intended_risk_pct": _num(plan.get("risk_pct_of_portfolio")),
    }
    # attribution
    cf.attribution = {
        "driving_agents": attribution_idx.get(ticker, []),
        "reconciliation": recon_idx.get(ticker, "unknown"),
    }
    # regime (global)
    cf.regime_state = dict(global_regime)
    # narrative
    cf.narrative_state = {
        "dominant_narrative": dominant_narrative,
        "sector_pressure": (sector_pressure.get(sector)
                            if isinstance(sector_pressure, dict) else None),
    }
    # catalysts touching this name
    cf.catalyst_state = {"catalysts": catalyst_idx.get(ticker, [])}
    # harvest (advisory recommendation + realized)
    adv = advisory_idx.get(key, {}) or advisory_idx.get(("*", ticker), {})
    realized = harvest_idx.get(ticker, [])
    cf.harvest = {
        "recommendation": adv.get("recommendation"),
        "rationale": adv.get("rationale"),
        "aggression": adv.get("aggression"),
        "realized_harvests": realized,
        "realized_total": round(sum(_num(h.get("amount")) or 0 for h in realized), 2),
    }
    # learning / ledger events for this name
    cf.learning = {"ledger_events": ledger_idx.get(ticker, [])}


def _carry_forward(cf: "TradeCaseFile", prior_by_id: Dict[str, Dict],
                   live_epoch: str = "") -> None:
    """Preserve entry-time forensics across cycles, EPOCH-GATED (P4.1).

    The plan that created a position ages out of trade_plans.json after its
    cycle. If THIS cycle produced no fresh reasoning/attribution for the case
    but a PRIOR canonical record did, carry the prior values forward so the
    WHY/WHO survives for the full life of the trade. Live execution/health/
    regime fields are always taken fresh (never carried).

    P4.1 trade-epoch gate: a carried `intended_entry` is valid ONLY within the
    SAME trade epoch (broker `positions_snapshot.first_seen`, which resets on a
    confirmed close→reopen). On epoch mismatch or unknown epoch the carried
    `intended_entry` is DROPPED (fail-safe to null / not_measurable) so a stale
    prior-trade price can never produce a measurable-but-wrong fill quality.
    Epoch state is observational/provenance only; it changes no behavior.
    """
    cf.entry_epoch = str(live_epoch or "")
    prior = prior_by_id.get(cf.case_id)
    if not prior:
        # No prior record. A fresh same-cycle plan entry is this epoch's own
        # intent → same-epoch when the epoch is known; otherwise unknown.
        if cf.reasoning.get("intended_entry") is not None:
            cf.reasoning["intended_entry_epoch_match"] = bool(cf.entry_epoch)
        else:
            cf.reasoning["intended_entry_epoch_match"] = None
        return
    # preserve original first_seen
    cf.first_seen = prior.get("first_seen", cf.first_seen)

    prior_epoch = str(prior.get("entry_epoch") or "")
    epoch_known = bool(cf.entry_epoch) and bool(prior_epoch)
    epoch_match = epoch_known and (cf.entry_epoch == prior_epoch)

    # reasoning: carry forward only if this cycle has nothing
    r = cf.reasoning
    reasoning_empty = (not r.get("consensus_signal")
                       and not r.get("backers")
                       and r.get("intended_entry") is None)
    if reasoning_empty and isinstance(prior.get("reasoning"), dict):
        pr = dict(prior["reasoning"])   # copy: never mutate the prior record
        if pr.get("consensus_signal") or pr.get("backers") or pr.get("intended_entry") is not None:
            if not epoch_match:
                # EPOCH MISMATCH/UNKNOWN → drop stale intended_entry (fail-safe).
                # Other carried context (backers/consensus) is left as prior
                # behavior; only the price reference that feeds fill quality is
                # invalidated.
                pr["intended_entry"] = None
            cf.reasoning = pr
            cf.reasoning["_carried_from_entry"] = True
            cf.reasoning["intended_entry_epoch_match"] = (
                True if (epoch_match and pr.get("intended_entry") is not None) else False
            )
    else:
        # fresh reasoning this cycle: a fresh plan entry refers to the current
        # epoch's intent → same-epoch when the epoch is known.
        if cf.reasoning.get("intended_entry") is not None:
            cf.reasoning["intended_entry_epoch_match"] = bool(cf.entry_epoch)
        else:
            cf.reasoning["intended_entry_epoch_match"] = None

    # attribution: carry forward driving agents if absent this cycle (unchanged)
    a = cf.attribution
    if not a.get("driving_agents") and isinstance(prior.get("attribution"), dict):
        pa = prior["attribution"]
        if pa.get("driving_agents"):
            cf.attribution["driving_agents"] = pa["driving_agents"]
            cf.attribution["_carried_from_entry"] = True
        # keep the most informative reconciliation
        if a.get("reconciliation") == "unknown" and pa.get("reconciliation") not in (None, "unknown"):
            cf.attribution["reconciliation"] = pa["reconciliation"]


# ──────────────────────────────────────────────────────────────────────────
# source indexers
# ──────────────────────────────────────────────────────────────────────────
def _index_execution_state(out: Path):
    """Index real order/fill records from the broker state files.

    Returns (orders_by_(acct,ticker), snapshot_by_(acct,ticker),
    errors_by_account). Covers the three Alpaca harvest accounts; other
    owner types (agent portfolios) simply won't have entries and degrade to
    position-level forensics.
    """
    acct_files = {
        "LEGACY": "alpaca_paper_state.json",
        "HARVEST_3": "alpaca_h3_state.json",
        "HARVEST_5": "alpaca_h5_state.json",
    }
    orders_by_key: Dict[Any, List[Dict]] = {}
    snap_by_key: Dict[Any, Dict] = {}
    errors_by_acct: Dict[str, List[Dict]] = {}
    for acct, fname in acct_files.items():
        doc = _load(out / fname)
        if not isinstance(doc, dict):
            continue
        errors_by_acct[acct] = doc.get("errors", []) or []
        for o in doc.get("orders", []) or []:
            sym = str(o.get("symbol") or o.get("ticker") or "").upper()
            if sym:
                orders_by_key.setdefault((acct, sym), []).append(o)
        for s in doc.get("positions_snapshot", []) or []:
            sym = str(s.get("symbol") or s.get("ticker") or "").upper()
            if sym:
                snap_by_key[(acct, sym)] = s
    return orders_by_key, snap_by_key, errors_by_acct


def _attach_execution_forensics(cf, owner, ticker, orders_idx, snap_idx, errors_by_acct):
    """Embed P2 execution-quality forensics into cf.execution['forensics']."""
    try:
        from ..execution.forensics import build_execution_forensics
    except Exception:
        return
    key = (owner, ticker)
    orders = orders_idx.get(key, [])
    snapshot = snap_idx.get(key)
    intended = {"intended_entry": (cf.reasoning or {}).get("intended_entry")}
    forensic = build_execution_forensics(
        orders=orders,
        snapshot_row=snapshot,
        intended=intended,
        broker_errors=errors_by_acct.get(owner, []),
        ticker=ticker,
        intended_entry_epoch_match=(cf.reasoning or {}).get("intended_entry_epoch_match"),
    )
    forensic["order_data_available"] = bool(orders) or snapshot is not None
    cf.execution["forensics"] = forensic


def _attach_move_attribution(cf, sector_pressure_map):
    """Embed P3 measurable move attribution into cf.attribution['move_attribution']."""
    try:
        from ..portfolios.move_attribution import build_move_attribution
    except Exception:
        return
    ma = build_move_attribution(cf.to_dict(), sector_pressure_map=sector_pressure_map)
    cf.attribution["move_attribution"] = ma


def _index_learning_state(out: Path):
    """Index the OPERATIONAL learning state: per-agent scoring weight and
    risk-engine freeze status, plus a system rollup. Deterministic join over
    the emitters the closed loop already writes (scoring.json, risk_state.json).
    """
    scoring = _load(out / "scoring.json")
    risk = _load(out / "risk_state.json")
    scoring_idx: Dict[str, Dict] = {}
    if isinstance(scoring, dict):
        for r in (scoring.get("leaderboard") or []):
            a = r.get("agent")
            if a:
                scoring_idx[a] = {
                    "weight_multiplier": r.get("weight_multiplier"),
                    "scored_calls": r.get("scored_calls"),
                    "win_rate": r.get("win_rate"),
                    "specialty": r.get("specialty"),
                }
    risk_idx: Dict[str, Dict] = {}
    # Phase-1 reconciliation: the two cohort safe-modes are computed
    # INDEPENDENTLY (agent layer vs harvest layer). Report BOTH with
    # provenance and a divergence flag — never collapse to one boolean.
    hard_stops = _load(out / "hard_stops.json")
    agent_safe = bool((risk.get("system") or {}).get("safe_mode")) if isinstance(risk, dict) else False
    harvest_safe = bool((hard_stops.get("system") or {}).get("cohort_safe_mode")) if isinstance(hard_stops, dict) else False
    system = {
        "frozen_agent_count": 0,
        "total_scored_calls": (scoring or {}).get("total_scored_calls", 0)
        if isinstance(scoring, dict) else 0,
        "cohort_safe_mode": {
            "agent_layer": {
                "active": agent_safe,
                "scope": "$10K agent portfolios",
                "source": "risk_state.json:system.safe_mode",
            },
            "harvest_layer": {
                "active": harvest_safe,
                "scope": "Alpaca harvest accounts (LEGACY/H3/H5)",
                "source": "hard_stops.json:system.cohort_safe_mode",
            },
            "divergent": agent_safe != harvest_safe,
            "any_active": agent_safe or harvest_safe,
        },
    }
    if isinstance(risk, dict):
        for a, st in (risk.get("agents") or {}).items():
            if isinstance(st, dict):
                risk_idx[a] = {"frozen": bool(st.get("frozen")),
                               "frozen_reason": st.get("frozen_reason", "")}
        system["frozen_agent_count"] = sum(1 for v in risk_idx.values() if v["frozen"])
    return scoring_idx, risk_idx, system


def _attach_fill_policy_shadow(cf, prior_by_id, oq_idx=None):
    """P4.2/P4.3: attach the observational shadow-governor block + dry-run diff.
    applied=false; epoch-gated cross-cycle state read from the prior case file.
    Reads LIVE order_quality.limit_buffer_bps read-only for the diff; never
    mutates order_quality/executor/risk. Fully removable with this helper +
    its call."""
    try:
        from ..execution.fill_policy_governor import compute_fill_policy_shadow
        from ..execution.fill_policy_telemetry import compute_diff
    except Exception:
        return
    forensics = cf.execution.get("forensics") if isinstance(cf.execution, dict) else None
    if not isinstance(forensics, dict):
        return
    prior = prior_by_id.get(cf.case_id) or {}
    prior_forensics = ((prior.get("execution") or {}).get("forensics") or {})
    prior_shadow = prior_forensics.get("fill_policy_shadow")
    shadow = compute_fill_policy_shadow(
        forensics=forensics, entry_epoch=cf.entry_epoch, prior_shadow=prior_shadow)
    # P4.3 dry-run diff against LIVE limit_buffer_bps (executor default 30 when absent)
    oq_row = (oq_idx or {}).get(str(cf.ticker).upper()) or {}
    live_buffer = oq_row.get("limit_buffer_bps", 30)
    prior_diff = (prior_shadow or {}).get("diff")
    shadow["diff"] = compute_diff(shadow, live_buffer, prior_diff)
    forensics["fill_policy_shadow"] = shadow


def _attach_learning_state(cf, scoring_idx, risk_idx, system):
    """Embed each trade's responsible-agent learning state into cf.learning.

    Reports the OPERATIONAL outcome of the closed loop (scoring weight → kill
    switch freeze) for the agents that drove this trade. This is observational
    reporting of an operational mechanism: the freeze itself changes behavior
    (a frozen agent stops opening trades); this surfaces whether that happened
    to the agents responsible for THIS trade.
    """
    driving = (cf.attribution or {}).get("driving_agents") or []
    names = []
    for d in driving:
        n = d.get("agent") if isinstance(d, dict) else d
        if n and n not in names:
            names.append(n)

    responsible = []
    authority_changed = False
    for n in names:
        sc = scoring_idx.get(n, {})
        rk = risk_idx.get(n, {})
        frozen = rk.get("frozen", False)
        wm = sc.get("weight_multiplier")
        if frozen:
            authority = "FROZEN"; authority_changed = True
        elif wm is None or sc.get("scored_calls", 0) == 0:
            authority = "unscored"
        elif wm < 0.85:
            authority = "reduced"; authority_changed = True
        elif wm > 1.15:
            authority = "boosted"; authority_changed = True
        else:
            authority = "neutral"
        responsible.append({
            "agent": n, "weight_multiplier": wm,
            "scored_calls": sc.get("scored_calls"), "specialty": sc.get("specialty"),
            "frozen": frozen, "authority": authority,
        })

    if not names:
        interpretation = ("no single responsible agent (consensus/harvest position); "
                          "capital authority governed by the cohort kill switch")
    elif authority_changed:
        froze = [r["agent"] for r in responsible if r["frozen"]]
        interpretation = (
            f"{len(names)} driving agent(s); authority CHANGED — "
            + (f"{', '.join(froze)} now FROZEN (no new opens). " if froze else "")
            + "future behavior altered by the learning loop")
    else:
        interpretation = (f"{len(names)} driving agent(s); authority unchanged this cycle")

    cf.learning["loop_state"] = {
        "responsible_agents": responsible,
        "authority_changed": authority_changed,
        "system": system,
        "interpretation": interpretation,
    }


# ──────────────────────────────────────────────────────────────────────────
# join-source indexers
# ──────────────────────────────────────────────────────────────────────────
def _global_regime(market_doc, regime_doc) -> Dict[str, Any]:
    md = market_doc if isinstance(market_doc, dict) else {}
    rd = regime_doc if isinstance(regime_doc, dict) else {}
    return {
        "regime": md.get("regime"),
        "vix": _num(md.get("vix")),
        "session": md.get("session"),
        "mode": md.get("mode"),
        "current_regimes": rd.get("current_regimes"),
    }


def _index_advisory(advisory_doc) -> Dict[Any, Dict]:
    idx: Dict[Any, Dict] = {}
    if not isinstance(advisory_doc, dict):
        return idx
    for a in advisory_doc.get("advisories", []) or []:
        owner = str(a.get("owner", "")).upper()
        ticker = str(a.get("ticker", "")).upper()
        if ticker:
            idx[(owner, ticker)] = a
            idx[("*", ticker)] = a  # fallback for owner-agnostic match
    return idx


def _index_attribution(attribution_doc):
    """Return (ticker->driving_agents, ticker->reconciliation)."""
    agents_idx: Dict[str, List[str]] = {}
    recon_idx: Dict[str, str] = {}
    if not isinstance(attribution_doc, dict):
        return agents_idx, recon_idx
    latest = attribution_doc.get("latest", {}) or {}
    for o in latest.get("tagged_orders", []) or []:
        sym = str(o.get("symbol") or o.get("ticker") or "").upper()
        if sym:
            agents_idx[sym] = o.get("driving_agents", [])
    for sym in latest.get("gold", []) or []:
        recon_idx[str(sym).upper()] = "gold"
    for sym in latest.get("orphans", []) or []:
        recon_idx[str(sym).upper()] = "orphan"
    for sym in latest.get("phantoms", []) or []:
        recon_idx[str(sym).upper()] = "phantom"
    return agents_idx, recon_idx


def _index_harvest(harvest_doc) -> Dict[str, List[Dict]]:
    idx: Dict[str, List[Dict]] = {}
    if not isinstance(harvest_doc, dict):
        return idx
    for r in harvest_doc.get("rows", []) or []:
        for sym in (r.get("source_tickers") or []):
            sym = str(sym).upper()
            idx.setdefault(sym, []).append({
                "id": r.get("id"),
                "account_id": r.get("account_id"),
                "status": r.get("status"),
                "amount": _num(r.get("amount")),
                "date": r.get("date"),
                "agent_attribution": r.get("agent_attribution"),
            })
    return idx


def _index_ledger(ledger_doc) -> Dict[str, List[Dict]]:
    idx: Dict[str, List[Dict]] = {}
    if not isinstance(ledger_doc, dict):
        return idx
    for r in ledger_doc.get("rows", []) or []:
        sym = str(r.get("ticker", "")).upper()
        if not sym:
            continue
        bucket = idx.setdefault(sym, [])
        if len(bucket) < 20:  # cap per name
            bucket.append({
                "ts": r.get("ts"),
                "category": r.get("category"),
                "account_id": r.get("account_id"),
                "reason": r.get("reason"),
            })
    return idx


def _index_plans(plans_doc, debate_dicts) -> Dict[str, Dict]:
    """Index this cycle's trade plans by ticker; enrich conviction from debates."""
    idx: Dict[str, Dict] = {}
    if isinstance(plans_doc, dict):
        for p in plans_doc.get("plans", []) or []:
            sym = str(p.get("ticker", "")).upper()
            if sym:
                idx[sym] = p
    # enrich with live debate conviction where a plan is absent
    if debate_dicts:
        for d in debate_dicts:
            sym = str(d.get("ticker", "")).upper()
            if not sym:
                continue
            cons = d.get("consensus", {}) or {}
            entry = idx.setdefault(sym, {})
            entry.setdefault("ticker", sym)
            entry.setdefault("name", d.get("name", sym))
            entry.setdefault("consensus_signal", cons.get("signal"))
            if entry.get("conviction") is None:
                entry["conviction"] = cons.get("avg_conviction")
            if not entry.get("backers"):
                entry["backers"] = [
                    {"agent": v.get("agent"), "conviction": v.get("conviction"),
                     "rationale": v.get("rationale")}
                    for v in d.get("verdicts", [])
                    if v.get("signal") in ("BUY", "STRONG_BUY")
                ]
            if not entry.get("dissenters"):
                entry["dissenters"] = [
                    {"agent": v.get("agent"), "signal": v.get("signal"),
                     "conviction": v.get("conviction"), "rationale": v.get("rationale")}
                    for v in d.get("verdicts", [])
                    if v.get("signal") in ("SELL", "STRONG_SELL")
                ]
    return idx


def _index_conviction(conviction_doc) -> Dict[str, Dict]:
    idx: Dict[str, Dict] = {}
    if not isinstance(conviction_doc, dict):
        return idx
    for bucket in ("ranked_opportunities", "holdings_review"):
        for o in conviction_doc.get(bucket, []) or []:
            sym = str(o.get("ticker", "")).upper()
            if sym and sym not in idx:
                idx[sym] = o
    return idx


def _index_catalysts(catalyst_doc) -> Dict[str, List[Dict]]:
    """Map ticker -> catalysts that explicitly reference it."""
    idx: Dict[str, List[Dict]] = {}
    if not isinstance(catalyst_doc, dict):
        return idx
    for bucket in ("daily", "weekly"):
        items = catalyst_doc.get(bucket)
        if not isinstance(items, list):
            continue
        for c in items:
            if not isinstance(c, dict):
                continue
            syms = c.get("tickers") or c.get("symbols") or []
            if isinstance(syms, str):
                syms = [syms]
            single = c.get("ticker") or c.get("symbol")
            if single:
                syms = list(syms) + [single]
            for sym in syms:
                sym = str(sym).upper()
                idx.setdefault(sym, []).append({
                    "type": c.get("type") or c.get("kind") or bucket,
                    "label": c.get("label") or c.get("title") or c.get("name"),
                    "date": c.get("date") or c.get("when"),
                })
    return idx


def _health_status(row: Dict, health_doc) -> str:
    """Derive healthy|watch|force_rotation from rotation/vulnerability scores."""
    rot = _num(row.get("rotation_score")) or 0
    vul = _num(row.get("vulnerability_score")) or 0
    if rot >= 0.66 or vul >= 0.75:
        return "force_rotation"
    if rot >= 0.4 or vul >= 0.5:
        return "watch"
    return "healthy"


__all__ = ["TradeCaseFile", "build_case_files", "SCHEMA_VERSION", "OUTPUT_FILE"]
