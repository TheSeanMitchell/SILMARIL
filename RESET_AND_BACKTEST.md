# Reset & Backtest Playbook

The most-asked operator questions, answered concretely.

## "How do I reset the site without losing learning?"

1. Actions tab → **Site Reset (preserves all learning)** → Run workflow
2. In the input field, type exactly `RESET` and submit
3. The workflow:
   - Backs up all protected files to `docs/data/_backups/learning_backup_*_pre_reset.tar.gz`
   - Wipes only cosmetic daily artifacts (signals.json, debates.json, etc.)
   - Verifies learning state intact
   - Commits

After reset, the next daily run regenerates all the cosmetic data using
existing learning. Beliefs, evolution cards, counterfactuals all persist.

## "How do I run a fresh backtest?"

1. Actions tab → **Backtest (preserves learning)** → Run workflow
2. Inputs:
   - `lookback_days`: default 730 (2 years). Larger = more data but slower.
   - `mode`: `walk_forward` (recommended) or `single_pass`
3. The workflow snapshots learning state pre-run, runs the backtest
   (which UPDATES beliefs additively — enriches them, doesn't replace),
   verifies post-run, commits.

Walk-forward is the right mode for this system: it splits history into
sliding windows, trains on the past, tests on the next, advances. This
is how systematic-trading research is supposed to be done — single-pass
risks look-ahead bias.

## "I want to wipe everything and start from scratch"

You don't want this. The whole point of Alpha 2.0 is that learning
accumulates across resets. But if you genuinely need a clean slate
(major architectural changes, ground truth corruption suspected):

1. Run the **Site Reset** workflow normally first (creates pre-reset backup)
2. Manually delete each protected file by editing in dev mode
3. Commit

The backup is in `docs/data/_backups/`. If you regret it, restore from
the tar.gz.

## "How do I verify learning is actually persisting?"

Three ways:

**a) Visit the persistence status page:**
`https://YOUR.github.io/SILMARIL/data/persistence_status.json`

Auto-updated by every daily run. Shows which protected files are present,
their sizes, and last-modified timestamps. If a file's mtime is advancing,
learning is updating.

**b) Run the verifier locally:**
```python
from pathlib import Path
from silmaril.learning.persistence_guard import verify_persistence
print(verify_persistence(Path('docs/data')))
```

**c) Check evolution cards:**
`https://YOUR.github.io/SILMARIL/evolution_cards.html`

Cards display lifetime XP and lifetime calls. These numbers monotonically
increase. If they ever decrease or reset, something is wrong.

## "I want to add a new protected file"

Edit `silmaril/learning/persistence_guard.py`. Add the filename to the
`PROTECTED_LEARNING_FILES` set. That's the only edit required — every
workflow imports from this list dynamically.

## "Backtest seems to take forever"

The backtest is run-time-bound by API rate limits, not CPU. To speed up:
- Reduce `lookback_days` to 365
- Use `single_pass` mode for prototyping (faster but biased)
- For development, use `python -m silmaril --demo` locally — uses cached
  sample data, runs in seconds

## "What if a workflow fails mid-run?"

Workflows are idempotent. Re-running picks up from saved state. The
only thing that doesn't auto-recover is a partial commit — if a workflow
fails AFTER writing learning files but BEFORE committing, you'll have
unsaved local state on the runner that disappears. Next run regenerates
it from scratch using the pre-existing committed state. Net result:
nothing lost, possibly one redundant computation.

## "I want to manually edit reflections.json"

In dev mode (`.` on the repo), open `docs/data/reflections.json`. Replace
`current.text` with your 1-3 sentence rule of thumb. Commit. Next daily
run injects it into every agent's context.

## "How do I trigger a stress test?"

Actions tab → **Adversarial Stress Test (manual)** → Run workflow.
Optional input: `lookback_days` (default 7). Output rendered at
`/stress_test.html`.

The verdict will be one of:
- **ROBUST** — survives 2% adversarial cost, edge is real
- **MODERATE** — degrades under cost but stays profitable
- **FRAGILE** — edge collapses under realistic frictions
- **NO_DATA** — no completed debates in the window yet

If you get FRAGILE in the first month, that's expected — you don't have
enough data yet. Run it weekly. The verdict should improve as the
adaptive weighting matures.
