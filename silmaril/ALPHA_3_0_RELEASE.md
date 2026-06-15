# ALPHA 3.0 — Harvest Architecture Expansion

**Tagline:** Multiple verified-harvest Alpaca accounts, **live SGOV auto-buy
per account**, honest day counts, pokemon-style learnable position pruning,
news disambiguation. Zero data destruction.

---

## What changed at a glance

| Concern | Before 3.0 | After 3.0 |
|---|---|---|
| Alpaca accounts | 1 (LEGACY) | 3 (LEGACY + HARVEST_3 + HARVEST_5) |
| Harvest pipeline | profitable close → "savings" counter incremented | profitable close → **automatic SGOV buy on same account** → ledger row transitions through VERIFIED |
| "Savings harvested" | equity-above-baseline (paper) | live SGOV holdings × current price (verified, per-account, comparable head-to-head) |
| SGOV vault protection | n/a | reserved symbol — close loop skips it, open loop blacklists it, can't be shorted |
| Trading capital sizing | included vault value (would re-leverage savings) | excludes vault value (savings stay locked) |
| Day counters | drifted (4d vs 6d) | unified time_basis (real / market / crypto) |
| Position staleness | trailing stop only | scorecard + advisory, per-agent learnable knob |
| News→ticker confusion | SNOW = Snow College | confidence-scored, 20+ collision rules |
| Existing data | — | **untouched. Nothing deleted.** |

---

## The verified harvest flow (Alpha 3.0 core)

For each of the three accounts on every cycle:

```
  position closes profitable
        │
        ▼
  INTENT row logged with source ticker + realized cash
        │
        ▼
  SELL_FILLED ← close order confirmed by Alpaca
        │
        ▼
  cycle aggregates all winners' realized cash
        │
        ▼
  SGOV BUY notional=$cash submitted to *same account*
        │
        ▼
  SGOV_QUEUED ← order accepted by Alpaca
        │
        ▼
  positions re-fetched 2s later
        │
        ▼
  SGOV_FILLED → VERIFIED ← shares actually held
```

Each account owns its own SGOV stack. Dashboard shows them side-by-side so
you can see at a glance which threshold (1.5% / 3% / 5%) compounds fastest.

Below the $5 sweep threshold, cash rolls forward and the ledger row marks
FAILED with `reason: below min sweep threshold`. SGOV itself is on the
`_RESERVED_VAULT_SYMBOLS` blacklist — it cannot be opened or shorted by
consensus signals, and the close loop skips it entirely.

---

## New files (additive)

```
silmaril/
  diagnostics/
    time_basis.py                 # real / market / crypto day counts
    harvest_accounts_status.py    # builds harvest_accounts.json rollup
  portfolios/
    staleness.py                  # position pruning advisory + per-agent knob
    verified_harvest.py           # state-machine ledger + SGOV reconciliation
  ingestion/
    ticker_disambiguation.py      # SNOW/PG/NOW/HD/EA filter
  execution/
    multi_account.py              # orchestrator for LEGACY + HARVEST_3 + HARVEST_5

scripts/
  migrate_to_alpha_3_0.py         # idempotent, additive, never destructive
```

## Patched files (surgical, backward-compatible)

```
silmaril/cli.py                       # multi-account block + advisory + disambig hooks
silmaril/execution/alpaca_paper.py    # SGOV auto-buy, vault guards, account_id propagation
silmaril/ingestion/news.py            # optional self-disambiguation flag
silmaril/diagnostics/run_health.py    # harvest_accounts summary block
docs/index.html                       # renderHarvestTab() replaced + SGOV sweep status
.github/workflows/daily.yml           # H3/H5 env vars wired in
```

---

## How to deploy

1. **Drop in files** from `silmaril_alpha_3_0.zip` (preserves folder layout).
2. **Run migration** (idempotent, safe to re-run):
   ```
   python scripts/migrate_to_alpha_3_0.py
   ```
3. **Commit and push.** Next `Daily Run` cron picks everything up.

GitHub secrets already in place per your screenshot: `ALPACA_API_KEY_H3`,
`ALPACA_API_SECRET_H3`, `ALPACA_API_KEY_H5`, `ALPACA_API_SECRET_H5`. ✓

LEGACY keeps trading. H3 and H5 come alive on first successful Alpaca call.
Profitable closes on any account automatically sweep into SGOV on that
same account.

---

## What you'll see

**On the HARVEST · ACCOUNTS tab, each account card now shows:**

- Equity, principal, cash, W/L, positions, time-basis
- **VERIFIED HARVESTED**: live SGOV market value (the honest number)
- **UNREALIZED ABOVE**: paper equity above baseline (the unverified extra)
- SGOV sweep status from last cycle: `✓ swept $X → SGOV (order id)` /
  `✗ rejected: <reason>` / `$X pending — below sweep threshold`
- Live SGOV qty held: `✓ live SGOV verified · 0.85 sh SGOV`

Below the cards: position-pruning advisory, news disambiguation strip,
Bills Paid leaderboard, verified-harvest ledger snippet (last 8 rows).

---

## Critical invariants

1. **Staleness pruning uses REAL CALENDAR DAYS, always.** Enforced by an
   explicit comment block in `silmaril/portfolios/staleness.py`. The
   `time_basis` helper is for *displaying* agent age — never for scoring.
2. **Verified ≠ unrealized.** Dashboard surfaces both side-by-side.
   Verified = live SGOV; unrealized = paper equity above baseline.
3. **SGOV is reserved.** No consensus signal can open, short, or close
   SGOV. Only the harvest sweep path can buy it.
4. **Trading capital excludes vault.** Once SGOV is held, position sizing
   uses `min(equity − vault_value, principal)` — savings stay locked.
5. **Backward compat.** Removing H3/H5 secrets reverts to pre-3.0
   behavior. `multi_account.py` silently skips unconfigured accounts.
6. **Additive migration.** `scripts/migrate_to_alpha_3_0.py` only
   *creates* files. Never modifies, never deletes existing state.

---

## What's verified end-to-end

Smoke tests bundled in this drop confirmed:

- ✅ All Python files AST-parse clean
- ✅ time_basis math (May 6→10 = 4 real / 2 market / 119 crypto-hours)
- ✅ Staleness scoring uses real-calendar age regardless of time_basis
- ✅ News disambiguation drops "Snow College" (conf 0.0); passes
  "Snowflake data cloud" (conf 0.7)
- ✅ Three accounts orchestrate; `account_id` propagates to ledger
- ✅ Profitable close → SGOV buy → VERIFIED state transition fires
- ✅ Vault is protected against adversarial STRONG_BUY / STRONG_SELL
- ✅ Trading capital correctly excludes vault from re-deployable pool

---

## Still NOT in this release (full transparency)

The following were diagnosed but deliberately deferred:

- **Senate breeder mutating staleness aggression.** Knob exists and is
  seeded to 0.5 per agent; nothing mutates it yet. ~50 lines, hooks
  ready in `silmaril/senate/elections.py`.
- **SPORTS_BRO quarantine.** Still shows +143.90% on the leaderboard
  from simulated data. ~20 lines to add `data_source: simulated` flag
  and filter the leaderboard.
- **Backtest vs live call-count split.** AEGIS's 1092 "calls" still
  includes backtest evaluations. ~80 lines to split into `live_calls`
  vs `backtest_calls`.
- **Per-news-row confidence badges in the feed.** The disambiguation
  engine filters drops out before they reach the dashboard, but
  individual surviving rows don't yet show their confidence score.
  ~15 lines in the news-feed renderer.
- **Auto-execution of EXIT recommendations.** Advisory only, by design,
  until the aggression knobs are calibrated.

None of these blocks the Senate election on the 1st.

---

## File counts

- **New:** 6 Python modules + 1 migration script + 2 docs = 9 files
- **Patched:** 6 files
- **Lines added:** ~1700 (mostly new modules, well-commented)
- **Lines removed:** ~110 (inside replaced functions only)
- **Data files preserved:** every single one

Alpha 3.0 ships clean. SGOV pipeline is live.
