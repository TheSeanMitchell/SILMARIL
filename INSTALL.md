# SILMARIL v2.0 — Drop-in Install

## What this is

A complete repo replacement. You delete your current repo's contents
and drop these in. After this, your repo will have:

- All 22 of your original agents, untouched
- 7 new v2 agents (atlas, nightshade, cicada, shepherd, nomad, barnacle, kestrel_plus)
- A backtest framework (silmaril/backtest/)
- 6 new catalyst sources (OPEX, index rebalance, macro releases, crypto unlocks, ex-dividend, earnings)
- Regime-sliced live scoring (silmaril/scoring/regime_sliced.py)
- Manual multi-LLM consensus prompts (silmaril/handoff/multi_llm_consensus.py)
- A new GitHub Actions workflow (Backtest) you can trigger with one click

## Install — 4 steps

### 1. Open github.dev

1. Go to `github.com/TheSeanMitchell/SILMARIL`
2. Press `.` (period) — github.dev opens

### 2. Delete the entire `silmaril/` folder

In the file explorer on the left:
1. Right-click on the `silmaril/` folder → **Delete**
2. Confirm

(Don't worry — git history preserves everything.)

### 3. Drag the new folders in

In your File Explorer (Windows), open the unzipped `SILMARIL_v2_complete/` folder.

Press **Ctrl+A** to select everything inside it (the 4 .md files plus
the `silmaril/`, `docs/`, and `.github/` folders).

Drag everything into the github.dev file tree on the left, dropping at
the very top (on the line that shows the repo name).

When prompted to overwrite existing files, click **Yes / Replace**.

### 4. Commit and push

In github.dev:
1. Click the source-control icon (third icon down, looks like a branch)
2. Type a commit message: `v2.0 complete: 7 new agents, backtest framework, expanded catalysts`
3. Click **Commit & Push**

Wait ~30 seconds. The repo is now v2.0.

## Run the reset

1. Go to your repo on GitHub.com
2. Click the **Actions** tab
3. In the left sidebar, click **SILMARIL Reset**
4. Click **Run workflow** (right side)
5. In the box that appears, type `RESET`
6. Click the green **Run workflow** button
7. Wait ~2 minutes — the reset wipes accumulated state and runs one
   clean live cycle with the new 22-agent cohort.

If the reset job fails, click into it and read the error. Most likely:
- `ModuleNotFoundError: silmaril.charts` — your real charts module
  wasn't in the build. Paste your original `silmaril/charts/__init__.py`
  contents over the stub I shipped.
- `ModuleNotFoundError: silmaril.sports` — same situation. Stub is in
  place, paste your real one over it.

## Run the backtest

1. Actions tab → **SILMARIL Backtest** → **Run workflow**
2. Defaults are: 2022-01-01 to 2026-01-01, demo universe, walk-forward enabled
3. Click the green button. Wait ~5–10 minutes.
4. Output lands in `docs/data/backtest_report.json` (auto-committed)

Read `walk_forward.stability` first — agents flagged BRITTLE there
should not be weighted equally with STABLE ones in your live cohort.

## Read these for context

- `ANSWERS.md` — out-of-sample validation explained, Polymarket/Kalshi
  auth reality, mobile, paid-automation deferral
- `ROADMAP_V2.md` — full v2.0 priority list and what's deferred
- `silmaril/backtest/README.md` — backtest framework details
- `README_V2.md` — package overview

## Known stubs

Two files in your live repo weren't included in the v2 build because
they weren't in the upload. I shipped working stubs that prevent
crashes:

- `silmaril/charts/__init__.py` — stub returns empty charts
- `silmaril/sports/__init__.py` — stub returns no markets

If your dashboard is missing chart data or sports markets after the
reset succeeds, paste your original versions of these two files back
over the stubs.
