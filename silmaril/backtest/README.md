# SILMARIL Backtest Framework

The point of this module is to answer one question before you trust
SILMARIL with any live capital, paper or otherwise:

> **Given the last four years of real market data, would these
> agents have made money?**

Until you can answer that yes, no number on the live dashboard
matters.

## Install

```bash
pip install yfinance pandas numpy pyarrow
```

That's it. No paid feeds. No API keys. yfinance is enough for OHLCV
on equities, ETFs, and a usable subset of crypto / FX.

## Run a four-year backtest

```bash
python -m silmaril.backtest \
    --start 2022-01-01 \
    --end 2026-01-01 \
    --universe demo \
    --agents all \
    --walk-forward \
    --splits 4 \
    --out-dir docs/data
```

What the flags mean:

- `--start` / `--end` — the historical window. Default is the last
  four calendar years.
- `--universe` — `demo` (25 hand-picked tickers spanning equities,
  ETFs, bonds, gold, crypto proxies) or `full` (your full
  `silmaril.universe.core` list, if available) or `custom` (pass
  `--tickers SPY,QQQ,...`).
- `--agents` — `all` (the registered cohort) or comma-separated
  list (e.g. `AEGIS,FORGE,KESTREL+`).
- `--walk-forward` — enable out-of-sample stability scoring
  (recommended).
- `--splits` — number of walk-forward windows (default 4).
- `--out-dir` — where to write the JSON report. The dashboard reads
  from `docs/data/backtest_report.json` by convention.
- `--no-cache` — bypass the `~/.cache/silmaril_backtest/` parquet
  cache (slow first run, fast every subsequent run).

## What it produces

A single JSON file with three sections:

```json
{
  "config": { "start": "...", "end": "...", "n_tickers": 25, ... },
  "overall": {
    "leaderboard": [
      { "agent": "AEGIS", "n_calls": 6204, "n_active": 4123,
        "win_rate": 0.534, "expectancy": 0.0021,
        "sharpe_ish": 0.84, "max_drawdown": -0.087 },
      ...
    ]
  },
  "by_regime": {
    "BULL":    [ /* same shape, only BULL-regime predictions */ ],
    "BEAR":    [ ... ],
    "CHOP":    [ ... ],
    "UNKNOWN": [ ... ]
  },
  "by_asset_class": {
    "equity":  [ ... ],
    "etf":     [ ... ],
    "crypto":  [ ... ],
    ...
  },
  "walk_forward": {
    "splits": [
      { "start": "2022-01-01", "end": "2023-01-01", "agents": [ ... ] },
      ...
    ],
    "stability": [
      { "agent": "AEGIS", "spread": 0.04, "classification": "STABLE" },
      { "agent": "ATLAS", "spread": 0.27, "classification": "BRITTLE" },
      ...
    ]
  }
}
```

Open this file in your editor or feed it to the dashboard.

## What gets measured (and what doesn't)

### Measured
- **Win rate** of directional calls (HOLD / ABSTAIN excluded).
- **Expectancy** per active call (mean signed next-day return).
- **Sharpe-ish ratio** — signed daily returns × √252. *This is for
  ranking only.* It is not a portfolio Sharpe.
- **Max drawdown** of the agent's signal-following equity curve
  ($1 start, 1% sizing per active call).
- **Walk-forward stability spread** — how much win rate moves
  between the N out-of-sample windows.

### Not measured (and why)
- **Slippage and fees.** v2.0 backtest is decision-quality only.
  Stage 1 paper trading on Alpaca will measure execution.
- **Sentiment-dependent agents.** VEIL and SPECK abstain in backtest
  because the historical sentiment data SILMARIL uses live isn't
  reproducible point-in-time. Their backtest scores will be near
  zero — that's correct, not a bug.
- **Realistic position sizing.** Equity curve assumes 1% per active
  call uniformly. Real position sizing is a v3 problem (see
  `ROADMAP_V2.md`).

## How no-lookahead is enforced

Every backtest day calls `bundle.slice_as_of(as_of_date)` which
returns the data window strictly before `as_of_date`. Indicators
are recomputed against that slice. Outcomes are scored against
`next_day_return(bundle, as_of_date)`, which only reads the *next*
trading day — never beyond.

If you ever extend an agent to peek at additional fields, do not
reach outside the `BacktestContext` object. The slice is the
contract.

## Cache

First run downloads ticker history into
`~/.cache/silmaril_backtest/{ticker}_{start}_{end}.parquet`.
Subsequent runs read from cache instantly. Override the cache root
with `SILMARIL_BACKTEST_CACHE=/some/other/dir`.

`--no-cache` forces a fresh download.

## Running just one agent

For debugging:

```bash
python -m silmaril.backtest \
    --start 2024-01-01 \
    --end 2026-01-01 \
    --universe custom --tickers SPY,QQQ,IWM \
    --agents KESTREL+ \
    --out-dir /tmp
```

This finishes in a minute or two and is useful when iterating on
agent logic.

## Walk-forward, in plain English

Read `ANSWERS.md` §1 in the parent directory. The short version:

The four-year window is split into N pieces (default 4 = 1-year
slices). Each agent is scored on each piece independently. The
spread between best and worst slice tells you whether the agent's
edge is real or a one-window fluke.

```
agent       slice1   slice2   slice3   slice4   spread   verdict
AEGIS        0.54     0.56     0.51     0.55     0.05     STABLE
KESTREL+     0.60     0.42     0.55     0.39     0.21     BRITTLE
```

A BRITTLE agent isn't useless, but you should not weight it equally
in the cohort. The dashboard should display this column prominently.

## Self-tests

The math has been verified on synthetic data:

- Trending series → trend agents score positive expectancy.
- Mean-reverting series → mean-rev agents score positive expectancy.
- Random walk → all agents score ~50% win rate (correctly noise).
- Hurst R/S estimator: trending 0.51–0.61, mean-reverting 0.33,
  random walk 0.56 — all in expected ranges.

If you change `metrics.py`, run the synthetic self-tests in
`replay.py` and `walk_forward.py` to confirm nothing regressed.

---
