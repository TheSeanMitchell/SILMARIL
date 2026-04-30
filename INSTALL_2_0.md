# SILMARIL Alpha 2.0 — Install Guide

You're not git-bashing. You're dragging folders into GitHub dev mode.
Here's the exact sequence.

## Step 1 — Add Alpaca secrets

GitHub repo → Settings → Secrets and variables → Actions. Add:

- `ALPACA_API_KEY` — from https://app.alpaca.markets/paper/dashboard/overview
- `ALPACA_API_SECRET` — same source

Confirm these are also set (should already be from prior installs):
ALPHA_VANTAGE_API_KEY, BIRDEYE_API_KEY, COINGECKO_API_KEY, EIA_API_KEY,
FINNHUB_API_KEY, FMP_API_KEY, FRED_API_KEY, OPENEXCHANGERATES_APP_ID,
POLYGON_API_KEY, TIINGO_API_KEY.

## Step 2 — Drop in the package

Press `.` on the GitHub repo to open dev mode (VS Code in browser).
Drag-drop these top-level folders from the unzipped `silmaril_alpha_2_0/`
into your repo root, allowing overwrites:

- `silmaril/` — replaces existing module
- `.github/workflows/` — replaces all workflow files
- `docs/` — adds new HTML pages and data templates

The package will not overwrite your existing `docs/data/*.json` learning
files because the new files use different names. Your `docs/index.html`
is also untouched — apply the changes from `INDEX_HTML_UPDATES.md` when
you have time (system works without them).

## Step 3 — Update requirements.txt

Add to your existing `requirements.txt`:

```
alpaca-py>=0.20.0
numpy>=1.24
```

## Step 4 — Wire the integration into cli.py

This is the only "code" step. Open `silmaril/cli.py` in dev mode. At the
top of the file with other imports, add:

```python
from silmaril.learning.integration import (
    pre_debate_learning_setup,
    post_debate_learning_update,
)
from silmaril.execution.alpaca_paper import execute_consensus_signals
from silmaril.agents._rename_map import all_new_codenames
from silmaril.portfolios.agent_portfolio import (
    load_portfolios, save_portfolios, ensure_all_agents_have_portfolios,
)
```

Find the section where you load asset contexts and BEFORE the agent
voting loop, add:

```python
learning_ctx = pre_debate_learning_setup(out_dir=Path('docs/data'), contexts=contexts)
```

In your `adjudicate()` call, pass the learning context:

```python
result = adjudicate(
    verdicts,
    regime=regime,
    beliefs=learning_ctx.beliefs,
    rolling_winrates=learning_ctx.rolling_winrates,
    drift_dampeners=learning_ctx.drift_dampeners,
    deterministic=False,
    guardian_codename="GUARDIAN",
)
```

After all debates complete and outcomes are scored, call:

```python
post_debate_learning_update(
    learning_ctx,
    debates=debate_results,
    portfolios=loaded_portfolios,
    price_history=price_history_dict,
    newly_scored_outcomes=outcome_records,
)
```

After consensus phase, before final commit:

```python
execute_consensus_signals(
    plans=plans_kept,
    state_path=Path('docs/data/alpaca_paper_state.json'),
    max_position_pct=0.05,
    min_consensus_conviction=0.60,
    max_total_positions=15,
)
```

When loading portfolios at the start of every run:

```python
portfolios = load_portfolios(Path('docs/data/agent_portfolios.json'))
portfolios = ensure_all_agents_have_portfolios(portfolios, all_new_codenames())
```

When appending to history (search for `"date": today_iso`), also add:

```python
"timestamp": datetime.now(timezone.utc).isoformat(),
```

## Step 5 — Commit

In dev mode, source control panel, type a commit message like
"Alpha 2.0 — Full Learning Mode" and commit + push.

## Step 6 — Trigger the first run

Actions tab → Daily Run (10-min cadence) → Run workflow.

After it completes, check:

- `docs/data/agent_beliefs.json` should exist and have content
- `docs/data/agent_evolution_cards.json` should have entries
- `docs/data/alpaca_paper_state.json` should show your account info
- Visit `https://YOUR.github.io/SILMARIL/evolution_cards.html` — should
  render the gamified cards
- Visit https://app.alpaca.markets/paper/dashboard/overview — orders
  should be placed (or zero if no high-conviction signals today)

## Step 7 — Apply index.html edits when convenient

Open `INDEX_HTML_UPDATES.md` in the unzipped package. Six edits, all
find-and-replace. Takes 10 minutes. The system works without them, but
you'll be missing some UI niceties (renamed agents, fixed timestamps, etc.).

## Troubleshooting

**Daily workflow fails with "no module named alpaca":** Make sure you
updated requirements.txt and the workflow ran `pip install`.

**Alpaca state file says "API key not set":** Confirm secrets are added
exactly as `ALPACA_API_KEY` and `ALPACA_API_SECRET` (case sensitive).

**Evolution cards page is empty:** Cards populate on the first scored
outcome. Wait for the first daily run with completed scoring (typically
24h after first deployment).

**I want to reset everything:** Use Actions → Site Reset. Type `RESET`
to confirm. It backs up all learning state first, then wipes only the
cosmetic daily artifacts. Beliefs, cards, counterfactuals, etc. survive.
