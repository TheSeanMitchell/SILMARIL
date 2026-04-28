# SILMARIL — Project Summary (Alpha 1.6)

**As of 2026-04-28. Owner: Sean Mitchell. Repo: github.com/TheSeanMitchell/SILMARIL.
Live site: theseanmitchell.github.io/SILMARIL.** This file exists so Sean can hand
SILMARIL off to a fresh conversation (with Claude or another AI) without re-explaining
the project from scratch. It is comprehensive on purpose. Read it before doing anything.

---

## 1. What SILMARIL is

A multi-agent financial intelligence dashboard. Twenty-two AI strategists (each
with a distinct trading philosophy) vote on every tracked asset. Their consensus
is published as a JSON-driven static dashboard hosted on GitHub Pages. The
project is funded by zero outside money, runs entirely on free tiers (GitHub
Actions, yfinance, RSS feeds), and refreshes itself every 30 minutes during
US market hours via scheduled GitHub Actions workflow.

The thematic frame is Tolkien's Silmarils — three jewels containing the light
of the Two Trees, Laurelin (gold) and Telperion (silver). The dashboard's
visual language is built around that.

The educational frame is a Marvel Cinematic Universe ensemble — each agent has
a Marvel-character archetype that explains its decision philosophy in plain
language for non-finance users.

---

## 2. Architecture

```
┌─ silmaril/                       (Python package)
│  ├─ agents/                      22 strategist classes + base ABC + lifecycle wrappers
│  ├─ analytics/                   technicals, sentiment, regime classifier
│  ├─ backtest/                    4-year out-of-sample replay framework
│  ├─ catalysts/                   OPEX, index rebal, macro, crypto unlocks, ex-div, earnings
│  ├─ charts/                      OHLC chart bundle generator
│  ├─ debate/                      arbiter — assembles consensus from votes
│  ├─ execution/                   broker mapping, fees, settlement
│  ├─ handoff/                     LLM consensus block builder, broker deeplinks
│  ├─ ingestion/                   yfinance prices, RSS news, market hours
│  ├─ portfolios/                  agent portfolio models (Baron, Steadfast)
│  ├─ risk/                        kill-switch engine for compounders
│  ├─ scoring/                     truth dashboard (live-prediction outcome tracker)
│  ├─ sports/                      Polymarket / Kalshi market fetcher
│  ├─ trade_engine/                trade plan generator
│  ├─ universe/                    ~360 ticker universe, expandable
│  ├─ cli.py                       entry point — orchestrates daily runs
│  ├─ __main__.py                  python -m silmaril CLI dispatcher
│  └─ __init__.py
├─ docs/                           GitHub Pages output (committed JSON + index.html)
│  ├─ index.html                   single-page React-free dashboard, ~5000 lines
│  └─ data/                        all generated JSON files (every cycle commits here)
├─ .github/workflows/
│  ├─ daily.yml                    every 30min during market hours; live data refresh
│  ├─ backtest.yml                 manual trigger; runs 4-yr replay framework
│  └─ reset.yml                    manual trigger; wipes accumulated state
└─ requirements.txt                (yfinance, feedparser, pandas, numpy, requests)
```

Daily runs commit JSON to `docs/data/`. The dashboard fetches those files at
load time and renders client-side. There is no server, no database, no auth.
This is the design: maximum auditability, zero ongoing cost.

---

## 3. The 22 strategists

| Codename | Specialty | Marvel Archetype | Active calls (4yr full) | Live status |
|---|---|---|---|---|
| **AEGIS** | Capital preservation, defensive cornerstone, veto power | Captain America | 53,326 | active |
| **FORGE** | Tech-sector momentum | Iron Man | 19,261 | active |
| **THUNDERHEAD** | Crypto specialist | Thor | 19,850 | active |
| **JADE** | Healthcare & biotech | Hulk | 7,222 | active |
| **VEIL** | Sentiment-driven contrarian | Scarlet Witch | 0 (needs sentiment) | live-only |
| **KESTREL** | Mean-reversion (RSI extremes) | Hawkeye | 10,411 | active |
| **OBSIDIAN** | Commodities & resources | Black Panther | 2,704 | active |
| **ZENITH** | Long-duration trend | Captain Marvel | 57,551 | active |
| **WEAVER** | Cross-asset correlation | Spider-Man | 40,902 | active |
| **HEX** | Bear-market specialist | Doctor Strange | 55,210 | active |
| **SYNTH** | Cross-market rotation | Vision | 4,276 | active |
| **SPECK** | Microcap / sentiment | Ant-Man | 0 (needs sentiment) | live-only |
| **VESPA** | Catalyst-window event trader | Wasp | 0 (needs earnings + news) | live-only |
| **MAGUS** | Macro index strategist | Doctor Strange variant | 4,860 | active |
| **TALON** | Market structure / indices only | Falcon | 1,603 | active |
| **MIDAS** | $1 hard-currency compounder ($1 → ?) | King Midas | $1 compounder |
| **CRYPTOBRO** | $1 crypto compounder | retail bro | $1 compounder |
| **JRR_TOKEN** | $1 meme-token compounder | parody | $1 compounder |
| **SCROOGE** | $1 dividend compounder | Scrooge McDuck | $1 compounder |
| **SPORTS_BRO** | Polymarket/Kalshi prediction-market trader, 48hr filter | Avengers prop-bet guy | $1 compounder |
| **ATLAS** *(v2)* | Macro regime caller | mythological | 2,739 | active |
| **NIGHTSHADE** *(v2)* | Form 4 insider cluster detector | — | 0 (needs SEC data) | wired-future |
| **CICADA** *(v2)* | Pre-earnings whisper trader | — | 0 (now wired in v1.6) | live-only |
| **SHEPHERD** *(v2)* | Bond & rate-sensitive specialist | — | 1,653 | active |
| **NOMAD** *(v2)* | ADR / home-listing arbitrage | — | 0 (needs foreign feeds) | wired-future |
| **BARNACLE** *(v2)* | 13F whale follower | — | 0 (needs 13F feeds) | wired-future |
| **KESTREL+** *(v2)* | Hurst-aware mean reversion | — | 706 | **#1 in backtest** |

The 7 v2 agents (atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus)
were added during the v2 push. Five of them require external data feeds we
haven't wired yet. KESTREL+ is the highest-Sharpe strategist on the
out-of-sample backtest.

Two agents — **THE BARON** (oil/energy) and **STEADFAST** (American blue-chip) —
also exist. They are strategists that ALSO run their own $10K career portfolios.
They live in the STRATEGISTS tab, not the PORTFOLIO MANAGERS tab, because they
vote in the team debate and manage capital simultaneously.

---

## 4. Five $1 portfolio managers ("compounders")

These start at $1 and try to compound. They have **lives** (death = balance below
$0.10) and a **death chart** showing their full lifecycle history. They are NOT
voting agents; they're capital allocators that take consensus + their own
discipline as input.

- **SCROOGE** — buys highest-yielding dividend stocks, hoards cash
- **MIDAS** — rotates between hard currencies (USD, JPY, CHF, gold, silver)
- **CRYPTOBRO** — rotates within top-10 crypto, no leverage
- **JRR_TOKEN** — meme-token speculator, allowed to die fast
- **SPORTS_BRO** — Polymarket / Kalshi only, half-Kelly, 48-hour close filter

---

## 5. Data flow

```
Daily run (every 30min during market hours):
   yfinance → prices → analytics (technicals, regime, vix)
                          ↓
   RSS feeds → sentiment scoring per ticker
                          ↓
   AssetContext built per ticker
                          ↓
   Each of 22 agents calls .evaluate(ctx) → Verdict
                          ↓
   debate/arbiter assembles consensus per ticker
                          ↓
   trade_engine generates plans (entry, stop, target, sizing)
                          ↓
   handoff/blocks builds LLM prompt blocks per plan
                          ↓
   compounders act on consensus (each has its own logic)
                          ↓
   scoring updates outcomes from yesterday's predictions
                          ↓
   Everything written to docs/data/*.json, committed, pushed
                          ↓
   GitHub Pages serves the static index.html which fetches and renders the JSON
```

**Backtest run (manual, ~30-40 min for full universe):**
Same pipeline but synthetic — no live news. `silmaril.backtest.replay`
builds historical AssetContexts from yfinance OHLC. Every agent votes
on every (ticker, date) tuple. Predictions are scored against next-day
returns. Output goes to `docs/data/backtest_report.json` and
`docs/data/backtest_walk_forward.json`.

---

## 6. Files in `docs/data/` (all auto-generated)

| File | Refreshes | Read by |
|---|---|---|
| `signals.json` | Every daily run | Markets tab — debates, consensus, summary |
| `trade_plans.json` | Every daily run | Execution tab + chart projections |
| `agent_portfolios.json` | Every daily run | Strategists tab — Baron + Steadfast |
| `scrooge.json` etc. | Every daily run | Portfolio Managers tab |
| `sports_bro.json` | Every daily run | Portfolio Managers tab |
| `sports_markets.json` | Every daily run | Sports Bro card source |
| `scoring.json` | Every daily run | Truth Dashboard |
| `risk_state.json` | Every daily run | Risk Dashboard |
| `catalysts.json` | Every daily run | Research tab |
| `charts.json` | Every daily run | Chart panels in featured debate |
| `handoff_blocks.json` | Every daily run | LLM Handoff Panel |
| `history.json` | Every daily run | Death Chart historical |
| `backtest_report.json` | Manual backtest only | Strategists tab Leaderboard |
| `backtest_walk_forward.json` | Manual backtest only | (future: stability badge) |

---

## 7. The dashboard (5 tabs)

**MARKETS** — featured debate, full debate table with search, asset table, prediction markets card.

**STRATEGISTS** — backtest leaderboard, the 22 agent bios, Baron + Steadfast specialist cards, career mode (visualizes per-strategist accuracy), risk dashboard, truth dashboard (live-prediction win rate).

**PORTFOLIO MANAGERS** — the 5 $1 compounders + the matchup card showing them head-to-head + death chart.

**EXECUTION** — every actionable trade plan with full broker detail (exchange, account type, settlement, fees, deeplinks to Robinhood/Schwab/Coinbase) + LLM handoff panel.

**RESEARCH** — Consolidated News Feed (v1.6 NEW), catalyst calendar, tutorials, about/glossary.

---

## 8. What's working well right now

- Live data pipeline runs reliably every 30 minutes
- All 22 agents are producing votes (15 active, 7 abstaining-by-design)
- Backtest framework runs end-to-end on full ~360-ticker universe
- Walk-forward validation working
- KESTREL+ (#1 strategist) hits 54.5% win rate on backtest, +0.65 Sharpe-ish
- 10 of the 15 voting strategists are profitable on out-of-sample data
- Dashboard tabs, search bar focus, rank badges, chart projections all working
- Concurrency lock between daily.yml and backtest.yml prevents push collisions

## 9. What's known-broken or limited (priority order for next conversation)

1. **AEGIS** is the worst-performing voting agent (47.8% win rate on 53K calls).
   It has veto power in arbiter.py, so a losing AEGIS hurts the whole cohort.
   Next conversation should diagnose AEGIS rationales on losing calls.

2. **ZENITH** has the highest call volume (57K) but is at 49.4% win rate.
   Same volume problem persists despite v2 fixes. Threshold tuning needed.

3. **5 v2 agents (NIGHTSHADE, NOMAD, BARNACLE, CICADA, VESPA) abstain in backtest**
   for lack of upstream data:
   - Insider transactions (NIGHTSHADE) — needs SEC EDGAR Form 4 feed
   - 13F whale data (BARNACLE) — needs WhaleWisdom or SEC scrape
   - ADR pairs (NOMAD) — needs foreign-listing price feed
   - Earnings whispers (CICADA) — needs Estimize (paid) or Zacks
   - VESPA needs sentiment + earnings together; v1.6 wired earnings but not historical sentiment

4. **No historical sentiment** — VEIL, SPECK, CICADA, VESPA all gate on
   sentiment_score, which is None in backtest. We can't backtest them honestly
   until we have an archive. Options: NewsAPI archive (paid), Marketaux (paid),
   build our own RSS archive going forward.

5. **Logo coverage** — Clearbit fallback works for ~70 mega-caps. Other ~290
   tickers fall back to colored letter. A monthly logo-cache workflow would fix.

6. **Chart confidence projections** show entry/stop/target only when a
   trade plan exists. They don't yet show individual agent targets when no
   consolidated plan exists.

7. **Mobile layout** — works but cramped. 5-tab nav collapses to 2-col grid
   under 768px but rest of site is desktop-first.

---

## 10. Decisions that have been made (don't re-litigate)

- **No automated paid LLM calls.** SILMARIL never spends money on inference.
  Multi-LLM consensus is manual: user copies prompt blocks, pastes into
  GPT/Claude/Gemini themselves, brings answers back.
- **No real money trading.** Stage 1 of the published roadmap is paper
  trading on Alpaca, but that's deferred until backtest stability is proven.
- **Public repo, free GitHub Actions.** Unlimited Actions minutes on public
  repos means there's no cost ceiling on backtests.
- **Static site, no auth, no DB.** Every run commits JSON to the repo so
  the audit trail is git history.
- **No crypto wallet integration.** SILMARIL recommends; the user trades
  through their own broker via deeplink.
- **Five tabs at the top, not sidebar.** Sean's preference: less scroll, more
  tab navigation. Also enables tab-persistence via localStorage.

---

## 11. Things Sean has explicitly rejected

- A separate "compounder competitions" page (the matchup card on the Portfolio
  Managers tab is sufficient)
- Discord / Telegram bot integrations (out of scope)
- Adding more strategists (22 is enough; improve what we have)
- Switching from Marvel theme to anything else

---

## 12. Coding conventions

- **Agents** subclass `silmaril.agents.base.Agent`, override `_judge(ctx)`,
  return a `Verdict(agent=, ticker=, signal=, conviction=, rationale=, factors=)`.
  Module exposes a lowercase singleton (`aegis = Aegis()`).
- **AssetContext** is a frozen dataclass with `ticker, asset_class, price,
  sma_20/50/200, rsi_14, atr_14, bb_width, sentiment_score, article_count,
  recent_headlines, days_to_earnings, market_regime, vix, ...`. Optional fields
  default to None — agents must guard for None on every read.
- **Workflows** share a concurrency group `silmaril-repo-write` so daily and
  backtest never push at the same time.
- **Backtest fields not available**: sentiment_score, article_count, event_flags,
  insider_*, whale_data, adr_local_spread_pct, consensus_eps, whisper_eps.
  Agents that need these MUST abstain gracefully when None — don't fabricate.
- **Index.html** is single-file. No build step. CSS at the top in a single
  `<style>` block. JS at the bottom in a single `<script>` block. Functions
  exported to `window` only when called from inline HTML handlers.

---

## 13. How to do common tasks

**Run a backtest:** Actions tab → SILMARIL Backtest → Run workflow → universe=demo (fast) or full (~30 min) → green button.

**Reset the live state:** Actions tab → SILMARIL Reset → type RESET → green button.

**Trigger a manual daily run:** Actions tab → SILMARIL Daily Run → Run workflow → green button.

**Edit code in github.dev:** Press `.` on the repo. github.dev opens. Edit, commit, push.

**Inspect an agent's decision logic:** Read `silmaril/agents/<name>.py`. Each agent is single-file, self-contained.

**Add a new strategist:** Create `silmaril/agents/<name>.py` subclassing Agent. Wire its lowercase singleton into `silmaril/cli.py`'s `MAIN_VOTERS` list. Add a bio entry in `silmaril/agents/bios.py` if one exists. Re-run daily to see it vote.

---

## 14. The roadmap

**Alpha 1.6 (current).** Agent threshold tuning from backtest data; concurrency lock; news feed; HOLD notifications for all compounders; trade-history timestamps; SportsBro filter diagnostic.

**Alpha 1.7 (next).** Wire historical sentiment archive (or accept that 4 agents will only earn live performance data). Address AEGIS underperformance. Logo cache workflow.

**Alpha 1.8.** First actual catalyst integrations: SEC EDGAR Form 4 (NIGHTSHADE), CFTC commitments (SHEPHERD enrichment), basic earnings calendar (CICADA enrichment).

**Beta 1.0.** Stage 1 paper-trading on Alpaca: top consensus picks of each day get a paper position; track real broker P&L vs backtest expectations.

**Beta 2.0.** Real-money phase, gated on Beta 1.0 producing >55% live win rate over 90 days.

---

## 15. Important quirks to remember

- Sean uses a 4K TV as monitor; mobile is future. Desktop-first design is correct.
- Sean lives in Las Vegas; references to "Eastern time" should be explicit (UTC offsets).
- The dashboard intentionally does NOT include ads, paywalls, or login.
- Sean is willing to KYC for Polymarket / Kalshi (read-only data is open) but isn't using paid feeds yet.
- "Going dark" in conversation means: produce one big response with the whole deliverable instead of asking clarifying questions step-by-step.
- Sean has been frustrated by past assistants making structural changes without
  reading his actual files first. Always read before writing.
