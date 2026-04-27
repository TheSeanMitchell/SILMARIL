"""
silmaril.agents.base — The contract every SILMARIL agent honors.

Every agent is a self-contained strategy. It receives an AssetContext
(everything the system knows about one asset at one point in time) and
returns a Verdict (its opinion, its conviction, and its reasoning).

The system does NOT reward agents for being right. It rewards them for
being clear. An agent that says HOLD with high conviction and a clean
rationale is more valuable than one that says BUY and gets lucky.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────
# Signal taxonomy
# ─────────────────────────────────────────────────────────────────

class Signal(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    ABSTAIN = "ABSTAIN"   # agent has no opinion on this asset (wrong specialty)


# ─────────────────────────────────────────────────────────────────
# AssetContext: everything an agent sees about one asset
# ─────────────────────────────────────────────────────────────────

@dataclass
class AssetContext:
    """The snapshot one agent receives when asked to evaluate one asset."""
    ticker: str
    name: str
    sector: Optional[str] = None
    asset_class: str = "equity"        # equity | etf | crypto | fx | commodity | rate

    # Price data (latest + short history)
    price: Optional[float] = None
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    avg_volume_30d: Optional[int] = None
    price_history: List[float] = field(default_factory=list)    # last N closes, oldest first

    # Technical indicators (computed upstream by analytics/)
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None           # average true range — volatility measure
    bb_width: Optional[float] = None         # Bollinger band width

    # Sentiment (aggregated from articles)
    sentiment_score: Optional[float] = None  # -1.0 .. +1.0
    article_count: int = 0
    source_count: int = 0
    recent_headlines: List[Dict[str, Any]] = field(default_factory=list)

    # Events
    earnings_date: Optional[str] = None
    days_to_earnings: Optional[int] = None
    event_flags: List[str] = field(default_factory=list)  # e.g. ["fda_pdufa", "fomc_week"]

    # Cross-market context
    correlations: Dict[str, float] = field(default_factory=dict)  # ticker -> corr coefficient

    # Market regime (same for all assets in one run — passed through for convenience)
    market_regime: str = "NEUTRAL"           # RISK_ON | RISK_OFF | NEUTRAL
    vix: Optional[float] = None


# ─────────────────────────────────────────────────────────────────
# Verdict: what an agent returns
# ─────────────────────────────────────────────────────────────────

@dataclass
class Verdict:
    """One agent's opinion on one asset at one moment."""
    agent: str                          # codename, e.g. "AEGIS"
    ticker: str
    signal: Signal
    conviction: float                   # 0.0 .. 1.0 — how strongly the agent believes it
    rationale: str                      # one-sentence human-readable reasoning
    factors: Dict[str, Any] = field(default_factory=dict)  # machine-readable evidence

    # Optional: if agent wants to pin a trade plan
    suggested_entry: Optional[float] = None
    suggested_stop: Optional[float] = None
    suggested_target: Optional[float] = None
    invalidation: Optional[str] = None  # plain-English: what would kill this thesis

    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "ticker": self.ticker,
            "signal": self.signal.value,
            "conviction": round(self.conviction, 3),
            "rationale": self.rationale,
            "factors": self.factors,
            "suggested_entry": self.suggested_entry,
            "suggested_stop": self.suggested_stop,
            "suggested_target": self.suggested_target,
            "invalidation": self.invalidation,
            "timestamp": self.timestamp.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────
# Agent: the abstract contract
# ─────────────────────────────────────────────────────────────────

class Agent(ABC):
    """Abstract base class for all SILMARIL agents.

    Every agent subclass defines:
      - codename:        the public identifier (e.g. "AEGIS")
      - specialty:       one-line description of its strategy
      - temperament:     how it "feels" (shown on agent profile pages)
      - inspiration:     the archetype it riffs on (for design reference only)
      - asset_classes:   which asset types it evaluates; ABSTAIN on others
    """

    # --- metadata (override in subclass) ---
    codename: str = "BASE"
    specialty: str = ""
    temperament: str = ""
    inspiration: str = ""
    asset_classes: tuple = ("equity", "etf")   # default: stocks and ETFs only

    # --- portfolio (initialized by the portfolio manager) ---
    starting_capital: float = 10_000.0

    def applies_to(self, ctx: AssetContext) -> bool:
        """Whether this agent has an opinion on this asset class at all."""
        return ctx.asset_class in self.asset_classes

    def evaluate(self, ctx: AssetContext) -> Verdict:
        """Public entry point. Checks applicability, then delegates to _judge()."""
        if not self.applies_to(ctx):
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale=f"{self.codename} does not evaluate {ctx.asset_class} assets.",
            )
        return self._judge(ctx)

    @abstractmethod
    def _judge(self, ctx: AssetContext) -> Verdict:
        """Produce a Verdict. Override this in every concrete agent."""
        raise NotImplementedError

    # --- helpers available to every agent ---

    @staticmethod
    def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, x))

    @staticmethod
    def _pct_above(price: float, reference: float) -> float:
        """Return (price - reference) / reference, handling None/zero safely."""
        if not reference or reference == 0:
            return 0.0
        return (price - reference) / reference
