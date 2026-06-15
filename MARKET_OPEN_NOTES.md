# SILMARIL — Market-open drop: real fills, visible news→decisions, truthful holdings

**Apply:** unzip over repo root, commit, push. Picked up next cycle. Drag-and-drop, paths preserved.

## The audit you asked for: is the learning REAL, or theater?
**Real.** I traced the full chain and verified it end-to-end:
- **Headlines → decisions:** the cycle computes a per-ticker sentiment score from real headline
  text (`aggregate_ticker_sentiment` — genuinely content-sensitive: +1.0 "earnings beat", −1.0
  "plunge/cuts outlook", 0.0 "routine board meeting") and passes it into every `AssetContext`.
  **14 of 35 agents gate their verdict on `ctx.sentiment_score`** (e.g., FORGE requires
  `sentiment ≥ threshold` for BUY/STRONG_BUY). So a positive headline can flip an agent from HOLD
  to BUY. Verified live on your data: UNH +0.67 → BUY, DELL +0.50 → BUY, CSCO +0.40 → BUY,
  FTNT +0.40 → BUY; TLT −1.00 → HOLD. (JPM +0.50 → SELL — proof the vote isn't blindly
  sentiment-driven; price/trend/risk also count.)
- **Scoring → participation:** outcomes drive per-agent weight multipliers; underperformers get
  frozen (AEGIS at 0.81×, KESTREL+ frozen). That gates their capital and votes — a real
  consequence loop, not a scoreboard.
- **Learning → next decision:** the belief digest + the new auto-reflection are injected into
  every agent's context each cycle. The loop closes.
- **Honest caveat:** the weights are still partly learned from 37%-stale outcomes, so *quality*
  depends on the clean week now starting. The mechanism is real; the inputs get trustworthy now.

## Fix 1 — accounts now trade "the way we'd want": no more off-hours dead orders
Root cause of the canceled EOG/PLD churn: **nothing in the order path checked market hours**, so
the 1 AM off-hours run fired market orders that can never fill → they sat until the canceller
cleared them → next cycle retried → loop. Added a single-chokepoint market-hours gate in
`alpaca_paper.py` (`_api_post` → `_DEFER_ORDER_SUBMIT`, set from the regular-session check at the
top of `execute_consensus_signals`). Off-hours: bookkeeping, sweeps and stale-cancel still run,
but **new orders defer to regular hours** where they actually fill. Verified the deferred path
returns falsy so a skipped order is never mis-recorded as a fill. This is what makes Monday's
deployment land cleanly instead of churning.

## Fix 2 — you can now SEE how the news moved decisions
`sentiment_score` was computed and thrown away — never persisted. Now `cli.py` writes it (plus
`article_count`) into signals.json, and the briefing has a new **"How the news moved decisions"**
card: the strongest positive-news names and the agents' actual vote, the negative-news names they
stepped back from, with a one-line note that 14 agents weight sentiment directly. The
edge-in-words is no longer invisible — it's the headline of the page.

## Fix 3 — the holdings panel was lying (phantom 42); now it's truthful
The "Going into Monday" card read `position_meta`, which **accumulates closed positions and never
prunes** — it showed LEGACY holding 42 names. Alpaca reality (your screenshots): LEGACY = 1 SGOV
dust ≈ flat, H3 = a few, H5 = 0. Switched the card to the real `positions_snapshot`. It now reads
**LEGACY 0 · HARVEST_3 3 (MNST·UNH·UUP) · HARVEST_5 0** — matching Alpaca exactly.

## What this truthful view reveals (watch Monday)
- **LEGACY is 100% cash** ($9,529, market-mode ATTACK, 0 positions) and **HARVEST_5 is flat +
  dormant**. LEGACY closed into the selloff and is holding dry powder — defensive agent judgment
  in a falling market, not a bug (I did not override it). **The Monday test:** during regular
  hours, does LEGACY deploy that cash into the BUY-consensus names (UNH/CSCO/FTNT/DELL)? If it
  stays flat through a full regular session despite BUY signals, deployment is the next thing to
  debug.
- **HARVEST_5 needs its secrets:** it's skipped because `ALPACA_API_KEY_H5`/`ALPACA_API_SECRET_H5`
  aren't detected at runtime. Set/verify them in GitHub repo secrets to bring it live. (The system
  skips it gracefully until then.)

## Files
- `silmaril/execution/alpaca_paper.py` — market-hours order gate.
- `silmaril/cli.py` — persist `sentiment_score`/`article_count` to signals.json.
- `docs/index.html`, `docs/briefing.html` — news→decisions card + truthful holdings.
- `docs/data/signals.json` — backfilled sentiment so the card shows live data now.
- `docs/data/opus_file_archive.json`, `docs/data/drift_sentinel.json` — refreshed (sentinel 9/9).

## Rollback
Order gate: set `_DEFER_ORDER_SUBMIT` always False (or remove the gate line in `_api_post`).
Everything else is additive/display. Data JSONs regenerate each cycle.
