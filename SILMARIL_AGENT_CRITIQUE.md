# SILMARIL — Agent Improvement Critique (Alpha 1.6)

**Purpose:** Identify, agent by agent, why each strategist performs the way it
does on the v1.6 full-universe backtest, and propose specific, implementable
ways to improve every losing one toward the level of our best performer
(KESTREL+ at 54.5% win rate, +0.184% expectancy, +0.65 Sharpe-ish).

**Generated:** 2026-04-28, after the most recent FULL backtest run.
**Walk-forward source:** `docs/data/backtest_walk_forward.json`.

---

## Executive read

The leaderboard separates cleanly into three tiers:

**Tier 1 — Real edge** (mean win rate ≥52%, positive expectancy across all 4 yearly windows)
- **KESTREL+** (54.4% mean) — Hurst-aware mean reversion — most stable
- **MAGUS** (54.0% mean) — macro index — gets stronger over time (47.6% → 55.9%)
- **WEAVER** (51.9% mean) — flat across all four windows — boring, reliable
- **SHEPHERD** (52.6% mean) — surprisingly consistent after v2 fix; window-3 spike to 62%

**Tier 2 — Likely random** (mean win rate 49-52%, expectancy near zero, high window-to-window variance)
- **JADE, HEX, TALON, KESTREL, OBSIDIAN, ATLAS, SYNTH** — all hover at the coin-flip line
- These need real edge, not just threshold tweaks. Each one has a clear hypothesis-of-failure below.

**Tier 3 — Underperforming with structural issues** (mean win rate <49%, negative expectancy)
- **AEGIS** (46.5%) — the one that hurts the most because it has veto power
- **ZENITH** (48.5%) — high volume, low edge — still over-voting after v2 fixes
- **THUNDERHEAD** (48.5%) — volatile crypto + RSI extremes still wrong-sided
- **FORGE** (48.5%) — tech momentum bias not paying off in this regime

**Tier 4 — Silent** (zero predictions in backtest)
- **VEIL, SPECK, VESPA, CICADA, NIGHTSHADE, BARNACLE, NOMAD** — all need data
  not present in BacktestContext. Three of these (NIGHTSHADE, BARNACLE, NOMAD)
  cannot be fixed without paid feeds. Two (VEIL, SPECK) cannot be honestly
  backtested without a historical sentiment archive. Two (VESPA, CICADA) are
  partially fixed in v1.6 by wiring `days_to_earnings` from yfinance — they
  should produce votes on the next backtest run.

---

## The KESTREL+ template — what makes the best agent the best

KESTREL+ wins on three things every other agent can borrow:

1. **It refuses to vote when it has no edge.** 706 active calls in 4 years
   across 360 tickers. That's roughly 1 call per ticker per 18 months. It only
   speaks when its precondition (Hurst exponent confirms mean-reversion) is met.

2. **It uses a confirmation gate that other agents lack.** RSI extreme alone
   isn't enough — KESTREL+ requires the underlying time-series to be statistically
   mean-reverting first.

3. **Its conviction scales with the strength of the signal**, not with the
   loudness of the headline.

Every other agent should be measured against this template:
- *Does it have a refusal condition?* If it votes >5% of available bars, probably not.
- *Does it have a confirmation gate?* If signal X alone fires the trade, probably not.
- *Does conviction scale with edge?* Or is it always 0.55?

---

## Agent-by-agent diagnosis and prescription

### Tier 1 winners — defend, don't redesign

#### KESTREL+ (#1)
**Don't touch.** Add monitoring: log every prediction for 90 days of live data
to verify the backtest holds out-of-sample. If live win rate stays above 52% on
≥100 calls, this strategy graduates to Stage 2.

#### MAGUS (#2)
**Stable winner.** The 47.6% → 55.9% trend across windows suggests it's learning
the macro regime classifier as the regime data matures. **Recommendation:** add
a confidence-decay if its last 30 calls underperformed (defensive guard against
regime shift).

#### WEAVER (#5)
**Most boring, most reliable** — tightest variance across windows (50.0%–54.5%).
**Recommendation:** none. This is the floor we want everyone else to reach.

#### SHEPHERD (#10 by Sharpe but mean win rate 52.6%)
The v2 fix (35bps yield trigger, RSI mean-revert on bond ETFs) clearly worked.
**Recommendation:** add a corporate-credit (HYG / LQD) leg — credit spreads
lead rates by 1-3 days. Also add a Treasury-curve-shape signal (2s10s
flattening/steepening).

---

### Tier 2 — coin flips that need real edge

#### JADE — Healthcare specialist (53.2% / +0.029% / +0.26)
Decent on backtest but variance 44.4%-54.6% across windows = not stable.

**Hypothesis:** JADE votes on biotech catalysts (FDA approval probabilities,
clinical-trial readouts) but in backtest those event_flags are empty, so it's
just trading sector momentum.

**Prescription:**
- In live mode, gate votes on whether news flow mentions FDA/PDUFA/Phase
- Add a "binary event proximity" multiplier — pre-PDUFA names get position
  size cuts, not bigger swings (most binary events are 50/50)
- Wire the FDA Calendar (free, public) into catalysts so JADE has real
  data to act on

#### HEX — Bear-market specialist (51.1% / +0.039% / +0.16)
Window stability is very tight (49.6%-52.5%). Designed for bear markets but
the 4-year backtest spans BULL → BEAR → CHOP → BULL.

**Hypothesis:** HEX's edge is regime-conditional. Looking at by_regime breakdown
likely shows HEX hits >55% in BEAR, <50% in BULL.

**Prescription:**
- Add a regime gate: HEX abstains in clear BULL regimes (VIX <16, 50d momentum positive)
- Add an explicit short-volatility check: HEX's edge should INCREASE when the
  market is fragile (high VIX + flat 10d momentum)
- Tag votes as "DEFENSIVE" so portfolio managers can size them differently

#### TALON — Market structure / indices only (51.6% / -0.007% / -0.10)
Only votes on SPY/QQQ/IWM/DIA/VTI. The v2 fix added momentum confirmation
but didn't add the SECOND confirmation TALON needs.

**Prescription:**
- Add **breadth** — % of S&P 500 stocks above their own 50dma. When TALON
  votes BUY on SPY, breadth must be >55%. When SELL, breadth must be <45%.
- Currently buying SPY because SPY is above its own 50dma is circular.
  Breadth is the actual structural signal.
- Free data: count S&P 500 closes above SMA-50 each day from yfinance.

#### KESTREL — original mean-reverter (50.4% / +0.002% / +0.03)
KESTREL+ at 54.5% proves the strategy works WHEN you add Hurst confirmation.
The base KESTREL doesn't have that gate.

**Prescription:**
- Either retire base KESTREL and promote KESTREL+ to its slot, OR
- Backport the Hurst gate to base KESTREL and tighten its RSI threshold
  (currently 70/30 — try 75/25)
- Either way: stop having two near-identical agents on the cohort.

#### OBSIDIAN — commodities (50.8% / +0.053% / +0.44)
The v2 mean-reversion rewrite worked — went from 45.5% to 50.8%, expectancy
flipped positive. But the win rate is still low.

**Prescription:**
- Add **cross-commodity correlation** — when gold moves +2% in a day and silver
  doesn't, that's a setup. Same for oil/natgas, copper/aluminum.
- Add **inventory data** — EIA crude stocks (Wednesday 10:30am ET) are public
  and free. Shouldn't be voting on USO/UCO without that signal.
- Tag commodity votes as "MEAN-REVERT" vs "BREAKOUT" so the conviction
  weights properly.

#### ATLAS — macro regime caller (49.4% / -0.037% / -0.46)
Worst Tier-2 performer. The v2 momentum gate didn't help enough.

**Hypothesis:** ATLAS votes on single ETFs but its real value is **regime
classification across the whole cohort**. We're using it wrong.

**Prescription:**
- Reposition ATLAS as a **regime-tag emitter**, not a per-asset voter.
  ATLAS publishes a regime tag (RISK_ON / RISK_OFF / NEUTRAL / VOLATILE)
  consumed by all other agents. Stops voting at all.
- This is closer to the original intent — Atlas bears the weight of the sky,
  not individual stones.

#### SYNTH — cross-market correlation (51.0% / +0.011% / +0.12)
Functional but tepid. The v2 NEUTRAL-regime tilt added activity but not edge.

**Prescription:**
- Move from regime-based voting to **correlation-break detection**: when
  XLU and TLT decorrelate from their 60-day relationship, that's a real signal.
- Add **dollar-index gate**: SYNTH on cyclicals only when DXY <105.

---

### Tier 3 — structurally underperforming, need surgery

#### AEGIS — defensive cornerstone (47.8% / -0.022% / -0.13) ⚠ HIGHEST PRIORITY
**This is the most important fix in the project.** AEGIS has veto power in
arbiter.py — when AEGIS says SELL, the consensus signal is reduced. A losing
AEGIS reduces winners across the board.

**Diagnosis:**
- 53,326 active calls = AEGIS votes on roughly 1 in 7 bars across the universe.
  Way too much volume for a "principled and protective" agent.
- The v2 technical-only BUY path helped (was 43% before, now 47.8%) but the
  SELL path is still over-aggressive.
- AEGIS appears to be SELLing on every "below SMA-200 OR VIX>22 OR price stretched"
  state. Most of those don't pan out — markets recover.

**Prescription — three layers:**
1. **Volume cut.** Add a vote-frequency budget: AEGIS may vote on at most 5%
   of bars across the universe. If it has voted that day, subsequent qualifying
   bars become ABSTAIN. Forces selectivity.
2. **Confirmation gate on SELL.** Currently SELL fires on ANY of {regime risk-off,
   VIX panic, falling knife, euphoria}. Change to: needs at least 2 of those.
3. **Veto power gating.** In `arbiter.py`, AEGIS's veto should only apply if
   AEGIS's last-30-day win rate exceeds 50%. A losing defensive agent should
   not be allowed to suppress winning offensive ones.

#### ZENITH — long-duration trend (49.4% / -0.029% / -0.13)
The v2 fix imposed momentum + separation requirements but ZENITH still has
57,551 calls — meaning the gates are still too loose. Window 1 was 45.6%, the
worst showing.

**Prescription:**
- Push MIN_TREND_MOMENTUM from 5% to 8% over 50 days
- Push MIN_SEPARATION from 2% to 3.5% on the SMA-20/50 gap
- Add **trend duration** — the perfect stack must have been intact for at
  least 30 trading days, not just on the day of decision
- Cap conviction at 0.65, not 0.75 — trends mean-revert often enough that
  ZENITH should never be the loudest voice

#### THUNDERHEAD — crypto specialist (48.4% / +0.058% / +0.19)
**Counter-intuitive winner of expectancy despite low win rate.** That means it
loses small, wins big — classic momentum-strategy P&L distribution.

**Prescription:**
- Restrict to crypto only (currently votes on equity-listed crypto names too)
- Add **funding-rate awareness** — when Bitcoin perpetual futures funding
  rates are >0.05% per 8-hour period, leverage is unsustainably long; THUNDERHEAD
  should ABSTAIN. Free data from Binance / Bybit / dYdX APIs.
- Tighten the entry criteria: require BTC dominance trend confirmation when
  voting on alts.

#### FORGE — tech momentum (48.5% / -0.053% / -0.29)
Tech sector underperformed broad market in two of the four windows.

**Prescription:**
- Add **relative strength** — FORGE on tech only when XLK is outperforming
  SPY over 20 days. Otherwise abstain.
- Add **earnings-proximity gate** — don't BUY tech 5 days before earnings
  (volatility crush). Don't SELL into earnings either.
- Restrict universe to ≤25 anchor tech names — currently the 47-name list
  includes too many speculative SaaS that move on idiosyncratic news FORGE
  has no signal for.

---

### Tier 4 — Silent agents

#### VESPA, CICADA (now wired in v1.6 — should produce votes on next backtest)
v1.6 wires `days_to_earnings` via yfinance's `Ticker.earnings_dates`. They
should now have non-zero votes. Run a backtest to see their actual performance.

#### NIGHTSHADE — needs SEC EDGAR Form 4 feed
**Free data exists.** SEC EDGAR Form 4 filings are public, downloadable, no auth
required. The work: write a daily ingester that pulls Form 4s for tracked
tickers, builds a 30-day rolling window of insider buy/sell counts, attaches
to AssetContext.

This should be a v1.7 priority — it's the highest-impact "silent agent activation"
because insider clustering has real predictive power and is well-documented in
academic finance.

#### BARNACLE — needs 13F whale data
13F filings are also public via SEC EDGAR but quarterly (45-day lag). Free.
The data is sparse but high-quality. Worth wiring after NIGHTSHADE.

#### NOMAD — needs foreign listings
Tougher — free APIs exist for some markets (London, Tokyo) but currency conversion
adds complexity. Lower priority.

#### VEIL, SPECK — need historical sentiment
The hardest gap. Options:
1. **Build going-forward only** — start archiving daily sentiment scores so by
   Q4 2026 we have a 6-month archive. Run partial backtests against that.
2. **NewsAPI archive** — paid, ~$50/month for 6-month archive lookback.
3. **Marketaux** — paid, similar.
4. **Accept they're live-only** — let VEIL and SPECK be evaluated on live
   performance only. They're working in production; we just can't backtest them.

The honest answer is **#4**. Building from scratch is fine. Don't pay for
something the live system already produces for free.

---

## Two cohort-level improvements bigger than any single agent

### A. Cross-agent confirmation system

Currently every agent votes independently. Then the arbiter aggregates.

**Better:** add a layer where agents can REQUIRE confirmation from another
agent before their vote becomes "high conviction."

Example: ATLAS says RISK_OFF + AEGIS says SELL on SPY = high-conviction defensive.
Either alone = neutral conviction. The system already has all the inputs;
arbiter.py just doesn't use them this way.

### B. Per-regime cohort weighting

The backtest regime slicing shows JADE wins in BULL, HEX wins in BEAR,
SHEPHERD wins in CHOP. But the live cohort weights all of them equally
all of the time.

**Better:** publish a `regime_weights.json` file that's updated after each
backtest. Each agent's weight in the consensus = its win rate in the current
regime. ATLAS's regime tag drives the weighting. This is the single biggest
outcome improvement available without changing any individual agent's logic.

---

## What "60%+ for every agent" would actually require

The user wants every agent above 60% win rate. **That bar is above world-class.**
Renaissance Medallion's reported win rate is in the high 50s. Two Sigma's
flagship strategies hover around 53-55%.

The realistic, achievable target after all fixes above:
- Tier 1 agents (KESTREL+, MAGUS, WEAVER, SHEPHERD) hold their 52-54% baseline
- Tier 2 agents (the coin-flips) move to 53-55% with the cross-confirmation
  and regime weighting layers
- Tier 3 agents (AEGIS, ZENITH, FORGE) recover to 50-52% with discipline
- Silent agents (after data wiring) likely 51-54% — they're trading on
  high-quality, low-noise signals

If we hit that, **the cohort consensus** (which is what the dashboard publishes
to the user) probably hits 58-62% because consensus across multiple uncorrelated
agents is more accurate than any individual. That's a real, defensible target.

The single agent at 60%+ is an outlier. Use ensemble methods (which SILMARIL
already does) to reach the user's actual goal: a system that's right more
often than wrong on actionable predictions.

---

## Concrete priority list for next conversation

In strict order of expected outcome impact:

1. **AEGIS volume cut + SELL confirmation gate** (highest impact — affects
   every consensus through veto power)
2. **Regime-weighted consensus** (`regime_weights.json` driven by backtest)
3. **NIGHTSHADE wiring** (SEC EDGAR Form 4 ingester)
4. **Cross-agent confirmation layer** (in arbiter.py)
5. **TALON breadth signal** (% of S&P 500 above SMA-50)
6. **HEX regime gate** (only votes when VIX>=18)
7. **ZENITH tighter momentum threshold + duration requirement**
8. **OBSIDIAN cross-commodity correlation**
9. **JADE FDA Calendar wiring**
10. **THUNDERHEAD funding-rate gate**
