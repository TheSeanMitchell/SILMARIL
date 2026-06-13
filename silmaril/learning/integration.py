"""
silmaril.learning.integration — One-call wiring for cli.py.

This module bundles every Alpha 2.0 learning enhancement into TWO functions
that hook into the existing cli.py daily-run pipeline:

  pre_debate_learning_setup(out_dir, contexts) -> LearningContext
      Call BEFORE agent voting. Loads beliefs, builds dissent digest,
      injects reflection, attaches learning_context to all asset contexts.

  post_debate_learning_update(out_dir, learning_ctx, results) -> None
      Call AFTER consensus and outcomes. Updates beliefs, evolution cards,
      time-of-day buckets, drift state, persistence status.

This gives the operator a clean integration: two function calls bracketing
the existing voting + arbiter logic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .bayesian_winrate import (
    AgentBeliefState, load_beliefs, save_beliefs, update_beliefs,
)
from .dissent_digest import build_dissent_digest, attach_digest_to_contexts
from .reflection import load_reflection, format_reflection_for_context
from .evolution_cards import (
    EvolutionCard, load_cards, save_cards, ensure_card,
)
from .counterfactual import log_counterfactual
from .regime_bandit import RegimeBanditStore, context_key
from .time_of_day import get_tod_bucket, record_tod_outcome
from .drift_detector import detect_drift, update_drift_state, get_drift_dampeners
from .persistence_guard import emit_persistence_status
from .correlation_matrix import compute_position_correlations, append_to_history
from .anomaly_detector import (
    detect_volume_spike, detect_price_gap, detect_atr_spike,
    detect_volume_divergence, record_anomalies, active_anomalies,
)


@dataclass
class LearningContext:
    """Bundle returned by pre-debate setup; consumed by post-debate update."""
    beliefs: Dict[str, AgentBeliefState] = field(default_factory=dict)
    cards: Dict[str, EvolutionCard] = field(default_factory=dict)
    bandit_store: Optional[RegimeBanditStore] = None
    rolling_winrates: Dict[str, float] = field(default_factory=dict)
    drift_dampeners: Dict[str, float] = field(default_factory=dict)
    digest: str = ""
    reflection: Optional[str] = None
    tod_bucket: str = "UNKNOWN"
    active_anomalies: List[Dict] = field(default_factory=list)
    out_dir: Optional[Path] = None
    timestamp: str = ""


def pre_debate_learning_setup(
    out_dir: Path,
    contexts: list,
) -> LearningContext:
    """
    Load all learning state and inject into asset contexts before voting.
    Idempotent — safe to call multiple times per day.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load beliefs
    beliefs = load_beliefs(out_dir / "agent_beliefs.json")

    # 2. Load evolution cards
    cards = load_cards(out_dir / "agent_evolution_cards.json")

    # 3. Bandit store
    bandit_store = RegimeBanditStore(out_dir / "regime_bandits.json")

    # 4. Build dissent digest from history + scoring
    digest = build_dissent_digest(
        scoring_path=out_dir / "scoring.json",
        history_path=out_dir / "history.json",
        counterfactuals_path=out_dir / "counterfactuals.json",
        lookback_days=7,
    )

    # 5. Load operator reflection
    reflection = load_reflection(out_dir / "reflections.json")
    reflection_block = format_reflection_for_context(reflection)

    # 6. Combine and attach to contexts
    learning_block = f"{digest}\n{reflection_block}".strip()
    if learning_block:
        attach_digest_to_contexts(contexts, learning_block)

    # 7. Compute rolling winrates from scoring
    rolling_winrates = {}
    scoring_path = out_dir / "scoring.json"
    if scoring_path.exists():
        try:
            sd = json.loads(scoring_path.read_text())
            for agent, stats in sd.get("by_agent", {}).items():
                rolling_winrates[agent] = stats.get("rolling_30d_win_rate", 0.50)
        except Exception:
            pass

    # 8. Drift dampeners
    drift_dampeners = get_drift_dampeners(out_dir / "drift_state.json")

    # 9. Time-of-day bucket
    tod_bucket = get_tod_bucket()

    # 10. Active anomalies
    anomalies = active_anomalies(out_dir / "anomaly_state.json")

    return LearningContext(
        beliefs=beliefs,
        cards=cards,
        bandit_store=bandit_store,
        rolling_winrates=rolling_winrates,
        drift_dampeners=drift_dampeners,
        digest=digest,
        reflection=reflection,
        tod_bucket=tod_bucket,
        active_anomalies=anomalies,
        out_dir=out_dir,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def post_debate_learning_update(
    learning_ctx: LearningContext,
    *,
    debates: List[Dict],
    portfolios: Optional[Dict] = None,
    price_history: Optional[Dict[str, List[float]]] = None,
    newly_scored_outcomes: Optional[List[Dict]] = None,
) -> Dict:
    """
    Update all learning state after a daily run completes.

    debates: list of {ticker, regime, asset_class, consensus_signal,
                      consensus_conviction, agreement_score, dissents,
                      verdicts}
    portfolios: optional, for correlation matrix computation
    price_history: optional {ticker: [last 90 closes]} for correlation
    newly_scored_outcomes: list of {agent, regime, won} from outcome scoring
    """
    out = learning_ctx.out_dir
    if out is None:
        return {"status": "no_out_dir"}

    report = {"updates": []}

    # 1. Update Bayesian beliefs
    if newly_scored_outcomes:
        learning_ctx.beliefs = update_beliefs(
            learning_ctx.beliefs, newly_scored_outcomes
        )
        save_beliefs(out / "agent_beliefs.json", learning_ctx.beliefs)
        report["updates"].append(f"beliefs: {len(newly_scored_outcomes)} outcomes")

    # 2. Update evolution cards (only grow)
    if newly_scored_outcomes:
        for o in newly_scored_outcomes:
            agent = o.get("agent")
            if not agent:
                continue
            card = ensure_card(learning_ctx.cards, agent)
            card.record_call(
                won=bool(o.get("won")),
                conviction=float(o.get("conviction", 0.5)),
                regime=o.get("regime", "UNKNOWN"),
                was_dissent=bool(o.get("was_dissent")),
            )
        save_cards(out / "agent_evolution_cards.json", learning_ctx.cards)
        report["updates"].append("evolution cards advanced")

    # 3. Update regime bandits (richer context)
    if newly_scored_outcomes:
        for o in newly_scored_outcomes:
            agent = o.get("agent")
            if not agent:
                continue
            ck = context_key(
                regime=o.get("regime", "UNKNOWN"),
                asset_class=o.get("asset_class", "equity"),
                vol=o.get("realized_vol"),
            )
            learning_ctx.bandit_store.update(agent, ck, bool(o.get("won")))
        learning_ctx.bandit_store.save()
        report["updates"].append("regime bandits advanced")

    # 4. Time-of-day performance
    if newly_scored_outcomes:
        for o in newly_scored_outcomes:
            agent = o.get("agent")
            if not agent:
                continue
            record_tod_outcome(
                out / "time_of_day_performance.json",
                agent,
                learning_ctx.tod_bucket,
                bool(o.get("won")),
            )
        report["updates"].append("time-of-day buckets advanced")

    # 5. Counterfactuals
    for d in debates:
        ndr = d.get("next_day_return")
        if ndr is None:
            continue
        for dissent in d.get("dissents", []):
            log_counterfactual(
                out / "counterfactuals.json",
                date_str=d.get("date", ""),
                ticker=d.get("ticker", ""),
                consensus_signal=d.get("consensus_signal", ""),
                dissenting_agent=dissent.get("agent", ""),
                dissent_signal=dissent.get("signal", ""),
                next_day_return=ndr,
            )

    # 6. Drift detection
    drift_by_agent = {}
    for agent, card in learning_ctx.cards.items():
        rolling = learning_ctx.rolling_winrates.get(agent, card.lifetime_win_rate)
        drift = detect_drift(
            rolling_30d_winrate=rolling,
            lifetime_winrate=card.lifetime_win_rate,
            n_recent_calls=min(card.lifetime_calls, 100),
        )
        if drift.get("drifting"):
            drift_by_agent[agent] = drift
    update_drift_state(out / "drift_state.json", drift_by_agent)
    if drift_by_agent:
        report["updates"].append(f"drift detected: {list(drift_by_agent.keys())}")

    # 7. Correlation matrix snapshot
    if portfolios and price_history:
        snap = compute_position_correlations(portfolios, price_history)
        append_to_history(out / "correlation_history.json", snap)
        report["updates"].append("correlation snapshot saved")

    # 8. Persistence health check
    emit_persistence_status(
        data_dir=out,
        output_path=out / "persistence_status.json",
    )
    report["updates"].append("persistence status emitted")

    return report


def detect_anomalies_for_universe(
    out_dir: Path,
    contexts: list,
) -> List[Dict]:
    """Scan all contexts for anomalies and persist to anomaly_state.json."""
    out_dir = Path(out_dir)
    state_path = out_dir / "anomaly_state.json"
    fresh_total = []
    for ctx in contexts:
        ticker = getattr(ctx, "ticker", None)
        if not ticker:
            continue
        anomalies = []
        cur_vol = getattr(ctx, "volume", None)
        avg_vol = getattr(ctx, "avg_volume_30d", None)
        if cur_vol and avg_vol:
            vs = detect_volume_spike(cur_vol, [avg_vol] * 30)  # rough; tighten if hist available
            if vs:
                anomalies.append(vs)
        prev_close = getattr(ctx, "prev_close", None)
        open_p = getattr(ctx, "open", None)
        if prev_close and open_p:
            pg = detect_price_gap(open_p, prev_close)
            if pg:
                anomalies.append(pg)
        if anomalies:
            fresh = record_anomalies(state_path, ticker, anomalies)
            fresh_total.extend(fresh)
    return fresh_total
