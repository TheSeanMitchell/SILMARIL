# REPO CLEANUP AUDIT — what to remove, trim, or rotate (June 12, 2026)
Companion to FINAL_ALPHA_1_0_MASTER_DOCUMENT.md. Additive law applies:
prefer attic/ or tag-preserve over deletion; the deletions below are the
deliberate, operator-approved exceptions for storage permanence.

## 1. THE STORAGE CURE (do this first)
Run **Actions → "Compact Git History (storage cure)" → type COMPACT**.
Effect: old history preserved at tag `history-backup-YYYYMMDD`, main
becomes a single-commit snapshot, repo collapses to ~worktree size
(~86MB). Monthly, or when api_health.storage.git_history_mb > 500.
After you're confident (e.g., 30 days), delete old `history-backup-*`
tags to reclaim fully: `git push origin :refs/tags/history-backup-...`.

## 2. WORKTREE TRIMS (safe now)
- docs/data/history.json (33MB) + docs/data/charts.json (20MB): the two
  whales. They are REGENERATED products. Action: cap their producers'
  row windows next session (spec'd); until then they're tolerable.
- docs/data/_backups/ (4MB): rotated by code; keep.
- Root stale docs → attic/: MONDAY_PREP_NOTES.md, MARKET_OPEN_NOTES.md,
  READ_ME_alpaca_disconnect_fix.md, SILMARIL_BOOTSTRAP_ALPHA_0.001.xml,
  ROADMAP.md + ROADMAP_2W.md (superseded by ROADMAP_TO_ALPHA_1.md),
  WIPE/RESET one-shot workflows you'll never rerun (wipe_for_alpha_2_1,
  migrate_alpha_3_0, reset_alpaca_grocery_to_truth) — move, don't delete.
- attic/cli_root_RETIRED_2026-06-12.py: KEEP (that's the law working).

## 3. HARDENING CHECKLIST (#7 — procedural, 20 minutes)
[ ] Rotate the PAT used by cron-job.org; least-privilege (repo:contents)
[ ] Branch protection on main: require the daily workflow green
[ ] Pin actions to SHAs (checkout@v4 → @<sha>)
[ ] Enable Dependabot (pip + actions)
[ ] Repo secrets audit: only ALPACA_*, data-provider keys, PAT

## 4. NEVER REMOVE
FINAL_ALPHA_1_0_MASTER_DOCUMENT.md · ROADMAP_TO_ALPHA_1.md · AUDIT.md ·
FOUNDING_CHARTER.md · attic/ · docs/data/*_history.json + lineage files
(agent_genomes, regime_history, vs_market_series, benchmark_price_log,
narrative_lifecycle_history, debut_watch completed[]) — these ARE the
system's memory.
