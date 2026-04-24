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
│   ├── ingestion/              ○ to port from STOX (fetcher, sources, cache)
│   ├── analytics/              ○ to build — technicals, regime, correlations
│   ├── universe/               ○ to build — 3-layer asset management
│   ├── risk_engine/            ○ to build — drawdown, regime filters
│   ├── leaderboard/            ○ to build — per-agent P&L, git-replay backfill
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
└── .github/workflows/          ○ to adapt from STOX (hourly/daily/weekend)
```

Legend:  ✓ built (working code)   ○ scaffolded (directory exists, implementation TBD)

---

## What works today

You can run `python run_demo.py` and get a complete debate produced by three
agents (AEGIS, FORGE, SCROOGE) over eight realistic sample asset contexts. The
output is real JSON in the exact schema the frontend consumes. Opening
`docs/index.html` in a browser (with `docs/data/` containing copies of the
four JSON files) renders the full dashboard.

**The proven path through the system:**

1. AssetContexts enter the arbiter
2. Each agent's `_judge(ctx)` produces a Verdict with conviction and rationale
3. Arbiter computes conviction-weighted consensus + agreement score + dissent
4. AEGIS's veto downgrades bullish consensus when its defensive conviction is high
5. Trade plans build from BUY-consensus debates using backer-weighted entry/stop/target
6. SCROOGE rolls his balance into the single highest-consensus pick
7. Handoff Blocks generate copy-ready LLM prompts with deep-links

---

## Remaining work to reach full production

### 1. Scale agents from 3 to 16

Each new agent is one file following the pattern in `aegis.py` or `forge.py`:
define metadata, override `_judge(ctx)`, return a Verdict. The arbiter and
trade engine require zero changes. Rough effort: ~1–2 hours per agent.

### 2. Real data ingestion

Port STOX's existing fetcher/normalizer/deduplicator/cache and news sources.
Add `silmaril/analytics/technicals.py` for SMA/RSI/ATR/BB computation over
yfinance price history. The AssetContext dataclass already has every field
these produce.

### 3. Universe management (3-layer)

- `universe/core.py` — the ~100 always-tracked tickers (indices, sector ETFs,
  mega-caps, BTC/ETH, DXY, gold, oil, 10Y yield)
- `universe/discovered.py` — tickers pulled from news; tracked for 7 days then
  graduate to core or age out
- `universe/registry.py` — unified interface

### 4. Leaderboard with historical bootstrap

The one-time backfill walks the existing STOX repo's git history of
`signals.json` commits, replays what each of the 16 new agents *would have
said* on each past day, and seeds the leaderboard. The site launches with a
real track record instead of an empty scoreboard.

### 5. GitHub Actions workflows

Adapt the three existing STOX workflows for SILMARIL:
- `hourly.yml` — market-hours refresh (9:30–16:00 ET)
- `daily.yml` — post-close full run with SCROOGE action
- `weekend.yml` — minimal keepalive

### 6. Additional frontend pages

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
