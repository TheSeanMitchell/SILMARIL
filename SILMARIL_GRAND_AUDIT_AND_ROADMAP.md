# SILMARIL — GRAND AUDIT & ROADMAP (Alpha 0.001)
**Date:** 2026-06-06 · **Basis:** Friday-night backup after a full `--live` run + cockpit + 3 Alpaca order screenshots
**Method:** every claim below was read out of the actual repo or the screenshots — no assumptions, no patches applied.

---

## 0. WHAT IS VERIFIABLY WORKING (the wins, confirmed this pass)

- **Profit gate has teeth on the career book:** AEGIS de-amplified 0.77→**0.81×**, KESTREL+ 0.70→**0.75×** (screenshot: agent specialty map). Negative-EV agents are no longer amplified above 1.0×.
- **SPORTS BRO fantasy number is capped** at $10,000 (was billions). Leaderboard no longer looks broken.
- **Edge tab is live on the cockpit** (tab bar: Anomalies · Agents · Accounts · Continuity · Orchestration · **Edge**).
- **Account-live fix works:** cockpit shows **2/3 live** — correct, because HARVEST_5's most recent order is Jun 4 (screenshot), so it is genuinely dormant, not mis-flagged.
- **Weekend gate works:** Friday's run executed at 03:38 **UTC Saturday**, so scoring was correctly skipped. The "0 new outcomes this run" is **benign**, not a failure.
- **Stale contamination is quarantined:** all 798 stale outcomes are legacy (pre-fix), excluded from win-rate / EV / beliefs. Your Sunday reset clears them.
- **Cockpit is honest:** it surfaces ATLAS (80% win / −$28.68 realized), roster drift, the $100k-vs-$10k base, HARVEST_3 `configured:false`. The truth surface is doing its job.

These are real. Now the hard findings.

---

## 1. FILE SIZE — your concern, answered with numbers

| File | Size | Behaviour |
|------|------|-----------|
| `docs/data/history.json` | **26.6 MB** | additive, 34 runs (~780 KB/run) |
| `docs/data/charts.json` | **11.0 MB** | per-run snapshot |
| `premortem_archive.json` | 4.1 MB | additive |
| `handoff_blocks.json` | 3.4 MB | additive |
| **docs/data total** | **54 MB** | 76 JSON files |
| **repo total** | **57 MB** | — |

**The tension you sensed is real.** "Additive forever" and "loads fast / stays under GitHub's limits" cannot both be true past a point:

- GitHub's **hard limit is 100 MB per file**. `history.json` at 780 KB/run trends toward that.
- **The cockpit downloads and parses the full 26 MB `history.json` on every page load** — and only uses it for run-cadence timestamps. That is the single biggest dashboard-performance problem today.

**The right model (not "stop being additive" — *tier* the additivity):**
- **Learning substrate** (scoring, beliefs, edge_study, ledgers) → stay additive. Small and precious.
- **Raw snapshots** (history, charts) → **rolling window + archive**: keep the most recent N runs live; roll older runs into compressed yearly files under `docs/data/_archive/`. Nothing is lost; the live file stays bounded.
- **Cockpit** → read a tiny `history_index.json` (timestamps only), never the 26 MB blob.

**This is Track A/B and is a Monday-adjacent priority** — not because it breaks Monday, but because every run makes it worse.

---

## 2. IS ALL THE DATA USED? — "snapshotting everything" vs "driving decisions"

**Snapshotting: yes, comprehensively.** 334 stocks debated every run, 318 headlines consolidated, 341 catalyst/events ingested. That completeness is *exactly why* history/charts are huge.

But **"ingested" is not "drives a decision."** That distinction is the core of the next finding.

---

## 3. NEWS AS PREDICTION — the heart of your question, audited honestly

You said news is the heart of how SILMARIL should predict. **Today it is ~20% wired.** Precisely:

**What HAS teeth (news actually moves a trade):**
- News → `analytics/sentiment.py` → **17 of 39 agents** fold sentiment into their vote → consensus → trade. This is the *only* path where a headline changes a decision. It is real and it works.

**What does NOT exist yet (your vision, not yet built):**
- **News → regime.** `analytics/regime.py` decides RISK_ON/OFF/NEUTRAL from **SPY vs its 200/50-day moving averages + VIX only** — **zero** news/sentiment inputs. News does not predict regime at all.
- **Headline repetition → "seismic opportunity."** There is **no** clustering, no repeated-ticker/theme momentum detector, nothing that says "this name keeps showing up — lean in." This mechanism simply isn't in the code.
- **Catalysts / upcoming events → trades.** 341 events are ingested, but they're consumed only by **display-only modules** (`conviction_engine`, `policy_router`, `narrative_tracker`) whose output never reaches the executor. The earnings/Fed calendar does not move positioning.
- **Regime baskets.** Not implemented — the word appears incidentally; there is no regime→basket allocation map with teeth.

**Verdict:** the ingestion is rich and the instinct is right — *this is the single biggest upside in the whole system.* The work is wiring, and all of it can be done **deterministically and explainably** (no synthetic AI), and tested on the clean week. See roadmap P-NEWS.

---

## 4. A "MENTAT" — an agent/team that analyzes the data and automates improvement

**Short answer: yes, feasible, and it should roll into the daily run — but as a deterministic analyst, not autonomous LLM agents, and it must *propose*, never *auto-apply*.**

Why this shape:
- You require determinism + explainability. A literal "team of LLM agents" rewriting the system fails that and re-introduces exactly the contamination risk we just spent weeks killing (a loop that changes its own behavior on noisy data spirals).
- The safe, powerful version is **one deterministic ANALYST pass** (call it the **Mentat**) that runs *after scoring in the daily cycle* — cheap, no extra API:
  1. **Reads the day's data** (scoring, beliefs, edge_study, news efficacy, regime accuracy, event hit-rate, agent drift).
  2. **Runs diagnostics** — `edge_study.py` is the seed; extend it into a full daily intelligence digest.
  3. **Writes `mentat_digest.json` + a cockpit panel** — "here is what changed, what's working, what's drifting."
  4. **Writes `mentat_proposals.json`** — concrete, bounded parameter suggestions (conviction threshold, per-agent universe via `applies_to()`, weight nudges) each with the evidence behind it. **The operator approves; nothing self-applies.**

That gives you the "constantly thinking, rethinking back on the data" loop you want, with a human gate where the danger lives. Later, once a proposal type proves itself over many weeks, *that specific type* can graduate to auto-apply behind a flag — earned, not assumed.

---

## 5. EVENING PREP — keep, improve, or eliminate?

**Eliminate it (or slim it to the overnight gap). One daily run can and already does do the work.**

Evidence:
- evening_prep's core action is `apply_post_cycle_protections(...)` — **the exact function the daily cycle already calls every run** (`cli.py` line 1681). Daily fires every 5–10 min, so protection already happens continuously.
- It is **not** a concurrency race (correction to earlier notes): daily and evening_prep **share the `silmaril-broker` group**, so GitHub serializes them. The cockpit's "separate groups / no lock" line is **stale and should be corrected**.
- It **does** cost you: overlapping schedules (daily `*/5 8-13` vs evening_prep `*/5 7-13`, `*/5 8-9`; daily `*/5 20-23` vs evening_prep `*/5 19-21`) mean redundant queued runs and **wasted price-API quota** — your stated concern.
- Its `SILMARIL_PROTECTION_ONLY` env flag is **dead** — `cli.py` reads it **0 times**, and evening_prep doesn't even invoke the CLI (it runs an inline `python -c`).

**Before deleting, fold in its two non-redundant side-effects** so nothing is lost: confirm the daily cycle also calls `write_clock()` and `build_leaderboard_v2()`; if not, add them (cheap). Then either delete evening_prep or restrict its cron to the **single overnight gap** daily covers sparsely. Net effect: fewer runs, less quota, simpler system, the overlap anomaly gone — all things you asked for.

---

## 6. OTHER WEIRDNESS (grounded in the screenshots + data)

- **Out-of-scope theater persists on the public dashboard.** `index.html` references CRYPTOBRO / SPORTS BRO / Polymarket **73 times** (screenshots: compounder cards, prediction-market bets, crypto agents). `cryptobro.json` / `sports_bro.json` / `jrr_token.json` still ship. `RUN_SYNTHETIC_COMPOUNDERS=False` stops their *simulation*, but the dashboard still *displays* them — directly contradicting the stocks-only mission and making the product look unfocused to any observer. **Purge from `index.html`** (or retire `index.html` in favour of the clean cockpit + a clean public board).
- **Outcomes carry no date field** (every outcome's date is empty). This makes accrual/recency invisible from `scoring.json` and means the cockpit's "stale by day" is really "stale at each snapshot." Adding a per-outcome scored-date is a small fix that makes a lot of analysis honest.
- **Execution-quality observability is only 2.083% measurable** (screenshot) because most fills are **market orders at unknown next-open prices** (Alpaca screenshots show many `Market` orders, some submitted in the evening). Slippage/edge can't be measured cleanly against an unknown entry. Prefer **limit orders at the quoted price** (some already are — good) so fills become measurable.
- **The Monday accrual test:** total outcomes are stuck at exactly 2052 across the last two backups. That's consistent with both being weekend/evening snapshots, but it's **the** thing to watch Monday: the total should climb past 2052 **and** the stale% should **not** climb. If the total stays flat on a trading day, the fresh-quote overlay isn't delivering in Actions and we debug that first.

---

## 7. THE ROADMAP — sequenced, Track-classified

**Tracks:** A = safe / additive / reversible · B = behavioural, operator-gated · C = future build.

### NOW → MONDAY (safe, high-leverage, mostly data-independent)
1. **[A] This audit committed to root.** (this file)
2. **[A] Correct the cockpit orchestration text** — they share a concurrency group; the "no lock" line is false.
3. **[B] Slim/eliminate evening_prep** — after confirming daily covers clock+leaderboard. Cuts quota + redundancy + the overlap anomaly. *Operator gate.*
4. **[A→B] Tier the additive data** — rolling window for `history.json`/`charts.json` + `_archive/`; cockpit reads `history_index.json` not the 26 MB blob. Stops the file-size bleed.
5. **[A] Per-outcome scored-date** in `outcomes.py` — makes accrual + day-analysis real.
6. **Sunday night:** reset the stale counter (your plan) so Monday starts clean.

### THE CLEAN WEEK (data-gated — the real test)
7. **Watch** the equity-directional t-stat (Edge tab) hold ≥ 2 as clean outcomes accrue; watch WEAVER/HEX keep their edge on fresh prices.
8. **[B] Clean belief rebuild** (touches protected `agent_beliefs.json`, operator's call) once a clean week exists.
9. **[B] Profit-based beliefs** — update beliefs by realized P&L, not just correctness.

### THE FLAGSHIP — P-NEWS: make news actually predict (deterministic, the biggest upside)
10. **[C] News-informed regime nowcast** — blend sentiment *breadth* (share of universe with strong +/− sentiment) into `regime.py` alongside SPY/VIX. Give regime a news input.
11. **[C] Headline-repetition / momentum signal** — cluster repeated tickers/themes over a rolling N-day window; a name that keeps surfacing earns a bounded conviction boost. This is your "seismic opportunity" detector.
12. **[C] Event-calendar positioning** — give the 341-event catalyst feed teeth: pre-earnings/Fed posture rules that actually reach the executor.
13. **[C] Regime→basket allocation** — define baskets per regime and let allocation tilt with teeth (currently absent).
14. **[A→B] Marketaux entity sentiment** — real per-entity sentiment to replace free RSS (no signup; key already in the workflow). Direct upgrade to the one news path that already has teeth.

### THE MENTAT — P-META: the self-analysis loop
15. **[A] `mentat_digest.json` + cockpit panel** — extend `edge_study` into a full daily diagnostic (news efficacy, regime accuracy, event hit-rate, agent drift). Read-only, runs in the daily cycle.
16. **[B] `mentat_proposals.json`** — bounded, evidence-backed parameter proposals; operator approves. Never auto-applies.
17. **[C] Earned auto-apply** — once a proposal type proves out over weeks, graduate *that type* behind a flag.

### REAL AGENT EVOLUTION (the long game)
18. **[C] Parameter-mutation of proven winners** (WEAVER/HEX) with fitness = realized profit. The Senate currently only *proposes* offspring cards; this makes evolution real.

---

## 8. EXECUTION ORDER TO MONDAY

The disciplined sequence is: **(1)** commit this audit, **(2)** ship the two pure-safe Track-A items (cockpit text fix + per-outcome date), **(3)** decide together on evening_prep (Track B — I won't change orchestration before a critical Monday without your go), **(4)** tier the additive data, **(5)** Sunday reset. Then the clean week runs and we watch the Edge tab. The flagship news-prediction builds (P-NEWS) start the moment we confirm clean outcomes are accruing — building them on contaminated data would repeat the original mistake.

**One honest caveat:** the most valuable items (P-NEWS, P-META) are deliberately *after* the clean week, because their entire value depends on a trustworthy input signal. Rushing them before Monday would be the same error that cost us the last several Alpha cycles. The pre-Monday work is real but bounded; the transformation is the week after.
