"""
silmaril.learning — Adaptive ensemble layer (Alpha 2.0 Full Learning Mode).

This package closes the feedback loop. Daily runs accumulate outcomes;
this module turns those outcomes into adaptive behavior on the next run.

PRINCIPLE: Every artifact in this package is on the PROTECTED_LEARNING_FILES
list. No workflow may delete these files. Training never resets.
"""
from .persistence_guard import (
    PROTECTED_LEARNING_FILES,
    is_protected,
    safe_reset,
    backup_learning_state,
    verify_persistence,
    emit_persistence_status,
)
from .evolution_cards import (
    EvolutionCard,
    load_cards,
    save_cards,
    ensure_card,
    LEVEL_THRESHOLDS,
)
from .bayesian_winrate import (
    BetaState,
    AgentBeliefState,
    load_beliefs,
    save_beliefs,
    update_beliefs,
)
from .thompson_arbiter import (
    sample_conviction_multipliers,
    deterministic_multipliers,
)
from .dissent_digest import build_dissent_digest, attach_digest_to_contexts
from .reflection import load_reflection, format_reflection_for_context, append_reflection
from .counterfactual import log_counterfactual, score_counterfactuals
from .hysteresis import (
    HysteresisBand, with_hysteresis,
    RSI_OVERBOUGHT, RSI_OVERSOLD, VIX_PANIC, VIX_CALM,
)
from .regime_bandit import RegimeBanditStore, context_key
from .slippage import estimate_slippage_bps, apply_slippage_to_pnl
from .correlation_matrix import compute_position_correlations, append_to_history
from .time_of_day import get_tod_bucket, record_tod_outcome, best_buckets_for_agent
from .news_quality import confirmation_score, update_source_reliability
from .anomaly_detector import (
    detect_volume_spike, detect_price_gap, detect_atr_spike,
    detect_volume_divergence, record_anomalies, active_anomalies,
)
from .premortem import (
    generate_premortem, archive_premortem, attach_premortem_to_rationale,
)
from .adversarial_stress import stress_test_signals, save_stress_results, SCENARIOS
from .drift_detector import detect_drift, update_drift_state, get_drift_dampeners
from .position_sizing import kelly_position_pct, can_open_position

__all__ = [
    "PROTECTED_LEARNING_FILES", "is_protected", "safe_reset",
    "backup_learning_state", "verify_persistence", "emit_persistence_status",
    "EvolutionCard", "load_cards", "save_cards", "ensure_card", "LEVEL_THRESHOLDS",
    "BetaState", "AgentBeliefState", "load_beliefs", "save_beliefs", "update_beliefs",
    "sample_conviction_multipliers", "deterministic_multipliers",
    "build_dissent_digest", "attach_digest_to_contexts",
    "load_reflection", "format_reflection_for_context", "append_reflection",
    "log_counterfactual", "score_counterfactuals",
    "HysteresisBand", "with_hysteresis",
    "RSI_OVERBOUGHT", "RSI_OVERSOLD", "VIX_PANIC", "VIX_CALM",
    "RegimeBanditStore", "context_key",
    "estimate_slippage_bps", "apply_slippage_to_pnl",
    "compute_position_correlations", "append_to_history",
    "get_tod_bucket", "record_tod_outcome", "best_buckets_for_agent",
    "confirmation_score", "update_source_reliability",
    "detect_volume_spike", "detect_price_gap", "detect_atr_spike",
    "detect_volume_divergence", "record_anomalies", "active_anomalies",
    "generate_premortem", "archive_premortem", "attach_premortem_to_rationale",
    "stress_test_signals", "save_stress_results", "SCENARIOS",
    "detect_drift", "update_drift_state", "get_drift_dampeners",
    "kelly_position_pct", "can_open_position",
]
