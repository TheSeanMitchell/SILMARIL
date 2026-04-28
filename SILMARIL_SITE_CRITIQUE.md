# SILMARIL — Site Critique & Improvement List (Alpha 1.6)

**Honest assessment of where the site stands as a product, what's good,
what's not, and what to do about it.**

---

## What's actually good

1. **It loads fast and works without auth.** Plain static HTML + JSON.
   No login, no paywall, no analytics tracking, no cookies.

2. **The 5-tab navigation is the right structure.** Markets / Strategists /
   Portfolio Managers / Execution / Research is the natural grouping for
   a financial-intelligence dashboard. The information architecture isn't
   the bottleneck.

3. **The backtest leaderboard is genuinely useful.** Showing ranked agent
   performance with real numbers (win rate, expectancy, Sharpe-ish, drawdown,
   equity curve) is more transparency than 95% of trading platforms offer.

4. **The Marvel-archetype framing works.** Non-finance users immediately grok
   "AEGIS is the defensive Captain America" in a way they don't grok
   "AEGIS is a defensive momentum agent."

5. **Educational copy is dense but well-written.** The catalyst calendar,
   tutorial section, glossary, and the hover tooltips on technical terms
   actually teach.

6. **The death chart for compounders is unique.** Showing a strategy's
   lifecycle — including the crashes — builds trust by showing what you're
   not hiding.

---

## What's mediocre

1. **Dense screens.** Even with 5 tabs, the Markets tab has a lot of vertical
   real estate consumed by the featured debate + full debate + asset table +
   prediction markets. On a 1080p monitor it's fine. On a 1440p+ display
   the cards spread out and look better.

2. **No timestamps on most data.** The user just asked for trade-history
   timestamps, and they're right — every action should be timestamped. Fixed
   in this drop. The same critique applies to stale-data indicators
   ("last updated 47 minutes ago") which we don't have.

3. **Sports Bro compactness.** The card design is OK but the user can't see
   AT A GLANCE why no bets were placed. Fixed in this drop with the filter
   diagnostic panel.

4. **The "Career Mode" visualization** is too cluttered. Each agent has
   a chart of their accuracy over time, but the visual treatment doesn't
   immediately communicate "this strategist is improving" vs "this strategist
   is degrading."

5. **No mobile-first effort.** Site collapses gracefully but it's clearly
   built for desktop. With ~360 tickers and lots of dense numerical content
   that's defensible — mobile would compromise the experience.

---

## What's actually broken

1. **No HOLD notifications for Baron / Steadfast.** The user noticed.
   When a daily run completes and Baron didn't trade, there's no record
   of "Baron evaluated, decided to hold." Critical for transparency. Should
   be added to those agents' history rendering. (See Open Questions for
   the implementation path.)

2. **Confidence indicators only show on featured asset.** When you click
   into another asset's chart, the entry/stop/target lines don't appear
   unless that ticker has a current trade plan. Users want to see strategist
   targets even on assets without consolidated plans.

3. **Logo coverage is partial.** ~70 mega-caps have logos via Clearbit;
   the other ~290 tickers fall back to a colored letter. Visually
   inconsistent. A monthly logo-cache GitHub Action would commit ~290 PNG
   files (~5MB total) to `docs/data/logos/` and fix this.

4. **Charts redraw their entire SVG on every state change.** Means hover
   states flicker. Fixable with virtual DOM (vanilla — using Preact
   would solve this with no build step) but probably not worth it.

5. **No way to filter the leaderboard by regime.** The backtest report has
   `by_regime` data but the dashboard only shows `overall`. Users can't see
   "who wins in CHOP markets" without opening the JSON.

6. **Search bar inside the asset table loses cursor on filter changes other
   than search itself** (signal/class/sort dropdowns trigger full re-render).
   v1.6 fixed the search-input case; the dropdowns still cause full re-render.

---

## Improvement list, prioritized

### 🔴 Tier A — should ship in v1.7 (next conversation)

| Item | Effort | Why |
|---|---|---|
| AEGIS volume cut + veto-gating | 30 min | Highest-impact agent fix; bleeds the cohort |
| Regime-weighted consensus | 2 hours | Single largest cohort-level win available without redesigning agents |
| Add stale-data indicator to topbar | 15 min | Trust-builder; "last refresh: 23 min ago · next refresh in 7 min" |
| HOLD action recording for Baron/Steadfast | 30 min | Transparency request from user |
| Add `last_run_at` to all compounder JSONs | 30 min | So freshness is visible everywhere |
| Per-regime leaderboard tab | 1 hour | Currently hidden in the JSON |

### 🟠 Tier B — v1.8

| Item | Effort | Why |
|---|---|---|
| NIGHTSHADE Form 4 ingester | 1-2 days | Activates a silent agent + provides high-quality signal |
| TALON breadth signal | 2 hours | Real edge for our market-structure agent |
| HEX regime-only gating | 30 min | Should win, currently coin-flip due to bad bull-market votes |
| Logo cache workflow | 2 hours | Visual consistency; one-time PNG commit |
| Forward-projected confidence on every chart with agent targets | 4 hours | Educational; show individual agent targets when no consolidated plan exists |
| FDA Calendar feed for JADE | 2 hours | Real catalyst data for biotech specialist |

### 🟡 Tier C — v2.0 (alpha → beta transition)

| Item | Effort | Why |
|---|---|---|
| Cross-agent confirmation layer in arbiter.py | 1 day | Quality-multiplier on consensus accuracy |
| OBSIDIAN cross-commodity correlation | 4 hours | Real signal for the commodity specialist |
| THUNDERHEAD funding-rate gate | 4 hours | Reduce false-positive longs into euphoric tops |
| Mobile-first redesign of chart panel | 1 day | Mobile experience parity |
| Live-prediction outcome tracking with 90-day rolling window | 4 hours | Truth dashboard becomes meaningfully predictive |
| Alpaca paper-trading integration (Stage 1) | 2-3 days | First real-world P&L data |

### 🟢 Tier D — beyond beta

- Multi-LLM consensus automation (still no paid LLM calls, but allow user
  to drop in their own keys voluntarily)
- Real-time WebSocket prices instead of 30-min polling
- Historical sentiment archive (going-forward only — don't pay for backfill)
- iOS / Android wrappers via Capacitor — only after mobile redesign
- Kalshi / Polymarket auth for SportsBro to actually place bets
  (read-only data is open; placing bets requires KYC)

---

## Specific UI fixes the user asked for

| Request | Status |
|---|---|
| 5-tab navigation | ✅ shipped v2.0 |
| Search bar focus fix (debate, asset, news) | ✅ shipped v1.6 |
| Confidence indicators projected on charts | ✅ shipped v2.1 |
| Logo support | ✅ partial (Clearbit fallback for ~70 mega-caps); workflow needed for full coverage |
| Rank badges on agent debate rows | ✅ shipped v2.1 |
| Tab persistence across reloads | ✅ shipped v2.0 |
| Trade history timestamps (not just date) | ✅ shipped v1.6 |
| HOLD notifications for all compounders | ✅ partial — UI ready in v1.6 (HOLD action handled in renderTradeHistory). Backend needs to actually emit HOLD entries to history when no trade fires. Add to v1.7 |
| SportsBro 48hr filter + diagnostic panel | ✅ shipped v1.6 |
| Consolidated news feed in Research tab | ✅ shipped v1.6 |
| Baron / Steadfast clarification (they're strategists, not compounders) | ✅ shipped v1.6 (subtitle updated) |
| Workflow concurrency lock (daily + backtest can't collide) | ✅ shipped v1.6 |
| Backtest predictions file kept out of commits (avoids 100MB limit) | ✅ shipped v1.6 |

---

## What this site is NOT, and shouldn't try to be

- **Not a brokerage.** It hands off to Robinhood/Schwab/Coinbase via deeplinks.
- **Not a paid signal service.** No subscription gate.
- **Not a robo-advisor.** It doesn't take custody of money.
- **Not a real-time HFT system.** 30-min polling is fine for the time horizon
  the strategists actually trade on.
- **Not a social platform.** No comments, no leaderboards of users.

Trying to be any of those would either compromise the static-site architecture
or create regulatory exposure. The current scope is correct.

---

## Honest take on the user's "60%+ for all agents" goal

The user has stated they believe all 22 agents can hit 60%+ win rates with
better catalysts and training. **This goal is not achievable in any rigorous
backtest framework**, because:

1. Win rate is heavily affected by the threshold for "active call." If we
   raise the conviction threshold to, say, 0.7, only the highest-confidence
   calls count — and selectively counting those can produce 65-70% win rates
   on small samples. But the trade-off is fewer actionable predictions.

2. Markets are roughly 52-53% predictable on liquid, well-covered assets.
   That's the baseline we're competing against. Beating 55% sustainably
   on next-day moves is genuinely good. Beating 60% sustainably on next-day
   moves requires either insider information or extreme selectivity.

3. The right metric for the user's actual goal — "make the site useful for
   making money" — is **expectancy × call frequency**, not win rate alone.
   A 51% strategy with +0.4% expectancy that fires 100 times beats a 60%
   strategy with +0.1% expectancy that fires 10 times.

The system has 4 strategists currently above 52% with positive expectancy
(KESTREL+, MAGUS, JADE, WEAVER). That's already enough for a working
ensemble. What the user really wants — and what's achievable — is to get
**the cohort consensus** (the displayed signal on the dashboard) to >55%
on actionable trades. That's a 6-12 month timeline with regime weighting
and Tier A fixes from this critique.

---

## Final recommendation

Run the site for 7-14 days as-is. Watch the dashboard. Note what frustrates
you, what you trust, what you don't. Then come back with a fresh conversation
and the SILMARIL_PROJECT_SUMMARY.md + this file. The Tier A items will be
the right starting point.
