# SILMARIL v2.0 — Open-Question Answers

This file answers the specific questions you raised in the v2
assessment. Each section is self-contained.

---

## 1. What "Out-of-Sample Validation" actually is (sec 6.4)

You said you didn't understand it. Here's the plain-English version.

### The trap it solves

When you backtest agents on the last four years of data, every agent
will look smarter than it actually is. Why? Because the agents'
parameters — the SMA windows, the RSI thresholds, the regime cutoffs
— are tuned to what *did* happen. If you tested AEGIS over 2022–2026
and it nailed it, the natural next step is to tweak its parameters
until it nails it even harder. After enough tweaking, you end up with
an agent that's perfectly fitted to that specific four-year window
and useless going forward. The technical name is **overfitting**.

Out-of-sample validation is the discipline that prevents this.

### How it works in two sentences

1. Split your historical data into a **training** window and a
   **test** window the agent has never seen.
2. Tune everything on the training window. Then run the unchanged
   agent against the test window. The test-window result is the only
   number you trust.

That's it.

### What we built for SILMARIL specifically

We didn't go with a single train/test split — that's the simplest
form, and it has its own problem (you got lucky with where you split).
Instead, the backtest framework ships with **walk-forward validation**,
which is the industry-standard version:

- The 4-year window gets divided into N equal slices (default 4).
- We score each agent independently on every slice.
- We then look at how stable each agent is across slices.
- An agent whose win rate swings from 65% to 38% across slices is
  flagged **BRITTLE**. An agent whose win rate stays 52–58% across
  every slice is flagged **STABLE**.

The output is a one-line classification per agent:

```
AEGIS      STABLE      win-rate spread 0.04
FORGE      STABLE      win-rate spread 0.07
KESTREL+   VARIABLE    win-rate spread 0.14
ATLAS      BRITTLE     win-rate spread 0.27
```

A BRITTLE agent might still be useful — but only in regimes where it
shines. We treat BRITTLE flags as "do not put in cohort with high
weight" warnings.

### Practical effect

When the dashboard shows a leaderboard after the v2 backtest run, the
ranking will not be "best on the whole 4 years". It will be "best
average performance across 4 separate test windows the agent never
got to optimize for". That is a much harder bar to clear and a much
more honest one.

You can read the full implementation in
`silmaril/backtest/walk_forward.py`. The CLI wires it on by default
when you pass `--walk-forward`.

---

## 2. Polymarket and Kalshi — what the API access actually requires

You offered to submit your driver's license and SSN. **You do not
need to.** Here's the actual situation as of late April 2026.

### Polymarket

There are three Polymarket APIs:

| API | What it gives you | Auth required |
|---|---|---|
| Gamma API | Markets, events, prices, volume, comments | **None** |
| Data API | Positions, trades, leaderboards | **None** |
| CLOB API (read) | Order books, prices, midpoints, history | **None** |
| CLOB API (trade) | Place / cancel orders | Polygon wallet signing |

For SILMARIL Stage 1 (paper trading via Alpaca for stocks, no live
prediction-market trading), **all data we need from Polymarket is on
the Gamma and Data APIs, which are completely open**. Base URLs:

- `https://gamma-api.polymarket.com`
- `https://data-api.polymarket.com`

No API key. No wallet. No KYC. No SSN. No DL. Rate limit is roughly
60 requests/minute on the Gamma side, plenty for our cadence.

If we ever wanted to actually *place* trades on Polymarket, we'd need
a Polygon wallet funded with USDC. Polymarket itself does not collect
SSN or government ID — it's a non-custodial crypto-settled venue. The
KYC, if any, would happen on the on-ramp service used to fund the
wallet (e.g., a US exchange when buying USDC), and that's KYC for the
on-ramp, not for Polymarket. There's no Polymarket form that asks
for an SSN.

### Kalshi

Kalshi is the opposite kind of venue: a CFTC-regulated US exchange
with USD settlement. Two-tier API access:

| Endpoint type | Auth required |
|---|---|
| Market data (markets, events, orderbooks, prices) | **None** for the public quickstart endpoints |
| Trading, portfolio, balance | RSA-PSS signed requests |

Base URL for read-only market data:
`https://api.elections.kalshi.com/trade-api/v2`

(The "elections" subdomain is misleading — it serves all Kalshi
markets, not just political ones.)

For SILMARIL Stage 1, **read-only market data is enough and it's
open**. We do not need a Kalshi account to pull market data into the
catalyst stream and into prediction-market-aware agents.

If and when we want to place actual Kalshi trades, then yes — Kalshi
is a regulated US derivatives venue, so you'd go through their
standard account-opening KYC just like opening a brokerage account.
That's a real account-opening flow with an ID upload and possibly
SSN, because they have to file with regulators. But that's a Stage 3
problem, not a Stage 1 problem.

### Recommendation

**Do nothing right now.** Don't open accounts. Don't submit
documents. We wire up:

- Polymarket Gamma API → catalyst feed (live prediction-market
  prices on macro events SILMARIL already cares about)
- Kalshi public market data → same purpose, different platform

Both are read-only HTTP requests with no auth. We'll write the
fetchers in v2.0 and they will Just Work without any account at all.

The earliest you'd ever need to submit ID is when we're ready to
flip from paper trading to real money on Kalshi specifically. We're
not close to that moment.

---

## 3. Mobile layout — acknowledged, deferred, but not forgotten

Your current viewing situation is a 4K TV. The dashboard is built
for that. For v2.0 we're keeping the desktop / TV-first layout
because changing it now would slow down everything else you said is
a higher priority.

What we **are** going to do for v2.0:

1. The new dashboard pages we add (regime leaderboard, backtest
   report, walk-forward stability table) are written with simple
   single-column layouts that already collapse cleanly on mobile.
2. The site CSS gets one breakpoint at 768px that stacks the agent
   tile grid into a single column. This costs us nothing.

What we're **not** going to do yet:

- A full responsive redesign with collapsible nav, swipe gestures,
  reorganized information density. That's its own project and it
  fights with the catalyst-roundup work for attention. Push to v2.1
  or v2.2 once the rest of v2.0 is settled.

If you ever want to check the dashboard from your phone in the
meantime, it'll work — just not beautifully.

---

## 4. The "astroturf paid automation" plan

You asked for everything that costs money to be deferred until the
project is more refined. Concrete plan:

### What we automate now (free or near-free)

- **yfinance** — the backtest data loader runs entirely on yfinance,
  which is free and unrate-limited within reason.
- **Polymarket Gamma + Data API** — free, no auth.
- **Kalshi public data** — free, no auth.
- **Finnhub free tier** — earnings calendar. Free up to 60 req/min,
  one API key, no card required. We already wire this in
  `silmaril/catalysts/earnings_calendar.py` — it gracefully no-ops
  if `FINNHUB_API_KEY` is unset.
- **EIA crude inventory dates, FOMC dates, OPEX dates** — pure date
  math, no API call. Already in `silmaril/catalysts/`.
- **Static crypto unlock and halving lists** — hard-coded for now,
  you can refresh from token.unlocks.app whenever convenient.

### What we defer (paid, automated, or both)

- **Multi-LLM consensus.** The whole point of `silmaril/handoff/` is
  that *you* run these prompts manually when you want a second
  opinion. The dashboard just gives you a Copy button. ChatGPT,
  Gemini, Grok, a fresh Claude — whichever you have free credits on.
  No automated calls means no surprise bill.
- **Options-flow data feeds** (Cheddar, Unusual Whales, BlackBoxStocks
  etc.). All are paid. v2.0 leaves the agent stubs in place
  (the "ZENITH-options-aware" path), but they only activate when an
  `options_flow` field is present on the context. No subscription =
  no activation. Document the integration shape so you can plug in
  any provider later.
- **Tier-1 sentiment data** (RavenPack, MarketPsych, Brain Sentiment).
  Replacing the current sentiment engine is on the priority list, but
  with a real budget call attached. v2.0 keeps sentiment-dependent
  agents (VEIL, SPECK) in the cohort with a clearly labeled "no
  sentiment available" fallback that makes them HOLD/ABSTAIN. They
  don't pretend to vote. When you fund a sentiment provider, we wire
  it in one place.
- **Live Polymarket / Kalshi *trading*.** Read-only, free. Trading,
  later, after Stage 1 paper-trading numbers are convincing.
- **Alpaca paper trading API**. This *is* free (paper trading on
  Alpaca has no cost), so it's our Stage 1 actuator. But until
  backtested numbers across walk-forward windows look good, we don't
  even bother wiring it.

### The gating rule

We will not flip on any paid automation feed until SILMARIL has
shown a positive expectancy in walk-forward testing on the last 4
years AND a positive expectancy in 30 days of forward paper trading.
If either of those is negative or noisy, paying for data won't fix
the agents.

---

## 5. On portfolio-level position sizing (sec 2.9)

You said you wanted agents to act independently — let them have
their own greed and impulses. We agree and v2.0 keeps it that way.

The thing the assessment was warning about is real, though: if every
agent independently sizes 10% of the book into the same trade, you
end up with 100%+ in one position. We're not going to solve that by
adding a portfolio governor in v2.0. We *are* going to solve it by:

- Logging each agent's *implied* sizing alongside their verdict, so
  the dashboard makes it visible when too many agents pile in.
- Adding a single "concentration warning" badge on the trade-plan
  card that lights up when the cohort's combined implied exposure
  in one ticker exceeds 25%. No automated cap. Just a visible flag.

That keeps the agents independent, surfaces the problem, and leaves
the actual sizing decision to you until we get to a real portfolio
overseer in v3.

---

## 6. On the "fork the GitHub project" idea

You floated the option of letting the current Alpha 1.4 site keep
running on GitHub Pages while you build v2.0 in a separate fork.

Our recommendation: **don't fork. Upgrade in place.**

Reasons:

1. The 30 days of data the current site would generate is already
   compromised — sentiment is unreliable, the agent cohort is missing
   ATLAS / NIGHTSHADE / CICADA / SHEPHERD / NOMAD / BARNACLE /
   KESTREL+, the catalysts are thin. Even if you ran it 60 days,
   you'd be measuring a system you've already decided to replace.
2. v2.0 has the backtest framework, which lets you generate four
   years of synthetic-counterfactual data in an afternoon. That's
   strictly more useful than two months of weak live data.
3. Fork maintenance is real. Two diverging codebases will need
   merges and they will go badly.

Better path: cut a `v1-archive` branch on the current repo (so the
old code is preserved if you ever want to look at it again), then
push v2.0 to `main`. The GitHub Pages site rebuilds, the dashboard
changes shape, and you start the 30-day clock with the real cohort.

---
