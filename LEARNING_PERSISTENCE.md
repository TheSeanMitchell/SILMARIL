# Learning Persistence Guarantee

The user requested: *"Their training cards should continuously evolve and
improve, no matter what they go through. They should never reset or
decline in performance."*

This document explains exactly how that's enforced.

## The Sacred List

In `silmaril/learning/persistence_guard.py` there's a Python set called
`PROTECTED_LEARNING_FILES`. It contains every file that constitutes
"agent training memory":

- `agent_beliefs.json` — Bayesian Beta states per agent per regime
- `agent_evolution_cards.json` — gamified XP/level cards (only grow)
- `regime_bandits.json` — contextual bandits per (regime, asset_class, vol)
- `counterfactuals.json` — what overruled dissents would have done
- `hysteresis_state.json` — current band states per agent per ticker
- `scoring.json` — rolling win rates and EV
- `agent_portfolios.json` — per-agent $10K portfolio history
- `scrooge.json`, `midas.json`, `cryptobro.json`, `jrr_token.json`,
  `sports_bro.json` — $1 compounder states
- `baron.json`, `steadfast.json` — specialist book history
- `history.json` — debate and outcome history
- `reflections.json` — operator-written rules of thumb
- `news_source_quality.json` — Bayesian source-reliability priors
- `anomaly_state.json` — recently-flagged anomalies (24h TTL)
- `drift_state.json` — performance drift detector state
- `stress_test_results.json` — adversarial stress test history
- `correlation_history.json` — daily correlation matrix snapshots
- `time_of_day_performance.json` — TOD bucket performance per agent
- `premortem_archive.json` — pre-mortem rationale archive
- `backtest_belief_snapshots.json` — walk-forward backtest snapshots
- `alpaca_paper_state.json`, `alpaca_equity_curve.json` — paper trading state

## How the guarantee is enforced

### 1. The reset workflow (`reset.yml`) calls `safe_reset()`

```python
from silmaril.learning.persistence_guard import safe_reset
report = safe_reset(Path('docs/data'), keep_protected=True)
```

`safe_reset` iterates `docs/data/`, and for each file checks
`is_protected(filename)` — which compares against `PROTECTED_LEARNING_FILES`.
Protected files are skipped entirely. Only daily-regenerated artifacts
(signals.json, trade_plans.json, debates.json, etc.) are removed.

### 2. The reset workflow has a confirmation gate

`workflow_dispatch` requires the operator to type `RESET` in the input
field. There is no scheduled reset. There is no API endpoint. Reset is
intentional, manual, and explicitly preserves learning.

### 3. Pre-reset backup is mandatory

Before the reset runs, `backup_learning_state()` snapshots all protected
files into `docs/data/_backups/learning_backup_YYYYMMDD_pre_reset.tar.gz`.
If something goes wrong, the snapshot is right there.

### 4. Post-reset verification

After reset, the workflow runs `verify_persistence()` and asserts
`len(report['present']) > 0`. If the assertion fails, the workflow
fails, the commit doesn't happen, and the operator gets alerted.

### 5. Backtest workflow follows the same pattern

`backtest.yml` snapshots learning state pre-run, runs the backtest
(which UPDATES beliefs additively), then verifies persistence is intact
post-run before committing. Backtest is non-destructive by design.

### 6. Daily workflow only adds, never deletes

`pre_debate_learning_setup` reads protected files. `post_debate_learning_update`
writes to protected files (incrementing counters, appending records).
Neither function deletes anything.

### 7. Weekly automatic backup

`weekly_backup.yml` runs Sunday midnight UTC. Snapshots all protected
files. 12-week rolling retention in `docs/data/_backups/`. Even if a
disaster happened that bypassed every other safeguard, you'd have at
worst one week's data loss.

## What this guarantee does NOT promise

- **It doesn't guarantee win rates increase.** Win rates can fluctuate
  with market regime. What's guaranteed is that the *data accumulates* —
  XP only grows, lifetime calls only grow, lifetime wins only grow,
  best_win_streak only grows. Drift can be detected and dampened, but
  the underlying state is not erased.

- **It doesn't guarantee no bugs.** A future code change could
  theoretically break this. The mitigation is: the protected list is a
  single Python set in one file. Any PR touching `persistence_guard.py`
  is the highest-attention PR in the codebase. The weekly backups are
  the floor.

- **It doesn't promise the agents become "smarter" without limits.**
  Rule-based agents have bounded capacity for adaptation. The Bayesian
  layer adapts WEIGHTING; the rules themselves are static unless you
  manually edit them. To get genuinely smarter agents you need either
  more rules, or eventually an LLM-in-the-loop layer (Phase 3 work).

## How to verify the guarantee yourself

After any workflow run:

```python
from pathlib import Path
from silmaril.learning.persistence_guard import verify_persistence
print(verify_persistence(Path('docs/data')))
```

Or visit `https://YOUR.github.io/SILMARIL/data/persistence_status.json`
which the daily workflow auto-updates.
