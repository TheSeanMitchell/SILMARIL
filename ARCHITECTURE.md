# SILMARIL — Architecture & Build State

This document describes what's currently implemented, what's architecturally scaffolded, and the roadmap to full production.

## Directory Layout

```
silmaril/
├── README.md                   ✓ built — public project story
├── ARCHITECTURE.md             ✓ this file
├── requirements.txt            ✓ built
├── .gitignore                  ✓ built
├── run_demo.py                 ✓ built — end-to-end demo runner
│
├── silmaril/                   Python package
│   ├── agents/
│   │   ├── base.py             ✓ built — Agent ABC, AssetContext, Verdict, Signal
│   │   ├── aegis.py            ✓ built — Capital Preservation (Cap archetype)
│   │   ├── forge.py            ✓ built — Tech Momentum (Iron Man archetype)
│   │   ├── scrooge.py          ✓ built — The $1 Compounder
│   │   ├── thunderhead.py      ○ scaffolded — Volatility Breakout (Thor)
│   │   ├── jade.py             ○ scaffolded — Oversold Reversion (Hulk)
│   │   ├── veil.py             ○ scaffolded — Sentiment Divergence (Widow)
│   │   ├── kestrel.py          ○ scaffolded — Precision Entry (Hawkeye)
│   │   ├── obsidian.py         ○ scaffolded — Commodities (Panther)
│   │   ├── zenith.py           ○ scaffolded — Long-duration Trend (Marvel)
│   │   ├── weaver.py           ○ scaffolded — Micro Scalper (Spider-Man)
│   │   ├── hex.py              ○ scaffolded — Probabilistic (Scarlet Witch)
│   │   ├── synth.py            ○ scaffolded — Cross-market (Vision)
│   │   ├── speck.py            ○ scaffolded — Small-cap (Ant-Man)
│   │   ├── vespa.py            ○ scaffolded — Event-driven (Wasp)
│   │   ├── magus.py            ○ scaffolded — Seasonality (Dr. Strange)
│   │   └── talon.py            ○ scaffolded — Market Structure (Falcon)
│   │
│   ├── debate/
│   │   └── arbiter.py          ✓ built — consensus + dissent + AEGIS veto
│   │
│   ├── handoff/
│   │   ├── blocks.py           ✓ built — pre-framed LLM prompts
│   │   └── deeplinks.py        ✓ built — ChatGPT/Claude/Gemini/Perplexity/Grok URLs
│   │
│   ├── trade_engine/
│   │   └── plans.py            ✓ built — full plans with entry/stop/target/R:R
│   │
│   ├── ingestion/              ✓ built — yfinance prices, Google News RSS, SEC EDGAR
│   ├── analytics/              ✓ built — technicals, sentiment, regime classifier
│   ├── universe/               ✓ built — ~100-ticker core universe across 8 asset classes
│   ├── risk_engine/            ○ to build — drawdown, regime filters
│   ├── leaderboard/            ○ to build — per-agent P&L tracking
│   └── output/                 ○ to build — JSON schema validation + writer
│
├── data/                       ✓ built — real output from demo run
│   ├── signals.json                — debates, consensus, dissent, verdicts
│   ├── trade_plans.json            — full plans with invalidation
│   ├── scrooge.json                — SCROOGE state
│   └── handoff_blocks.json         — pre-built LLM handoff contexts
│
├── docs/                       ✓ built — GitHub Pages site
│   └── index.html                  — the full dashboard, self-contained
│
└── .github/workflows/          ✓ built — daily.yml (post-close + weekend keepalive)
```

Legend:  ✓ built (working code)   ○ scaffolded (directory exists, implementation TBD)

---

## What works today

You can run `python -m silmaril --demo` and get a complete debate produced
by all 16 agents (AEGIS, FORGE, THUNDERHEAD, JADE, VEIL, KESTREL, OBSIDIAN,
ZENITH, WEAVER, HEX, SYNTH, SPECK, VESPA, MAGUS, TALON, and SCROOGE) over
realistic sample asset contexts. The output is real JSON in the exact
schema the frontend consumes. Opening `docs/index.html` in a browser
(with `docs/data/` containing the four JSON files) renders the full dashboard.

Run `python -m silmaril --live` to fetch real market data: prices from
yfinance, news from Google News RSS and SEC EDGAR, and technicals/sentiment
computed per-ticker. This is what the GitHub Actions workflow runs daily.

**The proven path through the system:**

1. Universe → ingestion fetches prices + news for ~100 tickers
2. Analytics layer computes SMA, RSI, ATR, Bollinger width, sentiment, regime
3. AssetContexts assemble from the analytics output
4. Each agent's `_judge(ctx)` produces a Verdict with conviction and rationale
5. Arbiter computes conviction-weighted consensus + agreement score + dissent
6. AEGIS's veto downgrades bullish consensus when its defensive conviction is high
7. Trade plans build from BUY-consensus debates using backer-weighted entry/stop/target
8. SCROOGE rolls his balance into the single highest-consensus pick
9. Handoff Blocks generate copy-ready LLM prompts with deep-links

---

## Remaining work

### 1. Leaderboard with historical tracking

Per-agent P&L tracking over time. The agents and output schema are ready; this
is a pure bookkeeping module that reads the daily signals.json files as they
accumulate and computes cumulative returns per agent.

### 2. Discovered-ticker universe layer

`universe/discovered.py` — tickers pulled from news that aren't in the core
universe, tracked for 7 days then either graduated to core or aged out.

### 3. Additional frontend pages

The dashboard page (`index.html`) is complete. Additional views to add:
- `/debates/` — all debates with filtering
- `/agents/:codename` — per-agent profile with track record
- `/plans/` — all active and historical plans
- `/scrooge/` — SCROOGE's full chart, deaths, and history
- `/leaderboard/` — full performance table

---

## Design principles (non-negotiable)

1. **Zero paid services.** Free APIs, free hosting, unlimited free GitHub Actions.
2. **Zero LLM in the pipeline.** Agents are rule-based and deterministic.
   LLMs enter the picture only through Handoff Blocks, on the user's own account.
3. **Transparent reasoning.** Every signal has an inspectable rationale. No black boxes.
4. **Educational framing.** Every view disclaims that this is simulation, not advice.
5. **Preserved history.** Nothing is deleted. Deaths, wrong calls, and backtest losses
   are part of the story — not hidden.

---

## Disclaimer

SILMARIL is an educational simulation. All portfolios, trade plans, and
leaderboard figures are hypothetical. Not financial advice.
