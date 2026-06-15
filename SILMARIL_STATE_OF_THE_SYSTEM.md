# SILMARIL — STATE OF THE SYSTEM (rounded up, 2026-06-06)

Single authoritative status. **Supersedes the six `ALPHA_0.001_*.md` notes** (archive
them — everything below captures them). Reads alongside `SILMARIL_GRAND_AUDIT_AND_ROADMAP.md`
(the deep audit) and `SILMARIL_BOOTSTRAP_ALPHA_0.001.xml` (session substrate).

---

## 0. MISSION — corrected and locked

SILMARIL explores **all tradable assets — every way to make money** — through competing,
named agent *philosophies* that debate, trade (paper), and learn. It is **not** stocks-only.

- The **live book** (3 Alpaca paper accounts: LEGACY / HARVEST_3 / HARVEST_5) currently
  trades **US equities + ETFs**. That is why "edge" is measured *per asset class* — equities
  is simply the class with live orders and the most clean data right now, not the whole point.
- The **compounders** (Scrooge, King Midas, CryptoBro, JRR Token, Sports Bro) are **kept** as
  philosophy demonstrators. They are **simulated** (mark-to-market), not live decision-makers —
  the goal of making them learn from reality is on the roadmap, honestly labelled as not-yet.
- **The analyst/improvement layer is rigid hard-coded rules — never an LLM.** Deterministic
  good/bad judgements, fully explainable. This is a hard constraint, not a preference.

---

## 1. VERIFIED WORKING (confirmed in the repo + screenshots)

- **Profit gate** — negative-EV agents are never amplified >1.0× on the career book
  (AEGIS 0.77→0.81×, KESTREL+ 0.70→0.75× in the live screenshots).
- **Stale-skip** — failed-fetch (entry==exit) outcomes are no longer recorded; the 798
  existing stale outcomes are **legacy**, flagged, and **excluded from win-rate / EV / beliefs**.
- **Equity leaderboard + edge study** — per-agent stats are equity-clean; `edge_study.json`
  regenerates every run. Significant equity edge today: **WEAVER (t≈3.97), HEX (t≈2.42)**;
  edge is **long-only**; all clean data is RISK_ON (regime untested).
- **Belief fix** — the real trade-driving Thompson beliefs train on **clean, equity,
  directional** outcomes and read the **correct sampled regime** (was landing in UNKNOWN).
- **Cockpit** — account-live fix (2/3 correct; HARVEST_5 genuinely dormant), Edge tab live,
  and the orchestration text is now **truthful** (shared `silmaril-broker` group, not a race).
- **SPORTS BRO** capped (no more fantasy billions). Root cleaned to canonical docs.

## 2. THIS TURN'S CHANGES (ship now)

- **`daily.yml` → single efficient cadence.** Slim trading-hours cron: `*/15 13-20` weekdays
  (regular session), 2 pre-market warm-ups (`0,40 12`), and **one** off-hours sample/day
  (`0 1 * * *`) for the 24/7 simulated compounders + overnight news. ~34 runs/weekday vs ~90.
  Big price-API-quota reduction, same clean-data coverage.
- **`evening_prep.yml` → DELETE.** Verified 100% redundant: the `--live` cycle already runs
  `apply_post_cycle_protections`, `write_clock`, and `build_leaderboard_v2` every run
  (cli.py ~1681). Its `SILMARIL_PROTECTION_ONLY` flag was dead (cli.py never read it).
- **Storage plan** — see `STORAGE_AND_SCALE.md`. Two-tier (LIVE rolling + ARCHIVE forever),
  GitHub-native, decades-proof, lossless. Keep `weekly_backup.yml` enabled.

### How to apply
1. Replace `.github/workflows/daily.yml` with the new one.
2. **Delete** `.github/workflows/evening_prep.yml`.
3. Add `STORAGE_AND_SCALE.md` + this file to root; archive the six `ALPHA_0.001_*.md`.
4. Confirm `weekly_backup.yml` is **enabled** in the Actions tab (data-safety net).

---

## 3. CURRENT DATA REALITY (watch Monday)

- **2052 scored outcomes** (1254 clean / 798 legacy-stale). Total has been flat across the
  last backups — consistent with weekend/evening snapshots + the weekend scoring gate.
- **The Monday test:** on a trading day the total should climb **past 2052** *and* the
  stale% should **not** climb. If the total stays flat on a trading day, the fresh-quote
  overlay isn't delivering in Actions and we debug that before anything else.
- **Sunday:** reset the stale counter (clears the 798 legacy) so Monday starts clean.
- **File sizes:** `history.json` 26 MB (additive, lossless, ~0.7 MB/day); cockpit loads it
  whole today — fixing that is the next build (see §5).

---

## 4. ACTIVE WORKFLOWS AFTER THIS CHANGE

- **`daily.yml`** — the sole trading runner (slim cadence above).
- **`weekly_backup.yml`** — KEEP enabled (tar.gz backups; your never-lose-data net).
- Everything else stays disabled (per your direction) until explicitly re-enabled.

---

## 5. ROADMAP — what's next (from the grand audit, rigid-rules only)

**Immediate next build (Track A, highest near-term value):**
- **Tier the data / fix cockpit load** — write `history_index.json`, archive-then-trim
  `history.json` to a rolling window, point the cockpit at the index. Lossless; instant load.

**The flagship — make news actually predict (deterministic, no LLM):**
- **News-informed regime** — blend sentiment *breadth* into `regime.py` (today it's SPY/VIX only).
- **Headline-repetition / momentum** — rolling N-day repeated-ticker/theme detector → bounded
  conviction boost. Your "seismic opportunity" signal.
- **Event-calendar positioning** — give the 341-event catalyst feed teeth into execution.
- **Regime → basket allocation** — define per-regime baskets that actually tilt allocation.
- **Marketaux entity sentiment** — upgrade the one news path that already has teeth (key in workflow).

**The Mentat (rigid deterministic self-analysis, proposes — never auto-applies):**
- Daily post-scoring diagnostic (`mentat_digest.json` + cockpit panel) on news efficacy,
  regime accuracy, event hit-rate, agent drift.
- `mentat_proposals.json` — bounded, evidence-backed parameter suggestions you approve.

**Data-gated (after a clean week):**
- Clean belief rebuild; profit-based beliefs; per-outcome scored-date.
- Expand belief training beyond equities **if/when** the live accounts begin trading other
  asset classes (Alpaca supports crypto) — keep beliefs matched to what is actually traded.

**Long game:**
- Real agent **evolution** — parameter-mutation of proven winners (WEAVER/HEX), fitness =
  realized profit. The Senate currently only proposes offspring cards; this makes it real.
- Make the **compounders learn from reality** (your original hope) rather than pure simulation.

---

*Discipline unchanged: read the actual file before editing, deliver complete drag-and-drop
files, validate on real data, reward realized profit over win-rate, and build the
news/learning upgrades on a clean signal — not on contaminated data.*
