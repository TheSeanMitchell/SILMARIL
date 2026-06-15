# SILMARIL — Alpha 0.001

**A multi-agent research system built to find a real, durable edge in US stocks.**

SILMARIL runs a roster of trading agents over US equities, executes their
consensus on Alpaca paper accounts, scores every call against clean price data,
and uses those scores to reweight the agents over time. The goal is singular:
**discover whether a repeatable stock edge exists here — and prove it with money,
not with a story.**

> Alpha 0.001 is a deliberate rebirth. After a long build that accreted crypto
> compounders, token traders, and prediction-market bots, the project is
> re-founded around one mission: **stocks, real trades, honest results.**
> Everything that can't place a real US-equity order is out of scope.

---

## What it is

- **Agents** (`silmaril/agents/`) — each reads an `AssetContext` (price, technicals,
  news sentiment, regime) and emits a `Verdict` (BUY/SELL/HOLD + conviction).
- **Debate + consensus** (`silmaril/senate/`) — agent verdicts are arbitrated into
  a per-ticker consensus.
- **Plans + risk** (`silmaril/portfolios/`, `silmaril/execution/`) — consensus
  becomes trade plans, filtered by risk and trend, then executed on Alpaca.
- **Scoring + learning** (`silmaril/scoring/`, `silmaril/learning/`) — every prior
  call is scored against fresh prices; Thompson sampling reweights each agent's
  conviction by its learned per-regime win rate; a kill-switch freezes chronic
  losers.
- **The cockpit** (`docs/cockpit.html` + `docs/silmaril-truth.js`) — the read-only
  truth surface. One honest view of system health, anomalies, and accounts.

Runs on a schedule via GitHub Actions; publishes to GitHub Pages.

---

## Current honest state (2026-06-05)

This section is kept truthful on purpose. See `SILMARIL_BOOTSTRAP_ALPHA_0.001.xml`
for the full machine-readable state.

**Working:**
- Scoring is **~99% clean** (was ~89% stale) — the data is finally trustworthy.
- Execution is fixed — extended-hours limit orders fill (the sub-penny 422 bug is gone).
- The learn→trade loop has real teeth: agent votes are scaled by learned per-regime
  win rates, and chronic losers get frozen.

**Not there yet — the honest part:**
- Over the last month the system is **−1.71% vs SPY** (behind buy-and-hold). One
  week ahead (+0.42%). No agent has yet proven a durable edge on clean data.
- Win-rate ≠ profit: some agents are "right" often but lose money. Scoring is being
  moved to reward realized P&L.
- Much of the analytics (sector rotation, conviction ranking, capital efficiency,
  narratives) is computed and displayed but **does not yet change a trade** — it's
  being wired in or cut.
- The "breed new agents" senate only proposes offspring; it never instantiates
  them. Being redirected toward evolving the parameters of existing agents.

**Out of scope (Alpha 0.001):** crypto, micro-cap tokens, prediction markets /
sports betting. The former synthetic compounders are disabled.

---

## Accounts

Three Alpaca **paper** accounts, each baselined at $10,000: `LEGACY` (Silmaril),
`HARVEST_3`, `HARVEST_5`. No real money is ever used.

---

## Running it

The system runs itself on GitHub Actions cron. To run a cycle manually:

```
python -m silmaril --live     # full pipeline: ingest → agents → plans → execute → score
python -m silmaril --demo     # offline demo with seeded data, no live API calls
```

Outputs land in `docs/data/*.json` and render on the cockpit / dashboard.

### Data sources

All free-tier or key-authenticated; **no new signups are required**. Keys are
supplied as GitHub Actions secrets. Prices use yfinance plus a keyed fresh-quote
overlay (FMP / Tiingo / Twelve Data / Finnhub); macro via FRED; news via Google
News RSS. (Marketaux, NewsAPI, Polygon, and Alpha Vantage keys are present but not
yet wired — see the roadmap.)

---

## Operating rules (non-negotiable)

1. **Read a file before you change it.** Every major regression traced to editing
   blind. No exceptions.
2. **Complete-file replacements only** — drag-and-drop, GitHub web-UI ready.
3. **Classify every change** — Track A (safe/additive/reversible), B (behavioral),
   C (future).
4. **Honesty over flattery.** "No edge yet" is a valid result. Nothing synthetic on
   the site.
5. **Optimize for realized money, not win-rate.**

---

## Roadmap (stock-edge first)

1. Reward profit, not just correctness, in scoring.
2. Wire Marketaux entity sentiment + article summaries into decisions; then measure
   whether sentiment actually predicts outcomes.
3. Give teeth to advisory analytics that prove out — or remove them.
4. Make agent "evolution" real via parameter mutation of existing agents.
5. Unify the roster, put the SPY benchmark on the cockpit, retire dead surfaces.

---

*Not financial advice. Paper-trading research project.*
