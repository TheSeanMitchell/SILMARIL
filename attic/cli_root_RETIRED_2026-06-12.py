"""
silmaril.cli — The main runner. Alpha 2.0 — Full Learning Mode.

Two modes:

  python -m silmaril --live    # Fetch real market data from yfinance + news RSS
  python -m silmaril --demo    # Use hand-crafted sample contexts for offline testing

The --live mode is what GitHub Actions runs on schedule. It populates
the live site at theseanmitchell.github.io/SILMARIL with real data.

The --demo mode is for local development and the repository's initial
commit, so the site renders meaningfully before the first scheduled run.

ALPHA 2.0 ADDITIONS:
  - Bayesian beliefs update each cycle (agent_beliefs.json — PROTECTED)
  - Thompson-sampled conviction multipliers boost hot agents
  - Evolution cards advance on every scored outcome (only grow)
  - Counterfactual logging for every overruled dissent
  - Operator reflections injected into agent contexts
  - Drift detection auto-dampens cold agents
  - Time-of-day performance buckets
  - Position correlation matrix nightly snapshot
  - Anomaly detection (volume spikes, price gaps)
  - Alpaca paper trading bridge (paper-only, hardcoded)
  - Two new agents: CONTRARIAN, SHORT_ALPHA
  - Persistence guard: training NEVER resets across any workflow
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from .agents.cryptobro import cryptobro, cryptobro_act, CryptoBroState, CRYPTOBRO_UNIVERSE
from .agents.baron import baron, BARON_UNIVERSE
from .agents.steadfast import steadfast, CROWN_JEWELS
from .agents.jrr_token import (
    jrr_token, jrr_token_act, JRRTokenState, JRR_UNIVERSE,
    SUB_100M_TOKENS, OVER_100M_TOKENS,
)
from .agents.bios import get_bio
from .agents.sports_bro import (
    sports_bro, sports_bro_act, SportsBroState, settle_expired_bets,
)

# ── v2.0 agents ─────────────────────────────────────────────────
from .agents.atlas import atlas
from .agents.nightshade import nightshade
from .agents.cicada import cicada
from .agents.shepherd import shepherd
from .agents.nomad import nomad
from .agents.barnacle import barnacle
from .agents.kestrel_plus import kestrel_plus

# ── ALPHA 2.0 new agents ────────────────────────────────────────
# These are imported defensively — if the modules don't exist yet
# (e.g. mid-merge), we gracefully skip them rather than crash.
try:
    from .agents.contrarian import Contrarian as _ContrarianClass
    contrarian = _ContrarianClass()
    _HAS_CONTRARIAN = True
except Exception as _e:
    contrarian = None
    _HAS_CONTRARIAN = False

try:
    from .agents.short_alpha import ShortAlpha as _ShortAlphaClass
    short_alpha = _ShortAlphaClass()
    _HAS_SHORT_ALPHA = True
except Exception as _e:
    short_alpha = None
    _HAS_SHORT_ALPHA = False

from .sports import fetch_markets, write_markets_json
from .catalysts import write_catalysts_json
from .charts import write_charts_json
from .handoff.brokers import build_broker_links
from .portfolios.agent_portfolio import (
    AgentPortfolio, agent_portfolio_act, load_portfolios, save_portfolios,
)
from .scoring.regime_tags import tag_context
from .scoring.outcomes import (
    score_prior_run, build_scoring_summary, load_scoring, save_scoring,
)
from .risk.engine import (
    AgentRiskState, SystemRiskState, DEFAULT_CONFIG,
    evaluate_agent_risk, evaluate_cohort_risk,
    filter_plans_by_risk, load_risk_state, save_risk_state,
)

from .debate.arbiter import Arbiter
from .trade_engine.plans import build_plan_from_debate
from .handoff.blocks import (
    build_asset_deep_dive,
    build_scrooge_narrative,
    build_debate_summary,
    build_trade_plan_handoff,
)
from .universe.core import all_entries, asset_class_of
from .analytics import technicals as ti
from .analytics.sentiment import aggregate_ticker_sentiment
from .analytics.regime import classify_regime, spy_trend_label

# ── ALPHA 2.0 Full Learning Mode imports ────────────────────────
# All defensively imported so if a module is missing mid-merge, the
# old runner still works. Each capability is gated by its _HAS flag.
try:
    from .learning.persistence_guard import (
        PROTECTED_LEARNING_FILES, emit_persistence_status, verify_persistence,
    )
    from .learning.bayesian_winrate import (
        load_beliefs, save_beliefs, update_beliefs,
    )
    from .learning.thompson_arbiter import sample_conviction_multipliers
    from .learning.dissent_digest import build_dissent_digest, attach_digest_to_contexts
    from .learning.reflection import load_reflection, format_reflection_for_context
    from .learning.evolution_cards import load_cards, save_cards, ensure_card
    from .learning.counterfactual import log_counterfactual
    from .learning.regime_bandit import RegimeBanditStore, context_key
    from .learning.time_of_day import get_tod_bucket, record_tod_outcome
    from .learning.drift_detector import (
        detect_drift, update_drift_state, get_drift_dampeners,
    )
    from .learning.correlation_matrix import (
        compute_position_correlations, append_to_history as append_corr_history,
    )
    from .learning.anomaly_detector import (
        detect_volume_spike, detect_price_gap, record_anomalies,
    )
    from .learning.premortem import generate_premortem, archive_premortem
    _HAS_LEARNING = True
except Exception as _e:
    _HAS_LEARNING = False
    logging.getLogger("silmaril").warning(
        "Alpha 2.0 learning modules not yet installed; running in compatibility mode. (%s)", _e
    )

try:
    from .execution.alpaca_paper import execute_consensus_signals
    _HAS_ALPACA = True
except Exception as _e:
    _HAS_ALPACA = False

try:
    from .agents._rename_map import display_label, all_new_codenames
    _HAS_RENAME_MAP = True
except Exception as _e:
    _HAS_RENAME_MAP = False
 
try:
    from .senate.candidates import (
        load_candidates, tag_shadow_verdicts,
        filter_shadow_verdicts_for_consensus, extract_candidate_summary)
    _HAS_SENATE = True
except Exception:
    _HAS_SENATE = False
    def load_candidates(): return []
    def tag_shadow_verdicts(d): pass
    def filter_shadow_verdicts_for_consensus(v): return v
    def extract_candidate_summary(d): return {}
 
try:
    from .ingestion.fred import get_macro_signals
    _HAS_FRED = True
except Exception:
    _HAS_FRED = False

try:
    from .portfolios.grocery import (
        load_ledger, save_ledger, build_leaderboard,
        COMPOUNDER_STARTING_CAPITAL, WEEKLY_TARGET)
    _HAS_GROCERY = True
except Exception:
    _HAS_GROCERY = False

# ─────────────────────────────────────────────────────────────────
# Full agent roster — the order here is the order shown in the UI
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# Agent Cohorts (Phase F)
#
# MAIN_VOTERS:  the panel of market experts. They vote in every debate.
#               Each runs a $10K career portfolio.
# SPECIALISTS:  niche operators. They act on consensus but DO NOT vote
#               (would muddy the consensus with ultra-narrow domain bias).
#               Some run $10K portfolios (Baron, Steadfast), some are
#               $1 compounders (Scrooge, Midas, CryptoBro, JRR Token).
# ─────────────────────────────────────────────────────────────────

MAIN_VOTERS: List[Agent] = [
    aegis, forge, thunderhead, jade, veil, kestrel, obsidian, zenith,
    weaver, hex_agent, synth, speck, vespa, magus, talon,
    # v2.0 additions:
    atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus,
]
# Alpha 2.0 additions to the voter panel
if _HAS_CONTRARIAN and contrarian is not None:
    MAIN_VOTERS.append(contrarian)
if _HAS_SHORT_ALPHA and short_alpha is not None:
    MAIN_VOTERS.append(short_alpha)

SPECIALIST_AGENTS: List[Agent] = [
    baron, steadfast,            # $10K career operators
    scrooge, midas, cryptobro, jrr_token, sports_bro,  # $1 compounders
]

# Backward compat alias — used elsewhere in the CLI for serialization
AGENTS: List[Agent] = MAIN_VOTERS + SPECIALIST_AGENTS
 
if _HAS_SENATE:
    _candidates = load_candidates()
    AGENTS = AGENTS + _candidates
    logging.getLogger("silmaril").info(
        "senate: %d candidate agent(s) loaded in shadow mode", len(_candidates))


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

    # Alpha 2.2 timeout fix: cap news to 100 tickers.
    # At ~8s/ticker sequential, 348 → 46 min (timeout). 100 → ~13 min (safe).
    # Priority: equities > ETFs > major crypto. Memecoins skipped (no feeds).
    _NEWS_CAP = 100
    _CRYPTO_SKIP_SUFFIXES = ("-USD",)
    _MEMECOIN_SKIP = {
        "PEPE-USD", "FLOKI-USD", "BONK-USD", "WIF-USD", "MOG-USD",
        "TURBO-USD", "BRETT-USD", "POPCAT-USD", "MEW-USD", "PNUT-USD",
        "ALT-USD", "SHIB-USD", "DOGE-USD",
    }
    # Build prioritised list: non-crypto first, then major crypto, skip memecoins
    _news_equity = [(t, n) for t, n, _ in entries
                    if not any(t.endswith(s) for s in _CRYPTO_SKIP_SUFFIXES)]
    _news_crypto = [(t, n) for t, n, _ in entries
                    if any(t.endswith(s) for s in _CRYPTO_SKIP_SUFFIXES)
                    and t not in _MEMECOIN_SKIP]
    name_pairs_capped = (_news_equity + _news_crypto)[:_NEWS_CAP]
    log.info(
        "Fetching news for %d/%d tickers (capped for timeout safety — "
        "%d equities/ETFs, %d crypto)...",
        len(name_pairs_capped), len(tickers),
        len([p for p in name_pairs_capped if not p[0].endswith("-USD")]),
        len([p for p in name_pairs_capped if p[0].endswith("-USD")]),
    )
    news_map = fetch_news_bulk(name_pairs_capped, max_articles_per=5)

    # ── ALPHA 3.0: Ticker disambiguation ─────────────────────────────
    # Strip false-match articles like "Snow College basketball" → SNOW,
    # "Duke point guard" → PG, "Here and Now" → NOW, etc. Drops are
    # logged to docs/data/ticker_disambiguation.json for dashboard.
    try:
        from .ingestion.ticker_disambiguation import filter_bulk as _disambig
        _name_map = {tkr: name for tkr, name in name_pairs_capped}
        news_map = _disambig(news_map, _name_map, data_dir=Path("docs/data"))
    except Exception as _de:
        log.warning("ticker disambiguation skipped: %s", _de)

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
                {"title": a.title, "source": a.source, "url": a.url,
                 "published": a.published_iso or ""}
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
    def gen_history(center: float, closes: int = 220, drift: float = 0.0002, vol: float = 0.015, seed_key: str = "") -> List[float]:
        """Generate a synthetic-but-plausible price history by random walk.
        Seeded deterministically by today's UTC date + a per-ticker key so
        every same-day cron run produces identical data (no spurious
        run-to-run drift), but each new UTC day evolves naturally."""
        import random
        from datetime import datetime, timezone
        today_iso = datetime.now(timezone.utc).date().isoformat()
        # Stable seed: hash of (ticker_key + today + price_anchor)
        seed_str = f"{seed_key}:{today_iso}:{int(center*100)}"
        seed_int = 0
        for ch in seed_str:
            seed_int = (seed_int * 31 + ord(ch)) & 0x7FFFFFFF
        random.seed(seed_int)
        out = [center * 0.85]
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
            ticker="ETH-USD", name="Ethereum", sector="Crypto",
            price=3520, change_pct=4.10, volume=0, avg_volume_30d=0,
            price_history=gen_history(2400, drift=0.0022, vol=0.034),
            sentiment_score=0.38, article_count=14,
            asset_class="crypto",
        ),
        build(
            ticker="SOL-USD", name="Solana", sector="Crypto",
            price=178.40, change_pct=6.85, volume=0, avg_volume_30d=0,
            price_history=gen_history(112, drift=0.003, vol=0.045),
            sentiment_score=0.55, article_count=8,
            asset_class="crypto",
        ),
        build(
            ticker="JPM", name="JPMorgan Chase & Co.", sector="Financials",
            price=196.20, change_pct=0.25, volume=9_500_000, avg_volume_30d=11_000_000,
            price_history=gen_history(180, drift=0.0008, vol=0.01),
            sentiment_score=0.10, article_count=4,
            days_to_earnings=18,
        ),
        # ── Phase F demo additions: oil/Baron + tokens/JRR + crown jewels/Steadfast ─
        build(
            ticker="USO", name="United States Oil Fund (WTI)", sector="Energy",
            price=78.40, change_pct=1.85, volume=4_200_000, avg_volume_30d=4_800_000,
            price_history=gen_history(72, drift=0.0010, vol=0.022),
            sentiment_score=0.18, article_count=6, asset_class="etf",
        ),
        build(
            ticker="XOM", name="Exxon Mobil", sector="Energy",
            price=118.90, change_pct=-0.85, volume=14_000_000, avg_volume_30d=15_500_000,
            price_history=gen_history(115, drift=0.0006, vol=0.014),
            sentiment_score=0.05, article_count=5,
        ),
        build(
            ticker="VLO", name="Valero Energy", sector="Energy",
            price=148.60, change_pct=2.10, volume=3_800_000, avg_volume_30d=4_500_000,
            price_history=gen_history(135, drift=0.0012, vol=0.018),
            sentiment_score=0.25, article_count=4,
        ),
        build(
            ticker="KO", name="Coca-Cola", sector="Staples",
            price=68.20, change_pct=-1.50, volume=14_000_000, avg_volume_30d=12_000_000,
            price_history=gen_history(72, drift=-0.0001, vol=0.008),
            sentiment_score=-0.05, article_count=2,
        ),
        build(
            ticker="DIS", name="Disney", sector="Communication",
            price=92.40, change_pct=-2.30, volume=11_000_000, avg_volume_30d=12_500_000,
            price_history=gen_history(98, drift=-0.0005, vol=0.014),
            sentiment_score=-0.18, article_count=8,
        ),
        build(
            ticker="PEPE-USD", name="Pepe (memecoin)", sector="Token",
            price=0.000018, change_pct=18.50, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.000012, drift=0.005, vol=0.08),
            sentiment_score=0.55, article_count=14, asset_class="crypto",
        ),
        build(
            ticker="SHIB-USD", name="Shiba Inu", sector="Token",
            price=0.0000242, change_pct=6.20, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.000022, drift=0.002, vol=0.045),
            sentiment_score=0.32, article_count=8, asset_class="crypto",
        ),
        build(
            ticker="ARB-USD", name="Arbitrum", sector="Token",
            price=0.74, change_pct=4.80, volume=0, avg_volume_30d=0,
            price_history=gen_history(0.65, drift=0.0018, vol=0.04),
            sentiment_score=0.28, article_count=5, asset_class="crypto",
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# ALPHA 2.0 — Pre-debate learning setup
# Loads beliefs, builds dissent digest, injects reflection.
# Returns a bundle that post-debate update consumes.
# ─────────────────────────────────────────────────────────────────

def _pre_debate_learning(out: Path, contexts: List[AssetContext]) -> dict:
    """Returns a learning context bundle. Empty dict if learning unavailable."""
    if not _HAS_LEARNING:
        return {}

    bundle = {
        "out": out,
        "beliefs": {},
        "cards": {},
        "rolling_winrates": {},
        "drift_dampeners": {},
        "tod_bucket": "UNKNOWN",
        "digest": "",
        "reflection": None,
        "multipliers": {},
    }

    try:
        bundle["beliefs"] = load_beliefs(out / "agent_beliefs.json")
    except Exception as e:
        log.warning("learning: load_beliefs failed: %s", e)

    try:
        bundle["cards"] = load_cards(out / "agent_evolution_cards.json")
    except Exception as e:
        log.warning("learning: load_cards failed: %s", e)

    # Build dissent digest from history + scoring
    try:
        bundle["digest"] = build_dissent_digest(
            scoring_path=out / "scoring.json",
            history_path=out / "history.json",
            counterfactuals_path=out / "counterfactuals.json",
            lookback_days=7,
        )
    except Exception as e:
        log.warning("learning: dissent digest failed: %s", e)

    # Operator reflection
    try:
        bundle["reflection"] = load_reflection(out / "reflections.json")
    except Exception as e:
        log.warning("learning: load_reflection failed: %s", e)

    # Inject into asset contexts
    reflection_block = format_reflection_for_context(bundle["reflection"]) if bundle["reflection"] else ""
    learning_block = f"{bundle['digest']}\n{reflection_block}".strip()
    if learning_block:
        try:
            attach_digest_to_contexts(contexts, learning_block)
            log.info("learning: injected %d chars of context into %d assets",
                     len(learning_block), len(contexts))
        except Exception as e:
            log.warning("learning: attach_digest failed: %s", e)

    # Compute rolling winrates from existing scoring.json
    scoring_path = out / "scoring.json"
    if scoring_path.exists():
        try:
            sd = json.loads(scoring_path.read_text())
            for row in sd.get("leaderboard", []):
                agent = row.get("agent")
                wr = row.get("rolling_30d_win_rate")
                if wr is None:
                    wr = row.get("win_rate")
                if agent and wr is not None:
                    bundle["rolling_winrates"][agent] = float(wr)
        except Exception as e:
            log.warning("learning: rolling_winrates failed: %s", e)

    # Drift dampeners
    try:
        bundle["drift_dampeners"] = get_drift_dampeners(out / "drift_state.json")
    except Exception as e:
        log.warning("learning: drift_dampeners failed: %s", e)

    # Time-of-day bucket
    try:
        bundle["tod_bucket"] = get_tod_bucket()
    except Exception:
        pass

    # Thompson-sampled conviction multipliers per agent for current regime
    try:
        regime = contexts[0].market_regime if contexts else "NEUTRAL"
        if bundle["beliefs"]:
            mults = sample_conviction_multipliers(bundle["beliefs"], regime)
            # Apply drift dampeners
            for agent, dmp in bundle["drift_dampeners"].items():
                if agent in mults and dmp < 1.0:
                    mults[agent] *= dmp
            bundle["multipliers"] = mults
    except Exception as e:
        log.warning("learning: thompson sampling failed: %s", e)

    return bundle


def _apply_conviction_multipliers(verdicts: list, multipliers: dict) -> list:
    """Scale each verdict's conviction by its agent's Thompson multiplier.
    Caps conviction at [0, 1] after scaling. Mutates in place."""
    if not multipliers:
        return verdicts
    for v in verdicts:
        agent = v.get("agent") if isinstance(v, dict) else getattr(v, "agent", None)
        if not agent:
            continue
        mult = multipliers.get(agent, 1.0)
        if isinstance(v, dict):
            cur = float(v.get("conviction", 0) or 0)
            v["conviction"] = max(0.0, min(1.0, cur * mult))
            v.setdefault("learning_multiplier", round(mult, 3))
        else:
            cur = float(getattr(v, "conviction", 0) or 0)
            try:
                v.conviction = max(0.0, min(1.0, cur * mult))
            except Exception:
                pass
    return verdicts


def _scan_anomalies(out: Path, contexts: List[AssetContext]) -> List[dict]:
    """Scan all contexts for anomalies, persist with TTL."""
    if not _HAS_LEARNING:
        return []
    state_path = out / "anomaly_state.json"
    fresh = []
    for ctx in contexts:
        anomalies = []
        try:
            cur_v = getattr(ctx, "volume", None) or 0
            avg_v = getattr(ctx, "avg_volume_30d", None) or 0
            if cur_v and avg_v:
                # Construct a synthetic 30-day history near the avg for z-score
                hist = [avg_v] * 30
                vs = detect_volume_spike(int(cur_v), hist, threshold_sigma=3.0)
                if vs:
                    anomalies.append(vs)
        except Exception:
            pass
        try:
            ph = getattr(ctx, "price_history", None) or []
            if len(ph) >= 2 and ctx.price:
                pg = detect_price_gap(open_price=ctx.price, prev_close=ph[-2])
                if pg:
                    anomalies.append(pg)
        except Exception:
            pass
        if anomalies and ctx.ticker:
            try:
                f = record_anomalies(state_path, ctx.ticker, anomalies)
                fresh.extend(f)
            except Exception:
                pass
    if fresh:
        log.info("learning: detected %d fresh anomalies", len(fresh))
    return fresh


# ─────────────────────────────────────────────────────────────────
# ALPHA 2.0 — Post-debate learning update
# Updates beliefs, evolution cards, drift state, counterfactuals.
# ─────────────────────────────────────────────────────────────────

def _post_debate_learning(
    bundle: dict,
    *,
    debate_dicts: list,
    portfolios: dict,
    new_outcome_dicts: list,
    contexts: List[AssetContext],
    today_iso: str,
) -> None:
    """Update all learning state after consensus + outcome scoring."""
    if not _HAS_LEARNING or not bundle:
        return

    out: Path = bundle.get("out")
    if not out:
        return

    # 1) Update Bayesian beliefs from newly scored outcomes
    if new_outcome_dicts:
        try:
            from .universe.core import is_equity_ticker

            def _regime_of(o):
                # Regime lives under tags.market_regime; the old top-level reads
                # were always None, so every update landed in the UNKNOWN bucket
                # while live trading samples the actual-regime bucket. Read tags.
                return (
                    (o.get("tags") or {}).get("market_regime")
                    or o.get("regime")
                    or o.get("market_regime")
                    or "UNKNOWN"
                )

            outcomes_for_beliefs = [
                {
                    "agent": o.get("agent"),
                    "regime": _regime_of(o),
                    "won": bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                    # Alpha 6.2: carry realized move so update_beliefs can
                    # profit-weight (big right calls count more than trivial
                    # ones; big wrong calls hurt more than small ones).
                    "return_pct": o.get("return_pct"),
                    "reward": o.get("reward"),
                }
                for o in new_outcome_dicts
                if o.get("agent")
                # Alpha 2.2: Only directional calls update beliefs.
                # HOLD votes carry no signal about future direction.
                and o.get("signal") not in ("HOLD",)
                # ALPHA 0.001: beliefs drive REAL trades via Thompson multipliers.
                # Train them on CLEAN, EQUITY-ONLY outcomes — never on stale-price
                # artifacts or crypto/macro (the stock mission). This stops the
                # real learning loop from being polluted by instruments we don't
                # trade and prices we don't trust.
                and not o.get("stale_price_suspected")
                and is_equity_ticker(o.get("ticker"))
            ]
            beliefs = update_beliefs(bundle["beliefs"], outcomes_for_beliefs)
            save_beliefs(out / "agent_beliefs.json", beliefs)
            log.info("learning: updated beliefs on %d clean equity outcomes", len(outcomes_for_beliefs))
        except Exception as e:
            log.warning("learning: belief update failed: %s", e)

    # 2) Advance evolution cards (only grow)
    if new_outcome_dicts:
        try:
            cards = bundle.get("cards", {})
            for o in new_outcome_dicts:
                agent = o.get("agent")
                if not agent:
                    continue
                card = ensure_card(cards, agent)
                card.record_call(
                    won=bool(o.get("correct", o.get("was_correct", o.get("won", False)))),
                    conviction=float(o.get("conviction", 0.5) or 0.5),
                    regime=o.get("regime") or "UNKNOWN",
                    was_dissent=bool(o.get("was_dissent", False)),
                )
            save_cards(out / "agent_evolution_cards.json", cards)
            log.info("learning: advanced %d evolution cards", len(cards))
        except Exception as e:
            log.warning("learning: evolution cards update failed: %s", e)

    # 3) Counterfactual logging — for each debate, log dissent vs consensus
    try:
        for d in debate_dicts:
            ndr = d.get("next_day_return")
            if ndr is None:
                continue
            consensus_signal = (d.get("consensus") or {}).get("signal", "HOLD")
            for v in d.get("verdicts", []):
                v_signal = v.get("signal")
                if v_signal in (consensus_signal, "ABSTAIN"):
                    continue
                try:
                    log_counterfactual(
                        out / "counterfactuals.json",
                        date_str=today_iso,
                        ticker=d.get("ticker", ""),
                        consensus_signal=consensus_signal,
                        dissenting_agent=v.get("agent", ""),
                        dissent_signal=v_signal,
                        next_day_return=float(ndr),
                    )
                except Exception:
                    pass
    except Exception as e:
        log.warning("learning: counterfactual logging failed: %s", e)

    # 4) Drift detection — scan evolution cards vs rolling winrates
    try:
        drift_by_agent = {}
        for agent, card in bundle.get("cards", {}).items():
            rolling = bundle["rolling_winrates"].get(agent, None)
            if rolling is None:
                continue
            n_calls = getattr(card, "lifetime_calls", 0) or 0
            if n_calls < 30:
                continue
            lt = getattr(card, "lifetime_win_rate", 0.5)
            d = detect_drift(
                rolling_30d_winrate=float(rolling),
                lifetime_winrate=float(lt),
                n_recent_calls=min(n_calls, 100),
            )
            if d.get("drifting"):
                drift_by_agent[agent] = d
        update_drift_state(out / "drift_state.json", drift_by_agent)
        if drift_by_agent:
            log.info("learning: drift detected for %s", list(drift_by_agent.keys()))
    except Exception as e:
        log.warning("learning: drift detection failed: %s", e)

    # 5) Time-of-day bucket update
    if new_outcome_dicts:
        try:
            bucket = bundle.get("tod_bucket") or "UNKNOWN"
            for o in new_outcome_dicts:
                agent = o.get("agent")
                if not agent:
                    continue
                record_tod_outcome(
                    out / "time_of_day_performance.json",
                    agent,
                    bucket,
                    bool(o.get("correct", o.get("won", False))),
                )
        except Exception as e:
            log.warning("learning: TOD update failed: %s", e)

    # 6) Correlation matrix snapshot
    try:
        portfolio_snap = {}
        for name, p in (portfolios or {}).items():
            cp = getattr(p, "current_position", None)
            if cp:
                portfolio_snap[name] = {"current_position": cp}
        # Build price_history map from contexts
        price_history = {}
        for ctx in contexts:
            ph = getattr(ctx, "price_history", None)
            if ph:
                price_history[ctx.ticker] = list(ph)[-90:]
        if portfolio_snap and price_history:
            snap = compute_position_correlations(portfolio_snap, price_history)
            append_corr_history(out / "correlation_history.json", snap)
            alerts = snap.get("concentration_alerts", [])
            if alerts:
                log.info("learning: %d concentration alerts", len(alerts))
    except Exception as e:
        log.warning("learning: correlation snapshot failed: %s", e)

    # 7) Persistence health check
    try:
        emit_persistence_status(out, out / "persistence_status.json")
    except Exception as e:
        log.warning("learning: persistence_status failed: %s", e)


# ─────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────

def run(mode: str = "demo", output_dir: str = "docs/data") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    today_iso = now.date().isoformat()
    log.info("✦ SILMARIL run starting — mode=%s", mode)

    if mode == "live":
        contexts = build_live_contexts()
    else:
        contexts = build_demo_contexts()

    if not contexts:
        log.error("No contexts built — aborting")
        sys.exit(1)

    # ── Backfill demo headlines for assets that don't have hand-written ones ─
    # In live mode, recent_headlines is populated by news.py from RSS.
    # In demo mode, only a couple of assets have curated headlines, so we
    # generate plausible synthetic ones so the news-feed UI is demonstrable.
    if mode == "demo":
        _backfill_demo_headlines(contexts)

    # ── ALPHA 2.0: Pre-debate learning setup ────────────────────
    # Loads agent_beliefs.json, builds dissent digest, injects operator
    # reflection into every asset context, computes Thompson-sampled
    # conviction multipliers, and applies drift dampeners.
    learning_bundle = _pre_debate_learning(out, contexts)

    # Anomaly scan (volume spikes, price gaps) — flagged for next debate
    _scan_anomalies(out, contexts)

    # ── Run the debate ──────────────────────────────────────────
    # Only the main voters vote in the debate. Specialists act on consensus
    # but their narrow universes would distort the cross-asset signal if
    # they could vote.
    arbiter = Arbiter(agents=MAIN_VOTERS, aegis_veto_enabled=True)
    debates = arbiter.resolve(contexts)
    debate_dicts = [d.to_dict() for d in debates]

    # ── ALPHA 2.0: Apply Thompson-sampled conviction multipliers ─
    # Each agent's voted conviction gets scaled by how confident the
    # Bayesian posterior is in that agent's win rate in this regime.
    # Confident hot agents get amplified voice; cold agents get muted.
    # Alpha 2.3: strip candidate shadow verdicts before consensus recomputation
    # so they don't affect the main panel vote. They remain in debate_dicts
    # for outcomes.py to score them — they just don't move the consensus needle.
    if _HAS_SENATE:
        tag_shadow_verdicts(debate_dicts)
        for _d in debate_dicts:
            _d["verdicts"] = filter_shadow_verdicts_for_consensus(_d["verdicts"])
 
    if learning_bundle.get("multipliers"):
        for d in debate_dicts:
            verdicts = d.get("verdicts", [])
            _apply_conviction_multipliers(verdicts, learning_bundle["multipliers"])
            # Recompute consensus signal/score from scaled verdicts
            _recompute_consensus_in_place(d)

    # ── Specialist votes (operator-only, never affects consensus) ─
    # Baron and Steadfast run $10K career portfolios; they need their
    # own verdicts attached to each debate so the portfolio system can
    # pick their best BUY. These verdicts are added AFTER consensus is
    # computed, so they don't influence the panel's vote.
    SPECIALIST_VOTERS = [baron, steadfast]
    ctx_by_ticker = {c.ticker: c for c in contexts}
    for d in debate_dicts:
        ctx = ctx_by_ticker.get(d["ticker"])
        if not ctx:
            continue
        for spec in SPECIALIST_VOTERS:
            if spec.applies_to(ctx):
                v = spec.evaluate(ctx)
                d.setdefault("verdicts", []).append({
                    "agent": v.agent,
                    "signal": v.signal.value,
                    "conviction": v.conviction,
                    "rationale": v.rationale,
                    "is_specialist": True,
                })

    # Annotate each debate with the context's asset_class (execution needs it)
    # and recent_headlines (so the dashboard can show what news drove the vote)
    # and regime tags (so we can later score performance by market condition)
    ctx_lookup = {c.ticker: c for c in contexts}
    for d in debate_dicts:
        c = ctx_lookup.get(d["ticker"])
        if c:
            d["asset_class"] = c.asset_class
            d["sector"] = c.sector
            d["recent_headlines"] = c.recent_headlines or []
            # Persist the news signal that fed the agents' votes, so the
            # headline→decision link is visible (not just computed and discarded).
            d["sentiment_score"] = c.sentiment_score
            d["article_count"] = c.article_count
            # Build a flat ctx-like dict for regime tagging
            ctx_flat = {
                "price": c.price,
                "sma_20": getattr(c, "sma_20", None),
                "sma_50": getattr(c, "sma_50", None),
                "sma_200": getattr(c, "sma_200", None),
                "atr_14": getattr(c, "atr_14", None),
                "volume": c.volume,
                "avg_volume_30d": c.avg_volume_30d,
                "article_count": c.article_count,
                "vix": c.vix,
                "market_regime": c.market_regime,
            }
            d["tags"] = tag_context(ctx_flat)

    # ── ALPHA 2.0: Pre-mortem on high-conviction calls ──────────
    # For consensus calls with conviction >= 0.55, generate explicit
    # kill-criteria and bear-case statements written into the rationale.
    if _HAS_LEARNING:
        try:
            for d in debate_dicts:
                cons = d.get("consensus") or {}
                conv = float(cons.get("avg_conviction", 0) or 0)
                sig = cons.get("signal", "HOLD")
                if conv < 0.55 or sig in ("HOLD", "ABSTAIN"):
                    continue
                c = ctx_lookup.get(d["ticker"])
                if not c:
                    continue
                ctx_summary = {
                    "price": c.price,
                    "sma_20": getattr(c, "sma_20", None),
                    "sma_50": getattr(c, "sma_50", None),
                }
                pm = generate_premortem(
                    signal=sig, conviction=conv, ticker=d["ticker"],
                    rationale=d.get("dissent_summary", ""), ctx_summary=ctx_summary,
                )
                if pm:
                    d["premortem"] = pm
                    archive_premortem(
                        out / "premortem_archive.json",
                        agent="CONSENSUS", ticker=d["ticker"],
                        signal=sig, conviction=conv, premortem=pm,
                    )
        except Exception as e:
            log.warning("learning: premortem generation failed: %s", e)

    debate_dicts.sort(
        key=lambda d: (d["consensus"]["score"], d["consensus"]["avg_conviction"]),
        reverse=True,
    )

    # ── Trade plans ─────────────────────────────────────────────
    # Top 16 by consensus across all debates (Phase F: was unbounded)
    TOP_PLAN_COUNT = 16
    plans = []
    for d in debate_dicts[:TOP_PLAN_COUNT]:
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

    # ── Once-per-day gate ─────────────────────────────────────────
    # The cron fires every 10 min during market hours. We want trade
    # decisions to happen ONCE per UTC day per agent, not on every
    # cron run. Multi-trade agents (CryptoBro/JRR/Sports/Baron) have
    # their own daily caps and reset counters at midnight UTC.
    def _scrooge_already_acted_today(s):
        # SCROOGE rotates at most 1× per day. If history shows action today, skip.
        return any((h.get("date") == today_iso) and h.get("action") in ("BUY", "SELL", "ROTATE", "HODL")
                   for h in (s.history or []))

    def _midas_already_acted_today(s):
        # MIDAS minimum cycle is 7 days, but in this gate we just check today
        return any(h.get("date") == today_iso for h in (s.history or []))

    # ── ALPHA 7.2: synthetic $1 compounders DISABLED ─────────────
    # SCROOGE, MIDAS, CRYPTOBRO, JRR_TOKEN and SPORTS_BRO run internal
    # *simulated* bankrolls — they are NOT real Alpaca trades and never
    # touch the executor or the $10k portfolios (DOLLAR_COMPOUNDERS are
    # excluded below). Per operator direction ("nothing synthetic on the
    # site"), their per-cycle action is turned off so they stop generating
    # fictional activity (and stop the Sports Bro market-fetch API calls).
    # Their state files freeze at last value; all downstream display,
    # heartbeat and logging still read them safely. Flip to True to re-enable.
    RUN_SYNTHETIC_COMPOUNDERS = False

    if RUN_SYNTHETIC_COMPOUNDERS and not _scrooge_already_acted_today(state):
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
    if RUN_SYNTHETIC_COMPOUNDERS and not _midas_already_acted_today(mstate):
        mstate = midas_act(mstate, midas_candidates, prices)
    midas_dict = mstate.to_dict()

    # ── CryptoBro (parallel multi-trade crypto compounder) ──────
    cbro_state_path = out / "cryptobro.json"
    cbstate = _load_or_init_cryptobro(cbro_state_path)
    cbro_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
    ]
    # CryptoBro respects his per-day cap inside act(); pass through.
    if RUN_SYNTHETIC_COMPOUNDERS:
        cbstate = cryptobro_act(cbstate, cbro_candidates, prices)
    cryptobro_dict = cbstate.to_dict()

    # ── JRR Token (two-tier penny token compounder) ─────────────
    jrr_state_path = out / "jrr_token.json"
    jrrstate = _load_or_init_jrr_token(jrr_state_path)
    jrr_candidates = [
        {
            "ticker": d["ticker"],
            "consensus": d["consensus"],
        }
        for d in debate_dicts
        if d["ticker"] in JRR_UNIVERSE
    ]
    if RUN_SYNTHETIC_COMPOUNDERS:
        jrrstate = jrr_token_act(jrrstate, jrr_candidates, prices)
    jrr_token_dict = jrrstate.to_dict()

    # ── Sports Bro (Polymarket + Kalshi) ────────────────────────
    sports_state_path = out / "sports_bro.json"
    sb_state = _load_or_init_sports_bro(sports_state_path)
    if RUN_SYNTHETIC_COMPOUNDERS:
        sports_markets = fetch_markets(mode=mode)
        sb_state = settle_expired_bets(sb_state)  # v3: auto-resolve expired bets
        sb_state = sports_bro_act(sb_state, sports_markets)
        write_markets_json(out / "sports_markets.json", sports_markets)
    sports_bro_dict = sb_state.to_dict()

    # ── Catalysts roundup ─── moved to after plans_kept is built
    # (see below, after risk filter) so we can pass relevant tickers.

    # ── Chart bundles for each debated ticker ───────────────────
    write_charts_json(out / "charts.json", debate_dicts, ctx_lookup)

    # ── Per-agent $10K career portfolios ─────────────────────────
    # Includes the main voters PLUS Baron and Steadfast (specialists
    # who run $10K career books). $1 compounders are excluded.
    portfolios_path = out / "agent_portfolios.json"
    portfolios = load_portfolios(portfolios_path)
    DOLLAR_COMPOUNDERS = {"SCROOGE", "MIDAS", "CRYPTOBRO", "JRR_TOKEN", "SPORTS_BRO"}
    main_agents = [a.codename for a in AGENTS if a.codename not in DOLLAR_COMPOUNDERS]

    # Load any pre-existing risk state to know which agents enter today frozen
    risk_path = out / "risk_state.json"
    prior_agent_risk, prior_system_risk = load_risk_state(risk_path)
    frozen_today = {n for n, s in prior_agent_risk.items() if s.frozen}
    if prior_system_risk.safe_mode:
        log.warning("  ⚠ Entering run in SAFE MODE: %s", prior_system_risk.safe_mode_reason)
        # In safe mode, ALL agents skip new opens
        frozen_today = set(main_agents)

    for agent_name in main_agents:
        if agent_name not in portfolios:
            portfolios[agent_name] = AgentPortfolio(agent=agent_name)
        p = portfolios[agent_name]

        # Once-per-day gate: only run trade decision if the agent
        # hasn't already acted on a trade today. Mark-to-market the
        # current equity on every cron run so the dashboard stays fresh.
        already_acted_today = any(
            h.get("date") == today_iso and h.get("action") in (
                "BUY", "SELL", "ROTATE", "HODL", "OPEN", "CLOSE", "FROZEN", "HOLD",
            )
            for h in (p.history or [])
        )

        if agent_name in frozen_today:
            # Mark equity but do not act
            mark = None
            if p.current_position:
                mark = prices.get(p.current_position["ticker"])
            equity = p.total_equity(mark)
            if not already_acted_today:
                p.history.append({
                    "date": today_iso,
                    "timestamp": now.isoformat(),  # ALPHA 2.0: real time, not just date
                    "action": "FROZEN",
                    "reason": (prior_agent_risk.get(agent_name).frozen_reason
                               if prior_agent_risk.get(agent_name)
                               else "System safe mode"),
                    "equity": round(equity, 4),
                })
                p.equity_curve.append({"date": today_iso, "equity": round(equity, 4)})
        elif not already_acted_today:
            portfolios[agent_name] = agent_portfolio_act(
                portfolios[agent_name], debate_dicts, prices,
            )
        # else: already acted today, no new action — equity will mark-to-market via prices
    save_portfolios(portfolios_path, portfolios, prices)

    # ── Phase C: outcome scoring (the learning loop) ────────────
    # Step 1: read existing history (which has yesterday's votes + tags)
    # Step 2: score those votes against today's prices
    # Step 3: append new outcomes to scoring.json
    # Step 4: rebuild the per-agent summary (win rate, EV, regime cuts)
    history_path = out / "history.json"
    history_data = {"runs": []}
    if history_path.exists():
        try:
            history_data = json.loads(history_path.read_text())
        except Exception:
            history_data = {"runs": []}

    scoring_path = out / "scoring.json"
    scoring_data = load_scoring(scoring_path)

    new_outcomes = score_prior_run(history_data, prices, today_iso)
    new_outcome_dicts = [o.to_dict() for o in new_outcomes]

    # Dedupe — never score the same (agent, ticker, predicted_at) twice
    existing_keys = {
        (o["agent"], o["ticker"], o["predicted_at"])
        for o in scoring_data.get("outcomes", [])
    }
    new_unique = [
        o for o in new_outcome_dicts
        if (o["agent"], o["ticker"], o["predicted_at"]) not in existing_keys
    ]
    all_outcomes = scoring_data.get("outcomes", []) + new_unique

    agent_codenames = [a.codename for a in AGENTS]
    scoring_summary = build_scoring_summary(all_outcomes, agent_codenames)
    save_scoring(scoring_path, all_outcomes, scoring_summary)

    # ── ALPHA 0.001: edge study (read-only analytic) ────────────
    # Where is the directional edge, actually? Writes edge_study.json from the
    # clean outcomes. Changes no trading/scoring — pure measurement. Wrapped so
    # a failure here can never break the cycle.
    try:
        from .learning.edge_study import write_edge_study
        _es = write_edge_study(out, all_outcomes)
        log.info("  Edge study: %d directional clean calls, overall %s (t=%+.2f)",
                 _es.get("n_directional", 0),
                 _es.get("overall", {}).get("verdict", "?"),
                 _es.get("overall", {}).get("t_stat", 0.0))
    except Exception as e:
        log.warning("  Edge study skipped: %s", e)

    # ── News & Event Intelligence (read-only, deterministic, NO LLM) ──
    # Forward event calendar + ETF regime baskets + news momentum from the day's
    # signals.json + catalysts.json. Display-only (Phase 1); wrapped so a failure
    # here can never break the cycle.
    try:
        from .intelligence.news_intelligence import build_news_intelligence
        _ni = build_news_intelligence(out)
        log.info("  News intelligence: %d dated events (to +%dd), %d stock baskets, %d in news",
                 _ni.get("event_calendar", {}).get("counts", {}).get("total_dated", 0),
                 _ni.get("event_calendar", {}).get("counts", {}).get("furthest_days", 0),
                 len(_ni.get("stocks", {}).get("baskets", [])),
                 _ni.get("summary", {}).get("names_in_news", 0))
    except Exception as e:
        log.warning("  News intelligence skipped: %s", e)

    # ── Event Recorder (append-only, deterministic, REAL data) ──
    # Captures market movement around tracked major events (SpaceX SPCX IPO) so
    # the full arc can be analyzed later. Reads news_intelligence.json (above) +
    # signals/benchmarking/alpaca state. Wrapped so a failure can't break the cycle.
    try:
        from .intelligence.event_recorder import record_event_snapshots
        _er = record_event_snapshots(out)
        for _ev in _er.get("events", []):
            if _ev.get("recording"):
                log.info("  Event recorder [%s]: T%+dd %s — %d snapshots captured",
                         _ev.get("id"), _ev.get("days_until", 0), _ev.get("phase", ""),
                         _ev.get("snapshot_count", 0))
    except Exception as e:
        log.warning("  Event recorder skipped: %s", e)

    # ── IPO Analysis & Learning (deterministic, REAL data) ──
    # Turns the recorded time series into the coverage/market/rotation arcs +
    # the playbook for the cockpit's IPO Watch. Wrapped so it can't break the cycle.
    try:
        from .intelligence.ipo_analysis import build_ipo_intelligence
        _ipo = build_ipo_intelligence(out)
        _ai = _ipo.get("active")
        if _ai:
            log.info("  IPO analysis: %s T%+dd %s — %d snapshots, coverage %s",
                     _ai.get("company"), _ai.get("days_until", 0), _ai.get("phase", ""),
                     _ai.get("snapshot_count", 0), _ai.get("arc", {}).get("coverage", {}).get("trend", "?"))
    except Exception as e:
        log.warning("  IPO analysis skipped: %s", e)

    # ── Catalyst Learning & Predictiveness (deterministic, REAL data) ──
    # Forward gauntlet + clustering->volatility + IPO proximity + the
    # ledger->outcome predictiveness loop. Wrapped so it can't break the cycle.
    try:
        from .catalysts.learning import build_catalyst_learning
        _cl = build_catalyst_learning(out)
        _clc = _cl.get("clustering", {})
        log.info("  Catalyst learning: %d upcoming, elevated_ahead=%s, ledger=%d linked=%d",
                 _cl.get("upcoming", {}).get("counts", {}).get("total", 0),
                 _clc.get("elevated_ahead"), _cl.get("learning", {}).get("ledger_size", 0),
                 _cl.get("learning", {}).get("linked_outcomes", 0))
    except Exception as e:
        log.warning("  Catalyst learning skipped: %s", e)

    # ── Deal Journal (read-only): news/catalyst/regime context per order, linked
    # to realized outcomes (wins + losses). Observes the trade path; never alters it.
    try:
        from .intelligence.deal_journal import build_deal_journal
        _dj = build_deal_journal(out)
        log.info("  Deal journal: %d deals (%d live, %d linked)",
                 _dj.get("deals_count", 0), _dj.get("live_count", 0), _dj.get("linked_count", 0))
    except Exception as e:
        log.warning("  Deal journal skipped: %s", e)

    log.info("  Scored %d new predictions (total tracked: %d)",
             len(new_unique), len(all_outcomes))
    if scoring_summary.get("best_agent"):
        b = scoring_summary["best_agent"]
        log.info("  Best agent: %s (win rate %.1f%%, EV %+.2f%%)",
                 b["agent"], (b["win_rate"] or 0) * 100, b["expected_value"] or 0)

    # ── ALPHA 2.0: Post-debate learning update ──────────────────
    # Update beliefs, evolution cards, drift state, counterfactuals,
    # time-of-day buckets, correlation matrix, persistence health.
    _post_debate_learning(
        learning_bundle,
        debate_dicts=debate_dicts,
        portfolios=portfolios,
        new_outcome_dicts=new_unique,
        contexts=contexts,
        today_iso=today_iso,
    )

    # ── Phase E: hard risk engine ───────────────────────────────
    # Use the prior_* state we loaded above as the basis; evaluate;
    # save updated state to disk
    agent_risk, system_risk = prior_agent_risk, prior_system_risk

    # Build a quick lookup of weight multipliers from scoring
    weight_lookup: Dict[str, float] = {}
    calls_lookup: Dict[str, int] = {}
    for r in scoring_summary.get("leaderboard", []):
        weight_lookup[r["agent"]] = r.get("weight_multiplier") or 1.0
        calls_lookup[r["agent"]] = r.get("scored_calls") or 0

    # Evaluate per-agent risk (use $10K career portfolio equity as the metric)
    main_agent_returns: List[float] = []
    for agent_name, p in portfolios.items():
        mark = None
        if p.current_position:
            mark = prices.get(p.current_position["ticker"])
        equity = p.total_equity(mark)

        risk_state = agent_risk.get(agent_name) or AgentRiskState(agent=agent_name)
        risk_state, log_msg = evaluate_agent_risk(
            risk_state,
            current_equity=equity,
            weight_multiplier=weight_lookup.get(agent_name),
            scored_calls=calls_lookup.get(agent_name, 0),
            today_iso=today_iso,
        )
        agent_risk[agent_name] = risk_state
        if log_msg:
            log.info("  %s", log_msg)

        ret_pct = ((equity / 10_000.0) - 1) * 100
        main_agent_returns.append(ret_pct)

    # System-wide cohort kill switch
    system_risk, sys_log = evaluate_cohort_risk(
        system_risk, main_agent_returns, today_iso,
    )
    if sys_log:
        log.warning("  ⚠ %s", sys_log)

    save_risk_state(risk_path, agent_risk, system_risk, DEFAULT_CONFIG)

    frozen = [n for n, s in agent_risk.items() if s.frozen]
    if frozen:
        log.info("  Frozen agents: %s", ", ".join(frozen))
    if system_risk.safe_mode:
        log.warning("  ⚠ SYSTEM IN SAFE MODE: %s", system_risk.safe_mode_reason)

    # ── Risk-filter the trade plans ─────────────────────────────
    plans_kept, plans_rejected = filter_plans_by_risk(plans)
    if plans_rejected:
        log.info("  %d plans rejected by risk engine", len(plans_rejected))

    # ── ALPHA 3.2: Three-month downtrend gate ───────────────────
    # Block BUY/STRONG_BUY plans on names with a 3-month return worse
    # than -5%, UNLESS the consensus is STRONG_BUY with conviction
    # ≥0.55 AND a strong catalyst is present. The Airbnb-style trade
    # ("dying stock with no catalyst, others using us for exit
    # liquidity") gets vetoed visibly with a structured reason that
    # flows into the decision_ledger and onto the dashboard.
    try:
        from .portfolios.three_month_filter import filter_plans_by_trend as _trend_filter
        from .portfolios.explainability import log_rejection as _log_rej
        # Build a ticker→debate-dict map and use the contexts list (already
        # has price_history attached) as the per-ticker lookup.
        _debates_by_ticker = {d["ticker"].upper(): d for d in debate_dicts}
        _contexts_by_ticker = {c.ticker.upper(): c for c in contexts}
        # Pre-build a lightweight catalysts-by-ticker index from the
        # catalysts.json file if it already exists from a prior cycle.
        _cat_idx: Dict[str, List[str]] = {}
        try:
            _cat_path = out / "catalysts.json"
            if _cat_path.exists():
                _raw = json.loads(_cat_path.read_text())
                for _it in ((_raw.get("daily") or []) + (_raw.get("weekly") or [])
                            or _raw.get("catalysts") or _raw.get("items") or []):
                    if not isinstance(_it, dict): continue
                    _tickers = _it.get("tickers") or (
                        [_it["ticker"]] if _it.get("ticker") else [])
                    _title = _it.get("title") or _it.get("headline") or _it.get("note") or ""
                    if not _title: continue
                    for _t in _tickers:
                        if _t:
                            _cat_idx.setdefault(str(_t).upper(), []).append(str(_title))
        except Exception:
            _cat_idx = {}

        plans_kept, _trend_rejected = _trend_filter(
            plans_kept,
            debates_by_ticker=_debates_by_ticker,
            contexts_by_ticker=_contexts_by_ticker,
            catalysts_by_ticker=_cat_idx,
        )
        for _rej in _trend_rejected:
            try:
                _log_rej(out, ticker=_rej.get("ticker", "?"),
                         reason=_rej.get("rejected_reason") or "3m downtrend",
                         category="rejected_by_three_month",
                         detail={
                             "consensus_signal":    _rej.get("consensus_signal"),
                             "conviction":          _rej.get("consensus_conviction"),
                             "three_month_return":  _rej.get("three_month_return"),
                             "catalyst_strength":   _rej.get("catalyst_strength"),
                         })
            except Exception:
                pass
        plans_rejected.extend(_trend_rejected)
        if _trend_rejected:
            log.info("  %d plans rejected by 3-month downtrend filter",
                     len(_trend_rejected))
    except Exception as _3m_e:
        log.warning("three_month_filter skipped: %s", _3m_e)

    # ── Catalysts roundup (with portfolio context for noise filtering) ──
    # Built here, AFTER plans_kept and portfolios are populated, so we can
    # pass the relevant ticker set. The aggregator uses this to filter the
    # 1,500-event firehose down to ~80 events that actually affect us.
    relevant_tickers = set()
    for _agent_p in portfolios.values():
        if getattr(_agent_p, "current_position", None):
            t = _agent_p.current_position.get("ticker")
            if t: relevant_tickers.add(t.upper())
    for _plan in plans_kept[:12]:
        t = _plan.get("ticker")
        if t: relevant_tickers.add(t.upper())
    write_catalysts_json(out / "catalysts.json", today_iso, relevant_tickers=relevant_tickers)

    # ── ALPHA 3.0: Multi-account Alpaca paper-trading bridge ────
    # Runs every configured account in sequence: LEGACY (existing),
    # HARVEST_3 (3% target, new), HARVEST_5 (5% target, new).
    # Accounts without env-var secrets are silently skipped.
    #
    # alpaca_state retains the LEGACY account's result so existing
    # run_health / dashboard consumers keep working unchanged. The new
    # harvest_accounts.json rollup gives the dashboard everything.
    alpaca_state: Dict[str, Any] = {
        "enabled": False,
        "reason": "Alpaca bridge not attempted (no _HAS_ALPACA flag)",
        "account": {},
        "errors": [],
    }
    multi_account_results: Dict[str, Dict[str, Any]] = {}
    if _HAS_ALPACA:
        try:
            # Adapt plan dicts to what alpaca_paper expects
            alpaca_plans = []
            for p in plans_kept:
                ticker = p.get("ticker", "")
                d = next((x for x in debate_dicts if x["ticker"] == ticker), None)
                if not d:
                    continue
                cons = d.get("consensus") or {}
                alpaca_plans.append({
                    "ticker": ticker,
                    "consensus_signal": cons.get("signal", "HOLD"),
                    "consensus_conviction": float(cons.get("avg_conviction", 0) or 0),
                    "entry_price": p.get("entry") or p.get("entry_price"),
                    "price": d.get("price"),
                    "asset_class": p.get("asset_class") or d.get("asset_class") or "equity",
                })
            # ── Alpha 3.3: compute the binding ExecutionPolicy BEFORE
            # running accounts. The policy reads market_state, profit_at_risk,
            # urgency, elite_mode, preservation_intelligence, etc. — and
            # decides halt_opens, force_close, elite_tickers, conviction
            # floors, trail tightness, sizing multipliers, sweep aggression.
            # The executor inside alpaca_paper.py now consumes this directly.
            _policy: Dict[str, Any] = {}
            _alloc_by_account: Optional[Dict[str, List[Dict[str, Any]]]] = None
            _sector_lookup = {c.ticker.upper(): (c.sector or "Unknown") for c in contexts}
            _contexts_lookup = {c.ticker.upper(): c for c in contexts}
            # Pull VIX/regime from the first context (canonical source —
            # same pattern _macro_brief uses).
            _vix = None
            _regime = None
            try:
                if contexts:
                    _vix = getattr(contexts[0], "vix", None)
                    _regime = getattr(contexts[0], "market_regime", None)
            except Exception:
                pass
            try:
                # Pre-emit market_state so the policy router can read it.
                from .portfolios.market_state import write_market_state as _write_ms
                _ms_payload = _write_ms(out, vix=_vix, regime=_regime)
            except Exception as _ms_pre_e:
                log.warning("market_state pre-write failed: %s", _ms_pre_e)
                _ms_payload = {}
            try:
                # Pre-emit profit_at_risk for currently-tracked positions
                # (best-effort; the cycle hasn't run yet, so we use the
                # position_meta from the prior cycle's state files).
                from .portfolios.profit_protection import write_profit_at_risk as _write_par_pre
                _positions_by_owner_pre: Dict[str, List[Dict[str, Any]]] = {}
                for _aid in ("LEGACY", "HARVEST_3", "HARVEST_5"):
                    _state_path = out / {"LEGACY": "alpaca_paper_state.json",
                                          "HARVEST_3": "alpaca_h3_state.json",
                                          "HARVEST_5": "alpaca_h5_state.json"}[_aid]
                    if not _state_path.exists():
                        continue
                    try:
                        _body = json.loads(_state_path.read_text())
                    except Exception:
                        continue
                    _meta = _body.get("position_meta") or {}
                    _positions_by_owner_pre[_aid] = [
                        {"symbol": _sym, "qty": _m.get("qty", 0),
                         "current_price": _m.get("entry_price"),
                         "avg_entry_price": _m.get("entry_price"),
                         "peak_price": _m.get("peak_price"),
                         "unrealized_pl": 0.0, "unrealized_plpc": 0.0,
                         "market_value": (_m.get("entry_price") or 0)
                                          * (_m.get("qty") or 0)}
                        for _sym, _m in (_meta.items() if isinstance(_meta, dict) else [])
                    ]
                _write_par_pre(out, _positions_by_owner_pre,
                               contexts_by_ticker=_contexts_lookup, vix=_vix)
            except Exception as _par_pre_e:
                log.warning("profit_at_risk pre-write failed: %s", _par_pre_e)
            try:
                from .portfolios.policy_router import compute_policy as _compute_pol
                _policy = _compute_pol(
                    data_dir=out,
                    plans=alpaca_plans,
                    multi_account_results={},   # not run yet
                    contexts_by_ticker=_contexts_lookup,
                    market_state=_ms_payload,
                )
                log.info("  Alpha 3.3 policy: %s winner=%s halt_opens=%s "
                         "elite=%s force_close=%d",
                         _policy.get("market_mode"),
                         _policy.get("winner_engine"),
                         _policy.get("halt_opens"),
                         _policy.get("elite_tickers"),
                         len(_policy.get("force_close") or {}))
            except Exception as _pr_e:
                log.warning("policy_router failed: %s", _pr_e)
                _policy = {}

            # ── Alpha 3.3: global allocator routes plans → accounts ──
            try:
                from .portfolios.global_allocator import (
                    allocate_plans_to_accounts as _alloc,
                    write_global_allocation as _write_alloc,
                )
                # Only consider accounts that have creds (others are skipped).
                from .execution.multi_account import HARVEST_ACCOUNTS as _HA
                import os as _os
                _enabled = [c.account_id for c in _HA
                            if _os.environ.get(c.env_key_var, "").strip()
                            and _os.environ.get(c.env_secret_var, "").strip()]
                if _enabled:
                    _allocation = _alloc(
                        alpaca_plans, _enabled,
                        elite_tickers=_policy.get("elite_tickers") or [],
                        urgency_priority_order=_policy.get("urgency_priority_order") or [],
                    )
                    _alloc_by_account = _allocation.get("by_account") or {}
                    _write_alloc(out, _allocation)
                    log.info("  Alpha 3.3 global allocator: %d assignments, %d unassigned",
                             len(_allocation.get("assignments") or []),
                             len(_allocation.get("unassigned") or []))
            except Exception as _ga_e:
                log.warning("global_allocator failed: %s", _ga_e)

            # ── ALPHA 6.0: pre-cycle hook — refresh hard_stops,
            # order_quality, correlation_book BEFORE the executor reads
            # them via multi_account.py's policy injection. ───────────
            try:
                from .alpha60 import run_alpha60_pre_cycle as _a60_pre
                _a60_pre_report = _a60_pre(
                    out, multi_account_results={},
                    contexts=contexts,
                    plans=alpaca_plans,
                    sector_lookup=_sector_lookup,
                )
                log.info("  Alpha 6.0 pre-cycle: ran=%s halted=%s safe_mode=%s",
                         _a60_pre_report.get("ran", []),
                         (_a60_pre_report.get("hard_stops_summary") or {})
                            .get("accounts_halted", []),
                         (_a60_pre_report.get("hard_stops_summary") or {})
                            .get("cohort_safe_mode", False))
            except Exception as _a60e:
                log.warning("alpha60 pre-cycle failed: %s", _a60e)

            try:
                from .execution.multi_account import run_all_harvest_accounts
                multi_account_results = run_all_harvest_accounts(
                    plans=alpaca_plans,
                    out_dir=out,
                    all_debate_signals={
                        d["ticker"]: (d.get("consensus") or {}).get("signal", "HOLD")
                        for d in debate_dicts
                    },
                    policy=_policy,
                    plans_by_account=_alloc_by_account,
                    contexts_by_ticker=_contexts_lookup,
                    sector_lookup=_sector_lookup,
                )
            except Exception as _orch_e:
                log.warning("multi-account orchestrator failed: %s", _orch_e)
                multi_account_results = {}

            # Keep LEGACY result as the canonical alpaca_state for back-compat
            legacy = multi_account_results.get("LEGACY")
            if legacy:
                alpaca_state = legacy

            if alpaca_state.get("enabled"):
                eq = alpaca_state.get("account", {}).get("equity")
                n_orders = len(alpaca_state.get("orders_placed", []))
                log.info("  Alpaca LEGACY: equity=$%s, orders=%d", eq, n_orders)
            for _aid, _astate in multi_account_results.items():
                if _aid == "LEGACY": continue
                if _astate.get("enabled"):
                    _eq = _astate.get("account", {}).get("equity")
                    log.info("  Alpaca %s: equity=$%s", _aid, _eq)
                else:
                    log.info("  Alpaca %s: skipped — %s", _aid,
                             _astate.get("reason", "")[:80])
        except Exception as e:
            import traceback as _tb
            tb_short = "".join(_tb.format_exception_only(type(e), e)).strip()
            log.warning("alpaca: bridge failed: %s", e)
            alpaca_state = {
                "enabled": False,
                "reason": f"Bridge raised exception: {tb_short}",
                "account": {}, "errors": [{
                    "time": datetime.now(timezone.utc).isoformat(),
                    "msg": tb_short,
                }],
                "exception_type": type(e).__name__,
            }
            try:
                _err_path = out / "alpaca_paper_state.json"
                _existing = {}
                if _err_path.exists():
                    try: _existing = json.loads(_err_path.read_text())
                    except Exception: _existing = {}
                _existing.update({
                    "enabled": False,
                    "reason": alpaca_state["reason"],
                    "errors": (_existing.get("errors", []) + alpaca_state["errors"])[-20:],
                    "last_run": datetime.now(timezone.utc).isoformat(),
                })
                _err_path.write_text(json.dumps(_existing, indent=2, default=str))
            except Exception:
                pass
    else:
        alpaca_state["reason"] = "alpaca_paper module not importable (_HAS_ALPACA=False)"

    # ── ALPHA 3.1: post-cycle protection sidecar ────────────────
    # Runs AFTER the multi-account cycle finished. Pure additive:
    # instant-sweep ($300/5%), retroactive stale-close (>=3d non-mover),
    # news-momentum escalation, big-winner closing-bell shield,
    # Friday/overnight danger-window liquidation, manual SWEEP switch.
    # During pre-market / after-hours sessions, orders are submitted as
    # limit + extended_hours so agents remain active in those windows.
    # If anything inside fails, the harvest rollup below still runs.
    try:
        from .portfolios.sweep_protection import apply_post_cycle_protections as _apply_sweep
        from .portfolios.market_clock import write_clock as _write_clock
        from .portfolios.bills_leaderboard_v2 import build_leaderboard_v2 as _bills_v2
        _apply_sweep(out, multi_account_results or {}, plans=alpaca_plans if _HAS_ALPACA else [])
        _write_clock(out)
    except Exception as _sp_e:
        log.warning("sweep_protection sidecar failed: %s", _sp_e)

    # ── ALPHA 3.2: adaptive intelligence sidecars ───────────────
    # Five sidecars publish JSON to docs/data/ for the dashboard:
    #   - market_state.json        : ATTACK/BALANCED/DEFENSIVE/PRESERVATION mode
    #   - conviction_ranking.json  : opportunity ranker + holdings review
    #   - profit_at_risk.json      : per-position vulnerability scorecard
    #   - operational_alerts.json  : missed_sweep / idle_cash / overnight_exposure
    #   - decision_ledger.json     : append-only "why we did/didn't act" log
    # All are advisory — they do not change orders. Any failure is
    # caught and logged; the rest of the run continues unaffected.
    #
    # Resolve vix/regime from the first context (canonical source in both
    # --live and --demo modes; matches the pattern used by _macro_brief).
    _vix = None
    _regime = None
    try:
        if contexts:
            _vix = getattr(contexts[0], "vix", None)
            _regime = getattr(contexts[0], "market_regime", None)
    except Exception:
        pass

    _market_state_payload: Dict[str, Any] = {}
    try:
        from .portfolios.market_state import write_market_state as _write_ms
        _market_state_payload = _write_ms(out, vix=_vix, regime=_regime)
        log.info("  Alpha 3.2 market_state: %s (%s)",
                 _market_state_payload.get("mode", "?"),
                 _market_state_payload.get("rationale", ""))
    except Exception as _ms_e:
        log.warning("market_state failed: %s", _ms_e)

    try:
        from .portfolios.conviction_engine import write_conviction_ranking as _write_cr
        _write_cr(out, plans_kept, multi_account_results or {})
    except Exception as _ce_e:
        log.warning("conviction_engine failed: %s", _ce_e)

    # Alpha 4.0: walk recent closes and write bucketed win-rate/expectancy
# for the empirical-lift consumers (conviction_engine, opportunity_urgency,
# parameter_tuning). Non-fatal on any failure.
    try:
        from .portfolios import signal_validation
        signal_validation.write_validation(out, lookback_days=60)
    except Exception as _sv_e:
        log.warning("signal_validation failed: %s", _sv_e)

    try:
        from .portfolios.profit_protection import write_profit_at_risk as _write_par
        # Gather positions from each account's state, fall back to position_meta
        _positions_by_owner: Dict[str, List[Dict[str, Any]]] = {}
        for _aid, _astate in (multi_account_results or {}).items():
            if not isinstance(_astate, dict) or not _astate.get("enabled"):
                continue
            _snap = _astate.get("positions_snapshot") or []
            if _snap:
                _positions_by_owner[_aid] = _snap
                continue
            _meta = _astate.get("position_meta") or {}
            _list = []
            for _sym, _m in (_meta.items() if isinstance(_meta, dict) else []):
                _list.append({
                    "symbol":         _sym,
                    "current_price":  _m.get("entry_price"),
                    "avg_entry_price": _m.get("entry_price"),
                    "peak_price":     _m.get("peak_price"),
                    "qty":            _m.get("qty", 0),
                    "unrealized_pl":  0.0,
                    "unrealized_plpc": 0.0,
                })
            _positions_by_owner[_aid] = _list
        _write_par(
            out, _positions_by_owner,
            contexts_by_ticker={c.ticker.upper(): c for c in contexts},
            vix=_vix,
        )
    except Exception as _par_e:
        log.warning("profit_protection failed: %s", _par_e)

    try:
        from .diagnostics.alerts import build_alerts as _build_alerts
        _build_alerts(out, multi_account_results or {},
                      market_state=_market_state_payload)
    except Exception as _al_e:
        log.warning("alerts builder failed: %s", _al_e)

    # ── ALPHA 5.0: deterministic narrative tracker + sector rotation ──
    # The master directive identifies catalyst interpretation as still
    # primitive. These two sidecars produce explainable, deterministic
    # narrative + sector-flow scores that downstream conviction and
    # policy engines can read on the NEXT cycle (additive — failures here
    # do not affect the current cycle's execution).
    _narrative_payload: Dict[str, Any] = {}
    _rotation_payload: Dict[str, Any] = {}
    try:
        from .portfolios.narrative_tracker import write_narrative_tracker as _write_nt
        # Catalysts: prefer the already-written catalysts.json sidecar; we
        # also pass `signals` (debate-level headlines) so the phrase counter
        # has the widest possible corpus.
        try:
            _cats_doc = json.loads((out / "catalysts.json").read_text())
            _cats_list = (_cats_doc.get("daily") or []) + (_cats_doc.get("weekly") or []) \
                or _cats_doc.get("catalysts") or _cats_doc.get("rows") or []
        except Exception:
            _cats_list = []
        _signals_for_nt = {"debates": debate_dicts}
        _narrative_payload = _write_nt(
            out, catalysts=_cats_list, signals=_signals_for_nt,
        )
        log.info("  Alpha 5.0 narrative_tracker: dominant=%s shift=%s conf=%.2f",
                 _narrative_payload.get("dominant_narrative") or "—",
                 _narrative_payload.get("regime_shift") or "NEUTRAL",
                 float(_narrative_payload.get("regime_shift_confidence") or 0.0))
    except Exception as _nt_e:
        log.warning("narrative_tracker failed: %s", _nt_e)

    try:
        from .portfolios.sector_rotation import write_sector_rotation as _write_sr
        _rotation_payload = _write_sr(
            out,
            narrative_payload=_narrative_payload,
            contexts_by_ticker={c.ticker.upper(): c for c in contexts},
            sector_lookup={c.ticker.upper(): (c.sector or "Unknown")
                            for c in contexts},
        )
        _strong = sum(1 for s in (_rotation_payload.get("sectors") or {}).values()
                       if s.get("flow_score", 0) >= 0.25)
        _weak = sum(1 for s in (_rotation_payload.get("sectors") or {}).values()
                     if s.get("flow_score", 0) <= -0.25)
        log.info("  Alpha 5.0 sector_rotation: %d strengthening / %d weakening · %s",
                 _strong, _weak,
                 _rotation_payload.get("rationale", "")[:80])
    except Exception as _sr_e:
        log.warning("sector_rotation failed: %s", _sr_e)

    # ── ALPHA 5.0: position health matrix (operator triage view) ────
    try:
        from .portfolios.position_health import build_position_health as _build_ph
        _ph_payload = _build_ph(
            out,
            multi_account_results=multi_account_results or {},
            sector_lookup={c.ticker.upper(): (c.sector or "Unknown")
                            for c in contexts},
        )
        _summary = _ph_payload.get("summary") or {}
        log.info("  Alpha 5.0 position_health: %d total · %d force-rotate · %d watch",
                 int(_summary.get("total_positions") or 0),
                 int(_summary.get("force_rotation") or 0),
                 int(_summary.get("watch") or 0))
    except Exception as _ph_e:
        log.warning("position_health failed: %s", _ph_e)

    # ── ALPHA 5.0: capital flow rollup (Sankey-ready) ───────────────
    try:
        from .portfolios.capital_flow import build_capital_flow as _build_cf
        _cf_payload = _build_cf(out, multi_account_results=multi_account_results or {})
        _totals = _cf_payload.get("totals") or {}
        log.info("  Alpha 5.0 capital_flow: deployed=$%.0f idle=$%.0f sgov=$%.0f harvest_today=$%.2f",
                 float(_totals.get("deployed_total") or 0.0),
                 float(_totals.get("idle_total") or 0.0),
                 float(_totals.get("sgov_vault_total") or 0.0),
                 float(_totals.get("harvested_today") or 0.0))
    except Exception as _cf_e:
        log.warning("capital_flow failed: %s", _cf_e)

    # ── ALPHA 5.0: learning transparency aggregator ────────────────
    # Makes "what is being learned" visible. Pure rollup — reads from
    # existing learning sidecars and writes one explainable summary.
    try:
        from .learning.transparency import build_learning_transparency as _build_lt
        _lt_payload = _build_lt(out)
        log.info("  Alpha 5.0 learning_transparency: %d highlights",
                 len(_lt_payload.get("highlights") or []))
    except Exception as _lt_e:
        log.warning("learning_transparency failed: %s", _lt_e)

    # ═════════════════════════════════════════════════════════════════
    # ALPHA 5.1 — PROFITABILITY ENGINEERING SIDECARS
    # ─────────────────────────────────────────────────────────────────
    # Order matters: deployment_floor before orchestrator before
    # benchmarking. Each invocation is wrapped in its own try/except —
    # a single failure never derails the cycle.
    # ═════════════════════════════════════════════════════════════════

    # 1. Deployment floor — account identity contract + harvest-only-overage rules.
    _deployment_floor_payload: Dict[str, Any] = {}
    try:
        from .portfolios.deployment_floor import build_deployment_floor as _build_df
        _deployment_floor_payload = _build_df(
            out, multi_account_results=multi_account_results or {})
        _summary = _deployment_floor_payload.get("summary") or {}
        log.info("  Alpha 5.1 deployment_floor: deployed_ratio=%.2f under=%d over_swept=%d",
                 float(_summary.get("system_deployed_ratio") or 0.0),
                 int(_summary.get("total_underdeployed") or 0),
                 int(_summary.get("total_over_swept") or 0))
    except Exception as _df_e:
        log.warning("deployment_floor failed: %s", _df_e)

    # 2. Setup classifier — tag every plan with an archetype.
    _setup_clf_payload: Dict[str, Any] = {}
    try:
        from .portfolios.setup_classifier import write_setup_classifications as _write_sc
        _setup_clf_payload = _write_sc(
            out, plans=plans,
            sector_rotation=_rotation_payload,
        )
        _totals = _setup_clf_payload.get("totals") or {}
        log.info("  Alpha 5.1 setup_classifier: %d classified · %d generic · %d elite",
                 int(_totals.get("classified") or 0),
                 int(_totals.get("generic") or 0),
                 int(_totals.get("elite") or 0))
    except Exception as _sc_e:
        log.warning("setup_classifier failed: %s", _sc_e)

    # 3. Regime memory — rolling 14-state persistence.
    try:
        from .portfolios.regime_memory import update_regime_memory as _upd_rm
        _rm_payload = _upd_rm(
            out,
            narrative=_narrative_payload,
            sector_rotation=_rotation_payload,
            market_state=_market_state_payload,
        )
        _summary = _rm_payload.get("summary") or {}
        log.info("  Alpha 5.1 regime_memory: dominant=%s · active=%d · stability=%.2f",
                 _summary.get("dominant_regime") or "—",
                 int(_summary.get("active_regimes") or 0),
                 float(_summary.get("stability_score") or 0.0))
    except Exception as _rm_e:
        log.warning("regime_memory failed: %s", _rm_e)

    # 4. Event impact — news → market/sector implications.
    try:
        from .portfolios.event_impact import build_event_impact as _build_ei
        _ei_payload = _build_ei(out, catalysts=_cats_list)
        _rollup = _ei_payload.get("rollup") or {}
        log.info("  Alpha 5.1 event_impact: %d events · net_risk_bias=%.2f · vol_pressure=%.2f",
                 int(_rollup.get("events_processed") or 0),
                 float(_rollup.get("net_risk_bias") or 0.0),
                 float(_rollup.get("volatility_pressure") or 0.0))
    except Exception as _ei_e:
        log.warning("event_impact failed: %s", _ei_e)

    # 5. Capital efficiency — active capital competition per position.
    try:
        from .portfolios.capital_efficiency import build_capital_efficiency as _build_ce
        _ce_payload = _build_ce(out,
                                   multi_account_results=multi_account_results or {})
        _summary = _ce_payload.get("summary") or {}
        log.info("  Alpha 5.1 capital_efficiency: deployment_eff=%.2f · stale_drag=%.2f · idle_drag=%.2f",
                 float(_summary.get("deployment_efficiency_score") or 0.0),
                 float(_summary.get("stale_holding_drag") or 0.0),
                 float(_summary.get("idle_capital_drag") or 0.0))
    except Exception as _ce_e:
        log.warning("capital_efficiency failed: %s", _ce_e)

    # 6. Portfolio orchestrator — central directive synthesis.
    try:
        from .portfolios.orchestrator import build_orchestrator as _build_orch
        _orch_payload = _build_orch(
            out,
            multi_account_results=multi_account_results or {},
            sector_lookup={c.ticker.upper(): (c.sector or "Unknown")
                            for c in contexts},
        )
        _directive = _orch_payload.get("directive") or {}
        log.info("  Alpha 5.1 orchestrator: objective=%s · posture=%s · target_exposure=%.2f",
                 _directive.get("system_objective_today") or "—",
                 _directive.get("posture") or "—",
                 float(_directive.get("target_market_exposure_pct") or 0.0))
    except Exception as _orch_e:
        log.warning("orchestrator failed: %s", _orch_e)

    # 7. Position manager — scaling / trimming / trailing directives.
    try:
        from .execution.position_manager import build_position_directives as _build_pd
        _pd_payload = _build_pd(
            out, multi_account_results=multi_account_results or {})
        _summary = _pd_payload.get("summary") or {}
        log.info("  Alpha 5.1 position_manager: %d directives · by_action=%s",
                 int(_summary.get("directives") or 0),
                 _summary.get("by_action") or {})
    except Exception as _pd_e:
        log.warning("position_manager failed: %s", _pd_e)

    # 8. Expectancy lab — setup × regime × sector empirical expectancy.
    try:
        from .learning.expectancy_lab import build_expectancy_lab as _build_el
        _el_payload = _build_el(out)
        _totals = _el_payload.get("totals") or {}
        log.info("  Alpha 5.1 expectancy_lab: %d trades indexed · %d combo buckets",
                 int(_totals.get("trades_indexed") or 0),
                 len(_el_payload.get("buckets") or {}))
    except Exception as _el_e:
        log.warning("expectancy_lab failed: %s", _el_e)

    # 9. Benchmarking — SPY / QQQ / XLE / XLK alpha + reality check.
    try:
        from .learning.benchmarking import build_benchmarking as _build_bm
        _bm_payload = _build_bm(
            out,
            contexts_by_ticker={c.ticker.upper(): c for c in contexts},
        )
        _windows = _bm_payload.get("windows") or {}
        _rolling = _bm_payload.get("rolling_metrics") or {}
        log.info("  Alpha 5.1 benchmarking: verdict=%s · win_rate=%.2f · profit_factor=%.2f",
                 _bm_payload.get("verdict") or "—",
                 float(_rolling.get("win_rate") or 0.0),
                 float(_rolling.get("profit_factor") or 0.0))
    except Exception as _bm_e:
        log.warning("benchmarking failed: %s", _bm_e)

    # 10. Failure attribution — 14-category loss classification.
    try:
        from .learning.failure_attribution import build_failure_attribution as _build_fa
        _fa_payload = _build_fa(out)
        _summary = _fa_payload.get("summary") or {}
        log.info("  Alpha 5.1 failure_attribution: %d classified · top failures: %s",
                 int(_summary.get("samples_classified") or 0),
                 [f["category"] for f in (_summary.get("top_failures") or [])[:3]])
    except Exception as _fa_e:
        log.warning("failure_attribution failed: %s", _fa_e)

    # ── Alpha 3.3: outcome-driven parameter tuning ───────────────
    # Walks the last 14 days of CLOSE orders across all account states,
    # attributes outcomes to the threshold that triggered them
    # (bleed_exit, etc.), and proposes bounded adjustments. The proposals
    # are persisted to docs/data/tuning_state.json; modules read them via
    # get_tuned_value() at the top of their relevant functions.
    try:
        from .learning.parameter_tuning import propose_adjustments as _propose
        _tuning = _propose(out, lookback_days=14)
        _total = _tuning.get("samples_total", 0)
        _props = len(_tuning.get("proposed") or {})
        if _props:
            log.info("  Alpha 3.3 parameter_tuning: %d proposed adjustments "
                     "from %d samples", _props, _total)
    except Exception as _pt_e:
        log.warning("parameter_tuning failed: %s", _pt_e)

    # ══════════════════════════════════════════════════════════════════
    # ALPHA 6.0 — POST-CYCLE WIRING + CROSS-AGENT LEARNING + AUDIT
    # Refreshes hard_stops, correlation_book, cross_agent_learning,
    # agent_evolution offspring proposal, and system_audit. Each runs
    # in its own try/except — none can derail the cycle.
    # ══════════════════════════════════════════════════════════════════
    try:
        from .alpha60 import run_alpha60_post_cycle as _a60_post
        _sector_lookup_post = {c.ticker.upper(): (c.sector or "Unknown")
                                for c in contexts}
        _a60_report = _a60_post(
            out,
            multi_account_results=multi_account_results or {},
            contexts=contexts,
            sector_lookup=_sector_lookup_post,
        )
        log.info("  Alpha 6.0 post-cycle: ran=%s offspring=%s audit=%s",
                 _a60_report.get("ran", []),
                 _a60_report.get("offspring_status", "?"),
                 (_a60_report.get("system_audit_summary") or {})
                    .get("overall_status", "?"))
        if _a60_report.get("errors"):
            for _err in _a60_report["errors"][:5]:
                log.warning("    alpha60 sub-error: %s", _err)
    except Exception as _a60e_post:
        log.warning("alpha60 post-cycle failed: %s", _a60e_post)

    # ── ALPHA 3.0: harvest accounts rollup + verified-harvest anchor ──
    try:
        from .portfolios import verified_harvest as _vh
        from .diagnostics.harvest_accounts_status import write_rollup as _write_rollup
        # 1) Anchor each enabled account's "equity above principal" into the
        #    verified-harvest ledger (status=ANCHOR). When SGOV auto-buy is
        #    wired in, additional rows will transition through to VERIFIED.
        _vault_recon: Dict[str, Dict[str, Any]] = {}
        for _aid, _astate in (multi_account_results or {}).items():
            if not isinstance(_astate, dict) or not _astate.get("enabled"):
                continue
            _eq = float((_astate.get("account") or {}).get("equity", 0) or 0)
            _pr = float(_astate.get("principal_target", 10000) or 0)
            try:
                _vh.anchor_account_savings(
                    data_dir=out, account_id=_aid,
                    equity=_eq, principal=_pr,
                    notes=f"Auto-anchor at cycle {datetime.now(timezone.utc).isoformat()}")
            except Exception as _ae:
                log.warning("verified_harvest anchor failed for %s: %s", _aid, _ae)
            # 2) Live vault reconciliation (SGOV holdings if present)
            try:
                _vault_recon[_aid] = _vh.reconcile_with_live_vault(
                    data_dir=out, account_id=_aid,
                    savings_vault=_astate.get("savings_vault"))
            except Exception as _re:
                log.warning("vault reconcile failed for %s: %s", _aid, _re)
        # 3) Write the rollup the dashboard reads
        _write_rollup(
            data_dir=out,
            multi_account_results=multi_account_results or {"LEGACY": alpaca_state},
            verified_harvest_summary=_vh.summary_by_account(out),
            vault_reconciliation=_vault_recon,
        )
    except Exception as _hr_e:
        log.warning("harvest_accounts rollup failed: %s", _hr_e)

    # ── ALPHA 3.1: corrected per-account Bills Paid Leaderboard ─
    # Sources truth from harvest_accounts.json + verified_harvest_ledger.json
    # so the bills bars only reflect VERIFIED SGOV cash (not at-risk paper).
    try:
        from .portfolios.bills_leaderboard_v2 import build_leaderboard_v2 as _bills_v2
        _bills_v2(out)
    except Exception as _bv2_e:
        log.warning("bills_paid_leaderboard_v2 failed: %s", _bv2_e)

    # ── ALPHA 3.0: position-pruning advisory (per-agent learnable knob) ──
    try:
        from .portfolios import staleness as _stale
        # Build positions_by_owner across (a) the legacy + new Alpaca
        # accounts and (b) every $10K agent portfolio.
        _positions_by_owner: Dict[str, List[Dict[str, Any]]] = {}
        # Alpaca accounts: take position_meta keys + current price into rows
        for _aid, _astate in (multi_account_results or {}).items():
            if not isinstance(_astate, dict) or not _astate.get("enabled"):
                continue
            _meta = _astate.get("position_meta") or {}
            _rows = []
            for _sym, _m in _meta.items():
                _rows.append({
                    "ticker": _sym,
                    "entry_price": _m.get("entry_price"),
                    "current_price": prices.get(_sym),
                    "peak_price": _m.get("peak_price"),
                    "entry_date": (_m.get("first_seen") or "")[:10],
                    "qty": _m.get("qty"),
                    "price_snapshots": _m.get("price_snapshots") or [],
                })
            if _rows:
                _positions_by_owner[_aid] = _rows
        # Agent portfolios
        for _agent_name, _p in (portfolios or {}).items():
            _pos = getattr(_p, "current_position", None)
            if _pos and _pos.get("ticker"):
                _positions_by_owner[_agent_name] = [{
                    "ticker": _pos.get("ticker"),
                    "entry_price": _pos.get("entry_price"),
                    "current_price": prices.get(_pos.get("ticker")),
                    "peak_price": _pos.get("peak_price"),
                    "entry_date": _pos.get("entry_date"),
                    "qty": _pos.get("qty"),
                    "price_snapshots": _pos.get("price_snapshots") or [],
                }]
        # Ensure every owner has a default aggression knob, then write advisory
        _owners = list(_positions_by_owner.keys())
        _aggr = _stale.ensure_aggression_for(out, _owners) if _owners else {}
        _stale.write_advisory(
            data_dir=out,
            positions_by_owner=_positions_by_owner,
            aggression_params=_aggr,
            today_iso=today_iso,
        )
    except Exception as _se:
        log.warning("staleness advisory failed: %s", _se)

 
    # ── Alpha 2.2: Attribution tagging ──────────────────────────
    try:
        from .execution.attribution import tag_orders
        _orders_placed = (alpaca_state or {}).get("orders_placed", [])
        if _orders_placed:
            tag_orders(
                orders_placed=_orders_placed,
                debate_dicts=debate_dicts,
                attribution_path=out / "alpaca_attribution.json",
            )
    except Exception as _attr_e:
        log.debug("attribution tagging skipped: %s", _attr_e)

    # ── ALPHA 6.3 (P1): canonical Trade Case Files ──────────────
    # Projection/join over the per-cycle emitters above (health, advisory,
    # attribution, harvest, ledger, plans, conviction, regime, narrative,
    # catalysts). Produces ONE forensic record per (account_id, ticker) and
    # carries entry-time reasoning forward across cycles. Single source of
    # truth for the trade card UI. NOT a parallel telemetry pipeline.
    try:
        from .trade_engine.case_file import build_case_files as _build_cases
        _cases_payload = _build_cases(out, debate_dicts=debate_dicts)
        log.info("  Alpha 6.3 case files: %d trades (%d open, %d planned, "
                 "%d w/harvest)",
                 _cases_payload.get("summary", {}).get("total", 0),
                 _cases_payload.get("summary", {}).get("open", 0),
                 _cases_payload.get("summary", {}).get("planned", 0),
                 _cases_payload.get("summary", {}).get("with_realized_harvest", 0))
    except Exception as _cf_e:
        log.warning("case_file build failed: %s", _cf_e)

    # ── Anti-drift sentinel — runs LAST so it can read every sidecar's
    # output. Read-only: asserts invariants (baseline=$10k, narrative fed,
    # accounts active, stale bounded, order hygiene, …) and logs drift over
    # time. Guarded so it can never break a cycle.
    try:
        from .diagnostics.drift_sentinel import build_sentinel as _build_sentinel
        _sentinel = _build_sentinel(out)
        log.info("  Drift sentinel: %s (overall=%s)",
                 _sentinel.get("summary"), _sentinel.get("overall"))
        for _c in _sentinel.get("invariants", []):
            if _c.get("status") in ("warn", "fail"):
                log.warning("  Drift %s: %s — %s", _c["status"].upper(),
                            _c["name"], _c["detail"])
    except Exception as _ds_e:  # noqa: BLE001
        log.warning("drift_sentinel failed: %s", _ds_e)

    # ── Handoff Blocks ──────────────────────────────────────────

    # ── Handoff Blocks ──────────────────────────────────────────
    per_asset_handoffs = {
        d["ticker"]: build_asset_deep_dive(_attach_headlines(d, contexts))
        for d in debate_dicts
    }

    per_plan_handoffs = {
        p["plan_id"]: build_trade_plan_handoff(p)
        for p in plans_kept
    }

    # Regime/VIX from the first context (all have the same macro)
    first = contexts[0]
    # Build per-specialist narratives (lightweight wrappers for each)
    def _agent_narrative(name, state, role):
        """Build a generic narrative handoff block for any agent state dict."""
        from .handoff.deeplinks import build_handoffs
        balance = state.get('balance', 0) if state else 0
        history = (state or {}).get('history', [])
        recent_trades = '\n'.join([
            f"  - {h.get('date', '?')}: {h.get('action', '?')} {h.get('ticker', h.get('market', '?'))}"
            for h in history[-5:]
        ]) or '  (no recent trades)'
        text = f"""You are reviewing the trading record of {name}, a SILMARIL specialist agent.

Role: {role}
Current balance: ${balance}
Lifetime trades: {len(history)}
Most recent activity:
{recent_trades}

Stress-test {name}'s recent decisions. Are they consistent with their stated philosophy?
Where would you push back? What blind spots might {name} have given the current market regime?
Reply concisely.
"""
        return {
            "title": f"{name} Stress Test",
            "context_text": text,
            "handoffs": build_handoffs(text),
        }

    # Build macro brief from market regime
    def _macro_brief():
        from .handoff.deeplinks import build_handoffs
        vix_str = f"{first.vix:.1f}" if first.vix is not None else "n/a"
        regime_str = first.market_regime if first.market_regime else "UNKNOWN"
        text = f"""SILMARIL Daily Macro Brief

Market regime: {regime_str}
VIX: {vix_str}
Total assets tracked: {len(contexts)}
Total debates resolved: {len(debate_dicts)}
Trade plans surviving risk filter: {len(plans_kept)}

Synthesize the macro picture for an investor reviewing this dashboard.
What are the 2-3 most important things they should know about today's tape?
What sectors or asset classes are showing the highest agreement among the agents?
What's being avoided?
Reply in 3-5 bullets, no preamble.
"""
        return {
            "title": "Macro Brief",
            "context_text": text,
            "handoffs": build_handoffs(text),
        }

    handoff_blocks = {
        "debate_summary": build_debate_summary(
            debate_dicts, market_regime=first.market_regime, vix=first.vix
        ),
        "scrooge_narrative": build_scrooge_narrative(scrooge_dict),
        "midas_narrative": _agent_narrative("MIDAS", midas_dict, "Hard-currency compounder · 7-day cycle · trades only FXE/FXY/FXF/UUP/GLD"),
        "cryptobro_narrative": _agent_narrative("CRYPTOBRO", cryptobro_dict, "Multi-trade crypto compounder · 5/day cap · highest volatility tolerance"),
        "jrr_token_narrative": _agent_narrative("JRR_TOKEN", jrr_token_dict, "Two-tier token trader · 6/day per tier · sub-$100M and over-$100M coins"),
        "sports_bro_narrative": _agent_narrative("SPORTS_BRO", sports_bro_dict, "Prediction-market bettor · half-Kelly · Polymarket + Kalshi only · never sportsbooks"),
        "baron_narrative": _agent_narrative("BARON", (portfolios.get("BARON").to_dict() if portfolios.get("BARON") else {}), "Oil & energy specialist · long/short · 2/day max · EIA Wednesday catalyst-aware"),
        "steadfast_narrative": _agent_narrative("STEADFAST", (portfolios.get("STEADFAST").to_dict() if portfolios.get("STEADFAST") else {}), "American blue-chip patriot · Crown Jewels universe · 30-day minimum hold"),
        "macro_brief": _macro_brief(),
        "per_asset": per_asset_handoffs,
        "per_plan": per_plan_handoffs,
    }

    # ── Agent roster for UI (with full bios) ────────────────────
    agent_roster = []
    for a in AGENTS:
        bio = get_bio(a.codename)
        roster_entry = {
            "codename": a.codename,
            "specialty": a.specialty,
            "temperament": a.temperament,
            "inspiration": getattr(a, "inspiration", ""),
            "bio": bio,
        }
        # Include display label from rename map if available
        if _HAS_RENAME_MAP:
            try:
                roster_entry["display_label"] = display_label(a.codename)
            except Exception:
                pass
        agent_roster.append(roster_entry)

    # ── Main output ─────────────────────────────────────────────
    signals_output = {
        "meta": {
            "version": "2.2.0",
            "project": "SILMARIL",
            "run_type": mode,
            "generated_at": now.isoformat(),
            "alpha_2_0_features": {
                "learning_loop": _HAS_LEARNING,
                "alpaca_paper": _HAS_ALPACA,
                "rename_map": _HAS_RENAME_MAP,
                "contrarian_agent": _HAS_CONTRARIAN,
                "short_alpha_agent": _HAS_SHORT_ALPHA,
            },
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
        "candidate_summary": extract_candidate_summary(debate_dicts) if _HAS_SENATE else {},
        "senate_enabled": _HAS_SENATE,
    }

    _write(out / "signals.json", signals_output)

    # Decorate each kept plan with broker deeplinks BEFORE writing
    for p in plans_kept:
        p["brokers"] = build_broker_links(
            p.get("ticker", ""),
            p.get("asset_class", "equity"),
        )

    _write(out / "trade_plans.json", {
        "meta": signals_output["meta"],
        "plans": plans_kept,
        "rejected": plans_rejected,
        "risk_filter_applied": True,
    })

    # ── Heartbeat: ensure every compounder shows TODAY's activity ────
    # Even when the daily-gate fires (Scrooge already acted today, JRR cap hit,
    # SportsBro has an open bet) the compounder dict was missing any 'today'
    # history entry — making the dashboard look frozen across multiple runs.
    # Insert a HEARTBEAT entry once per compounder per day so the trade
    # history shows the user "yes, this strategist is alive and was checked
    # this run; here's why it didn't trade." Idempotent: subsequent runs the
    # same day update the existing HEARTBEAT's last_check_at instead of
    # appending a new one, so we don't bloat history.json.
    _today_iso = today_iso
    _now_iso   = now.isoformat()
    def _ensure_heartbeat(d: Dict[str, Any], reason: str) -> None:
        if not isinstance(d, dict): return
        history = d.get("history") or []
        # Walk back recent entries: did we ALREADY act today? If yes, skip.
        for h in reversed(history[-20:]):
            if h.get("date") != _today_iso:
                break
            if h.get("action") in ("BUY", "SELL", "BET", "OPEN", "CLOSE",
                                   "SETTLE", "CLOSE_BET", "CAPITAL_RESET",
                                   "REINCARNATION", "MIGRATION"):
                return  # real action today; no heartbeat needed
        # Update existing heartbeat from today, or append a new one.
        for h in reversed(history):
            if h.get("date") == _today_iso and h.get("action") == "HEARTBEAT":
                h["last_check_at"] = _now_iso
                h["check_count"]   = int(h.get("check_count", 1)) + 1
                h["reason"]        = reason
                d["history"]       = history
                return
        history.append({
            "date":          _today_iso,
            "timestamp":     _now_iso,
            "last_check_at": _now_iso,
            "action":        "HEARTBEAT",
            "reason":        reason,
            "check_count":   1,
        })
        d["history"] = history

    # Per-compounder reason logic — explain WHY no trade fired today.
    if isinstance(scrooge_dict, dict):
        _r = ("Already rotated today — HODLing position." if scrooge_dict.get("last_action_date") == _today_iso
              else "No qualifying signal in scope this cycle.")
        _ensure_heartbeat(scrooge_dict, _r)
    if isinstance(midas_dict, dict):
        _r = ("Already rotated today — HODLing hard-currency basket." if midas_dict.get("last_action_date") == _today_iso
              else "No FX/precious-metals signal cleared the floor.")
        _ensure_heartbeat(midas_dict, _r)
    if isinstance(cryptobro_dict, dict):
        _trades_today = cryptobro_dict.get("trades_today", 0)
        _cap = cryptobro_dict.get("max_trades_per_day", 5)
        _r = (f"Daily cap hit ({_trades_today}/{_cap}) — HODLing." if _trades_today >= _cap
              else "No qualifying crypto signal this cycle.")
        _ensure_heartbeat(cryptobro_dict, _r)
    if isinstance(jrr_token_dict, dict):
        _ensure_heartbeat(jrr_token_dict, "No qualifying token signal in either tier this cycle.")
    if isinstance(sports_bro_dict, dict):
        _open = len(sports_bro_dict.get("open_bets") or [])
        _trades_today = sports_bro_dict.get("trades_today", 0)
        _cap = sports_bro_dict.get("max_trades_per_day", 8)
        if _open > 0:
            _r = f"{_open} open bet(s) awaiting resolution — no new bet placed."
        elif _trades_today >= _cap:
            _r = f"Daily bet cap hit ({_trades_today}/{_cap})."
        else:
            _r = "No prediction market with positive edge in 72h window."
        _ensure_heartbeat(sports_bro_dict, _r)

    _write(out / "scrooge.json", scrooge_dict)
    _write(out / "midas.json", midas_dict)
    _write(out / "cryptobro.json", cryptobro_dict)
    _write(out / "jrr_token.json", jrr_token_dict)
    _write(out / "sports_bro.json", sports_bro_dict)
    _write(out / "handoff_blocks.json", handoff_blocks)
 
    # ── Grocery harvest leaderboard ──────────────────────────────
    # ALPACA harvest is now anchored to REAL money, not an accumulator.
    # Previously we incremented a counter on every "harvest event" — but
    # the cash never actually left the trading book, so the leaderboard
    # showed lifetime $574 while Alpaca itself showed only ~$330 of real
    # gains. Now the trading book is capped at principal_target and any
    # equity above principal_target IS the savings, by definition.
    #
    # For agent portfolios (AEGIS, FORGE, etc.) we keep the additive
    # ledger model since each agent has its own self-contained $10K
    # book that genuinely accumulates harvested savings via mark-to-market.
    if _HAS_GROCERY:
        try:
            # 1) ALPACA: replace prior accumulator with real savings.
            # alpaca_state["realized_savings"] is computed in alpaca_paper.py
            # as max(0, equity - principal_target). Mirror that into the
            # ALPACA ledger so the dashboard reflects ground truth.
            if alpaca_state and alpaca_state.get("enabled"):
                _real_savings = float(alpaca_state.get("realized_savings", 0) or 0)
                _alp_ledger = load_ledger(out, "ALPACA", 10_000.0)
                # Set absolute lifetime, NOT add to it. The realized_savings
                # value is already the cumulative truth from Alpaca itself.
                _alp_ledger.set_lifetime(_real_savings,
                    reason=f"Equity ${alpaca_state.get('account', {}).get('equity', 0):,.2f} − "
                           f"principal ${alpaca_state.get('principal_target', 10000):,.2f}")
                save_ledger(out, _alp_ledger)
                # Drop any pending counter — it was the inflating quantity
                alpaca_state["grocery_pending_harvest"] = 0.0

            # 2) Per-agent portfolios: each $10K agent has its own book and
            # genuinely realizes savings via mark-to-market. Pull whatever
            # `savings_pending_grocery` they accumulated this cycle (set by
            # agent_portfolio.mark_to_market when a position closes in tier).
            for _agent_name, _p in (portfolios or {}).items():
                _pending = float(getattr(_p, "savings_pending_grocery", 0) or 0)
                if _pending > 0:
                    _agent_ledger = load_ledger(out, _agent_name, 10_000.0)
                    _agent_ledger.harvest(
                        _pending,
                        reason=f"{_agent_name} tiered harvest this cycle")
                    save_ledger(out, _agent_ledger)
                    _p.savings_pending_grocery = 0.0

            # 3) Build + write the leaderboard
            _leaderboard = build_leaderboard(out)
            _write(out / "grocery_leaderboard.json", _leaderboard)
            log.info(
                "grocery: leaderboard — %d harvesters, "
                "combined weekly $%.2f / $%.2f",
                len(_leaderboard.get("leaderboard", [])),
                _leaderboard.get("total_weekly_all", 0),
                WEEKLY_TARGET)
        except Exception as _g_e:
            log.warning("grocery leaderboard failed: %s", _g_e)

    # ── Rolling history (per-agent track record, accumulates each run) ─
    _append_history(out / "history.json", debate_dicts, plans, now)

    # Portfolio leaderboard for the log
    leaderboard = []
    for name, p in portfolios.items():
        mark = None
        if p.current_position:
            mark = prices.get(p.current_position["ticker"])
        equity = p.total_equity(mark)
        leaderboard.append((name, equity))
    leaderboard.sort(key=lambda r: r[1], reverse=True)

    log.info("✦ SILMARIL run complete")
    log.info("  %d debates resolved", len(debate_dicts))
    log.info("  %d trade plans (kept after risk filter; %d rejected)",
             len(plans_kept), len(plans_rejected))
    log.info("  SCROOGE:   $%.4f (life #%d)", scrooge_dict["balance"], scrooge_dict["current_life"])
    log.info("  MIDAS:     $%.4f (life #%d)", midas_dict["balance"], midas_dict["current_life"])
    log.info("  CRYPTOBRO: $%.4f (life #%d, %d trades today)",
             cryptobro_dict["balance"], cryptobro_dict["current_life"],
             cryptobro_dict.get("trades_today", 0))
    log.info("  JRR_TOKEN: $%.4f (life #%d, sub:$%.4f over:$%.4f)",
             jrr_token_dict["balance"], jrr_token_dict["current_life"],
             jrr_token_dict["tiers"]["sub_100m"]["balance"],
             jrr_token_dict["tiers"]["over_100m"]["balance"])
    if leaderboard:
        log.info("  Top agent portfolio: %s @ $%.2f", leaderboard[0][0], leaderboard[0][1])
    log.info("  Output: %s", out.resolve())

    # ── ALPHA 2.0: Final persistence sanity check ───────────────
    if _HAS_LEARNING:
        try:
            persistence_health = verify_persistence(out)
            log.info("  Learning state: %d/%d protected files present",
                     len(persistence_health["present"]), persistence_health["total_protected"])
        except Exception:
            pass

    # ── ALPHA 2.1: write run_health.json (single source of truth) ────
    # Captures: Alpaca account/equity/savings, last cycle activity,
    # catalyst source statuses, every agent's status today (silent or active),
    # and any issues. Read this ONE file to know if the system is healthy.
    try:
        from .diagnostics.run_health import write_run_health
        cat_diag = {}
        try:
            cat_path = out / "catalysts.json"
            if cat_path.exists():
                cat_payload = json.loads(cat_path.read_text())
                cat_diag = cat_payload.get("_diagnostic", {})
        except Exception:
            pass
        # alpaca_state is now ALWAYS bound (initialized at top of alpaca block,
        # populated by execute_consensus_signals or by the except branch with
        # the actual exception message). No more `'alpaca_state' in dir()` guard.
        write_run_health(
            out_dir=out,
            debate_dicts=debate_dicts,
            portfolios=portfolios if 'portfolios' in dir() else None,
            alpaca_state=alpaca_state,
            catalysts_diag=cat_diag,
            main_agents=main_agents if 'main_agents' in dir() else None,
            today_iso=today_iso,
        )
    except Exception as e:
        log.warning("run_health write failed: %s", e)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

# ALPHA 2.0: Recompute consensus from scaled verdicts after applying
# Thompson multipliers. We re-derive signal/score from the modified
# convictions without changing the existing Arbiter class.
_SIGNAL_SCORE = {
    "STRONG_BUY":  +2.0, "BUY":         +1.0,
    "HOLD":         0.0, "ABSTAIN":      0.0,
    "SELL":        -1.0, "STRONG_SELL": -2.0,
}


def _recompute_consensus_in_place(debate: dict) -> None:
    """After verdicts have had their conviction scaled, recompute the
    consensus block to reflect the new weighting. Conservative — only
    updates avg_conviction and consensus.score; preserves agreement_score
    and signal threshold logic from the existing arbiter."""
    verdicts = debate.get("verdicts", []) or []
    if not verdicts:
        return
    total = 0.0
    weight = 0.0
    n_directional = 0  # count only non-ABSTAIN, non-HOLD voters
    for v in verdicts:
        sig = v.get("signal", "HOLD")
        if sig == "ABSTAIN":
            continue
        s = _SIGNAL_SCORE.get(sig, 0.0)
        c = float(v.get("conviction", 0) or 0)
        total += s * c
        weight += c
        if sig not in ("HOLD", "ABSTAIN"):
            n_directional += 1
    if weight == 0:
        return
    avg_score = total / weight
    cons = debate.setdefault("consensus", {})
    cons["score"] = round(avg_score, 4)
    # FIX: divide by directional voters only — not all verdicts (which includes
    # every ABSTAIN agent and dilutes conviction from ~0.79 down to ~0.07).
    cons["avg_conviction"] = round(weight / max(1, n_directional), 4)
    # Keep the existing signal unless it crosses a major threshold
    # (we don't want to flip signal direction here — that's the arbiter's job)


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
            last_action_date=data.get("last_action_date", ""),
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
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return MidasState()


def _load_or_init_cryptobro(path: Path) -> CryptoBroState:
    if not path.exists():
        return CryptoBroState()
    try:
        with path.open() as f:
            data = json.load(f)
        return CryptoBroState(
            balance=data.get("balance", 1.0),
            current_position=data.get("current_position"),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            history=data.get("history", []),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return CryptoBroState()


def _load_or_init_jrr_token(path: Path) -> JRRTokenState:
    from .agents.jrr_token import TierState
    if not path.exists():
        return JRRTokenState()
    try:
        with path.open() as f:
            data = json.load(f)
        tiers = data.get("tiers", {})
        sub_data = tiers.get("sub_100m", {})
        over_data = tiers.get("over_100m", {})
        sub_history = sub_data.get("recent_history", [])
        over_history = over_data.get("recent_history", [])
        return JRRTokenState(
            sub_tier=TierState(
                name="SUB_100M",
                balance=sub_data.get("balance", 0.50),
                current_position=sub_data.get("current_position"),
                history=sub_history,
            ),
            over_tier=TierState(
                name="OVER_100M",
                balance=over_data.get("balance", 0.50),
                current_position=over_data.get("current_position"),
                history=over_history,
            ),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return JRRTokenState()


def _load_or_init_sports_bro(path: Path) -> SportsBroState:
    if not path.exists():
        return SportsBroState()
    try:
        with path.open() as f:
            data = json.load(f)
        return SportsBroState(
            balance=data.get("balance", 1.0),
            open_bets=data.get("open_bets", []),
            history=data.get("history", []),
            lifetime_peak=data.get("lifetime_peak", 1.0),
            current_life=data.get("current_life", 1),
            life_start_date=data.get("life_start_date", datetime.now(timezone.utc).date().isoformat()),
            deaths=data.get("deaths", []),
            trades_today=data.get("trades_today", 0),
            last_action_date=data.get("last_action_date", ""),
        )
    except Exception:
        return SportsBroState()


def _append_history(path: Path, debate_dicts, plans, now) -> None:
    """Append a compact per-run snapshot to history.json so agent track
    records accumulate across runs. Kept small (verdicts only — not full
    debate transcripts) to avoid unbounded file growth.

    ALPHA 2.0: Adds `timestamp` (full ISO datetime) alongside the
    date-only `date` field, so the dashboard can show real run times
    instead of always displaying 17:00.
    """
    today = now.date().isoformat()
    timestamp_iso = now.isoformat()  # ALPHA 2.0: real time
    snapshot = {
        "date": today,
        "timestamp": timestamp_iso,  # ALPHA 2.0
        "generated_at": timestamp_iso,
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
                "tags": d.get("tags", {}),
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
        json.dump(_sanitize_for_json(data), f, indent=2, default=str, allow_nan=False)


def _attach_headlines(debate: dict, contexts: List[AssetContext]) -> dict:
    for ctx in contexts:
        if ctx.ticker == debate["ticker"]:
            return {**debate, "recent_headlines": ctx.recent_headlines}
    return debate


# Realistic synthetic-headline pool for demo mode. In --live mode these
# come from RSS via news.py; demo mode needs them to demonstrate the UI.
_DEMO_HEADLINE_POOLS = {
    "Technology": [
        ("Tech earnings season frames AI capex debate", "Reuters"),
        ("Hyperscaler spending guide raised for 2026", "Bloomberg"),
        ("Semis sector breadth widens beyond top three names", "Barron's"),
        ("Cloud infrastructure outlook: revenue acceleration likely", "WSJ"),
    ],
    "Index": [
        ("Index breadth improves as small-caps participate", "Bloomberg"),
        ("Volatility compressed; range-bound trading continues", "Reuters"),
        ("Quarter-end rebalance flows expected this week", "WSJ"),
    ],
    "Crypto": [
        ("Spot ETF flows turn positive after week of outflows", "CoinDesk"),
        ("Layer-1 activity ticks higher on weekend volume", "The Block"),
        ("Stablecoin supply growth signals risk-on positioning", "Bloomberg"),
    ],
    "Commodities": [
        ("Gold holds near record on real-rate compression", "Bloomberg"),
        ("Central bank gold buying continues into Q2", "Reuters"),
        ("Silver industrial demand outlook lifts on solar growth", "WSJ"),
    ],
    "FX": [
        ("Dollar firms on hawkish Fed minutes language", "Reuters"),
        ("DXY consolidates as rate-cut expectations recede", "Bloomberg"),
    ],
    "Rates": [
        ("Long-duration bonds catch bid on duration buying", "Bloomberg"),
        ("Treasury auction demand exceeds expectations", "WSJ"),
    ],
    "Energy": [
        ("OPEC+ production discipline supports crude floor", "Reuters"),
        ("Refining margins expand into summer driving season", "Bloomberg"),
    ],
    "Discretionary": [
        ("Consumer credit data softens; discretionary at risk", "Bloomberg"),
        ("Retail same-store sales miss on weather effects", "WSJ"),
    ],
    "Financials": [
        ("Bank earnings highlight net-interest-margin pressure", "Reuters"),
        ("Loan-loss provisions tick higher in commercial real estate", "Bloomberg"),
    ],
}
_DEMO_HEADLINE_DEFAULT = [
    ("Markets digest mixed economic data ahead of catalysts", "Reuters"),
    ("Sector rotation continues; cross-asset correlations easing", "Bloomberg"),
]


def _backfill_demo_headlines(contexts: List[AssetContext]) -> None:
    """Mutate contexts so any ticker without headlines gets 2 plausible ones."""
    import random
    rng = random.Random(42)  # deterministic across runs
    for ctx in contexts:
        if ctx.recent_headlines:
            continue
        pool = _DEMO_HEADLINE_POOLS.get(ctx.sector, _DEMO_HEADLINE_DEFAULT)
        picks = rng.sample(pool, k=min(2, len(pool)))
        ctx.recent_headlines = [
            {"title": t, "source": s, "url": ""} for (t, s) in picks
        ]


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


def _sanitize_for_json(obj):
    """Recursively replace NaN, +Inf, -Inf with None so the resulting
    JSON is valid for browsers. JSON spec forbids these values; Python's
    default encoder writes them as 'NaN'/'Infinity' which JS cannot parse."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _write(path: Path, data) -> None:
    clean = _sanitize_for_json(data)
    with path.open("w") as f:
        json.dump(clean, f, indent=2, default=str, allow_nan=False)


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

