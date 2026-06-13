# SILMARIL Roadmap — Road to Monday and Beyond (Alpha 0.001)

Philosophy: **additive, not subtractive.** We add signal, measurement, and teeth;
we leave unproven machinery dormant rather than delete it. And we **never force a
decision that the data will make better next week** — anything data-dependent waits
for a clean week; everything else we press forward on now.

Three buckets: **DONE**, **DO NOW** (data-independent, safe before Monday),
**WAIT FOR DATA** (decide next week, once a clean week has accumulated).

---

## ✅ DONE (shipped this week)

The foundation — without this nothing downstream could be trusted:

- **Clean data**: keyed fresh-quote price overlay; stale excluded from scoring;
  one-time prune; non-trading-day gate. Stale fell from ~89% → ~0.8%.
- **Execution works**: sub-penny 422 fixed (extended-hours limit orders fill);
  cross-workflow broker lock (no order race).
- **Honest scoring**: clean-evidence gate; **profit gate** (negative-EV agents can
  no longer be amplified — de-amplified AEGIS/KESTREL+/FORGE/SPECK/ZENITH).
- **Better news labels**: sentiment magnitude weighting + 2-word negation.
- **No fiction**: synthetic compounders disabled; crypto/tokens/sports out of scope.
- **Edge study + dead-news fix** (this drop): we can now *see* where edge is, and
  news is finally a learnable dimension.

---

## ▶ DO NOW — data-independent, additive (the Monday push)

These don't need a week of data. They add signal/measurement/visibility and are
safe to ship immediately.

### News & signal quality (your stated priority)
1. **Marketaux entity sentiment** — wire the key you already own (no signup) to get
   server-side per-entity sentiment; blend with / override the lexicon. *(news.py)*
2. **Score article summaries, not just headlines** — use the `summary` field already
   fetched; ~doubles text signal per article. *(cli.py one line, sentiment.py)*
3. **Earnings-proximity tag** — Finnhub earnings dates are already fetched; tag each
   call "pre-earnings / post-earnings / none" so the edge study can test it. *(regime_tags.py, edge_study.py)*
4. **Fundamentals context** — pull FMP P/E, growth, margins (key owned); expose to
   agents and add as an edge-study cut. *(ingestion, agents)*

### Measurement (find the edge faster — all additive)
5. **Consensus-strength dimension** — tag each call with how many agents agreed;
   test whether high-agreement calls have edge. *(edge_study.py + plan tagging)*
6. **Holding-period sweep** — score the same calls at multiple exit windows (1d / 3d
   / 5d) to find where the edge is strongest. *(edge_study.py)*
7. **More edge-study cuts** — trend_state, vol_state, liquidity_state (data's already
   tagged); surface them so risk-off/high-vol edges show up the moment they exist.

### Visibility (truth on the front page)
8. **Benchmark → cockpit** — put "are we beating SPY net of costs" as the headline
   number on the truth surface. It's the scoreboard; it shouldn't be buried. *(cockpit.html, silmaril-truth.js)*
9. **Edge-study panel on the cockpit** — render `edge_study.json` (WEAVER significant,
   long-only, etc.) so the edge map is visible, not just in logs. *(cockpit.html, silmaril-truth.js)*
10. **WEAVER spotlight** — surface the one significant agent prominently; start a
    dedicated clean-data track record for it.

---

## ⏳ WAIT FOR DATA — decide next week (after a clean week)

These are the calls that a week of clean, varied data will make *correctly*. Doing
them now would be guessing. We prepare the measurement now (above) so the decision
is evidence-based later.

1. **Profit-weighting from realized P&L** — fold the career-book P&L into agent
   weights once it's trusted (currently noisy/single-position; e.g. VESPA +$662 on
   2 calls). Needs more samples.
2. **Give teeth to advisory analytics that prove out** — *additively*: once the edge
   study shows (say) sector or regime predicts, let it gate or size trades. Leave the
   ones that don't predict dormant — no deletion. Needs the edge data, esp. a
   risk-off period to test regime claims.
3. **Recalibrate conviction-weighting** — the data already hints conviction isn't
   informative; confirm over a week before changing how Thompson scales it.
4. **Long-bias** — SELL signals show no edge so far; with more SELL samples, down-
   weight or gate shorting. Confirm first.
5. **Capital toward proven agents** — reallocate (not cull) toward WEAVER-class
   agents as clean track records lengthen. Additive reweighting, evidence-gated.
6. **Regime-specialist validation** — needs a RISK_OFF / high-VOL stretch to test
   whether any agent has genuine regime-specific edge.

---

## 🏗 BIGGER BUILDS — future (all additive expansions)

1. **Real agent evolution (the breeder, with teeth)** — the senate proposes offspring
   but never instantiates them. Replace the dead "new agent class" path with
   **parameter mutation of winners**: clone WEAVER, perturb its thresholds, let the
   variant trade, keep it if it scores better. Fitness = realized profit (from the
   profit-scoring work). This is the tractable version of "breed like Pokémon."
2. **New data sources (additive)** — Polygon aggregates, Alpha Vantage technicals
   (both keys owned), short-interest, insider transactions, options-implied moves.
3. **Multi-timeframe / intraday** — more samples per day → faster, more significant
   edge detection.
4. **Portfolio-level edge sizing** — size positions by an agent's measured edge and
   confidence, not flat allocation.
5. **Cockpit as the single front door** — once it carries the benchmark + edge panel,
   make it the home page; retire the synthetic-era surfaces from view (kept in repo).

---

## Guiding rules (unchanged)

- Read every file before editing it. Complete-file replacements only.
- Classify every change: A (safe/additive/reversible), B (behavioral), C (future).
- Reward realized money, not win-rate.
- Honest "no edge" is an acceptable outcome — the machine must say so plainly.
- Add and wire before deleting. Nothing wasted.

> The single most important number to watch starting Monday: **directional edge
> t-stat in `edge_study.json`.** Today it's +1.60 (suggestive). If a clean week pushes
> it past +2.0 — concentrated in WEAVER and the long side — that's a real, defensible
> stock edge to build the rest of the system around.
