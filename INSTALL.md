# SILMARIL v2.0 — Drop-in install

## What's in this folder

```
silmaril_v2_FINAL/
├── INSTALL.md                <- you are reading this
├── verify_v2.py              <- run after installing to confirm health
├── ANSWERS.md                <- your open questions answered
├── ROADMAP_V2.md             <- v2 priority list
├── README_V2.md              <- overview
└── silmaril/                 <- merge with your existing silmaril/ folder
    ├── cli.py                <- already wired with v2 imports + cohort
    ├── agents/               <- 7 new agent files (no __init__.py)
    │   ├── atlas.py
    │   ├── barnacle.py
    │   ├── cicada.py
    │   ├── kestrel_plus.py
    │   ├── nightshade.py
    │   ├── nomad.py
    │   └── shepherd.py
    ├── backtest/             <- brand new folder
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── README.md
    │   ├── data_loader.py
    │   ├── engine.py
    │   ├── metrics.py
    │   ├── replay.py
    │   └── walk_forward.py
    ├── scoring/              <- brand new folder
    │   ├── __init__.py
    │   └── regime_sliced.py
    ├── catalysts/            <- 6 new files (no __init__.py)
    │   ├── crypto_unlocks.py
    │   ├── earnings_calendar.py
    │   ├── ex_dividend.py
    │   ├── index_rebalance.py
    │   ├── macro_releases.py
    │   └── opex.py
    └── handoff/              <- 1 new file (no __init__.py)
        └── multi_llm_consensus.py
```

The folders that already exist in your repo (`agents/`, `catalysts/`,
`handoff/`) ship with **only the new files** — no `__init__.py`, so
nothing of yours gets overwritten. The two brand-new folders
(`backtest/`, `scoring/`) ship complete with their own `__init__.py`.

The one existing file we **do** replace is `silmaril/cli.py` — it's
been merged with the seven new agent imports and the v2 catalyst
hookup already in place. Your existing logic is unchanged.

---

## Install (3 steps, ~2 minutes)

### 1. Drop into github.dev

1. Go to `github.com/TheSeanMitchell/SILMARIL`
2. Press `.` (the period key) to open github.dev
3. In the file explorer on the left, drag the **contents** of this
   folder into your repo:
   - `INSTALL.md`, `verify_v2.py`, `ANSWERS.md`, `ROADMAP_V2.md`,
     `README_V2.md` go at repo root
   - The `silmaril/` folder merges with your existing `silmaril/` —
     new files appear in the right subfolders, `cli.py` gets replaced
4. github.dev will prompt you to confirm the `cli.py` overwrite.
   Confirm it. Your existing version is preserved in git history if
   you ever need it.

### 2. Commit and push

In github.dev:
1. Click the source-control icon on the left (the branchy thing)
2. Type a commit message:
   `v2.0: backtest framework, 7 new agents, expanded catalysts`
3. Click **Commit & Push**

### 3. Verify (optional but recommended)

In your local terminal (not github.dev), pull and run:

```bash
git pull
pip install yfinance pandas numpy pyarrow
python verify_v2.py
```

You should see `ALL CHECKS PASSED -- v2.0 install is healthy.`

If something fails, the verify script tells you exactly which file
is missing or which import broke.

---

## After install — run the backtest

This is the priority-#1 thing v2.0 was built for: getting honest
numbers on whether the agents have edge before any live trading.

```bash
python -m silmaril.backtest \
    --start 2022-01-01 \
    --end 2026-01-01 \
    --universe demo \
    --walk-forward \
    --out-dir docs/data
```

First run downloads ~25 tickers of OHLC history (a few minutes).
Subsequent runs are fast — data is cached at
`~/.cache/silmaril_backtest/`.

Output: `docs/data/backtest_report.json`. The
`walk_forward.stability` section is the section to read first —
agents flagged BRITTLE there should not be weighted equally with
STABLE ones in your live cohort.

---

## What got changed in `cli.py` (just so you know)

Three small surgical edits, nothing removed:

1. **Seven new imports** added next to the existing agent imports
   (lowercase instances `atlas`, `nightshade`, `cicada`, `shepherd`,
   `nomad`, `barnacle`, `kestrel_plus`).
2. **`MAIN_VOTERS` list extended** to include the new 7. Your
   existing 15 are unchanged. The cohort is now 22 main voters.
3. **Catalysts roundup augmented** — after `write_catalysts_json()`
   runs, the v2 sources (OPEX, index rebalance, macro, crypto
   unlocks, ex-dividend, earnings) get appended to `catalysts.json`
   under a new `events` key. Each source is wrapped in try/except
   so if any one source fails, the others still go through.

If you want to see the changes diff against your original, github
will show them when you commit.

---

## Read these for context

- `ANSWERS.md` — out-of-sample validation explained, Polymarket and
  Kalshi auth (you don't need to submit your DL/SSN), mobile and
  paid-automation deferral.
- `ROADMAP_V2.md` — full v2.0 priority list and what's deferred.
- `silmaril/backtest/README.md` — backtest framework quick-start.
- `README_V2.md` — package overview.

---

## If something breaks

The `verify_v2.py` script tells you exactly which file is missing
or which import broke. Past that:

- **`from .agents.X import Y` errors**: a v2 agent file landed
  somewhere wrong, or `cli.py` didn't get replaced.
- **`fetch_X catalysts skipped: ...`** in pipeline logs: that's
  expected behavior — each catalyst source is best-effort. The rest
  of the pipeline keeps running.
- **Backtest can't reach yfinance**: try `pip install --upgrade
  yfinance`, or use `--no-cache` to bypass the local cache.
