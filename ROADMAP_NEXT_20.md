# SILMARIL — Next 20 Updates Roadmap

You asked me to envision the next 20 updates. Here's the genuine vision,
ordered roughly by leverage and difficulty. Some of these are weeks of
work. Some are an afternoon. None is fluff.

I'm being honest about what's hard: the gap between "rule-based agents
voting" and "real systematic trading platform" is wide, and that's where
updates 11-20 live.

---

## Tier 1 — Telemetry & Data Quality (Updates 2.1–2.4)

### 2.1 — Slippage feedback loop
Compare each Alpaca paper fill price to the price at signal-time. Use
the gap to calibrate the slippage model per ticker per asset class. After
30 days of fills, slippage estimates are no longer priors — they're
empirically measured.

### 2.2 — Pre-market signal pre-computation
At 8am ET, fetch overnight news, gap data, and futures levels. Run a
"pre-open debate" so that when the 9:30am open hits, the system already
has positioned signals rather than reacting late.

### 2.3 — Live equity curve attribution
For every $ of P&L on the Alpaca paper account, attribute it to specific
agents based on which agents drove the consensus. Builds the "this is
who actually made you money" panel.

### 2.4 — Backfill engine improvements
Right now backtest re-runs through current logic. Add a "frozen-logic"
backtest mode that snapshots the codebase at each historical date and
runs that version's agents. Removes look-ahead bias from logic changes.

---

## Tier 2 — New Specialist Agents (Updates 2.5–2.10)

### 2.5 — OPTIONS_FLOW agent
Reads unusual-options-activity from free sources (Cheddar Flow free tier,
Trade Alert RSS, BlackBoxStocks free signals). Large block calls in OTM
strikes 2-4 weeks out is one of the most predictive retail-accessible
signals. Universe: large-cap optionable only.

### 2.6 — INSTITUTIONAL_MOMENTUM agent
Tracks 13F changes (already free from SEC EDGAR) but with quarterly lag
mitigation: focuses on positions that show up across multiple smart-money
filings simultaneously. Ackman + Burry + Dalio all opening NVDA in same
quarter is a signal.

### 2.7 — SOCIAL_VELOCITY agent
Tracks ticker mention velocity on free sources (Reddit r/wallstreetbets
JSON API, StockTwits trending API, Google Trends API — all free).
Rate-of-change of mentions, not absolute mentions. Sudden 10x increase
in WSB mentions on a non-meme ticker is highly predictive.

### 2.8 — MACRO_LEAD agent
Reads FRED macro releases (CPI, PCE, NFP, retail sales, housing starts).
Computes surprise-vs-consensus and relates to historical sector-rotation
patterns. Free, slow-cadence, but predictive on regime flips.

### 2.9 — CRYPTO_ONCHAIN agent
For crypto names (BTC, ETH, SOL, etc.) tracks free on-chain data:
exchange inflows/outflows (large outflow = accumulation = bullish),
miner balance changes, stablecoin supply changes. Glassnode free tier
+ Coinglass free API.

### 2.10 — EARNINGS_QUALITY agent
For names announcing earnings, reads the press release (free via SEC
EDGAR 8-K filings) and scores: GAAP vs non-GAAP gap (red flag),
revenue beat sustainability, guidance change vs analyst consensus.
This is a real edge — most retail tools only show the headline beat/miss.

---

## Tier 3 — Execution & Risk (Updates 2.11–2.14)

### 2.11 — Conditional orders on Alpaca
Move from market orders to bracket orders with stop and target attached
at fill time. Alpaca supports this natively. Each consensus signal
becomes: limit-buy + stop-loss + profit-target as one bundled order.

### 2.12 — Portfolio-level risk governor
Hard caps that override per-position decisions: max sector exposure 25%,
max single-asset 5%, max gross leverage 1.5x. The governor sits between
the consensus and the broker — if a signal would breach a cap, it gets
downsized or rejected.

### 2.13 — Multi-account paper trading
Three Alpaca paper accounts running in parallel: Conservative (only
strong consensus, 3% positions), Standard (current logic), Aggressive
(includes lower-conviction signals, 7% positions). After 90 days, A/B
test which calibration won.

### 2.14 — Volatility-regime position scaling
Auto-reduce position sizing when VIX > 25, auto-increase when VIX < 15.
This is one of the highest-Sharpe overlays in systematic trading and
is purely free to implement.

---

## Tier 4 — Genuine Intelligence Layer (Updates 2.15–2.18)

### 2.15 — XGBoost meta-filter on the consensus pipeline
After 90 days of forward data, train an XGBoost classifier with features
= per-agent verdicts + regime + TOD bucket + correlation alerts +
news quality, target = next-day correct. The classifier acts as a
*post-consensus filter*: if it predicts <55% probability the consensus
is right, downsize. If >65%, full size. Free training, free inference,
significant Sharpe lift.

### 2.16 — Sentence-transformer news classification
Replace keyword-matching in catalysts with sentence-transformer embeddings
(all-MiniLM-L6-v2 is free, runs locally on CPU in <100ms). Suddenly
the system understands semantic similarity, not just keyword matches.
"Quarterly earnings disappointment" matches "missed analyst expectations"
matches "EPS shortfall."

### 2.17 — RAG-based reflection automation
Once you're comfortable spending ~$5/month on LLM API, replace the
manual reflection step with a RAG pipeline: pull yesterday's debates,
outcomes, and current positions; ask Claude/GPT to write a 3-sentence
rule. Run via GitHub Actions, write to reflections.json, commit. The
human-in-the-loop becomes optional rather than required.

### 2.18 — Auto-generated agent prompts
Right now agents are hand-coded Python rules. Add a meta-agent that,
on detected drift, writes a *new* rule and proposes it as a code change
(GitHub PR). Human approves or rejects. The system literally proposes
new strategies.

---

## Tier 5 — Platform Maturation (Updates 2.19–2.20)

### 2.19 — Multi-user mode
The "user profiles" become real accounts with their own watchlists,
their own reflection injections, their own paper-trading mirrors.
Static-site auth via GitHub OAuth (free).

### 2.20 — The bridge to live capital
After 12+ months of consistent forward live data showing positive risk-
adjusted returns AFTER slippage AFTER stress-test costs AFTER drift,
present a *defensible* go/no-go framework for moving capital. Not "let's
try $1000" — proper criteria: Sharpe > 1.0 over 12 months, max drawdown
< 15%, robust to 2% adversarial cost, no agent contributing > 30% of
P&L (concentration risk), passes all weekly stress tests for a quarter.

If those criteria are met, the next conversation is about live execution.
If they're not met, the answer is "stay paper." Either answer is a real
answer based on real data, not vibes.

---

## What I'd build next, if I had to pick

**Update 2.1 (slippage feedback loop)** — highest leverage. After 30 days
of Alpaca paper fills, you have empirical slippage per ticker. That makes
every other module's P&L estimates real instead of theoretical.

**Update 2.5 (OPTIONS_FLOW agent)** — second highest. Unusual options
activity is one of the few free signals where retail can occasionally
front-run institutional positioning.

**Update 2.11 (bracket orders)** — third. Real execution discipline. Stop
and target attached at fill time means no manual exits, no emotion,
and clean P&L attribution.

**Update 2.15 (XGBoost meta-filter)** — fourth. After 90 days of forward
data, this is the single biggest performance lift available without
adding paid data sources.

That's the honest priority order if you want to build for impact.
