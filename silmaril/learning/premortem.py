"""
silmaril.learning.premortem

Before issuing any high-conviction BUY or SELL, the agent is forced to
articulate a structured pre-mortem: "what would have to be true for me
to be wrong?"

This is a known cognitive-bias mitigation used by institutional analysts
(Daniel Kahneman, Gary Klein research). It surfaces hidden assumptions
and creates an explicit invalidation criterion.

We append the pre-mortem to the verdict's rationale and archive it for
later analysis.

Storage: docs/data/premortem_archive.json (PROTECTED)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def generate_premortem(
    signal: str,
    conviction: float,
    ticker: str,
    rationale: str,
    ctx_summary: dict,
) -> dict:
    """
    Generate a structured pre-mortem block for a high-conviction call.

    Returns a dict with:
      - kill_criteria: specific conditions that would invalidate the thesis
      - bear_case: a one-sentence articulation of why this could be wrong
      - confidence_check: explicit list of assumptions
    """
    if conviction < 0.55 or signal in ("HOLD", "ABSTAIN"):
        return {}  # only required for high-conviction calls

    is_bullish = signal in ("BUY", "STRONG_BUY")
    is_bearish = signal in ("SELL", "STRONG_SELL")

    kill_criteria = []
    bear_case = ""
    assumptions = []

    if is_bullish:
        # Standard bull-case kill criteria
        price = ctx_summary.get("price", 0)
        sma_50 = ctx_summary.get("sma_50")
        if price and sma_50:
            kill_criteria.append(
                f"Price closes below SMA-50 ({sma_50:.2f}) for 2 consecutive days"
            )
        kill_criteria.append(
            f"Stop-loss: -3% from entry (~{price * 0.97:.2f})"
        )
        kill_criteria.append(
            "Negative news catalyst (earnings miss, guidance cut, major contract loss)"
        )
        kill_criteria.append(
            "VIX spikes above 30 within 48 hours (regime flip to RISK_OFF)"
        )
        bear_case = (
            f"This BUY thesis fails if {ticker} can't hold above its short-term "
            "support and a single negative catalyst would invalidate the setup."
        )
        assumptions = [
            "Current regime persists for at least 2-3 sessions",
            "No surprise negative headline in the 24-hour window",
            "Liquidity remains normal — no flash-crash risk",
        ]

    elif is_bearish:
        price = ctx_summary.get("price", 0)
        kill_criteria.append(
            f"Price reclaims prior swing high (cover stop)"
        )
        kill_criteria.append(
            f"Stop-loss: +3% above entry (~{price * 1.03:.2f})"
        )
        kill_criteria.append(
            "Positive surprise catalyst (beat-and-raise, M&A, regulatory win)"
        )
        kill_criteria.append(
            "Short-squeeze indicators: heavy short interest + retail-favorite status"
        )
        bear_case = (
            f"This SELL/SHORT thesis fails if {ticker} catches a positive surprise "
            "or if short-squeeze dynamics overwhelm fundamentals."
        )
        assumptions = [
            "No imminent positive catalyst in the next 1-3 sessions",
            "Short-borrow remains available and reasonably priced",
            "Broader sector weakness aligns with this name",
        ]

    return {
        "kill_criteria": kill_criteria,
        "bear_case": bear_case,
        "assumptions": assumptions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def archive_premortem(
    archive_path: Path,
    agent: str,
    ticker: str,
    signal: str,
    conviction: float,
    premortem: dict,
) -> None:
    if not premortem:
        return
    data = {"records": []}
    if archive_path.exists():
        try:
            data = json.loads(archive_path.read_text())
        except Exception:
            pass

    record = {
        "agent": agent,
        "ticker": ticker,
        "signal": signal,
        "conviction": conviction,
        **premortem,
    }
    data.setdefault("records", []).append(record)
    data["records"] = data["records"][-5000:]
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(json.dumps(data, indent=2))


def attach_premortem_to_rationale(rationale: str, premortem: dict) -> str:
    if not premortem:
        return rationale
    parts = [rationale]
    if premortem.get("bear_case"):
        parts.append(f"\n[PRE-MORTEM] {premortem['bear_case']}")
    kc = premortem.get("kill_criteria", [])
    if kc:
        parts.append("[KILL CRITERIA] " + "; ".join(kc[:3]))
    return "\n".join(parts)
