"""
Demo runner for the SILMARIL vertical slice.

Runs AEGIS, FORGE, and SCROOGE against a realistic set of sample
AssetContexts representing a typical trading day. Produces the exact
JSON files the static frontend consumes:

  data/signals.json        — debate output per asset
  data/scrooge.json        — SCROOGE's state and history
  data/trade_plans.json    — active trade plans from BUY-consensus debates
  data/handoff_blocks.json — pre-built Handoff Blocks per view

This is a VERTICAL SLICE. The real pipeline has 16 agents and ~100+
assets; this demo has 3 agents and 8 assets so you can see the whole
path from data to UI in one glance. Scaling up = adding more agent
modules and expanding the asset list; the architecture is unchanged.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from silmaril.agents.aegis import aegis
from silmaril.agents.forge import forge
from silmaril.agents.scrooge import scrooge, scrooge_act, ScroogeState
from silmaril.agents.base import AssetContext
from silmaril.debate.arbiter import Arbiter
from silmaril.handoff.blocks import (
    build_asset_deep_dive,
    build_scrooge_narrative,
    build_debate_summary,
)
from silmaril.trade_engine.plans import build_plan_from_debate


# ─────────────────────────────────────────────────────────────────
# Sample universe — representative of a real day
# Values are hand-crafted to exercise different agent code paths.
# ─────────────────────────────────────────────────────────────────

SAMPLE_CONTEXTS = [
    AssetContext(
        ticker="NVDA", name="NVIDIA Corporation", sector="Technology", asset_class="equity",
        price=135.80, change_pct=2.15, volume=280_000_000, avg_volume_30d=220_000_000,
        sma_20=128.40, sma_50=122.10, sma_200=110.30,
        rsi_14=62.5, atr_14=3.80, bb_width=0.12,
        sentiment_score=0.48, article_count=14, source_count=8,
        days_to_earnings=11,
        recent_headlines=[
            {"title": "Nvidia earnings preview: analysts expect another beat", "source": "Reuters"},
            {"title": "Data center spending accelerates into 2026 cycle", "source": "Bloomberg"},
            {"title": "Export controls tighten for next-gen AI chips", "source": "CNBC"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="AAPL", name="Apple Inc.", sector="Technology", asset_class="equity",
        price=178.50, change_pct=-0.42, volume=58_000_000, avg_volume_30d=55_000_000,
        sma_20=176.20, sma_50=179.80, sma_200=182.10,
        rsi_14=48.3, atr_14=2.10, bb_width=0.08,
        sentiment_score=0.05, article_count=9, source_count=6,
        recent_headlines=[
            {"title": "Apple Services revenue hits record; hardware mixed", "source": "WSJ"},
            {"title": "China iPhone shipments down third straight quarter", "source": "Reuters"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="AMD", name="Advanced Micro Devices", sector="Technology", asset_class="equity",
        price=162.30, change_pct=3.85, volume=95_000_000, avg_volume_30d=60_000_000,
        sma_20=151.00, sma_50=142.50, sma_200=131.20,
        rsi_14=71.2, atr_14=5.20, bb_width=0.15,
        sentiment_score=0.55, article_count=11, source_count=7,
        recent_headlines=[
            {"title": "AMD data-center revenue doubles YoY", "source": "Barron's"},
            {"title": "Hyperscaler orders point to sustained MI300 demand", "source": "The Information"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="MSFT", name="Microsoft Corporation", sector="Technology", asset_class="equity",
        price=412.00, change_pct=1.05, volume=22_000_000, avg_volume_30d=25_000_000,
        sma_20=405.20, sma_50=398.40, sma_200=378.00,
        rsi_14=58.5, atr_14=5.40, bb_width=0.09,
        sentiment_score=0.22, article_count=7, source_count=5,
        recent_headlines=[
            {"title": "Microsoft Copilot adoption exceeds internal targets", "source": "The Information"},
            {"title": "Azure growth reaccelerates on AI workload mix", "source": "Bloomberg"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="TSLA", name="Tesla Inc.", sector="Technology", asset_class="equity",
        price=182.60, change_pct=-4.20, volume=150_000_000, avg_volume_30d=110_000_000,
        sma_20=195.80, sma_50=202.40, sma_200=215.00,
        rsi_14=32.1, atr_14=8.90, bb_width=0.18,
        sentiment_score=-0.32, article_count=18, source_count=9,
        recent_headlines=[
            {"title": "Tesla delivery forecast cut by several analysts", "source": "Reuters"},
            {"title": "EV price war intensifies in China market", "source": "CNBC"},
            {"title": "Robotaxi timeline questioned after regulatory delays", "source": "Bloomberg"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="SPY", name="SPDR S&P 500 ETF", sector="Index", asset_class="etf",
        price=528.40, change_pct=0.35, volume=75_000_000, avg_volume_30d=80_000_000,
        sma_20=522.00, sma_50=515.80, sma_200=492.40,
        rsi_14=61.8, atr_14=4.20, bb_width=0.06,
        sentiment_score=0.12, article_count=25, source_count=12,
        recent_headlines=[
            {"title": "S&P 500 closes at record as breadth widens", "source": "WSJ"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="XOM", name="Exxon Mobil", sector="Energy", asset_class="equity",
        price=112.80, change_pct=0.85, volume=15_000_000, avg_volume_30d=18_000_000,
        sma_20=110.20, sma_50=108.40, sma_200=105.60,
        rsi_14=54.2, atr_14=2.20, bb_width=0.07,
        sentiment_score=0.08, article_count=5, source_count=4,
        recent_headlines=[
            {"title": "Oil prices steady on OPEC+ discipline", "source": "Reuters"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
    AssetContext(
        ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials", asset_class="equity",
        price=195.20, change_pct=-0.15, volume=9_500_000, avg_volume_30d=11_000_000,
        sma_20=192.40, sma_50=188.60, sma_200=180.20,
        rsi_14=56.8, atr_14=2.80, bb_width=0.05,
        sentiment_score=0.10, article_count=4, source_count=3,
        recent_headlines=[
            {"title": "JPMorgan earnings beat on net interest income", "source": "Bloomberg"},
        ],
        market_regime="RISK_ON", vix=16.8,
    ),
]


# ─────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────

def run_demo(output_dir: str = "data") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)

    # ── Run the debate ──────────────────────────────────────────
    # Note: SCROOGE always abstains on individual assets; he only acts on consensus.
    arbiter = Arbiter(agents=[aegis, forge, scrooge], aegis_veto_enabled=True)
    debates = arbiter.resolve(SAMPLE_CONTEXTS)
    debate_dicts = [d.to_dict() for d in debates]

    # Sort by consensus strength
    debate_dicts.sort(
        key=lambda d: (d["consensus"]["score"], d["consensus"]["avg_conviction"]),
        reverse=True,
    )

    # ── Build trade plans from BUY-consensus debates ────────────
    plans = []
    for d in debate_dicts:
        plan = build_plan_from_debate(d, portfolio_size=10_000.0)
        if plan:
            plans.append(plan.to_dict())

    # ── SCROOGE acts on consensus ───────────────────────────────
    scrooge_state = _load_or_init_scrooge(out / "scrooge.json")
    top_for_scrooge = [
        {
            "ticker": d["ticker"],
            "signal": d["consensus"]["signal"],
            "consensus_score": d["consensus"]["score"],
            "avg_conviction": d["consensus"]["avg_conviction"],
            "rationale": d.get("dissent_summary", ""),
        }
        for d in debate_dicts
    ]
    prices = {ctx.ticker: ctx.price for ctx in SAMPLE_CONTEXTS}
    scrooge_state = scrooge_act(scrooge_state, top_for_scrooge, prices)
    scrooge_dict = scrooge_state.to_dict()

    # ── Build Handoff Blocks ────────────────────────────────────
    per_asset_handoffs = {
        d["ticker"]: build_asset_deep_dive(_enrich_with_headlines(d, SAMPLE_CONTEXTS))
        for d in debate_dicts
    }
    handoff_blocks = {
        "debate_summary": build_debate_summary(debate_dicts, market_regime="RISK_ON", vix=16.8),
        "scrooge_narrative": build_scrooge_narrative(scrooge_dict),
        "per_asset": per_asset_handoffs,
    }

    # ── Build the main signals.json ─────────────────────────────
    signals_output = {
        "meta": {
            "version": "2.0.0",
            "project": "SILMARIL",
            "run_type": "demo",
            "generated_at": now.isoformat(),
            "disclaimer": (
                "SILMARIL is an educational simulation. All content is for informational "
                "and entertainment purposes only. NOT financial advice. Always consult a "
                "licensed professional."
            ),
        },
        "market_state": {
            "regime": "RISK_ON",
            "vix": 16.8,
            "spy_trend": "UP",
        },
        "universe": {
            "core_count": len(SAMPLE_CONTEXTS),
            "watchlist_count": 0,
            "discovered_count": 0,
            "total": len(SAMPLE_CONTEXTS),
        },
        "agent_roster": [
            {"codename": a.codename, "specialty": a.specialty, "temperament": a.temperament,
             "inspiration": a.inspiration}
            for a in [aegis, forge, scrooge]
        ],
        "summary": _compute_summary(debate_dicts),
        "debates": debate_dicts,
    }

    _write(out / "signals.json", signals_output)
    _write(out / "trade_plans.json", {"meta": signals_output["meta"], "plans": plans})
    _write(out / "scrooge.json", scrooge_dict)
    _write(out / "handoff_blocks.json", handoff_blocks)

    print(f"✦ SILMARIL demo complete.")
    print(f"  {len(debate_dicts)} debates resolved")
    print(f"  {len(plans)} actionable trade plans generated")
    print(f"  SCROOGE balance: ${scrooge_dict['balance']:.4f} (life #{scrooge_dict['current_life']})")
    print(f"  Output written to: {out.resolve()}")


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _load_or_init_scrooge(path: Path) -> ScroogeState:
    if not path.exists():
        return ScroogeState()
    with path.open() as f:
        data = json.load(f)
    state = ScroogeState(
        balance=data.get("balance", 1.0),
        current_position=data.get("current_position"),
        lifetime_peak=data.get("lifetime_peak", 1.0),
        current_life=data.get("current_life", 1),
        life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
        history=data.get("history", []),
        deaths=data.get("deaths", []),
    )
    return state


def _enrich_with_headlines(debate: dict, contexts: list) -> dict:
    """Attach headlines from the source context to a debate dict for handoff rendering."""
    for ctx in contexts:
        if ctx.ticker == debate["ticker"]:
            return {**debate, "recent_headlines": ctx.recent_headlines}
    return debate


def _compute_summary(debates: list) -> dict:
    from collections import Counter
    counts = Counter(d["consensus"]["signal"] for d in debates)
    return {
        "total_tracked": len(debates),
        "strong_buy_count": counts.get("STRONG_BUY", 0),
        "buy_count": counts.get("BUY", 0),
        "hold_count": counts.get("HOLD", 0),
        "sell_count": counts.get("SELL", 0),
        "strong_sell_count": counts.get("STRONG_SELL", 0),
        "vetoes": sum(1 for d in debates if d.get("aegis_veto")),
    }


def _write(path: Path, data) -> None:
    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)


if __name__ == "__main__":
    run_demo()
