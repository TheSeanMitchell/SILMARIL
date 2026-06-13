# SILMARIL — 2-Week Roadmap (Jun 10 – Jun 24, 2026)
The standing reference for the Fable-5 sprint. Re-read at the start of every session.
Status: [ ] open · [~] in progress · [x] done

## WEEK 1 — SPCX capture + word-engine maturation
- [x] Session hard-gate: no order creation when market closed (fixed off-hours blanket-sell)
- [x] Zero-price exit guard; clock-shaped EXITS (defer into lows, harvest into highs)
- [x] Clock-shaped ENTRIES (refuse market-buys in a stock's typical daily-high window)
- [x] Word-engine v2: phrases, events, decisive catalysts, anticipation tier, IPO phrases
- [x] Per-stock fingerprints recording: timing clock + news personality + daily deltas
- [x] IPO calendar tracker (SPCX imminent); feeds health matrix; realized-$ attribution
- [x] FABLEBOY_5 voter live — first agent built on the full word stack
- [ ] SPCX debut (Fri): confirm SPCX + IPO-complex names enter the universe at listing;
      capture debut-window rows in news_history/timing_history; post-mortem Sat
- [x] Verify session gate in production logs (expect "no payload" suppressions overnight)
- [ ] Deltas + clock + personality sections begin filling (2-3 sessions) — review quality

## WEEK 2 — prediction + selection pressure
- [x] DR. STRANGE (shadow agent) — SHIPPED early (module+suite+briefing): per-stock empirical distributions from news_history
      (sent/antic/catalyst/personality/clock) -> 1000-path Monte Carlo -> trade only
      >=90%-agreement paths -> one decision/day, tracked vs main cohort. NO live orders.
- [x] SENATE/POKEMON REVIVAL — senate.yml shipped (first election Sun): senate elections currently load candidates in shadow
      (candidate_alpha/beta/gamma). With stale share falling: re-enable scheduled
      elections on CLEAN-ONLY records; demote persistent losers from MAIN_VOTERS to
      shadow; breed top-2 clean performers -> first post-stale hybrid offspring.
      (Workflow audit: no senate .yml exists — elections run in-code; add a weekly
      senate step to daily.yml Friday close or a small senate.yml.)
- [ ] WEEKLY AGENT AUDIT (every Fri): clean-only win-rate + profit-weight + realized-$
      per agent -> freeze/demote list -> operator sign-off in briefing
- [ ] DEDICATED INSTRUMENT VOTERS (ETF proxies trade on equity rails TODAY, same gates):
      OILMAN (USO/XLE), SATOSHI_DESK (IBIT/BITO; note: proxy trades equity hours —
      24/7 crypto rails would need Alpaca crypto endpoints + separate clock, Phase C),
      INDEXER (SPY/QQQ). Same word-stack pattern as Fableboy 5; side-by-side panel.
- [ ] 4TH PAPER ACCOUNT "PICKS_TRACKER": mirrors top consensus pick(s) 1:1, no gates —
      isolates selection skill from execution gates. Needs new Alpaca paper keys
      (ALPACA_API_KEY_PT / ALPACA_API_SECRET_PT) + cfg block in multi_account.
- [ ] REGIME BASKETS page: how the regime is decided (inputs -> state), basket
      composition (ETF-style bundles incl. tokens/crypto majors already tracked),
      stance history, and how stance feeds policy routing. Surface in cockpit tab.
- [ ] "vs the market" visual upgrade: deployment-adjusted comparison (vs SPY scaled by
      avg deployment), equity sparklines, and the honest-caveat kept front and center.
- [~] News net widening (vocab round 3 SHIPPED; RSS pulls remain): add RSS pulls (Reuters/AP business, sector feeds) into
      fetch_news_bulk with per-source meter in api_health; vocab expansion round 3
      (options-flow phrases, 13F/holder language, supply-chain chatter).
- [ ] Briefing section polish: news-moved (group by event type), clock (sparkline of
      tod curve), wanted-vs-got (show the blocking gate by name from decision ledger),
      traded-and-why (attach catalyst + personality + clock context per trade).

## STANDING RULES (unchanged)
Read before editing · whole-file drag-and-drop delivery · additive only · no LLMs in
analyst layers · reward realized profit · paper-only until 90 clean days.
