# ROADMAP_TO_ALPHA_1.md — the push to June 22

This document is the continuity anchor. Any future session (or future agent)
reads this first. It encodes the doctrine, what is DONE and VERIFIED, what
remains for ALPHA 1.0, and the exact specs so nothing drifts when context runs
out. Updated June 11, 2026 (SPCX debut week, Fable 5 cutoff June 22).

## DOCTRINE (now canonical — fold into FOUNDING_CHARTER on next pass)
- THE GOAL: a harvest engine that reliably banks **$100+/day from $10K**, by
  mastering IN and OUT — buy each stock's daily low window, sell its high
  window, verify every dollar against broker fills. Each paper account is an
  experiment toward that engine.
- ALL VALUABLES: stocks first (Alpaca), but every valuable — crypto, gold,
  oil, metals, macro — gets the same words, same judgement, same permanent
  record (valuables.py is the seed).
- ACCOUNTS COMPETE, not cooperate: LEGACY (full consensus) vs HARVEST_3
  (3% tier) vs HARVEST_5 (headlines-only Wordsmith). The duel board ranks
  them; the winner's method is what gets plugged into the single live account
  one day. The handoff must be: "plug account-N's method into live."
- TRUTH LAW: synced is everything; fills or it didn't happen; every judge is
  itself judged; nothing deleted, losers demoted by the senate.

## DONE AND VERIFIED (do not rebuild — only extend)
Words: vocab r1–r5, catalysts, anticipation, events, IPO tape, commodities/
crypto. Relevance filter (same-name collision killer). Source fingerprints
with live earned weights + judge-the-judge. Clocks: 80+ bar-seeded
fingerprints; refuse-the-top, rest-at-floor, clock harvest, harvest clock-
gate, giveback guard, session hard-gate, whole-share extended. Learning:
profit-weighted Thompson belief multipliers ARE wired into consensus; senate
elections SEAT (bench/promote via shadow); amnesty commits. Measurement:
report card (picks, would-vs-wouldn't, per-gate bench, calibration, headline
edge w/ Wilson CIs, deployment truth), harvest fill-truth, sentinel alarms,
archive layer (lossless). SPCX: console + thesis checkpoints, EDGAR 424B
watch, social pulse. UI: briefing organs, stock.html profiles, universal
links, three-window deltas. Scheduling: external cron (cron-job.org) live
every 20 min market hours.

## REMAINING FOR ALPHA 1.0 (ranked; specs below)
1. **Per-domain clocks** so the external cron can run 24/7 every 20 min
   safely: gate EXPENSIVE work by domain — stock news fetch only 08:30–16:30
   ET Mon–Fri; valuables/crypto every run; social hourly; EDGAR every run
   during SPCX month then 4h. Spec: a `domain_clock(domain) -> bool` helper
   in suite/cli consulted before each fetch family; budgets logged to
   api_health. DO NOT widen the external cron to 24/7 until this lands.
2. **Wantgot truth v2**: plans carry intended notional; reconcile intended vs
   filled vs held per name; render the diff with reasons (gate, pending
   limit, partial). Kills the "stale third account" confusion class.
3. **vs-market judge v2**: persist daily Δ-vs-SPY/QQQ series; trend verdict
   (IMPROVING/FLAT/DECAYING over 5 sessions); EDGE-DECAY alarm via sentinel;
   feed senate context. (v1 duel board ships June 11.)
4. **Breeding automation**: senate already promotes/demotes. Spec offspring:
   top-2 VOTER hybrids = weighted blend of parents' signal weights + mutation
   ±10%; born PROBATIONARY, shadow first 2 weeks; cap roster at 24. Then the
   evolution loop is human-free.
5. **Equity-edge attribution per agent** (cockpit tab): realized P&L share by
   verdict participation; feeds breeding fitness alongside clean hit-rate.
6. **Docs to ALPHA 1.0**: refresh README; fold doctrine into
   FOUNDING_CHARTER; regenerate AUDIT.md matrix; prune attic/ per list;
   version badges -> ALPHA 1.0 on the 22nd only if suite green + sentinel
   quiet + duel board populated 5+ sessions.
7. **Hardening (start NOW, finish by 22nd)**: rotate the exposed PAT; GitHub
   branch protection on main; pin action versions; Dependabot on; secrets
   audit (Alpaca keys scoped paper-only); repo private decision; quarterly
   key-rotation note in SCHEDULING.md; backup = git history (verified).
8. **News board v2** ("hit-board"): per-row clock-window chip, personality,
   source-weighted read, oracle flag, 1-click to stock.html (v1 partial).

## OPERATING RHYTHM TO THE 22ND
Mon: per-domain clocks + wantgot v2. Tue: vs-market judge v2 + news board v2.
Wed: breeding automation + equity attribution. Thu: docs/ALPHA 1.0 pass +
hardening checklist. Fri 19–22: observation, duel verdict, tag ALPHA 1.0.
Every session: install bundle -> run daily -> backup zip -> next bundle.

## WALK-AWAY CRITERIA (the honest bar)
Four consecutive clean weeks where: sentinel raised zero unresolved alarms,
senate ran unattended, no bundle installs required, duel board stable, and
the report card's calibration is positive. Until then it's automated with a
human heartbeat check; after that, it's automated.

## INJECTED JUNE 11 LATE SESSION — operator's pre-SPCX directive (ranked)
Shipped immediately (this bundle): per-domain clocks (#1 ✓), wantgot truth
v2 (#2 ✓), H5 wordsmith origination starvation FIXED (shape bug; now loud),
universe expanded 349→615 (520 equities — full S&P 500 fill, best-effort
static list, verify membership on next networked pass), "Going into Monday"
made day-aware on index+briefing (was hardcoded weekend copy nothing audited).

REMAINING, ranked against the existing list (specs binding):
A. VALUABLES PARITY PROGRAM — the big one; phased, never all-at-once:
   A1. Valuables voter agent ("GOLDSMITH"): FABLEBOY-pattern voter whose
       jurisdiction is ONLY non-equity names (crypto tickers + GLD/SLV/USO/
       UNG/CPER/etc. proxies — the tradeable expressions of valuables).
       Conviction from valuables_history word scores; conviction-weighted
       sizing applies automatically (it already keys off plan score). Joins
       MAIN_VOTERS like fableboy5 did; learning rows flow through the same
       profit-weighted loop. THIS IS THE WEDGE: senate/elections/breeding
       then cover valuables agents FOR FREE because they're roster agents.
   A2. Valuables "how the news moved decisions" UI section: same template
       as the stock news board, fed from valuables_history.json (it already
       records words/anticipation/catalysts per valuable per day).
   A3. Valuables fingerprints permanence: timing + news fingerprints for
       -USD and macro-ETF names (the organs exist; confirm these classes
       aren't filtered out, extend budgets).
   A4. Valuables click-through cards (stock.html pattern → valuable.html)
       with full history chart + fingerprint overlay + NEXT-SESSION
       expectation bands (engine's clock windows + Dr. Strange picks).
       This is also where stock cards gain tomorrow-expectation overlays.
   A5. Separate-but-equal senate ledgers: tag every agent stocks|valuables;
       elections run per jurisdiction; breeding (#4) breeds within
       jurisdiction. Roster cap 24 splits 16 stocks / 8 valuables initially.
B. IPO WATCH AUTO-ROTATION: when SPCX (or any tracked debut) reaches
   priced+5 sessions, edgar_watch + spcx-console machinery auto-advances to
   the next ipo_calendar entry (nearest future date, exchange-listed).
   Console generalizes: SPCX → "DEBUT WATCH: <ticker>". PENDING_LISTINGS
   auto-append from ipo_calendar rows (additive; never removes). The IPO
   calendar already self-fills from Finnhub/FMP — rotation closes the loop
   so no human ever names the next debut.
C. SECTION HEALTH MATRICES: api_health already has the data; render a
   per-section source-status chip row (NEWS / VALUABLES / SOCIAL / EDGAR /
   PRICES) on briefing + intelligence so a dead provider is visible inside
   the section that depends on it, not just on the health page.
D. LIQUIDITY-AWARE WANTGOT CLOSURE: wantgot v2 exposes blocked_negative_cash
   per name; next: conviction-ranked capital queue — when cash runs out,
   intents queue and the NEXT cycle's free cash goes to the highest-
   conviction queued name first (additive planner input, not a new gate).
E. TAB DEEPENING PASS (post-1.0 unless time allows): catalyst tab shows
   per-catalyst-class Wilson CI edge vs base rate updating daily; deal
   journal rows carry the engine's forward expectation at entry (clock
   window + conviction + expected harvest) so every deal is a testable
   prediction; intelligence tab gets the aggression/ergonomics pass; EDGE
   tab highlights success/penalizes failure via the existing report-card
   series. Frozen-agent auto-debug: sentinel rule that detects >N-day
   frozen agents and files an amnesty-review row for the senate run.
DOCTRINE ADDITIONS (operator, June 11): everything that judges gets judged
and the judgement feeds elections/breeding; constant fixed roster always
breeding toward better offspring; stocks and valuables separate but equal;
the bar stays: find edge, then SUBSTANTIATE it over and over.

## JUNE 11 NIGHT SESSION — laws updated, guards hardened (shipped)
NEW LAWS (supersessions are recorded, never erased — additive history):
- NEWS ROTATION LAW supersedes the Alpha 2.2 fixed 100-cap: time-budgeted
  rotating window (100/cycle, cursor persisted) covers the FULL 500+ equity
  universe every ~6 session cycles; held positions ride every cycle. The
  constraint was always the 30-min runner, never the number — uncapping
  sequentially would have broken every run, so the cap was retired by
  redesign, not deletion.
- STOCKS-ONLY MISSION GUARD: all three Alpaca accounts are traditional-
  equities-only at the order choke point (structural check: blocks -USD/
  -USDT patterns AND macro-commodity ETFs like GLD/USO, fail-closed).
  Valuables trade in their own future zone/account — set up now so we
  never kick ourselves later. Block category: blocked_not_equity_mission.
- STORAGE + CRON-PRESSURE METERS in api_health: repo/archive MB vs GitHub
  free limits (ok<500MB, watch<1GB, warn<2GB, critical beyond, with
  migration guidance) and estimated per-provider quota usage vs free-tier
  budgets with ride-the-limit doctrine: push cadence to 'riding' (70%),
  back off on 'over' + delivery collapse. Per-provider call
  instrumentation = roadmap C extension.
- NO-SYNTHETIC-DATA is confirmed core doctrine (already charter law; the
  S&P fill list is universe CONFIG, not decision-path data).
OPERATOR DECISIONS RECORDED:
- Harvest strategy authority delegated; decision: the DUEL BOARD decides.
  HARVEST_3 (3% clock-gated tier) wears the crown as of June 11; winner's
  method is the live-plug candidate. No hunch overrides a measured verdict.
- The $100/day goal is recorded as the mission's center of gravity AND the
  honesty law applies to it: the report card / calibration / duel series
  are the only valid proof. Current verdict: NOT PROVEN. Nothing ships
  that fakes progress toward it.
NEXT-SESSION SPECS (binding):
- F. VALUABLES CLOCK BACKFILL: seed timing fingerprints for -USD + macro
  names from free historical OHLC (yfinance daily/intraday where present;
  CoinGecko range API as crypto fallback) through the SAME bar-seeding path
  stocks used. Injectable fetchers; offline-safe; rows append to the same
  permanent stores. Buy-low-window/sell-high-window parity with stocks.
- G. IPO PREDICTION ENGINE ("the week ahead" deepening): per upcoming IPO,
  a pre-debut expectation card built from the word engine (anticipation +
  catalyst + sentiment series), sector sympathy map (which held names move
  on debut news), and a graded prediction row written BEFORE debut and
  scored after T+5 — judged like every judge, feeding source weights and
  senate context. Card becomes the stock card at listing (auto via
  PENDING_LISTINGS). Generalizes to MAJOR-PR events later.

## CONSOLIDATED STATE — June 11, final session (THE summary; supersedes
## nothing, absorbs everything: original prompt + all operator directives)
MISSION: $100/day from $10K via mastered in/out timing — recorded with the
honesty clause: report-card/calibration/duel series are the only proof;
verdict today NOT PROVEN; fees truth says real-world drag would already
exceed realized P&L (LEGACY est. drag = 227% of realized). Operator vow on
record: no real dollars until proven, and only losable ones.
SHIPPED & VERIFIED (June 11, three bundles):
1 per-domain clocks -> cron runs 24/7 (live); 2 wantgot truth v2 (live —
intents now visible per cycle per book); H5 wordsmith origination FIXED
(593 rows fed, 5 candidates approved, intents flowing); universe 615 names
/520 equities; day-aware UI; news ROTATION law (full-universe coverage
~6 cycles, holdings every cycle); STOCKS-ONLY hard guard at order choke
(crypto/tokens/macro-ETFs can never reach any Alpaca account); storage +
cron-pressure meters; STOCKS_NEWS clock (information never sleeps: every
run in-session, hourly sweeps off-hours/weekends — only TRADING keeps
market hours); FEES TRUTH organ (SEC+TAF+slippage estimated over every
historical & future order; round-trip law: $0.43/$1K market, $0.03/$1K
limit — every harvest floor must clear it). Suite 22/22, sentinel quiet.
ALPHA 1.0 TAG DISCIPLINE: tag requires suite green + sentinel quiet +
duel board 5+ SESSIONS. Duel went live June 11 -> earliest honest tag
~June 17-18. The 22nd deadline holds; the tag is earned, not declared.
REMAINING TO 1.0 (order of attack, absorbing every operator ask):
Tue: vs-market judge v2 (#3) · GOLDSMITH valuables voter (A1) · IPO
  auto-rotation (B) · fee-aware harvest floors (H: min_harvest must clear
  round_trip_cost; wire fees_truth into harvest gate + deal journal rows).
Wed: breeding automation (#4) · equity-edge attribution (#5) · valuables
  clock backfill from free historical OHLC (F) · valuables news board (A2).
Thu: IPO prediction engine w/ graded pre-debut cards (G) · asset cards w/
  platform-grade charts + tomorrow-expectation overlays (A4 — Yahoo/Alpaca-
  style: price, volume, clock windows, Dr. Strange picks, engine bands) ·
  section health chips (C) · docs (#6) + hardening (#7) + news board v2 (#8).
Fri-Mon 19-22: observation, duel verdict, calibration check, TAG.
STANDING LAWS RESTATED FOR ANY FUTURE SESSION: read-before-edit; additive
only; fills or it didn't happen; every judge judged; no LLMs in analyst
layers; no synthetic data in the decision path; deliver drag-drop zips w/
READ_ME inside; prove everything (py_compile + synthetic + real-data +
node --check); surface ambiguities; honest non-cheerleading tone; the
walk-away bar is four clean unattended weeks.

## JUNE 12 EARLY SESSION — Tuesday slate landed in full (shipped+proven)
#3 VS-MARKET JUDGE v2: persisted daily alpha Δ series (vs_market_series
   .json, permanent); trend judge (5v10 sessions) with verdicts
   WARMING_UP / EDGE-BUILDING / MIXED / EDGE-DECAY; EDGE-DECAY emits an
   alarm row; the judge judges ITSELF (decay calls scored against the 3
   sessions that follow — every judge gets judged, structurally).
   Day 1 of real series recorded; honest WARMING_UP until day 8.
A1 GOLDSMITH seated in MAIN_VOTERS: valuables-jurisdiction word voter
   (crypto/token/commodity/fx/macro; abstains on all equities). Valuables
   doctrine encoded: stronger follower ride (24/7 tape), catalysts weigh
   0.40 (rarer+dirtier), thin-tape cap 0.45 under 2 articles, conviction
   ceiling 0.80 (fee gravity). The senate/elections/breeding machinery now
   covers the valuables bloodline automatically. Stocks-only order guard
   keeps its votes out of Alpaca by construction.
H  FEE-AWARE HARVEST FLOOR live at the harvest gate: dollar gain must
   clear 2x estimated round-trip (SEC+TAF+slippage) or the tier cannot
   fire; blocked as harvest_below_fee_floor (visible in wantgot/ledger).
   Proven: $0.40 dust win on $800 blocked; +1.2% ($9.60) flows.
B  DEBUT ROTATION: debut_watch.json — SPCX seeded (imports console price
   track); completes at 5 distinct live-price sessions; auto-advances to
   nearest calendar entry; lineage archived forever; IDLE+re-arm on empty
   calendar. No human ever names the next IPO again. Lifecycle proven
   end-to-end (SPCX->next->IDLE), queue-leak bug found+fixed in test.
Suite now 24/24. REMAINING TO TAG: breeding automation (#4) + equity-edge
attribution (#5) Wed; valuables backfill (F) + valuables news board (A2)
Wed; IPO prediction cards (G) + asset charts w/ expectation overlays (A4)
+ health chips (C) Thu; docs (#6) + hardening (#7) + news board v2 (#8)
Thu; observe Fri-Mon; TAG on duel-board day 5+ with suite green.

## JUNE 12 SECOND SESSION — UI surfacing + BREEDING LIVE (shipped+proven)
UI (operator: "make sure we can SEE it all") — index.html gained:
  vs-market judge section (verdict chip + Δ trend + judge-judged score);
  real-world fee bill section (round-trip law, per-account drag,
  paper->real equity view, fees-vs-realized ratio); debut-rotation strip
  under the SPCX console (current watch / phase / sessions / next-up
  queue); feeds-health extended with storage meter, cron-pressure chips,
  domain-clock states; wantgot section UPGRADED to truth-v2 verdicts
  (per-intent first-gate reasons, ORIGINATED badge, deployment gap).
  All node --check'd + runtime-smoked with stubbed DOM/data.
#4 BREEDING AUTOMATION LIVE: offspring are GENOMES, never generated code
  (hybrid_voter.py = the species' shared word-judge body; agent_genomes
  .json = the permanent bloodline). Fitness = per-agent EQUITY EDGE from
  the simulation books (#5's attribution feed). Top-2 crossover + ±10%
  seeded mutation (reproducible births), gene bounds, 7-day cadence per
  jurisdiction, born PROBATIONARY_SHADOW, auto-seated via the candidate
  loader, cap refusal w/ senate-must-demote message. Gen-1 honesty: a
  single genome-bearer breeds mutation-only variants until a second
  earns a record — then true crossover (proven gen-2 in test).
  SUPERSESSION RECORDED: roster cap 24 -> 30 (live roster was already 26
  main voters; freezing evolution below current size was never intent).
  FIRST BIRTHS ON REAL DATA: HYB_STO_G1_0612F (FABLEBOY_5 line) and
  HYB_VAL_G1_0612G (GOLDSMITH line) — both shadow-seated. Two bugs found
  BY TESTS before live: injected-clock track-days; queue-leak (prior).
Suite 25/25. REMAINING: valuables backfill (F) + valuables news board
(A2) + asset cards w/ expectation overlays (A4) + IPO prediction cards
(G) + health chips (C) + docs (#6) + hardening (#7) + news board v2 (#8);
observe; TAG at duel day 5+.

## JUNE 12 THIRD SESSION — THE METADATA SPINE (operator audit answered)
REGIME MONO-STATE: CONFIRMED REAL AND FIXED. v1 was one axis (SPY trend +
VIX) pinned RISK_ON — 3,025 learning rows, one label, zero conditioning
power. regime v2 ADDS four orthogonal axes (v1 untouched; AEGIS veto
intact): market RISK_ON/NEUTRAL/SIDEWAYS/RISK_OFF/BEAR/PANIC · volatility
COMPRESSED/CALM/NORMAL/EXPANSION/SPIKE +EXPANDING/CONTRACTING · breadth
STRONG/MIXED/WEAK/NARROW · liquidity AMPLE/TIGHT/CRUNCH (labeled proxy:
VIXxbreadth until depth data lands) · defensive-rotation flag (XLP/XLU/
XLV vs XLK/XLY/XLC) · composite FULL_RISK_ON/CONSTRUCTIVE/CHOP/DEFENSIVE/
STRESS. Missing inputs -> UNKNOWN, never faked.
MARKET TRUTH SPINE (market_truth.py): daily benchmark_price_log (SPY/QQQ/
VIX/11 SPDRs/advancers/leaders-share, self-building) -> regime_axes.json
+ regime_history.json (permanent, join_key=date) -> trade_benchmarks.json:
EVERY CLOSE carries trade/SPY/QQQ/sector returns + alpha + excess +
relative strength once its window sits in the log; the 95 pre-log trades
are marked unavailable, never invented. CATALYST TAXONOMY guaranteed:
canonical nine (earnings/guidance/ipo/macro/analyst/product_launch/
regulatory/ma/unknown) w/ normalizer proven 10/10.
NARRATIVE LIFECYCLE (narrative_lifecycle.py): Start/Acceleration/Peak/
Decay (+QUIET/STEADY/WARMING) from heat=|sent|+|antic|+1[catalyst];
permanent daily history. LIVE DAY ONE: 594 names — 23 START, 12 ACCEL,
11 PEAK-candidates, 24 DECAY.
IPO LIFECYCLE: six canonical phases on the debut watch (pre-rumor/rumor
reserved for social+424B flags; announcement/pricing/listing/post_listing
deterministic) + related_symbols sympathy set per IPO (sector peers;
honest empty+note when calendar lacks sector). LIVE: SPCX phase=listing.
CLI DUPLICATE: root cli.py was stale (2,996 vs live 3,228). Per additive
law: full copy -> attic/cli_root_RETIRED_2026-06-12.py; root replaced by
a forwarding shim to silmaril.cli. It can never drift again.
AEGIS SAMPLE DOMINANCE: acknowledged; conditioning answer = the new axes
(per-regime per-agent splits dilute any one agent's sample share); senate
weighting review queued post-tag. UI DRIFT AUDIT: automated — all data
files referenced by index/cockpit/debug exist; zero dead fetches.
NOTE: VIX joins the log when present in signals; until then vol axis
reads UNKNOWN honestly. Suite 27/27.

## JUNE 12 FINAL SESSION — SEALED. See FINAL_ALPHA_1_0_MASTER_DOCUMENT.md
(the closing source of truth; every June-12 operator item answered there)
and REPO_CLEANUP_AUDIT.md (storage cure + trims + hardening checklist).
Shipped this session: wantgot misclassification fixed at source+surface;
api_health v1.3 (worktree/.git split; age-aware broker errors — "0 in
48h, plumbing clean"); expectation graph on every asset card (crypto
included, Dr. Strange overlay); -USD linkification; the 50/50 stocks/
valuables interleave law on the news feed; compact_history.yml. Suite
27/27 · sentinel 0 · SPCX in listing phase · tag window opens ~Jun 17.
