"""
silmaril.scoring.outcomes — Score yesterday's predictions against today's prices.

The learning loop:

  Day N:    agents vote, debate resolves, positions open
  Day N+1:  we look at what happened to each ticker overnight
            and score every BUY / SELL / HOLD vote on that ticker

A BUY is "right" if the price went up by more than fees.
A SELL is "right" if the price went down.
A HOLD is "right" if the price moved by less than half an ATR.
An ABSTAIN is never scored — silence is not a prediction.

Agent score is the running track record across all closed predictions.
This lets us answer:
  "What is FORGE's win rate in trending markets?"
  "What is THUNDERHEAD's expected value when conviction > 0.7?"
  "Which agent has the worst max drawdown of conviction-weighted returns?"

Runs at the start of every CLI cycle, before today's debate. Persisted
to scoring.json so the Truth Dashboard can read it without recomputing.

--- ALPHA 2.0 PATCH NOTES ---

Bug fixed: prior-run date comparison was comparing a full ISO timestamp
string (e.g. "2026-04-30T20:26:33+00:00") against a YYYY-MM-DD date string
(e.g. "2026-04-30"). These never matched, so prior_run was always resolved
to the most recent run in history — which was today's own run — and every
ticker was scored against its own prices (entry == exit, 0% return,
all directional calls marked wrong). This cascaded into:

  - All agents trending toward 0% win rate
  - Weight multipliers dropping below 0.85x kill threshold
  - Mass agent freezes (THUNDERHEAD, VEIL, KESTREL, ZENITH, WEAVER, HEX, SYNTH)
  - Cohort avg return corrupted → safe_mode triggered
  - Evolution cards never populated (no valid scored outcomes)

Fix: normalize date to YYYY-MM-DD via [:10] before comparison.
Stale-price guard added: if entry == exit after a clean cross-day lookup,
the outcome is logged as a warning and still recorded (real price may be
genuinely flat) but flagged with stale_price_suspected=True for diagnostics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import math as _math

log = logging.getLogger("silmaril.scoring")


def _sanitize_json(obj):
    """Recursively convert NaN/Inf to None for valid JSON output."""
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


# Score thresholds
HOLD_TOLERANCE_PCT = 0.6   # within ±0.6%, a HOLD is correct


@dataclass
class CallOutcome:
    """One scored prediction."""
    agent: str
    ticker: str
    signal: str               # BUY / STRONG_BUY / SELL / STRONG_SELL / HOLD
    conviction: float
    predicted_at: str         # ISO date the call was made
    scored_at: str            # ISO date we scored it
    entry_price: float
    exit_price: float
    return_pct: float
    correct: bool             # was the directional read right?
    reward: float             # signed reward used for EV: +return for right BUY, etc.
    tags: Dict[str, str]      # regime tags at decision time
    stale_price_suspected: bool = False  # True when entry == exit across different dates

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "ticker": self.ticker,
            "signal": self.signal,
            "conviction": round(self.conviction, 3),
            "predicted_at": self.predicted_at,
            "scored_at": self.scored_at,
            "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "return_pct": round(self.return_pct, 3),
            "correct": self.correct,
            "reward": round(self.reward, 4),
            "tags": self.tags,
            "stale_price_suspected": self.stale_price_suspected,
        }


def _normalize_date(raw: Any) -> str:
    """
    Normalize any date-like value to YYYY-MM-DD.

    history.json may store dates as full ISO timestamps
    (e.g. "2026-04-30T20:26:33.860063+00:00") or as plain date strings
    ("2026-04-30"). Both cases are handled by taking the first 10 chars.
    This was the root cause of the scoring bug: comparing ISO timestamps
    to YYYY-MM-DD strings always returned True (never matched), so
    prior_run was set to the most recent run (today's own run) and every
    ticker was scored against its own prices.
    """
    if raw is None:
        return ""
    return str(raw)[:10]


def score_prior_run(
    history_data: Dict[str, Any],
    today_prices: Dict[str, float],
    today_iso: str,
) -> List[CallOutcome]:
    """
    Walk the prior run's verdicts and score each one against today's prices.
    Returns the new outcomes generated this run (excludes outcomes we
    already scored in earlier runs).

    today_iso must be a plain YYYY-MM-DD string (e.g. "2026-04-30").
    """
    runs = history_data.get("runs", [])
    if not runs:
        log.info("scoring: no runs in history — nothing to score")
        return []

    # Find the most recent run that is NOT today (we only score runs whose
    # predictions can be measured against newer prices).
    #
    # CRITICAL: normalize both sides to YYYY-MM-DD before comparing.
    # history runs may store date as a full ISO timestamp string.
    today_date = _normalize_date(today_iso)
    prior_run = None
    for r in reversed(runs):
        run_date = _normalize_date(r.get("date"))
        if run_date != today_date:
            prior_run = r
            log.info(
                "scoring: found prior run from %s to score against today (%s)",
                run_date, today_date,
            )
            break

    if not prior_run:
        log.info(
            "scoring: no prior run from a different calendar day found "
            "(all %d runs are from %s) — nothing to score yet",
            len(runs), today_date,
        )
        return []

    outcomes: List[CallOutcome] = []
    prior_date = _normalize_date(prior_run.get("date", ""))
    stale_price_count = 0
    skipped_no_price = 0

    for v in prior_run.get("verdicts", []):
        ticker = v.get("ticker")
        entry_price = v.get("price")
        exit_price = today_prices.get(ticker)

        if entry_price is None or exit_price is None:
            skipped_no_price += 1
            continue

        if entry_price <= 0:
            log.warning("scoring: %s has non-positive entry_price %s — skipping", ticker, entry_price)
            continue

        # Flag if prices look suspiciously identical across different days.
        # This can happen with stale yfinance cache or crypto tickers that
        # genuinely didn't move — we record but flag for inspection.
        stale_suspected = (entry_price == exit_price)
        if stale_suspected:
            stale_price_count += 1

        return_pct = ((exit_price / entry_price) - 1) * 100.0

        tags = v.get("tags") or {}

        for vote in v.get("votes", []):
            sig = vote.get("signal")
            if sig in (None, "ABSTAIN"):
                continue
            agent = vote.get("agent")
            if not agent:
                continue
            conv = float(vote.get("conviction", 0.0))

            correct, reward = _score_call(sig, return_pct)

            outcomes.append(CallOutcome(
                agent=agent,
                ticker=ticker,
                signal=sig,
                conviction=conv,
                predicted_at=prior_date,
                scored_at=today_date,
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=return_pct,
                correct=correct,
                reward=reward,
                tags=tags,
                stale_price_suspected=stale_suspected,
            ))

    if stale_price_count:
        log.warning(
            "scoring: %d/%d tickers had entry_price == exit_price across "
            "dates %s → %s. Suspected stale price cache. Check yfinance "
            "or price_cache.json. These outcomes are recorded but flagged "
            "stale_price_suspected=True.",
            stale_price_count,
            len(prior_run.get("verdicts", [])),
            prior_date,
            today_date,
        )

    if skipped_no_price:
        log.debug(
            "scoring: skipped %d verdicts with missing entry or exit price",
            skipped_no_price,
        )

    log.info(
        "scoring: produced %d call outcomes from prior run (%s) vs today (%s)",
        len(outcomes), prior_date, today_date,
    )
    return outcomes


def _score_call(signal: str, return_pct: float) -> Tuple[bool, float]:
    """
    Was this directional call correct? What's the EV-style reward?
    Reward sign convention: positive = the call paid off, negative = it didn't.
    Reward magnitude: the % move (signed by direction of correctness).
    """
    if signal == "STRONG_BUY":
        return (return_pct > 0, return_pct)
    if signal == "BUY":
        return (return_pct > 0, return_pct)
    if signal == "STRONG_SELL":
        return (return_pct < 0, -return_pct)
    if signal == "SELL":
        return (return_pct < 0, -return_pct)
    if signal == "HOLD":
        # Right if the move was small in either direction
        within = abs(return_pct) <= HOLD_TOLERANCE_PCT
        # Reward small if right (you didn't get whipsawed), small negative if wrong
        return (within, HOLD_TOLERANCE_PCT - abs(return_pct))
    return (False, 0.0)


# ─────────────────────────────────────────────────────────────────
# Aggregation: roll outcomes up into per-agent stats
# ─────────────────────────────────────────────────────────────────

def build_scoring_summary(
    all_outcomes: List[Dict[str, Any]],
    agent_codenames: List[str],
) -> Dict[str, Any]:
    """
    Build the Truth Dashboard payload. Per agent:
      - total scored calls
      - win rate
      - expected value (avg reward)
      - max single-call drawdown
      - per-regime breakdown (trending vs ranging, high vs low vol, etc.)
      - performance-weighted "weight multiplier" usable by the consensus engine
    """
    by_agent: Dict[str, List[Dict[str, Any]]] = {a: [] for a in agent_codenames}
    for o in all_outcomes:
        agent = o.get("agent")
        if agent in by_agent:
            by_agent[agent].append(o)

    rows = []
    for agent, outcomes in by_agent.items():
        n = len(outcomes)
        if n == 0:
            rows.append({
                "agent": agent,
                "scored_calls": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": None,
                "expected_value": None,
                "max_drawdown_pct": None,
                "best_call_pct": None,
                "worst_call_pct": None,
                "avg_conviction": None,
                "by_regime": {},
                "weight_multiplier": 1.0,
                "weight_explanation": "Insufficient data — neutral weight applied.",
            })
            continue
        wins = sum(1 for o in outcomes if o["correct"])
        losses = n - wins
        rewards = [o["reward"] for o in outcomes]
        ev = sum(rewards) / n
        worst = min(rewards)
        best = max(rewards)
        avg_conv = sum(o["conviction"] for o in outcomes) / n

        # Stale-price diagnostic
        stale_count = sum(1 for o in outcomes if o.get("stale_price_suspected"))
        stale_pct = stale_count / n if n else 0

        # Regime cuts
        by_regime = _split_by_regime(outcomes)

        # Weight multiplier — used by Phase E to up/downweight votes
        weight_mult, expl = _compute_weight_multiplier(n, wins / n, ev, worst)

        row = {
            "agent": agent,
            "scored_calls": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / n, 3),
            "expected_value": round(ev, 3),
            "max_drawdown_pct": round(worst, 3),
            "best_call_pct": round(best, 3),
            "worst_call_pct": round(worst, 3),
            "avg_conviction": round(avg_conv, 3),
            "by_regime": by_regime,
            "weight_multiplier": round(weight_mult, 3),
            "weight_explanation": expl,
        }
        if stale_count:
            row["stale_price_calls"] = stale_count
            row["stale_price_pct"] = round(stale_pct, 3)
        rows.append(row)

    rows.sort(key=lambda r: (r["expected_value"] or -999, r["win_rate"] or -1), reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_scored_calls": len(all_outcomes),
        "agents_with_track_record": sum(1 for r in rows if r["scored_calls"] > 0),
        "leaderboard": rows,
        "best_agent": rows[0] if rows and rows[0]["scored_calls"] > 0 else None,
        "worst_agent": next(
            (r for r in reversed(rows) if r["scored_calls"] > 0), None
        ),
    }


def _split_by_regime(outcomes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Cut the outcomes by each regime tag dimension."""
    dims = ["market_regime", "trend_state", "vol_state", "news_state"]
    out: Dict[str, Dict[str, Any]] = {}
    for dim in dims:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for o in outcomes:
            label = (o.get("tags") or {}).get(dim, "UNKNOWN")
            buckets.setdefault(label, []).append(o)
        dim_stats = {}
        for label, items in buckets.items():
            n = len(items)
            wins = sum(1 for x in items if x["correct"])
            ev = sum(x["reward"] for x in items) / n
            dim_stats[label] = {
                "n": n,
                "win_rate": round(wins / n, 3),
                "ev": round(ev, 3),
            }
        out[dim] = dim_stats
    return out


def _compute_weight_multiplier(n, win_rate, ev, worst) -> Tuple[float, str]:
    """
    Convert an agent's track record into a weight multiplier in [0.5, 1.5].
    Until they have 10+ scored calls, weight stays neutral at 1.0.
    """
    if n < 10:
        return 1.0, f"Only {n} scored calls — weight neutral (need 10+)."

    # Performance score: blend win-rate (above 50%) and EV (above 0)
    wr_z = (win_rate - 0.5) * 2     # -1 to +1
    ev_z = max(-1.0, min(1.0, ev / 2.0))  # ±2% EV → ±1
    blended = 0.5 * wr_z + 0.5 * ev_z   # -1 to +1

    mult = 1.0 + 0.5 * blended
    mult = max(0.5, min(1.5, mult))

    if mult > 1.15:
        msg = f"Above-baseline performance: {win_rate:.0%} win rate, {ev:+.2f}% EV. Boosted to {mult:.2f}×."
    elif mult < 0.85:
        msg = f"Below-baseline performance: {win_rate:.0%} win rate, {ev:+.2f}% EV. Reduced to {mult:.2f}×."
    else:
        msg = f"On-baseline performance: {win_rate:.0%} win rate, {ev:+.2f}% EV. Weight near neutral."
    return mult, msg


# ─────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────

def load_scoring(path: Path) -> Dict[str, Any]:
    """Load the rolling scoring file, or return a fresh skeleton."""
    if not path.exists():
        return {"outcomes": [], "summary": {}}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {"outcomes": [], "summary": {}}


def save_scoring(path: Path, outcomes: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    """Persist outcomes + summary, capping outcome history so file stays bounded."""
    capped = outcomes[-3000:]  # ~6 months of daily votes for 17 agents on 17 assets
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcomes": capped,
        "summary": summary,
    }
    path.write_text(json.dumps(_sanitize_json(payload), indent=2, default=str, allow_nan=False))
