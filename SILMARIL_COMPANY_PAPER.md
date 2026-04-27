# SILMARIL — Company Paper

**Version:** 6.2 (Post-LLM-Handoff Refactor)
**Repository:** github.com/TheSeanMitchell/SILMARIL
**Live site:** theseanmitchell.github.io/SILMARIL
**Project owner:** Sean Mitchell
**Document purpose:** A comprehensive technical reference written for AI assistants (Claude, ChatGPT, Gemini, Grok) to immediately understand the entire system in one read. Every architectural decision, every agent's job, every data flow, every known weakness is documented here.

---

## 1. What SILMARIL Is

SILMARIL is a **multi-agent financial intelligence simulator**. It runs every 30 minutes during US market hours, ingesting live prices from Yahoo Finance and news sentiment from open RSS feeds, and producing a daily debate among 22 distinct agents about ~348 tracked assets across stocks, ETFs, crypto majors, low-cap tokens, hard currencies, oil, and prediction markets.

The output is a single static dashboard at theseanmitchell.github.io/SILMARIL hosted on GitHub Pages. The dashboard shows: today's consensus, dissent, trade plans surviving a risk filter, broker deeplinks for human-in-the-loop execution, five $10 compounder agents reincarnating after death, two $10K career operators specializing by domain, prediction-market plays via Polymarket and Kalshi, real-time catalyst roundup, full agent roster with player-card-style scoring stats, career mode for users to play against the agents with $10K of fake money, LLM handoff prompts to stress-test any view with an external model.

The Tolkien naming (SILMARIL, Laurelin, Telperion) is intentional decoration — the system is a serious financial reasoning engine that happens to wear an aesthetic.

## 2. The 22 Agents

The cohort splits into three groups by role:

### 2.1 Main Voters (15)

These vote in the consensus debate. Each has a specialty and abstains on assets outside their domain — silence as signal. Their abstention is a refusal to add noise.

| Codename | Specialty | Temperament | Inspiration |
|---|---|---|---|
| **AEGIS** | Risk-first guardian | Cautious constructive — only signals BUY when calm volatility + clean trend | The shield that blocks bad trades |
| **FORGE** | Trend-momentum builder | High-conviction on confirmed uptrends with sentiment + technicals aligned | The smith who builds positions in the fire |
| **THUNDERHEAD** | Macro/contrarian | Heavyweight bear on overbought tape; loud when consensus is too rosy | The storm before regime change |
| **JADE** | Sector rotation | Identifies which sector is leading vs lagging the broader tape | The strategist who sees the field |
| **VEIL** | Sentiment-driven | Acts on news flow — bullish when sentiment > +0.3, bearish < -0.3 | The reader of the room |
| **KESTREL** | Mean reversion | Fades extremes — sells overbought, buys oversold | The hawk that strikes in pullbacks |
| **OBSIDIAN** | Commodities specialist | Only votes on metals, oil, energy ETFs | The hard-asset realist |
| **ZENITH** | Multi-timeframe trend | Looks for "perfect stack": price > SMA20 > SMA50 > SMA200 | The cosmic alignment hunter |
| **WEAVER** | Cross-asset correlation | Spots when stocks and crypto are diverging | The pattern-weaver |
| **HEX** | Technical-only | Pure RSI/MACD/Bollinger Band signals, ignores news | The mathematician |
| **SYNTH** | Macro regime | RISK_ON cyclical exposure, RISK_OFF defensive | The conductor of regime |
| **SPECK** | Low-coverage edge | Looks for assets with thin news flow but rising prices | The early-bird scout |
| **VESPA** | Volatility-aware | High-VIX → cash; low-VIX → growth | The volatility strategist |
| **MAGUS** | Index-only oracle | Only votes on SPY/QQQ/IWM/DIA | The big-picture seer |
| **TALON** | Index futures only | Only votes on /ES /NQ /YM equivalents | The futures hawk |

### 2.2 Specialist Career Operators (2 × $10,000 portfolios)

These do **not** vote in the debate. They take consensus as input and apply their own discipline as a filter.

- **THE BARON** — Oil & energy specialist. Universe: USO, BNO, UCO, SCO, DRIP, UNG, BOIL, KOLD, XLE, XOP, OIH, GUSH, AMLP, plus integrated majors (XOM, CVX, COP, OXY, SLB, VLO, PSX, MPC) and explorers (HES, EOG, PXD, MRO, APA, DVN). Trades up to 2× per day. Catalyst-aware: pre-positions for EIA inventory print every Wednesday 10:30 AM ET, OPEC+ meetings, hurricane season disruptions.
- **STEADFAST** — American blue-chip patriot. Universe: 45 "Crown Jewels" (AAPL, MSFT, NVDA, GOOGL, META, AMZN, BRK-B, JNJ, UNH, XOM, JPM, V, MA, HD, PG, KO, PEP, WMT, COST, MCD, DIS, NKE, ABBV, LLY, PFE, MRK, BAC, WFC, ABT, TMO, LIN, ACN, CRM, ADBE, ORCL, CSCO, AVGO, BLK, GS, MS, SCHW, CAT, DE, BA, HON, RTX, LMT, NOC). Buys quality on dips, never chases hype, 30-day minimum hold. Refuses to sell into a panic.

### 2.3 Compounder Agents (5 × $10 starting capital)

These are deliberately small-stakes agents designed to make their philosophy visible through compounding mechanics. When their balance falls below $0.50 (death threshold), they "reincarnate" with a fresh $10 — death is an instructive feature, not a bug. Each has a different cycle and discipline:

- **SCROOGE** — The patient miser. 1 rotation per day max. Fee-aware (won't rotate unless edge ≥ 2.0× round-trip cost). Universe: top liquid ETFs.
- **MIDAS** — Hard-currency compounder. Universe limited to FXE, FXY, FXF, UUP, GLD. 7-day minimum cycle. The "preserve capital" archetype.
- **CRYPTOBRO** — Multi-trade crypto compounder. 5 trades/day cap. Fee-aware (1.5× threshold for fast trades). Universe: top crypto majors. The highest-volatility tolerance archetype.
- **JRR_TOKEN** — Two-tier token trader. $5 in SUB-$100M coins, $5 in OVER-$100M coins. 6 trades/day per tier (12 total). Targets high-volatility low-cap tokens.
- **SPORTS_BRO** — Polymarket + Kalshi only. Half-Kelly sizing. 8 bets/day max. Settlements based on bet deadline + current market probability proxy. Never traditional sportsbooks.

## 3. The Decision Pipeline

### 3.1 Daily Cycle

Every cron run (every 30 min during market hours; 4×/day on weekends for crypto):

1. **Ingest**: `fetch_universe_prices(tickers)` pulls 14 months of OHLC for each of the 348 tickers via yfinance batch download. RSS sentiment via per-ticker Yahoo + finance-tuned VADER lexicon.
2. **Build contexts**: each ticker becomes an `AssetContext` with price, history, indicators (SMA-20/50/200, RSI-14, ATR-14, Bollinger width), sentiment score, headline list, market regime, VIX level.
3. **Each main agent's `judge(ctx)` returns a `Verdict`**: signal (STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL/ABSTAIN), conviction [0..1], rationale string, and optional `suggested_entry`/`suggested_stop`/`suggested_target` for plan-eligible signals.
4. **Arbiter aggregates**: weights each verdict by scoring system's weight multiplier (0.85× for underperforming agents, up to 1.25× for proven ones). Computes consensus signal and agreement score per asset.
5. **Once-per-day gate**: if any compounder has already acted today (history shows action with `date == today_iso`), skip its act() — don't double-trade on the next cron run.
6. **Specialist actions**: surviving compounders + Baron + Steadfast act on consensus output, each respecting their own discipline.
7. **Trade plan generator**: builds plans from STRONG_BUY consensus with conviction-weighted entry/stop/target. Caps target at +12% above entry, clamps stop between 1.5% and 6%.
8. **Risk engine**: filters plans through daily DD freeze (-8% kills the plan), kill switch (any agent with weight<0.85× after 15+ scored calls is frozen), cohort safe mode (system-wide -5% triggers conservative defaults).
9. **Scoring**: yesterday's predictions get scored against today's actual price moves. Weight multipliers update.
10. **Output**: 15 JSON files written to `docs/data/`. GitHub Action commits + pushes. GitHub Pages rebuilds.

### 3.2 The Once-Per-Day Gate (Critical Bug Fix)

Before this fix, every cron run was treated as a fresh trading day. After 30 min, SCROOGE rotated again. After 4 runs, his books showed 4 days of trading and inflated returns. The orchestration-level gate (`_scrooge_already_acted_today`, `_midas_already_acted_today`, plus the portfolio-loop's `already_acted_today` check for Baron/Steadfast/main agents) ensures trade decisions fire **exactly once per UTC date per agent**. Multi-trade agents (CryptoBro 5/day, JRR Token 12/day, Sports Bro 8/day, Baron 2/day) respect their per-day caps inside their own logic.

Mark-to-market still happens on every cron run so the dashboard equity figures stay current. What's gated is the trade decision.

### 3.3 The NaN Guard (Three Layers)

Python's `json.dump` happily emits `NaN` and `Infinity` — invalid JSON that crashes JavaScript's `JSON.parse`. Fix at three layers:

1. **Source**: `analytics/technicals.py` skips NaN inputs in ATR; `compute_all()` sanitizes any NaN/Inf indicator output to None.
2. **Write**: every JSON write goes through `_sanitize_for_json()` recursive helper plus `allow_nan=False`. Loud Python error rather than silent broken JSON.
3. **Read**: frontend `loadData()` is tolerant — strips NaN/Infinity tokens from text before `JSON.parse` so legacy stale JSON doesn't break the page.

## 4. Data Flow

### 4.1 Inputs
- **yfinance** (open): 14-month OHLC daily candles for all 348 tickers via batch download.
- **Yahoo Finance RSS** (open): per-ticker headline feeds.
- **EIA API** (free, key required): weekly crude inventory schedule. Key in `EIA_API_KEY` repo secret.
- **Finnhub API** (free tier, key required): earnings calendar, press releases. Key in `FINNHUB_API_KEY` repo secret.
- **Polymarket gamma API** (open): prediction markets (currently demo data, live wiring straightforward).
- **Kalshi API** (open): prediction markets (currently demo data).

### 4.2 Outputs (15 JSON files in docs/data/)
- `signals.json` — consensus debates per asset, full verdict list, agent roster, meta
- `trade_plans.json` — risk-filtered plans with entry/stop/target/shares + broker deeplinks
- `scrooge.json`, `midas.json`, `cryptobro.json`, `jrr_token.json`, `sports_bro.json` — per-compounder state
- `agent_portfolios.json` — main 15 agents' $10K portfolios + Baron + Steadfast
- `scoring.json` — Truth Dashboard: win rate, EV, weight multipliers
- `risk_state.json` — frozen agents, cohort safe-mode triggers
- `catalysts.json` — daily + weekly catalysts with clickable source links
- `charts.json` — per-ticker OHLC bundles for chart rendering
- `sports_markets.json` — Polymarket + Kalshi listings sorted by edge
- `handoff_blocks.json` — LLM handoff prompts (debate, scrooge, midas, cryptobro, jrr_token, sports_bro, baron, steadfast, macro, per-asset, per-plan)
- `history.json` — rolling 120-day equity curve snapshots

### 4.3 Storage Model
GitHub-native: code lives in `silmaril/` Python package, dashboard in `docs/index.html`, data in `docs/data/*.json`. GitHub Pages serves `docs/` directly. Every workflow run commits and pushes the data delta. No database, no server, no auth. Just static files.

## 5. The Dashboard

Single self-contained `docs/index.html` (~4000 lines, ~1.3MB rendered). All CSS and JS inline. Loads 15 JSON files via `fetch()` on page load. No build step, no bundler.

### 5.1 Layout (Top to Bottom)
1. **Header** — site title, last-updated timestamp, regime + VIX
2. **Featured Debate** (left) + **Full Debate** (right) two-column
   - Featured: full transcript of consensus on the highest-agreement asset, agent verdicts, recent headlines, embedded chart with timeframe selector + line/candle toggle, agent vote panel below chart
   - Full Debate: scrollable list of all 348 assets with quick-search, click to feature, color-coded asset class tags, asset logos via Clearbit + letter-block fallback
3. **Compounder Grid** — 5 cards (SCROOGE, MIDAS, CryptoBro, JRR Token, Sports Bro), each showing: balance, life #, days alive, peak/deaths/lifetime trades/daily cap, current position with execution receipt, last narrative bubble, expandable trade history (last 25 actions)
4. **Compounder Matchup** — bar chart % return from $10 inception, 5 rows, scaled symmetrically around 0%
5. **Specialists** — Baron + Steadfast in two large cards. Each shows: philosophy, equity, cash, position value, realized P&L, lifetime fees, win rate, current position with stop/target, narrative, Today's Watchlist (their domain assets ranked by debate agreement), expandable trade history
6. **Risk Engine Dashboard** — cohort-level frozen agents, kill switches, safe mode status
7. **Career Mode** — 10 user profile slots × $10,000 each, leaderboard against all agents + compounders
8. **Truth Dashboard** — agent scoring leaderboard with WIN%, EV, weight multiplier
9. **All Tracked Assets** — filterable/sortable/searchable table with watchlist star toggle
10. **Prediction Markets** — Polymarket + Kalshi rows, clickable, sorted by edge
11. **Agent Roster** — player-card-style: WIN%, EV, weight, scored-call count, mini portfolio strip
12. **Trade Plans** — surviving plans with full execution detail, broker deeplinks
13. **Catalysts Roundup** — daily + weekly events with clickable source links (Yahoo, EIA, FOMC, BLS, OPEC, SEC, Earnings Whisper)
14. **Compounder Mortality** — death chart across all 5 compounders
15. **Tutorials** — 5-question expandable Q&A
16. **LLM Handoff** — tabbed panel: Daily Debate / SCROOGE / MIDAS / CRYPTOBRO / JRR TOKEN / SPORTS BRO / BARON / STEADFAST / Featured Asset Deep Dive / Macro Brief
17. **About** — mission statement, disclaimers, source attribution

### 5.2 LocalStorage Keys
- `silmaril_careers_v3` — 10 career mode slots, $10K each, migration from v1/v2
- `silmaril_watchlist_v1` — list of starred tickers

## 6. Asset Class Detection

Rules in `detectAssetClass(ticker)`:
- Ends with `-USD` and not in token list → **crypto**
- Ends with `-USD` and in token list (PEPE, FLOKI, BONK, WIF, MOG, TURBO, BRETT, POPCAT, SHIB, JTO, ENA, PYTH, TIA, DYM, ALT, STRK, MEW, PNUT, ARB) → **token**
- UUP, UDN, FXE, FXY, FXF, FXB, FXC, FXA → **fx**
- GLD, IAU, GDX, GDXJ, SLV, SIVR, PPLT, PALL, CPER → **commodities**
- USO, BNO, UCO, SCO, DRIP, UNG, BOIL, KOLD, XLE, XOP, OIH, GUSH, AMLP → **energy**
- Starts with SPY/QQQ/IWM/DIA/VTI/EFA/EEM/XL/XOP/VOO/BND/TLT/HYG/LQD/IBB/XBI/IYR/SMH/SOXX/ARKK → **etf**
- Default → **equity**

Color coding visible everywhere ticker is shown:
- equity = gold, etf = sky-blue, crypto = mint, token = rose, fx = silver, commodities = burnt-orange, energy = burnt-orange, prediction = purple

## 7. The Risk Engine

Three-layer protection:

### 7.1 Daily Drawdown Freeze
Any agent whose 1-day equity drops 8%+ has all new trades blocked for that day.

### 7.2 Track-Record Kill Switch
Any agent with >15 scored calls and weight multiplier < 0.85× is **frozen** indefinitely. Their verdicts no longer count in arbitration. Currently HEX is frozen (0% win rate after 15 calls).

### 7.3 Cohort Safe Mode
If the entire main-15 cohort drops more than 5% in a single day, **all** plans get a conservative override: stops widen to 4%, position sizes shrink to 1% of capital. Reset on next green day.

## 8. Trade Plan Realism

Generator caps to prevent unrealistic plans:
- **Target ≤ +12%** above entry. (Earlier bug: AAPL plan with $294 target when AAPL had never traded above $260.)
- **Stop between 1.5% and 6%** below entry. Tighter than 1.5% gets eaten by fees+spread; wider than 6% isn't a stop, it's a hope.
- **Reward-to-risk ≥ 1.5:1** enforced by construction.
- Conviction-weighted aggregation across all backers (only BUY/STRONG_BUY voters with finite suggested levels participate).
- Filtered plans show in `trade_plans.rejected[]` with reason; survivors in `trade_plans.plans[]`.

## 9. Sports Bro Settlement Mechanism

Two paths:
1. **Explicit**: bet has `resolved: true` and `won: bool` from venue API.
2. **Deadline proxy**: bet's `deadline` date has passed → look up current `market_prob` from today's markets feed → if YES side and prob ≥ 0.50, mark won; if NO side and prob < 0.50, mark won. Resolution basis logged as `"deadline-passed proxy (mkt 67%)"`.

Payout math: YES bet at price *p* pays multiplier `1/p` of stake on win, $0 on loss. So a $1 bet at 40¢ pays $2.50 on win = $1.50 profit, –$1.00 on loss.

## 10. Why Demo Mode Is Now Deterministic

`gen_history()` in `cli.py` was seeded from `hash(center) & 0xFFFF` — Python's hash randomization meant every process produced different prices for the same ticker. Different cron runs = different demo data = different agent decisions = phantom drift between runs. Fix: seed from `f"{ticker_key}:{today_iso}:{int(price_anchor*100)}"` so every same-day run produces identical demo data. **Live mode unaffected** — yfinance prices are stable for a given timestamp.

## 11. The 348-Asset Universe

Live mode merges core + expanded universes via `all_entries()`:
- Core (silmaril/universe/core.py): INDICES, SECTOR_ETFS, MEGA_CAPS, TECH_GROWTH, CRYPTO, COMMODITIES, BONDS_RATES, FX_MACRO
- Expanded (silmaril/universe/expanded.py): full S&P 500 plus top crypto plus low-cap tokens plus full oil complex plus hard currencies

Deduplicated by ticker. Result: 348 assets in live mode, ~25 in demo (curated demo set).

## 12. The GitHub Workflow

### 12.1 daily.yml
Triggers: cron `*/30 13-21 * * 1-5` (every 30 min during US market hours) + `0 0,6,12,18 * * 0,6` (weekend crypto refresh) + manual dispatch. Runs Python pipeline with FINNHUB_API_KEY and EIA_API_KEY env vars from secrets, then commits and pushes the docs/data delta.

### 12.2 reset.yml
Manual trigger. Requires typing "RESET" to confirm. Wipes all stateful JSON files (scoring, history, risk_state, all compounder states, agent_portfolios, signals, trade_plans, etc.), then runs a clean `python -m silmaril --live` cycle and commits. Used after major bug fixes to start tracking from a clean state.

## 13. The LLM Handoff System

Bring-your-own-LLM stress testing. `handoff_blocks.json` contains 11 prompt templates:

1. **debate_summary** — full debate transcript across all 348 assets
2. **scrooge_narrative** — SCROOGE's last few moves, asks LLM to critique
3. **midas_narrative** — MIDAS's hard-currency moves
4. **cryptobro_narrative** — CryptoBro's recent rotations
5. **jrr_token_narrative** — JRR Token's two-tier moves
6. **sports_bro_narrative** — Sports Bro's bet log
7. **baron_narrative** — Baron's oil positioning
8. **steadfast_narrative** — Steadfast's blue-chip discipline
9. **macro_brief** — 5-bullet macro summary request
10. **per_asset[ticker]** — deep dive on the featured asset
11. **per_plan[ticker]** — stress test of a specific surviving trade plan

Each prompt has 4 handoff strategies: ChatGPT (URL param prefill), Claude (copy + open homepage), Gemini (URL param), Grok (copy + open). Display as a tabbed panel in the dashboard, one tab per narrative.

## 14. Career Mode

10 user profile slots × $10,000 starting capital each. Stored in `localStorage` under key `silmaril_careers_v3`. Migration logic: if older v1/v2 data is loaded, slots are padded to 10. User trades against the same prices the agents see, with realistic fees (SEC Section 31, FINRA TAF, commission, spread). Leaderboard shows user slots ranked alongside all 22 agents.

## 15. The Truth Dashboard

Scoring per agent based on next-day price move vs the agent's signal:
- **Win**: BUY signal where next close > today's close, or SELL where next < today
- **Loss**: opposite
- **Push**: HOLD or |next_change| < 0.5%

Stats accumulate over rolling window. Weight multiplier = `0.85 + 0.40 × win_rate` for agents with ≥10 scored calls; 1.00× neutral otherwise. Below 0.85× after 15 calls = frozen.

## 16. The Agent Vote Panel (Below Chart)

Replaced the cramped `△ AEGIS △ VEIL ▽ HEX` overlay markers. New design: grid of cells below the chart, one per agent who voted (or abstained), color-coded left border by agent identity, signal label inside, conviction percentage, hover tooltip showing the rationale. Clean, scannable, doesn't fight the chart for visual space.

## 17. The Candle Toggle

For crypto and tokens, the chart defaults to candlesticks rendered as inline SVG. For stocks/ETFs/FX/commodities, defaults to the gold area-line chart. Toggle button (🕯/〜) in the chart header swaps between modes. Both render from the same OHLC bundle.

## 18. Known Limitations

- **No order placement**: dashboard is read-only. Broker deeplinks send the user to the broker's asset page; the user reviews and places the trade themselves.
- **No real-time pricing**: yfinance data is end-of-day. Intraday accuracy depends on yfinance's free-tier latency.
- **Sentiment scoring is simple**: VADER lexicon tuned for finance terms. Not GPT-grade sentiment.
- **Prediction markets are demo**: live wiring to Polymarket gamma API + Kalshi v2 is straightforward but not yet flipped.
- **Backtesting is incomplete**: scoring measures next-day moves only. No multi-day, no Sharpe, no max drawdown computation per agent.
- **No leverage modeling**: all positions assumed unlevered cash.
- **Crypto-token edge depends on RSS coverage**: low-cap tokens get sparse news flow; agents fall back to pure technicals.

## 19. Deployment Procedure

1. Repository: `github.com/TheSeanMitchell/SILMARIL`
2. Press `.` from the repo page → opens github.dev
3. Drag the unzipped `silmaril/` folder over existing files in the editor
4. Commit with descriptive message
5. Push
6. GitHub Pages rebuilds in ~30 seconds at theseanmitchell.github.io/SILMARIL
7. Optional: Actions tab → run "SILMARIL Reset" with "RESET" confirmation to wipe accumulated state

## 20. File Map

```
silmaril/
├── silmaril/                    # Python package
│   ├── __main__.py              # python -m silmaril entry
│   ├── cli.py                   # Main orchestration
│   ├── agents/                  # All 22 agent definitions
│   │   ├── base.py              # Agent + Verdict + Signal types
│   │   ├── bios.py              # Long-form bios for each agent
│   │   ├── aegis.py … talon.py  # 15 main voters
│   │   ├── baron.py, steadfast.py  # 2 specialist career operators
│   │   ├── scrooge.py, midas.py, cryptobro.py, jrr_token.py, sports_bro.py  # 5 compounders
│   │   └── fee_aware_rotation.py  # Shared fee-edge math
│   ├── universe/
│   │   ├── core.py              # INDICES, MEGA_CAPS, etc + all_entries()
│   │   └── expanded.py          # Full S&P 500 + tokens + oil complex
│   ├── ingestion/
│   │   ├── prices.py            # yfinance batch loader
│   │   └── news.py              # RSS sentiment
│   ├── analytics/
│   │   ├── technicals.py        # SMA, RSI, ATR, Bollinger
│   │   └── sentiment.py         # Finance-tuned VADER
│   ├── debate/
│   │   └── arbiter.py           # Consensus aggregator
│   ├── trade_engine/
│   │   └── plans.py             # Plan generator + realism caps
│   ├── execution/
│   │   └── detail.py            # Realistic fee modeling
│   ├── risk/
│   │   └── engine.py            # DD freeze, kill switch, safe mode
│   ├── scoring/
│   │   ├── outcomes.py          # Win/loss scoring
│   │   └── regime_tags.py       # Regime classification
│   ├── portfolios/
│   │   └── agent_portfolio.py   # $10K portfolio mechanics
│   ├── handoff/
│   │   ├── blocks.py            # LLM prompt builders
│   │   ├── deeplinks.py         # ChatGPT/Claude/Gemini/Grok URL builders
│   │   └── brokers.py           # Broker deeplink generation
│   ├── catalysts/__init__.py    # Daily + weekly catalyst roundup
│   ├── charts/__init__.py       # Per-ticker chart bundles
│   ├── sports/__init__.py       # Polymarket + Kalshi clients
│   ├── cache/
│   │   └── market_hours.py      # NYSE/CRYPTO/FX/FUTURES schedules
│   ├── output/
│   │   └── (writers)
│   └── leaderboard/
│       └── (rankings)
├── docs/                        # GitHub Pages root
│   ├── index.html               # Self-contained dashboard (~4000 lines)
│   └── data/                    # 15 JSON files written by pipeline
└── .github/workflows/
    ├── daily.yml                # Cron + env-var-driven runs
    └── reset.yml                # Manual wipe-and-clean
```

## 21. The Two Trees

The dashboard's footer references **Laurelin** (gold) and **Telperion** (silver). They're the two trees of Valinor in Tolkien's mythology, the source of light before the sun and moon. SILMARIL is the gem that captured their light. The metaphor in this project: market signal as light. Many sources, one captured essence. The gold and silver palette throughout the dashboard is the visual continuation of the metaphor.

## 22. Mission Statement

SILMARIL is a learning system, not a trading recommendation engine. It exists to make the difference between *signal* and *noise* legible: how 15 different decision frames look at the same asset on the same day, how fees and slippage and discipline compound, which agents earn their weight and which collapse, which catalysts move which sectors. **It is not financial advice.** Past performance is not indicative of future results. Markets change faster than any system. The agents themselves can be wrong, and several of them (CryptoBro, JRR Token, Sports Bro) are designed to fail in instructive ways.

What you can do here: watch agents debate; learn how friction compounds; track which voices earn trust; play career mode against them; copy LLM handoff prompts to stress-test today's call against a model of your choice; tap a broker deeplink to take the trade in your own account, where you and only you decide.
