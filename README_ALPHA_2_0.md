# SILMARIL Alpha 2.0 — Drop-In Package

**You're looking at the unzipped contents of the Alpha 2.0 update.**

Everything in this folder is meant to be merged into your existing
`SILMARIL/` repo at the same paths. After unzipping:

1. Open your repo in GitHub dev mode (press `.` on the repo page)
2. Drag the `silmaril/` folder into your repo root, allow merge/overwrite
3. Drag the `.github/` folder into your repo root, allow merge/overwrite
4. Drag the `docs/` folder into your repo root, allow merge
5. Update your existing `requirements.txt` per `requirements_additions.txt`
6. Wire two function calls into your existing `silmaril/cli.py` per `INSTALL_2_0.md`
7. Commit + push

That's it. The new daily workflow runs at 10-minute cadence (public
repo = unlimited Actions minutes). The Alpaca paper bridge will start
placing orders once you add the `ALPACA_API_KEY` and `ALPACA_API_SECRET`
secrets.

---

## Read these in order

1. **`ALPHA_2_0_RELEASE.md`** — what changed and why, plus honest framing
2. **`INSTALL_2_0.md`** — exact step-by-step install
3. **`LEARNING_PERSISTENCE.md`** — the "training never resets" guarantee
4. **`RESET_AND_BACKTEST.md`** — operator playbook
5. **`INDEX_HTML_UPDATES.md`** — six find-and-replace edits for index.html
   (optional — system works without them)
6. **`ROADMAP_NEXT_20.md`** — the next 20 updates vision

---

## What's in here

```
silmaril/
├── learning/          (NEW — 19 modules, the adaptive ensemble layer)
│   ├── persistence_guard.py    ← THE sacred list. Training never resets.
│   ├── evolution_cards.py      ← Gamified XP cards. Only grow.
│   ├── bayesian_winrate.py     ← Beta posterior per agent per regime
│   ├── thompson_arbiter.py     ← Conviction multiplier sampling
│   ├── dissent_digest.py       ← Cross-agent learning injection
│   ├── reflection.py           ← Manual rule-of-thumb injection
│   ├── counterfactual.py       ← What overruled dissents would have done
│   ├── hysteresis.py           ← Threshold bands prevent flicker
│   ├── regime_bandit.py        ← Contextual bandits per regime
│   ├── slippage.py             ← Realistic fill modeling
│   ├── correlation_matrix.py   ← Concentration alerts
│   ├── time_of_day.py          ← TOD performance buckets
│   ├── news_quality.py         ← Multi-source confirmation
│   ├── anomaly_detector.py     ← Volume/price anomaly flags
│   ├── premortem.py            ← Forced bear-case articulation
│   ├── adversarial_stress.py   ← Manual-trigger stress test
│   ├── drift_detector.py       ← Performance drift dampener
│   ├── position_sizing.py      ← Half-Kelly with vol scaling
│   └── integration.py          ← Two-function wiring for cli.py
│
├── agents/            (3 files — additive)
│   ├── _rename_map.py          ← Single source of truth for names
│   ├── contrarian.py           ← NEW: crowded-trade fade
│   ├── short_alpha.py          ← NEW: daily-move shorts
│   └── sports_bro.py           ← Updated: closest-resolving bets
│
├── debate/
│   └── arbiter.py              ← Rewritten: Thompson + conditional veto
│
├── execution/         (NEW)
│   └── alpaca_paper.py         ← Free paper trading bridge
│
└── portfolios/
    └── agent_portfolio.py      ← All 22 agents get portfolios

.github/workflows/
├── daily.yml                   ← 10-min cadence with learning loop
├── backtest.yml                ← Preserves learning, walk-forward
├── reset.yml                   ← Preserves learning state explicitly
├── reflection.yml              ← 4:30pm ET placeholder bootstrap
├── stress_test.yml             ← Manual adversarial stress test
├── correlation_check.yml       ← Nightly correlation snapshot
└── weekly_backup.yml           ← Sunday backups, 12-week retention

docs/
├── stress_test.html            ← NEW dashboard page
├── correlation_matrix.html     ← NEW dashboard page
├── evolution_cards.html        ← NEW dashboard page
└── data/
    ├── reflections.json        ← Initial template
    └── agent_evolution_cards.json
```

---

## Quick sanity check after install

After your first daily run on Alpha 2.0:

✓ `docs/data/agent_beliefs.json` exists and has content
✓ `docs/data/agent_evolution_cards.json` has entries
✓ `docs/data/alpaca_paper_state.json` shows account info
✓ `https://YOUR.github.io/SILMARIL/evolution_cards.html` renders cards
✓ `https://app.alpaca.markets/paper/dashboard` shows orders or empty cash

Run an adversarial stress test from the Actions tab, view results at
`https://YOUR.github.io/SILMARIL/stress_test.html`.

---

**Disclaimer:** Educational simulation only. Not financial advice. Paper
trading only — there is no live-trading code path in this package.
