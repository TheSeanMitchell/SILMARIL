# SILMARIL v2.0 Roadmap

This is the explicit checklist of what's done, what remains, and the
order to do it in.

---

## What's in this delivery

### ✅ The backtest framework (priority #1)
You said this was the most critical piece. It is built and
math-verified.

- `silmaril/backtest/data_loader.py` — yfinance loader with on-disk
  parquet cache at `~/.cache/silmaril_backtest/`, OHLCV history,
  VIX, 10Y yield, no-lookahead slicer.
- `silmaril/backtest/replay.py` — point-in-time context builder.
  Computes SMA20/50/200, RSI14, ATR14, Bollinger width, MACD,
  20-day momentum, 20-day volatility. Classifies regime (BULL /
  BEAR / CHOP / UNKNOWN) per day from VIX + SPY momentum.
- `silmaril/backtest/engine.py` — runs every agent against every
  ticker on every trading day in the window. One-bug-per-agent
  isolation; one agent failing doesn't kill the run.
- `silmaril/backtest/metrics.py` — win rate, expectancy, Sharpe-ish
  (×√252 on signed next-day returns), max drawdown, equity curve
  from $1 with 1% sizing per active call. Slices by regime and
  asset class.
- `silmaril/backtest/walk_forward.py` — out-of-sample stability
  scoring (this is the answer to your "I don't understand 6.4"
  question — see `ANSWERS.md` §1).
- `silmaril/backtest/__main__.py` — CLI entry point.

Run it:

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

Synthetic-data smoke test verified the math: trending series score
positively for trend agents, mean-reverting series score positively
for mean-rev agents, random walks score 48–49% (correctly).
Walk-forward correctly classified MEANREV as BRITTLE on a hostile
window and STABLE on its native one. See `silmaril/backtest/README.md`
for quick-start.

### ✅ Seven new agents (priority #9)
All located in `silmaril/agents/`. Each follows the existing Agent
interface and abstains gracefully when its required upstream data
isn't wired.

- `atlas.py` — ATLAS, macro strategist for broad ETFs only.
- `nightshade.py` — Form 4 insider transaction watcher (equities).
- `cicada.py` — earnings whisper / drift trader, only votes when
  earnings are within 7 days.
- `shepherd.py` — bond-yield watcher, votes only on bonds and
  rate-sensitive sectors.
- `nomad.py` — ADR / home-listing arb (BABA/9988, TSM/2330, etc).
- `barnacle.py` — 13F whale-follower across 12 hard-coded
  institutional CIKs.
- `kestrel_plus.py` — Hurst-aware mean reversion. Only fades RSI
  extremes when the underlying time-series is actually mean-reverting
  (Hurst < 0.45). Uses canonical R/S analysis.

### ✅ Six expanded catalyst sources (priority #10)
All in `silmaril/catalysts/`.

- `earnings_calendar.py` — Finnhub free-tier with `days_to_earnings()`
  helper for CICADA. No API call if `FINNHUB_API_KEY` is unset.
- `ex_dividend.py` — yfinance-driven dividend dates for 40 SP500
  payers.
- `index_rebalance.py` — pure date math for SP500 / Russell / MSCI /
  Nasdaq-100 rebalance windows.
- `opex.py` — pure date math for monthly OPEX (3rd Friday) and
  quarterly triple-witching.
- `crypto_unlocks.py` — illustrative static schedule for major
  unlocks plus BTC halving estimates. Tag the type so the agent can
  size accordingly.
- `macro_releases.py` — FOMC / CPI / PPI / PCE / GDP / EIA crude
  schedule with watchlist tags.

A `fetch_all_catalysts(days_ahead=14)` aggregator is exposed at the
package level for the dashboard to consume in one call.

### ✅ Regime-sliced live scoring (priority #13 / sec 6.5)
`silmaril/scoring/regime_sliced.py`

- Classifies each prediction's regime at the time it was made.
- Buckets predictions by `(agent, regime)`.
- Computes win rate, expectancy, cumulative return per cell.
- Detects "specialists" — agents whose performance in their best
  regime is meaningfully better than their overall average.

The dashboard endpoint that consumes this should call
`build_regime_leaderboard(predictions, metric="expectancy")` and
render the four regime tables side by side, plus a "specialist
spotlight" callout.

### ✅ Manual multi-LLM consensus prompts (priority #11 / sec 6.3)
`silmaril/handoff/multi_llm_consensus.py`

Four copy-pasteable prompt builders. **Zero API calls.** The
dashboard adds a button on each verdict tile that calls one of these
and copies the result to the clipboard. You paste into ChatGPT,
Gemini, Grok, a fresh Claude — whichever you have spare credits on
that day.

- `build_consensus_prompt(...)` — primary "rate this cohort" prompt.
- `build_red_team_prompt(...)` — adversarial "argue against this".
- `build_catalyst_review_prompt(...)` — "which catalyst kills this?"
- `build_summary_prompt(...)` — plain-English paragraph for sharing.

Each is short enough that even free-tier daily token limits don't
bite.

### ✅ Documentation
- `ANSWERS.md` — answers to your specific open questions
  (out-of-sample explainer, Polymarket/Kalshi reality, mobile,
  paid-automation deferral, fork vs upgrade).
- `ROADMAP_V2.md` — this file.
- `README_V2.md` — overview.
- `silmaril/backtest/README.md` — backtest quick-start.

---

## What you need to wire up after merging this

These steps are deliberately small and ordered.

### Step 1 — Run the backtest before anything else

This is your priority #1 before you spend time on anything else in
v2.0. Until the backtest produces a leaderboard you trust, every
other change is decoration.

```bash
cd <silmaril-repo>
pip install yfinance pandas numpy pyarrow
python -m silmaril.backtest \
    --start 2022-01-01 \
    --end 2026-01-01 \
    --universe demo \
    --walk-forward \
    --out-dir docs/data
```

Inspect `docs/data/backtest_report.json`. Look at the by-regime
slice. Look at the walk-forward stability column. Some of your
existing agents will look a lot worse than the dashboard currently
suggests. That's the point.

### Step 2 — Cut the v1-archive branch, then merge v2 to main

```bash
git checkout -b v1-archive
git push origin v1-archive
git checkout main
# merge the silmaril_v2/ contents into the repo
```

Don't fork. See `ANSWERS.md` §6.

### Step 3 — Register the new agents and catalysts

In whatever file in the live site currently registers the cohort
(probably `silmaril/agents/__init__.py` or a config), add:

```python
from silmaril.agents.atlas import ATLAS
from silmaril.agents.nightshade import NIGHTSHADE
from silmaril.agents.cicada import CICADA
from silmaril.agents.shepherd import SHEPHERD
from silmaril.agents.nomad import NOMAD
from silmaril.agents.barnacle import BARNACLE
from silmaril.agents.kestrel_plus import KESTREL_PLUS

ALL_AGENTS = [..., ATLAS, NIGHTSHADE, CICADA, SHEPHERD, NOMAD,
              BARNACLE, KESTREL_PLUS]
```

For catalysts, replace the current single-source roundup call with:

```python
from silmaril.catalysts import fetch_all_catalysts
events = fetch_all_catalysts(days_ahead=14)
```

The aggregator wraps `fetch_earnings_calendar`,
`fetch_ex_dividend_calendar`, `fetch_index_rebalances`,
`fetch_opex_calendar`, `fetch_crypto_unlocks`, and
`fetch_macro_calendar` — call any individually if you only want one
source.

### Step 4 — Add the regime leaderboard page to the dashboard

Two things on the dashboard:

1. A new page (or tab) that calls `build_regime_leaderboard()` on
   the live prediction log and renders four side-by-side tables.
2. A "specialist" callout widget at the top.

This requires no new data sources — it just needs the live
predictions log to carry the regime classification, which the
current code is already capable of computing on the fly when
predictions are written.

### Step 5 — Wire the manual consensus button

Add a "Get second opinion" dropdown menu on each verdict tile with
four options (consensus, red team, catalyst, summary). Each option
calls the corresponding builder and copies to clipboard.

This is purely a frontend change; the backend already returns the
prompt strings.

### Step 6 — Cut the 30-day clock

After steps 1–5 land and the dashboard rebuilds cleanly, that's
v2.0. Start the live forward-tracking 30-day window from that
moment. Compare: walk-forward backtest expectancy → 30-day live
expectancy. If they line up roughly, the system is honest. If live
is materially worse than backtest, something is wrong (data
snooping, latency, missing fees) and we go find it before adding
features.

---

## What's deferred (and why)

| Item | Sec | Defer until |
|---|---|---|
| Replace sentiment engine | Pri 2 | After backtest is honest. Paid feeds are pointless if the underlying logic is wrong. |
| Options-flow data | Pri 4 | After 30-day live confirms backtest. Costs money and adds attack surface. |
| Live Polymarket/Kalshi *trading* | Pri 5 | Stage 3 — after Alpaca paper trading shows positive numbers. Read-only data goes in now. |
| Mobile redesign | sec 2.10 | v2.1 or later. Single breakpoint added in v2.0 for survivability; full responsive layout is its own project. |
| Portfolio-level sizing | sec 2.9 | v3. Concentration warning badge in v2.0. See `ANSWERS.md` §5. |
| Automated multi-LLM consensus | sec 6.3 | Maybe never. Manual is by design — zero token spend, full control. |
| Deeplinks (sec 2.8) | sec 2.8 | Easy work, queued for v2.1. Not gating anything. |
| Trade-plan generation overhaul (sec 2.5) | sec 2.5 | v2.1 — depends on having confidence in the cohort first. |

---

## Version after v2.0

Tentative naming:

- **v2.1** — deeplinks, mobile breakpoint refinement,
  trade-plan generation overhaul, log/feedback-loop improvements.
- **v2.2** — sentiment engine replacement (paid integration, gated
  on backtest results being convincing).
- **v3.0** — portfolio overseer, options-flow integration,
  Stage 2 (real-money paper account on Alpaca), eventual Stage 3
  (real Kalshi / Polymarket positions).

---
