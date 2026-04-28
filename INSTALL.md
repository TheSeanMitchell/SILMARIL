# SILMARIL v1.6 — Install Guide

This drop is the "end of week" comprehensive update. It addresses every
issue from the latest conversation thread:

- Workflow push collisions (daily + backtest pushing simultaneously) → **fixed** with concurrency lock
- Backtest 100MB file limit error → **fixed** by excluding predictions file from commit
- SportsBro placing zero bets → **debugged** with filter diagnostic panel + multi-field deadline support
- Trade history rows showing date but not timestamp → **fixed**
- HOLD action not visible in trade history → **fixed** (renderTradeHistory now handles HOLD)
- Empty Research tab → **fixed** with new Consolidated News Feed
- Confusion about Baron/Steadfast tab placement → **clarified** with new subtitle
- VESPA/CICADA always abstaining in backtest → **partially fixed** by wiring days_to_earnings via yfinance

Plus three new documents at the repo root for handoff to a fresh conversation:

- **SILMARIL_PROJECT_SUMMARY.md** — comprehensive project state, file inventory, conventions
- **SILMARIL_AGENT_CRITIQUE.md** — agent-by-agent diagnosis with prescriptions
- **SILMARIL_SITE_CRITIQUE.md** — site assessment + prioritized improvement list

## Files in this drop

```
silmaril_alpha16/
├── SILMARIL_PROJECT_SUMMARY.md        ← read this first when starting a new conversation
├── SILMARIL_AGENT_CRITIQUE.md
├── SILMARIL_SITE_CRITIQUE.md
├── INSTALL.md                          ← this file
├── silmaril/
│   ├── agents/
│   │   └── sports_bro.py               ← multi-field deadline support, filter diagnostics
│   └── backtest/
│       ├── replay.py                   ← wires days_to_earnings via yfinance
│       └── metrics.py                  ← (unchanged from v2.1, included for completeness)
├── .github/workflows/
│   ├── backtest.yml                    ← concurrency lock + predictions file excluded + retry-on-rejection
│   └── daily.yml                       ← concurrency lock + retry-on-rejection
└── docs/
    └── index.html                      ← consolidated news feed, HOLD action, trade timestamps, sports diagnostic
```

## Install steps

1. Right-click `silmaril_alpha16.zip` → Extract All → Desktop
2. Press `.` on your repo at github.com/TheSeanMitchell/SILMARIL
3. Drag the contents of `silmaril_alpha16/` (the inner files, not the wrapper folder)
   onto the github.dev tree at the repo root
4. Replace prompts will appear for ~7 files. Click **Replace All**
5. Source-control panel → message: `v1.6: workflow lock, news feed, trade timestamps, HOLD viz, sports diagnostic, project summary docs` → Commit & Push

## Verify after push

1. Visit Actions tab — both workflows should show "main" running with the
   concurrency group `silmaril-repo-write` listed
2. Open the live site, click the **RESEARCH** tab — should now show the
   Consolidated News Feed at the top
3. Click any compounder card — trade history rows should show MM-DD HH:MM,
   not just MM-DD
4. Click **PORTFOLIO MANAGERS** tab → Sports Bro card → scroll to bottom of
   the card. Should see "Filter Activity · last run …" panel showing
   total candidates / filtered out / qualified counts.

## After verifying — re-run backtest if you want fresh agent rankings

The v1.6 wiring of days_to_earnings means VESPA and CICADA should now
produce non-zero predictions. Run **SILMARIL Backtest** with:
- start: `2022-01-01`
- end: `2026-01-01`
- universe: `full`
- walk_forward: `yes`

Wait ~30-40 min. New `backtest_report.json` and `backtest_walk_forward.json`
will land in `docs/data/`. Open them on github.com to confirm VESPA/CICADA
now have non-zero call counts.

## What's NOT in this drop

The Tier A improvements from `SILMARIL_AGENT_CRITIQUE.md` are NOT in this drop:

- AEGIS volume cut + veto-gating
- Regime-weighted consensus
- HOLD-action recording for Baron/Steadfast (UI is ready but backend needs work)
- Stale-data indicator on topbar

Those are the right starting point for the next conversation. The three
documents at the repo root are designed to give a fresh assistant everything
needed to pick up where this conversation left off.
