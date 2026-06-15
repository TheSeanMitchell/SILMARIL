# SILMARIL — Project Bootstrap & State Summary
_Generated for the Monday clean-data start. This is the plain-record handoff: what the
system is, what holds true today, and what to watch. Pairs with the canonical
`SILMARIL_BOOTSTRAP_v6.3.xml` substrate._

---

## 1. What SILMARIL is
An autonomous, multi-agent **paper-trading research system** (no real money). ~39 named
agents run senate / debate / scoring / learning cycles over three Alpaca **paper** accounts.
The mission is **edge detection** — "edge in news, in words; actions in numbers." News and
narrative are predictive inputs; trades are the reactive expression. The system is
deterministic and explainable end-to-end: **no LLMs in any analyst layer, no synthetic data.**

- Repo: `github.com/TheSeanMitchell/SILMARIL`
- Live front door (briefing): `theseanmitchell.github.io/SILMARIL/`
- Operator Cockpit (deep view): `…/cockpit.html`
- Scale: **189 Python files, ~45,700 LOC**, 174 wired (see §8).

## 2. The three accounts — $10,000 baseline each (firm)
| Account | ID | Strategy | Equity (this backup) | vs $10k |
|---|---|---|---|---|
| LEGACY ("Silmaril") | PA3U0HDV3ETB | 1.5% trench-warfare harvester | $9,529 | −4.7% |
| HARVEST_3 | PA3RR1IC9UVD | 3% disciplined (skips TINY) | $9,641 | −3.6% |
| HARVEST_5 | PA3BLURBA7EP | 5% conviction (skips TINY+MINI) | $9,656 | −3.4% |

**$10,000 is the permanent baseline for every account.** The old $100k Alpaca default has been
purged from code (`alpaca_paper.py` defaults to 10000; the "heal" forces any legacy/100000 to
exactly 10000 and never resets principal to current equity) and from data (the orphaned
`alpaca_equity_curve.json`, frozen on the $100k base, is cleared). The drift sentinel asserts
this every cycle (`principal_baseline`).

## 3. Doctrine — non-negotiables
- **Real data only.** No synthetic data or logic, anywhere.
- **No LLMs in analyst layers.** All reasoning is deterministic rules (incl. the new
  auto-reflection and the narrative engine).
- **Additive, never destructive.** New panels/modules; agents are promoted/elected/evolved,
  never deleted. (Sole sanctioned replacement to date: the front-door `index.html` → briefing.)
- **Reward realized profit, not win-rate.** Win-rate ≠ profit (see ATLAS: 80% win, −$28.68).
- **Read before write.** Never patch a file without reading its current contents.
- **Clean data gating.** Stale-priced outcomes are quarantined from learning, never deleted.

## 4. Verified state at this backup (2026-06-08, ~05:12 UTC)
- **Scoring:** 2,143 outcomes; 1,345 clean / 798 stale (**37.2%**, trend flat). Stale is
  quarantined from learning. Monday is the first clean trading week.
- **Narrative engine (edge-in-words):** **FED and working** — 294 headlines → dominant
  narrative `ai_rally`, regime tilt rotating, Technology/Health-Care leading, Utilities fading.
  (Was silently starved at 0 headlines until the `recent_headlines` fix — see §5.)
- **Order hygiene:** stale-order canceller live; HARVEST_3 has cancelled lingering unfilled
  orders 6× (visible as "canceled" EOG/PLD rows in Alpaca). LEGACY/H5 had none to cancel.
- **Agents:** 8 classify Verified (FORGE, HEX, OBSIDIAN, STEADFAST, SYNTH, THUNDERHEAD, WEAVER,
  ZENITH) — none has yet proven *realized* edge on clean data. 2 frozen on stale-era scores
  (AEGIS, KESTREL+) — candidates to unfreeze mid-week once clean prices exist.
- **IPO:** SpaceX (SPCX) debuts **Fri Jun 12** — largest IPO in history (~$1.9T). Recorder at
  6 snapshots. The macro gauntlet around it: ORCL earnings (Jun 10), **CPI (Jun 11)**, ADBE/LEN
  (Jun 11), **FOMC (Jun 18)**, triple-witching + S&P rebalance (Jun 19). Books carry 91
  positions into the open, 9 in the SpaceX complex.
- **Drift sentinel:** **9/9 invariants holding.**

## 5. What was built recently (most recent first)
- **Anti-drift sentinel** (`diagnostics/drift_sentinel.py`, NEW): read-only invariant checker,
  runs last each cycle, logs drift over time. Asserts baseline=$10k, **narrative fed** (regression
  guard for the starvation bug), accounts active, stale bounded, frozen bounded, orphans bounded,
  order hygiene, deal-linking. Surfaced on the briefing ("System integrity: 9/9").
- **Autonomous deterministic reflection** (`learning/reflection.py` + `reflection.yml`): replaces
  the empty manual placeholder. Composes a real 2–4 sentence rule of thumb from the day's data
  (narrative, catalyst gauntlet, IPO-complex performance, clean-data discipline) and injects it
  into every agent's context. No LLM. Self-sustaining learning loop.
- **Catalyst-starvation fixes (×4):** `regime_memory`, `event_impact`, the cli catalyst index,
  and `sweep_protection` all read catalysts via the dead key `"catalysts"`; the file uses
  `daily`/`weekly`. Fixed → sweep_protection now sees **74 catalyst-tagged tickers** (was 0),
  case files and regime scoring get real catalysts. (event_impact now receives the calendar; its
  rules match *directional* phrases so it activates on directional catalysts.)
- **Narrative-engine starvation fix:** `_gather_headlines` read `news`/`headlines`; signals.json
  uses `recent_headlines`; cli passed catalysts via the wrong key. Fixed → headline_count 0→294,
  real `ai_rally` narrative now feeds all 11 consumer modules.
- **$10k baseline enforced everywhere** + **stale-order canceller** (`alpaca_paper.py`).
- **UI overhaul:** the site root is now the plain-English mobile briefing (was a 406 KB wall).
- **OPUS file archive** (`opus_file_archive.json`): one-line purpose for all 189 files + wiring
  graph + honest orphan classification.

## 6. Active workflows (audited — all good)
- **Daily Run** (`daily.yml`) — heartbeat. Cron: every 15 min during the US session
  (`*/15 13-20 * * 1-5`), 2 pre-market warm-ups (`0,40 12 * * 1-5`), 1 off-hours/day
  (`0 1 * * *`). Write-safe concurrency (`silmaril-broker`, cancel-in-progress=false). Commits
  `docs/data` + the briefing; pull-rebase + 3× push retry. Runs the post-cycle sidecars incl.
  the new drift sentinel.
- **Daily Reflection Bootstrap** (`reflection.yml`) — 8:30 PM UTC weekdays. Now writes the
  **auto-reflection** (falls back to an empty operator placeholder only if no data).
- **Senate Elections** (`senate.yml`) — 06:00 UTC on the 1st & 15th; Conclave on the 1st
  (runtime day-check gates it correctly). Promotes/demotes/graduates agents; commits state.
- **Weekly Learning Backup** (`weekly_backup.yml`) — Sun 00:00 UTC. Tars protected learning
  state to `_backups/`, prunes to 12 weeks.
- (Nightly Correlation Matrix has a cron but is **disabled in the GitHub UI** — won't run.)
- All reset/diagnose/migration workflows are **disabled** (manual-only), as intended.

## 7. Known issues / watch items (none Monday-blocking)
- **Win-rate ≠ realized** (ATLAS 80% win, −$28.68): display-only; honest by design.
- **Roster drift**: portfolios=31, risk_state=31, scoring(track)=20, a reset hardcode=27. The
  reset hardcode would diverge *if a reset ran* (resets are disabled). Unify the roster source
  before re-enabling any reset.
- **`position_meta` accumulation**: ~42 "positions" tracked on a $9.5k account — meta isn't
  pruned when a position closes. Cosmetic (inflates the holdings count); prune-on-close later.
- **HARVEST_5 quiet**: last activity Jun 4. If it should trade, confirm its Alpaca secrets.
- **4 truly-disconnected files** (duplicate `status_emitter`s, old `market_hours`,
  `backtest_to_beliefs`): attic when convenient. The sentinel warns if this count grows.

## 8. File wiring (from the OPUS archive)
189 files / ~45,700 LOC; **174 wired**. Of the 15 not imported at module level: Senate/Conclave
are workflow-invoked; the Alpha-4.0 modules import lazily; candidate_alpha/beta/gamma are
intentional Conclave births; **4 are truly disconnected** (see §7). Nothing is silently rotting.

## 9. Readiness gates — what to watch Mon → Fri
1. **Monday (the test that matters):** outcomes climb past ~2,143 **while the stale share does
   not climb.** That proves the price overlay feeds fresh quotes inside Actions. If flat on a
   trading day, debug the overlay first. The sentinel's `stale_bounded` check will warn if stale
   climbs >3 points.
2. **Tuesday:** ORCL earnings (Jun 10) — first real catalyst→outcome link in the ledger and the
   deal journal's "why."
3. **Mid-week:** unfreeze AEGIS/KESTREL+ once clean prices exist; build the IPO ecosystem map.
4. **Friday:** SPCX debut — recorder + catalyst gauntlet + deal journal capture it; SPCX
   auto-joins the universe.
- Every cycle: the **drift sentinel** logs a daily integrity entry — read it on the briefing.
  The **auto-reflection** refreshes each evening and teaches the next day's agents.

---
_Read-only, paper-trading. All numbers above are from the 2026-06-08 backup and update each run._
