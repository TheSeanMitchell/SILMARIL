# ✦ SILMARIL

**A transparent, multi-agent financial intelligence operating system.**

> *"The Silmarils held the light of the Two Trees — gold of Laurelin and silver of Telperion — preserved against the night. This system does something smaller: it preserves the reasoning behind every trade signal, so nothing is lost to a black box."*

> ⚠️ **EDUCATIONAL SIMULATION ONLY. NOT FINANCIAL ADVICE.**

---

## What it is

SILMARIL is not a trading bot. It's a **financial intelligence operating system** — a team of sixteen specialist agents that each analyze the market through a distinct lens, debate publicly, and produce fully-specified trade plans with the reasoning preserved.

Every number on the site is inspectable. Every agent's logic is a readable Python module. Every trade plan has an entry, a stop, a target, and an invalidation condition. Every debate shows who dissented and why.

**Zero paid APIs. Zero hidden LLM calls. 100% transparent.**

---

## The sixteen agents

Fifteen specialists + one saver. Each agent is a self-contained strategy with its own personality, its own portfolio, and its own reputation on the leaderboard.

| Codename | Specialty | Temperament |
|---|---|---|
| **AEGIS** | Capital Preservation | The veto cop — defends against drawdowns |
| **FORGE** | Tech-Sector Momentum | Calculated-risk innovator |
| **THUNDERHEAD** | Volatility Breakout | Explosive, high-conviction swings |
| **JADE** | Oversold Mean Reversion | Rage-buys the panic |
| **VEIL** | Sentiment Divergence | Sees what the market misses |
| **KESTREL** | Precision Entries | Patient hunter, tight stops |
| **OBSIDIAN** | Commodities & Resources | Sovereign plays, hard assets |
| **ZENITH** | Long-Duration Trend | Rides momentum to the peak |
| **WEAVER** | Micro Scalper | Many small, quick wins |
| **HEX** | Probabilistic Edge | Statistical arbitrage |
| **SYNTH** | Cross-Market Correlation | Connects the dots across assets |
| **SPECK** | Small-Cap & Overlooked | Finds the forgotten |
| **VESPA** | Event-Driven | Earnings, Fed, FDA, catalysts |
| **MAGUS** | Seasonality & Time | History rhymes |
| **TALON** | Market Structure | Index-level, breadth, regime |
| **SCROOGE** | The $1 Compounder | A single dollar, compounded forever |

SCROOGE is special. He starts with $1. Every day, he takes whatever he has and puts it entirely into the single highest-consensus trade plan. Next day, he sells and rolls it into the next. When he blows up — and he will — the counter resets to $1 and we show the reset. The pain of the reset is part of the lesson. *If you had invested just one dollar a day, here's where you'd be.*

---

## The Handoff Block

Every asset page, every debate, every trade plan ends with a **Handoff Block** — a copy-ready context bundle with one-click deep-links to your LLM of choice (ChatGPT, Claude, Gemini, Perplexity, Grok). Click the icon, your LLM opens with the full context and a pre-framed question already loaded.

SILMARIL doesn't compete with your LLM. SILMARIL makes you a better prompter.

---

## Architecture

```
ingestion  →  universe  →  analytics  →  agents  →  debate  →  trade_engine  →  output
    ↑                                                                              ↓
    └────────────────────────── leaderboard ← performance  ←─────────────────────┘
```

- **Ingestion**: RSS, Google News, SEC EDGAR, yfinance — all free, all cached
- **Universe**: ~100-asset core + user watchlists + news-discovered tickers
- **Analytics**: sentiment, technicals, correlations, event calendar, regime classification
- **Agents**: sixteen independent strategies, one Python module each
- **Debate**: arbiter collects verdicts, computes consensus, identifies dissent
- **Trade engine**: full trade plans with entry/stop/target/invalidation
- **Output**: canonical JSON → static site → GitHub Pages
- **Leaderboard**: historical performance tracking with git-replay backfill

---

## Running it

Public repo, GitHub Actions (unlimited minutes on public repos), GitHub Pages. No paid services.

```bash
git clone https://github.com/YOUR/silmaril
cd silmaril
pip install -r requirements.txt

python -m silmaril --demo    # sample contexts, offline (great for dev)
python -m silmaril --live    # fetch real prices + news, write docs/data/*.json
```

The GitHub Actions workflow (`.github/workflows/daily.yml`) runs `--live`
automatically after every US market close and commits fresh data to the repo.

---

## The disclaimer that matters

SILMARIL is an **educational simulation**. Every portfolio, every trade plan, every leaderboard number is hypothetical. Nothing here is financial advice. Past simulated performance does not predict future results — especially when the "past" is itself a backtest. Consult a licensed professional before putting real money anywhere.

---

*Built for learning. Powered by open data. Preserved against the night.*
