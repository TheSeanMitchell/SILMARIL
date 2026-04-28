# SILMARIL v2.0 Delivery

This directory is the v2.0 build, ready to merge into the main
SILMARIL repo. Hand-rolled, math-verified, free of paid dependencies.

## Read these first

1. **`ANSWERS.md`** — direct answers to the open questions in your
   v2 assessment (out-of-sample, Polymarket/Kalshi auth, mobile,
   deferred-automation plan, fork vs in-place).
2. **`ROADMAP_V2.md`** — the merge / wire-up checklist and the
   priority order for everything else.
3. **`silmaril/backtest/README.md`** — quick-start for running the
   backtest framework against the last four years.

## Directory layout

```
silmaril_v2/
├── ANSWERS.md
├── ROADMAP_V2.md
├── README_V2.md                          (this file)
└── silmaril/
    ├── backtest/                         # Priority #1: out-of-sample testing
    │   ├── README.md
    │   ├── __init__.py
    │   ├── __main__.py                   # CLI entry point
    │   ├── data_loader.py                # yfinance + parquet cache
    │   ├── replay.py                     # point-in-time context, no lookahead
    │   ├── engine.py                     # iterate days × tickers × agents
    │   ├── metrics.py                    # win rate, expectancy, Sharpe-ish
    │   └── walk_forward.py               # out-of-sample stability scoring
    │
    ├── agents/                           # Seven new agents
    │   ├── __init__.py
    │   ├── atlas.py                      # macro strategist
    │   ├── nightshade.py                 # Form 4 insider watcher
    │   ├── cicada.py                     # earnings whisper
    │   ├── shepherd.py                   # bond yield watcher
    │   ├── nomad.py                      # ADR arb
    │   ├── barnacle.py                   # 13F whale-follower
    │   └── kestrel_plus.py               # Hurst-aware mean reversion
    │
    ├── catalysts/                        # Six expanded catalyst sources
    │   ├── __init__.py                   # fetch_all_catalysts() aggregator
    │   ├── earnings_calendar.py          # Finnhub free-tier — fetch_earnings_calendar()
    │   ├── ex_dividend.py                # yfinance ex-div — fetch_ex_dividend_calendar()
    │   ├── index_rebalance.py            # SP500/Russell/MSCI/Nasdaq — fetch_index_rebalances()
    │   ├── opex.py                       # OPEX dates — fetch_opex_calendar()
    │   ├── crypto_unlocks.py             # token unlocks + halvings — fetch_crypto_unlocks()
    │   └── macro_releases.py             # FOMC/CPI/PPI/PCE/GDP — fetch_macro_calendar()
    │
    ├── scoring/                          # Regime-sliced live scoring
    │   ├── __init__.py
    │   └── regime_sliced.py              # answers "who shines in chop?"
    │
    └── handoff/                          # Manual multi-LLM consensus
        ├── __init__.py
        └── multi_llm_consensus.py        # four prompt builders, zero API calls
```

## Sanity-check checklist before you merge

- [ ] `python -m silmaril.scoring.regime_sliced` prints a JSON
      leaderboard (synthetic self-test).
- [ ] `python -m silmaril.handoff.multi_llm_consensus` prints four
      formatted prompts (self-test).
- [ ] `python -m silmaril.backtest --help` shows the CLI options.
- [ ] You've installed `yfinance pandas numpy pyarrow`.
- [ ] You've read `ANSWERS.md` §2 about Polymarket/Kalshi (you do
      not need to submit your driver's license to anyone yet).
- [ ] You've read `ROADMAP_V2.md` §"What you need to wire up" — the
      six-step merge guide.

## What this delivery does **not** include

Deliberately. See `ANSWERS.md` §4 and `ROADMAP_V2.md` for the full
deferral list.

- No sentiment engine replacement.
- No options-flow data integration.
- No live Polymarket / Kalshi trading.
- No automated multi-LLM consensus (manual by design).
- No mobile redesign (one breakpoint only).
- No portfolio-level sizing (concentration badge in dashboard work).
- No paid API keys required for anything.

---

Built for SILMARIL. Last updated April 2026.
