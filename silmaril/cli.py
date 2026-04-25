"""
silmaril.cli — The main runner.

Two modes:

  python -m silmaril --live    # Fetch real market data from yfinance + news RSS
  python -m silmaril --demo    # Use hand-crafted sample contexts for offline testing

The --live mode is what GitHub Actions runs on schedule. It populates
the live site at theseanmitchell.github.io/SILMARIL with real data.

The --demo mode is for local development and the repository's initial
commit, so the site renders meaningfully before the first scheduled run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .agents.base import Agent, AssetContext
from .agents.aegis import aegis
from .agents.forge import forge
from .agents.scrooge import scrooge, scrooge_act, ScroogeState
from .agents.thunderhead import thunderhead
from .agents.jade import jade
from .agents.veil import veil
from .agents.kestrel import kestrel
from .agents.obsidian import obsidian
from .agents.zenith import zenith
from .agents.weaver import weaver
from .agents.hex_agent import hex_agent
from .agents.synth import synth
from .agents.speck import speck
from .agents.vespa import vespa
from .agents.magus import magus
from .agents.talon import talon
from .agents.midas import midas, midas_act, MidasState, MIDAS_UNIVERSE
from .agents.bios import get_bio

from .debate.arbiter import Arbiter
from .trade_engine.plans import build_plan_from_debate
from .handoff.blocks import (
    build_asset_deep_dive,
    build_scrooge_narrative,
    build_debate_summary,
)
from .universe.core import all_entries, asset_class_of
from .analytics import technicals as ti
from .analytics.sentiment import aggregate_ticker_sentiment
from .analytics.regime import classify_regime, spy_trend_label


# ─────────────────────────────────────────────────────────────────
# Full agent roster — the order here is the order shown in the UI
# ─────────────────────────────────────────────────────────────────

AGENTS: List[Agent] = [
    aegis, forge, thunderhead, jade, veil, kestrel, obsidian, zenith,
    weaver, hex_agent, synth, speck, vespa, magus, talon,
    scrooge, midas,
]


log = logging.getLogger("silmaril")


# ─────────────────────────────────────────────────────────────────
# Live mode — real market data
# ─────────────────────────────────────────────────────────────────

def build_live_contexts() -> List[AssetContext]:
    """Fetch prices + news, compute analytics, assemble AssetContexts."""
    from .ingestion.prices import fetch_universe_prices, fetch_vix, fetch_earnings_dates
    from .ingestion.news import fetch_news_bulk

    entries = all_entries()
    tickers = [tkr for tkr, _, _ in entries]

    log.info("Fetching prices for %d tickers...", len(tickers))
    price_snaps = fetch_universe_prices(tickers)

    log.info("Fetching VIX...")
    vix = fetch_vix()

    log.info("Fetching earnings dates (best-effort)...")
    earnings = fetch_earnings_dates([t for t in tickers if t not in {"^VIX"}])

    log.info("Fetching news for %d tickers (this takes a few minutes)...", len(tickers))
    name_pairs = [(tkr, name) for tkr, name, _ in entries]
    news_map = fetch_news_bulk(name_pairs, max_articles_per=5)

    # Regime from SPY + VIX
    spy = price_snaps.get("SPY")
    spy_sma_50 = ti.sma(spy.closes, 50) if spy else None
    spy_sma_200 = ti.sma(spy.closes, 200) if spy else None
    regime = classify_regime(
        spy_price=spy.price if spy else None,
        spy_sma_50=spy_sma_50,
        spy_sma_200=spy_sma_200,
        vix=vix,
    )
    log.info("Market regime: %s (VIX %s)", regime, f"{vix:.1f}" if vix else "n/a")

    contexts: List[AssetContext] = []
    now = datetime.now(timezone.utc).date()

    for tkr, name, sector in entries:
        snap = price_snaps.get(tkr)
        if not snap:
            continue

        indicators = ti.compute_all(snap.closes, snap.highs, snap.lows)
        articles = news_map.get(tkr, [])
        titles = [a.title for a in articles]
        sources = list({a.source for a in articles})
        sent_score, sent_count = aggregate_ticker_sentiment(titles)

        earn_date = earnings.get(tkr)
        days_to_earn = None
        if earn_date:
            try:
                ed = datetime.fromisoformat(earn_date).date()
                days_to_earn = (ed - now).days
            except Exception:
                pass

        ctx = AssetContext(
            ticker=tkr,
            name=name,
            sector=sector,
            asset_class=asset_class_of(tkr),
            price=snap.price,
            change_pct=snap.change_pct,
            volume=snap.volume,
            avg_volume_30d=snap.avg_volume_30d,
            price_history=snap.closes,
            sma_20=indicators["sma_20"],
            sma_50=indicators["sma_50"],
            sma_200=indicators["sma_200"],
            rsi_14=indicators["rsi_14"],
            atr_14=indicators["atr_14"],
            bb_width=indicators["bb_width"],
            sentiment_score=sent_score,
            article_count=sent_count,
            source_count=len(sources),
            recent_headlines=[
                {"title": a.title, "source": a.source, "url": a.url}
                for a in articles[:5]
            ],
            earnings_date=earn_date,
            days_to_earnings=days_to_earn,
            market_regime=regime,
            vix=vix,
        )
        contexts.append(ctx)

    log.info("Built %d contexts with full analytics", len(contexts))
    return contexts


# ─────────────────────────────────────────────────────────────────
# Demo mode — sample contexts (for initial commit + offline dev)
# ─────────────────────────────────────────────────────────────────

def build_demo_contexts() -> List[AssetContext]:
    """Hand-crafted sample contexts designed to exercise all 16 agents."""
    # Common price-history fill so statistical agents have data
    def gen_history(center: float, closes: int = 220, drift: float = 0.0002, vol: float = 0.015) -> List[float]:
        """Generate a synthetic-but-plausible price history by random walk."""
        import random
        random.seed(hash(center) & 0xFFFF)
        out = [center * 0.85]   # start lower
        for _ in range(closes):
            out.append(out[-1] * (1 + drift + random.gauss(0, vol)))
        return out

    base_regime = "RISK_ON"
    base_vix = 17.2

    def build(**overrides) -> AssetContext:
        defaults = dict(
            market_regime=base_regime,
            vix=base_vix,
            asset_class="equity",
            source_count=5,
        )
        defaults.update(overrides)
        # Auto-fill technicals if price_history is provided
        if "price_history" in defaults and defaults["price_history"]:
            ph = defaults["price_history"]
            closes = ph
            highs = [c * 1.012 for c in closes]
            lows = [c * 0.988 for c in closes]
            indicators = ti.compute_all(closes, highs, lows)
            for k, v in indicators.items():
                defaults.setdefault(k, v)
        return AssetContext(**defaults)

    return [
        build(
            ticker="NVDA", name="NVIDIA Corporation", sector="Technology",
            price=138.40, change_pct=2.15, volume=280_000_000, avg_volume_30d=220_000_000,
            price_history=gen_history(100, drift=0.003),
            sentiment_score=0.52, article_count=14,
            days_to_earnings=9,
            recent_headlines=[
                {"title": "NVIDIA earnings preview: analysts expect another beat", "source": "Reuters"},
                {"title": "Data center spending accelerates into 2026 cycle", "source": "Bloomberg"},
            ],
        ),
        build(
            ticker="AAPL", name="Apple Inc.", sector="Technology",
            price=179.20, change_pct=-0.42, volume=58_000_000, avg_volume_30d=55_000_000,
            price_history=gen_history(175, drift=0.0005, vol=0.011),
            sentiment_score=0.03, article_count=9,
        ),
        build(
            ticker="AMD", name="Advanced Micro Devices", sector="Technology",
            price=165.80, change_pct=4.25, volume=105_000_000, avg_volume_30d=60_000_000,
            price_history=gen_history(120, drift=0.0025),
            sentiment_score=0.58, article_count=11,
        ),
        build(
            ticker="MSFT", name="Microsoft Corporation", sector="Technology",
            price=414.00, change_pct=1.05, volume=22_000_000, avg_volume_30d=25_000_000,
            price_history=gen_history(360, drift=0.0012),
            sentiment_score=0.22, article_count=7,
        ),
        build(
            ticker="TSLA", name="Tesla Inc.", sector="Discretionary",
            price=178.40, change_pct=-4.80, volume=165_000_000, avg_volume_30d=110_000_000,
            price_history=gen_history(215, drift=-0.001),
            sentiment_score=-0.38, article_count=18,
        ),
        build(
            ticker="SPY", name="SPDR S&P 500 ETF", sector="Index",
            price=528.40, change_pct=0.35, volume=75_000_000, avg_volume_30d=80_000_000,
            price_history=gen_history(495, drift=0.0008, vol=0.008),
            sentiment_score=0.12, article_count=25,
            asset_class="etf",
        ),
        build(
            ticker="QQQ", name="Invesco QQQ (Nasdaq-100)", sector="Index",
            price=445.20, change_pct=0.75, volume=42_000_000, avg_volume_30d=48_000_000,
            price_history=gen_history(410, drift=0.0012, vol=0.011),
            sentiment_score=0.15, article_count=12,
            asset_class="etf",
        ),
        build(
            ticker="IWM", name="iShares Russell 2000", sector="Index",
            price=208.50, change_pct=-0.32, volume=28_000_000, avg_volume_30d=32_000_000,
            price_history=gen_history(200, drift=0.0002),
            sentiment_score=-0.08, article_count=3,
            asset_class="etf",
        ),
        build(
            ticker="XOM", name="Exxon Mobil", sector="Energy",
            price=114.20, change_pct=1.15, volume=15_000_000, avg_volume_30d=18_000_000,
            price_history=gen_history(108, drift=0.0008),
            sentiment_score=0.18, article_count=5,
        ),
        build(
            ticker="GLD", name="SPDR Gold Shares", sector="Commodities",
            price=218.40, change_pct=0.62, volume=8_000_000, avg_volume_30d=9_500_000,
            price_history=gen_history(198, drift=0.0012),
            sentiment_score=0.15, article_count=4,
            asset_class="etf",
        ),
        build(
            ticker="SLV", name="iShares Silver Trust", sector="Commodities",
            price=28.40, change_pct=0.85, volume=18_000_000, avg_volume_30d=16_000_000,
            price_history=gen_history(25, drift=0.0015, vol=0.018),
            sentiment_score=0.22, article_count=3,
            asset_class="etf",
        ),
        build(
            ticker="UUP", name="Invesco DB US Dollar Index", sector="FX",
            price=28.95, change_pct=-0.12, volume=1_800_000, avg_volume_30d=2_000_000,
            price_history=gen_history(28.5, drift=0.0001, vol=0.004),
            sentiment_score=0.05, article_count=2,
            asset_class="etf",
        ),
        build(
            ticker="TLT", name="iShares 20+ Year Treasury", sector="Rates",
            price=92.80, change_pct=0.45, volume=18_000_000, avg_volume_30d=20_000_000,
            price_history=gen_history(95, drift=-0.0003, vol=0.007),
            sentiment_score=-0.05, article_count=4,
            asset_class="etf",
        ),
        build(
            ticker="BTC-USD", name="Bitcoin", sector="Crypto",
            price=68420, change_pct=3.25, volume=0, avg_volume_30d=0,
            price_history=gen_history(52000, drift=0.0018, vol=0.03),
            sentiment_score=0.42, article_count=22,
            asset_class="crypto",
        ),
        build(
            ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials",
            price=196.20, change_pct=0.25, volume=9_500_000, avg_volume_30d=11_000_000,
            price_history=gen_history(180, drift=0.0008, vol=0.01),
            sentiment_score=0.10, article_count=4,
            days_to_earnings=18,
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────

def run(mode: str = "demo", output_dir: str = "docs/data") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    log.info("✦ SILMARIL run starting — mode=%s", mode)

    if mode == "live":
        contexts = build_live_contexts()
    else:
        contexts = build_demo_contexts()

    if not contexts:
        log.error("No contexts built — aborting")
        sys.exit(1)

    # ── Run the debate ──────────────────────────────────────────
    arbiter = Arbiter(agents=AGENTS, aegis_veto_enabled=True)
    debates = arbiter.resolve(contexts)
    debate_dicts = [d.to_dict() for d in debates]

    # Annotate each debate with the context's asset_class (execution needs it)
    ctx_lookup = {c.ticker: c for c in contexts}
    for d in debate_dicts:
        c = ctx_lookup.get(d["ticker"])
        if c:
            d["asset_class"] = c.asset_class
            d["sector"] = c.sector

    debate_dicts.sort(
        key=lambda d: (d["consensus"]["score"], d["consensus"]["avg_conviction"]),
        reverse=True,
    )

    # ── Trade plans ─────────────────────────────────────────────
    plans = []
    for d in debate_dicts:
        plan = build_plan_from_debate(d, portfolio_size=10_000.0)
        if plan:
            plans.append(plan.to_dict())

    # ── SCROOGE ─────────────────────────────────────────────────
    scrooge_state_path = out / "scrooge.json"
    state = _load_or_init_scrooge(scrooge_state_path)
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
    prices = {ctx.ticker: ctx.price for ctx in contexts}
    state = scrooge_act(state, top_for_scrooge, prices)
    scrooge_dict = state.to_dict()

    # ── MIDAS (parallel hard-currency compounder) ───────────────
    midas_state_path = out / "midas.json"
    mstate = _load_or_init_midas(midas_state_path)
    midas_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
    ]
    mstate = midas_act(mstate, midas_candidates, prices)
    midas_dict = mstate.to_dict()

    # ── Handoff Blocks ──────────────────────────────────────────
    per_asset_handoffs = {
        d["ticker"]: build_asset_deep_dive(_attach_headlines(d, contexts))
        for d in debate_dicts
    }

    # Regime/VIX from the first context (all have the same macro)
    first = contexts[0]
    handoff_blocks = {
        "debate_summary": build_debate_summary(
            debate_dicts, market_regime=first.market_regime, vix=first.vix
        ),
        "scrooge_narrative": build_scrooge_narrative(scrooge_dict),
        "per_asset": per_asset_handoffs,
    }

    # ── Agent roster for UI (with full bios) ────────────────────
    agent_roster = []
    for a in AGENTS:
        bio = get_bio(a.codename)
        agent_roster.append({
            "codename": a.codename,
            "specialty": a.specialty,
            "temperament": a.temperament,
            "inspiration": a.inspiration,
            "bio": bio,
        })

    # ── Main output ─────────────────────────────────────────────
    signals_output = {
        "meta": {
            "version": "2.1.0",
            "project": "SILMARIL",
            "run_type": mode,
            "generated_at": now.isoformat(),
            "disclaimer": (
                "SILMARIL is an educational simulation. All content is for informational "
                "and entertainment purposes only. NOT financial advice. Always consult a "
                "licensed professional before investing."
            ),
        },
        "market_state": {
            "regime": first.market_regime,
            "vix": first.vix,
            "spy_trend": spy_trend_label(
                next((c.price for c in contexts if c.ticker == "SPY"), None),
                next((c.sma_50 for c in contexts if c.ticker == "SPY"), None),
            ),
        },
        "universe": {
            "core_count": len(contexts),
            "watchlist_count": 0,
            "discovered_count": 0,
            "total": len(contexts),
        },
        "agent_roster": agent_roster,
        "summary": _compute_summary(debate_dicts),
        "debates": debate_dicts,
    }

    _write(out / "signals.json", signals_output)
    _write(out / "trade_plans.json", {"meta": signals_output["meta"], "plans": plans})
    _write(out / "scrooge.json", scrooge_dict)
    _write(out / "midas.json", midas_dict)
    _write(out / "handoff_blocks.json", handoff_blocks)

    # ── Rolling history (per-agent track record, accumulates each run) ─
    _append_history(out / "history.json", debate_dicts, plans, now)

    log.info("✦ SILMARIL run complete")
    log.info("  %d debates resolved", len(debate_dicts))
    log.info("  %d trade plans", len(plans))
    log.info("  SCROOGE: $%.4f (life #%d)", scrooge_dict["balance"], scrooge_dict["current_life"])
    log.info("  MIDAS:   $%.4f (life #%d)", midas_dict["balance"], midas_dict["current_life"])
    log.info("  Output: %s", out.resolve())


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _load_or_init_scrooge(path: Path) -> ScroogeState:
    if not path.exists():
        return ScroogeState()
    try:
        with path.open() as f:
            data = json.load(f)
        return ScroogeState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
        )
    except Exception:
        return ScroogeState()


def _load_or_init_midas(path: Path) -> MidasState:
    if not path.exists():
        return MidasState()
    try:
        with path.open() as f:
            data = json.load(f)
        return MidasState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
        )
    except Exception:
        return MidasState()


def _append_history(path: Path, debate_dicts, plans, now) -> None:
    """Append a compact per-run snapshot to history.json so agent track
    records accumulate across runs. Kept small (verdicts only — not full
    debate transcripts) to avoid unbounded file growth."""
    today = now.date().isoformat()
    snapshot = {
        "date": today,
        "generated_at": now.isoformat(),
        "verdicts": [
            {
                "ticker": d["ticker"],
                "consensus": d["consensus"]["signal"],
                "consensus_score": d["consensus"]["score"],
                "agreement": d["consensus"]["agreement_score"],
                "votes": [
                    {
                        "agent": v["agent"],
                        "signal": v["signal"],
                        "conviction": v["conviction"],
                    }
                    for v in d.get("verdicts", [])
                ],
                "price": d.get("price"),
            }
            for d in debate_dicts
        ],
        "plans": [
            {
                "ticker": p["ticker"],
                "entry": p.get("entry"),
                "stop": p.get("stop"),
                "target": p.get("target"),
                "reward_risk_ratio": p.get("reward_risk_ratio"),
                "backers": [b["agent"] for b in p.get("backers", [])],
            }
            for p in plans
        ],
    }

    # Load existing, append, trim to last 120 snapshots (~6 months of trading days)
    data = {"runs": []}
    if path.exists():
        try:
            with path.open() as f:
                data = json.load(f)
        except Exception:
            data = {"runs": []}

    # Dedupe: if a run already exists for this date, replace it
    runs = [r for r in data.get("runs", []) if r.get("date") != today]
    runs.append(snapshot)
    runs = runs[-120:]
    data["runs"] = runs

    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)


def _attach_headlines(debate: dict, contexts: List[AssetContext]) -> dict:
    for ctx in contexts:
        if ctx.ticker == debate["ticker"]:
            return {**debate, "recent_headlines": ctx.recent_headlines}
    return debate


def _compute_summary(debates: List[dict]) -> dict:
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


# ─────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SILMARIL — multi-agent financial intelligence")
    parser.add_argument("--live", action="store_true", help="Fetch real market data")
    parser.add_argument("--demo", action="store_true", help="Use sample data (default)")
    parser.add_argument("--output", default="docs/data", help="Output directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    mode = "live" if args.live else "demo"
    run(mode=mode, output_dir=args.output)


if __name__ == "__main__":
    main()
