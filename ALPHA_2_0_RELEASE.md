# SILMARIL Alpha 2.0 — Release Notes

**Codename: Full Learning Mode**
**Date: 2026-04-30**

This is a major architecture release. We skipped 1.6 and went straight to 2.0
because the surface-area of changes warranted it. The system is now an
**adaptive ensemble** with persistent learning, paper-money trading, and
new agents specifically built for daily-move shorts and crowded-trade fades.

---

## What's new

### 1. Full Learning Mode — the adaptive ensemble layer

A new `silmaril/learning/` module closes the feedback loop. Every daily
run now:

- **Updates Bayesian beliefs** about each agent's win rate per regime
  (Beta posterior with gentle decay so old data doesn't dominate forever)
- **Samples conviction multipliers** via Thompson sampling — uncertain agents
  get variable voice (exploration), confident agents get stable voice
  (exploitation). This is the same algorithm production multi-armed-bandit
  systems use
- **Builds a dissent digest** — yesterday's overruled-minority wins and
  hot/cold streaks get injected into every agent's context as
  `learning_context`. Cross-agent learning, no LLM API needed
- **Loads operator reflections** — you can hand-write 1-3 sentences in
  `docs/data/reflections.json` after each market close (or paste a
  Perplexity/Grok response into it) and that gets injected as a rule of thumb
- **Logs counterfactuals** — when consensus overrules a dissent, we record
  what *would* have happened if we'd listened. After 90+ days, this tells
  us which dissents are signal vs noise
- **Applies hysteresis bands** — SELL fires when RSI > 70 but doesn't reset
  until RSI < 65. Critical at 10-minute cadence to prevent flicker
- **Maintains contextual bandits** per (regime, asset_class, vol_quartile)
  — agents earn voice in the contexts where they actually have edge
- **Detects performance drift** — when an agent's rolling 30-day win rate
  drops 7%+ below their lifetime, we apply an automatic conviction dampener

### 2. Training never resets

Every learning artifact lives on the **PROTECTED_LEARNING_FILES** list
defined in `silmaril/learning/persistence_guard.py`. The reset workflow,
backtest workflow, and daily workflow all import this list and refuse to
touch it. There is no command, secret, or env var that wipes learning.
A weekly backup workflow snapshots all protected files to
`docs/data/_backups/` every Sunday — 12-week rolling retention.

### 3. Two new agents

**SHORT_ALPHA** — Daily-move short specialist. Detects negative
catalysts (earnings miss, FDA rejection, CFO resigns, short reports,
guidance cuts) on liquid large-caps only. Squeeze-risk blacklist excludes
GME-style names. 1-3 day horizon, +3% hard stop. Honest design — retail
shorting has narrow edge, this is the defensible slice.

**CONTRARIAN** — Crowded-trade fade detector. When RSI, sentiment,
put/call ratio, and price-stretch all align in the same direction, the
crowd is leaning. CONTRARIAN fades the crowd. Large-cap universe only.

### 4. Alpaca paper trading bridge

Free, paper-only, hardcoded. Every consensus BUY/SELL at conviction
≥ 0.60 becomes a real-shaped market order in your Alpaca paper account.
Shorts enabled when your account supports them. 5% per-position cap,
15-position concurrent cap. Equity curve persisted to
`docs/data/alpaca_equity_curve.json`. The base URL is `paper-api.alpaca.markets`
— no parameter or secret can flip this to live trading. Adding live
trading would require a separate, deliberately-named module that does
not exist in this codebase.

### 5. Six new analytics modules

- **Slippage modeling** — basis-points cost applied to every fill, scales
  with asset class, volatility, and order participation
- **Position correlation matrix** — nightly snapshot, alerts when 3+
  agents hold positions with > 0.7 correlation
- **Time-of-day awareness** — performance bucketed by OPENING_30 /
  MORNING / LUNCH_LULL / AFTERNOON / POWER_HOUR
- **News quality scoring** — multi-source confirmation multiplier
  (1.0 single, 1.5 two sources, 2.0 three+)
- **Anomaly detection** — volume spikes, price gaps, ATR spikes, volume
  divergence, with 24h TTL to prevent re-firing
- **Pre-mortem generation** — every high-conviction call now has explicit
  kill criteria written into the rationale

### 6. New workflows

- `daily.yml` — **10-minute cadence** during US market hours (public
  repo = unlimited Actions minutes)
- `backtest.yml` — preserves learning state, runs walk-forward
- `reset.yml` — explicitly preserves all PROTECTED_LEARNING_FILES
- `reflection.yml` — 4:30pm ET weekday placeholder bootstrap
- `stress_test.yml` — manual-trigger adversarial stress test, results
  rendered at `/stress_test.html`
- `correlation_check.yml` — nightly correlation matrix snapshot
- `weekly_backup.yml` — Sunday midnight UTC, snapshots all protected files

### 7. Three new dashboard pages

- `/evolution_cards.html` — gamified XP/level cards for each agent. Cards
  only grow, never reset. Achievements unlock at 100/1000/10000 calls,
  5/10/20-win streaks, etc.
- `/stress_test.html` — robustness verdict + scenario results, history
  preserved across runs
- `/correlation_matrix.html` — concentration alerts, pairwise correlations

### 8. Frontend bug fixes (apply via INDEX_HTML_UPDATES.md)

- Trade history timestamps no longer all show 17:00 — uses real
  `timestamp` field that backend now writes
- Consolidated News Feed sorts strictly by time, no more ticker grouping
- User profile entries rank inline with agents on leaderboard
- Agent display names use professional labels (Guardian, Reverter, etc.)

### 9. Sports Bro fix

Now always picks the closest-resolving bet. Tries 72-hour window first,
falls back to 7 days, falls back to top-10 closest. Per-sport priors
weight the EV calculation. You'll actually see Sports Bro working now.

### 10. All 22+ agents get portfolios

The `ensure_all_agents_have_portfolios` helper makes this idempotent.
Every codename in `_rename_map.py` gets a $10K paper portfolio on
inception, even silent ones.

---

## Honest framing on what this delivers

This is genuinely the best version of an adaptive multi-agent ensemble
I can deliver without an LLM API budget. After 90+ days of forward live
data accumulating in the new belief and counterfactual stores, you'll
have what you need for the genuinely advanced layer (XGBoost meta-filter,
pre-trained sentiment models, etc.).

What this WILL NOT do:
- Beat institutional quants. They have microsecond execution and $50K/month
  data feeds.
- Turn $1,000 into $14,000 in 48 hours.
- Generate "true advantage" shorting penny stocks from Twitter sentiment
  (squeeze risk is asymmetric).

What this WILL do:
- Give you a transparent, self-auditing trading-thought platform
- Adapt with each cycle and improve continuously
- Execute paper trades on Alpaca with proper risk controls
- Provide the 90-day data foundation needed before any real-money discussion

After 90 days of clean data, ping me with the new `scoring.json`,
`counterfactuals.json`, and `alpaca_equity_curve.json`. We can then
make a defensible go/no-go call on the next stage.
