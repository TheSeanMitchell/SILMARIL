"""
silmaril.backtest.engine

The main BacktestEngine. Wires together: data loading, day-by-day replay,
agent invocation, prediction logging, and result writing.

This version invokes agents via their real interface:
  - agent.codename       (not agent.name)
  - agent.applies_to(ctx) (filter)
  - agent.evaluate(ctx)   (returns Verdict)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .data_loader import (
    HistoryBundle,
    load_universe_history,
    load_vix_series,
    load_tnx_series,
    trading_days_between,
)
from .replay import (
    build_context,
    classify_regime,
    next_day_return,
)


@dataclass
class BacktestConfig:
    tickers: List[str]
    start: date
    end: date
    agents: List[Any]  # real silmaril.agents.base.Agent instances
    use_cache: bool = True
    skip_news_dependent: bool = True
    output_path: Optional[str] = None


@dataclass
class Prediction:
    """A single agent verdict at a moment in time, with its eventual outcome."""
    date: str
    ticker: str
    asset_class: str
    agent: str
    signal: str
    conviction: float
    rationale: str
    regime: str
    next_day_return: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "ticker": self.ticker,
            "asset_class": self.asset_class,
            "agent": self.agent,
            "signal": self.signal,
            "conviction": self.conviction,
            "rationale": self.rationale,
            "regime": self.regime,
            "next_day_return": self.next_day_return,
        }


@dataclass
class BacktestResult:
    config: BacktestConfig
    predictions: List[Prediction] = field(default_factory=list)
    coverage: Dict[str, int] = field(default_factory=dict)
    days_replayed: int = 0
    universe_loaded: int = 0

    def summary(self) -> str:
        lines = [
            "=" * 60,
            f"SILMARIL BACKTEST -- {self.config.start} to {self.config.end}",
            "=" * 60,
            f"Days replayed:    {self.days_replayed}",
            f"Tickers loaded:   {self.universe_loaded}/{len(self.config.tickers)}",
            f"Total predictions: {len(self.predictions)}",
            "",
            "Agent coverage (predictions made):",
        ]
        for agent_name, count in sorted(self.coverage.items(), key=lambda x: -x[1]):
            lines.append(f"  {agent_name:18s}  {count:>6} predictions")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": {
                "start": self.config.start.isoformat(),
                "end": self.config.end.isoformat(),
                "tickers": self.config.tickers,
                "agents": [_agent_label(a) for a in self.config.agents],
            },
            "days_replayed": self.days_replayed,
            "universe_loaded": self.universe_loaded,
            "coverage": self.coverage,
            "predictions": [p.to_dict() for p in self.predictions],
        }


def _agent_label(agent: Any) -> str:
    """Get a stable name for an agent instance.
    Real SILMARIL agents have .codename. Stubs may have .name."""
    return getattr(agent, "codename", None) or getattr(agent, "name", None) or agent.__class__.__name__


class BacktestEngine:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.history: Dict[str, HistoryBundle] = {}
        self.vix: Optional[pd.Series] = None
        self.tnx: Optional[pd.Series] = None

    # --- Data preparation ---

    def load_data(self) -> None:
        if not self.history:
            self.history = load_universe_history(
                self.config.tickers, self.config.start, self.config.end,
                use_cache=self.config.use_cache,
            )
        if self.vix is None:
            self.vix = load_vix_series(self.config.start, self.config.end)
        if self.tnx is None:
            self.tnx = load_tnx_series(self.config.start, self.config.end)

    def _vix_at(self, d: date) -> Optional[float]:
        if self.vix is None:
            return None
        ts = pd.Timestamp(d)
        sub = self.vix[self.vix.index <= ts]
        if sub.empty:
            return None
        return float(sub.iloc[-1])

    def _tnx_at(self, d: date) -> Optional[float]:
        if self.tnx is None:
            return None
        ts = pd.Timestamp(d)
        sub = self.tnx[self.tnx.index <= ts]
        if sub.empty:
            return None
        return float(sub.iloc[-1])

    def _spy_momentum_20d(self, d: date) -> Optional[float]:
        spy = self.history.get("SPY")
        if spy is None:
            return None
        h = spy.slice_as_of(d, lookback_days=30)
        if len(h) < 21:
            return None
        return float(h["Close"].iloc[-1] / h["Close"].iloc[-21] - 1.0)

    # --- Replay loop ---

    def run(self) -> BacktestResult:
        self.load_data()
        result = BacktestResult(
            config=self.config,
            universe_loaded=len(self.history),
        )
        # Pre-populate coverage map with every agent's codename
        for agent in self.config.agents:
            result.coverage[_agent_label(agent)] = 0

        days = trading_days_between(self.config.start, self.config.end)
        print(f"[backtest] replaying {len(days)} trading days x "
              f"{len(self.history)} tickers x {len(self.config.agents)} agents")

        for i, d in enumerate(days):
            if i % 50 == 0 and i > 0:
                print(f"[backtest]   day {i}/{len(days)} ({d.isoformat()}), "
                      f"{len(result.predictions)} predictions so far")

            vix = self._vix_at(d)
            tnx = self._tnx_at(d)
            spy_mom = self._spy_momentum_20d(d)
            regime = classify_regime(vix, spy_mom)
            market_state = {
                "vix": vix, "tnx": tnx,
                "spy_momentum_20d": spy_mom, "regime": regime,
            }

            for ticker, bundle in self.history.items():
                ctx = build_context(
                    ticker, bundle, d,
                    vix_level=vix, tnx_level=tnx, regime=regime,
                    market_state=market_state,
                )
                if ctx is None:
                    continue

                ndr = next_day_return(bundle, d)

                for agent in self.config.agents:
                    label = _agent_label(agent)

                    # Real SILMARIL agents use evaluate(ctx) (which calls _judge internally).
                    # Stubs may use evaluate too, or judge. Try evaluate first.
                    try:
                        if hasattr(agent, "evaluate"):
                            verdict = agent.evaluate(ctx)
                        elif hasattr(agent, "judge"):
                            verdict = agent.judge(ctx)
                        else:
                            continue
                    except Exception as e:
                        # One agent's bug shouldn't kill the backtest
                        if i == 0 and result.coverage.get(label, 0) == 0:
                            # Only log first error per agent to avoid log spam
                            print(f"[backtest] {label} on {ticker}@{d}: {type(e).__name__}: {e}")
                        continue

                    sig = getattr(verdict, "signal", None)
                    if sig is None:
                        continue
                    sig_str = sig.name if hasattr(sig, "name") else str(sig)

                    pred = Prediction(
                        date=d.isoformat(),
                        ticker=ticker,
                        asset_class=ctx.asset_class,
                        agent=label,
                        signal=sig_str,
                        conviction=float(getattr(verdict, "conviction", 0.0) or 0.0),
                        rationale=str(getattr(verdict, "rationale", "") or ""),
                        regime=regime,
                        next_day_return=ndr,
                    )
                    result.predictions.append(pred)
                    result.coverage[label] = result.coverage.get(label, 0) + 1

            result.days_replayed += 1

        if self.config.output_path:
            self._write_json(result)

        return result

    def _write_json(self, result: BacktestResult) -> None:
        out = Path(self.config.output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)
        print(f"[backtest] wrote {out} ({len(result.predictions)} predictions)")
