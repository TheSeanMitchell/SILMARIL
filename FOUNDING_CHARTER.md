# SILMARIL — Founding Charter (Alpha 0.001)

This is the constitution of the project. It exists because SILMARIL grew large and
clever before it grew honest and effective. Alpha 0.001 re-founds it on a single,
unambiguous purpose and a short list of rules earned through a month of real pain.

---

## I. The one purpose

**Find a real, repeatable edge in US stocks — and prove it with realized money.**

Not a dashboard. Not a zoo of agents. Not a clever architecture. Those are means.
The end is a measurable edge in equities, demonstrated against an honest benchmark
(SPY buy-and-hold, net of costs). If that edge does not exist here, the system must
say so plainly. **"No demonstrated edge" is an acceptable, honest outcome.** A
beautiful system that quietly trails the market is a failure dressed as a success.

---

## II. Scope discipline

SILMARIL trades **US equities and equity ETFs**, for real, on Alpaca paper.

Crypto, micro-cap tokens, and prediction-market/sports betting are **out of scope**
as of Alpaca 0.001. They diluted focus, generated synthetic numbers, and could not
even execute on the broker. Any agent that cannot place a real US-equity order is
disabled or removed. The system is a window into reality — so everything on it must
*be* reality.

---

## III. The five rules (non-negotiable)

1. **Read before you write.** Never modify a file without reading its true current
   contents in full. Every catastrophic regression in this project's history —
   the dashboard wipeout, the broken execution bridge, cascading indentation
   failures — came from editing something we hadn't actually read. This rule is
   first because violating it has hurt us most.

2. **Ship whole files.** Deliverables are complete, drag-and-drop, GitHub-web-UI-
   ready file replacements. No diffs, no "insert at line N", no partial files.

3. **Classify every change.** Track A = safe now (read-only, additive, reversible).
   Track B = behavioral (changes trading or scoring). Track C = future. Never
   resolve the classification silently; the operator decides when Track B ships.

4. **Honesty over flattery.** Report what is broken, what has no effect, and what
   trails the benchmark — directly. Never fabricate, simulate, or internally
   compound a number and present it as real.

5. **Reward money, not correctness.** Win-rate is a vanity metric until it is tied
   to realized P&L. Optimize the system for dollars.

---

## IV. Hard-won lessons (the scar tissue)

- **A learning loop fed garbage learns garbage.** ~89% of scored outcomes were
  stale-price artifacts; the loop concluded that do-nothing agents were geniuses
  and froze the agents that actually traded. Clean data is the precondition for
  everything. Guard it (non-trading-day gate, fresh-quote overlay, stale exclusion).

- **Sophistication can break execution.** The system computed precise limit prices
  Alpaca rejected (sub-penny 422), so orders silently never filled — while a
  "dumber" market-order version would have traded. Complexity that defeats the
  basics is negative value.

- **Intelligence without teeth is decoration.** Sector rotation, conviction
  rankings, capital-efficiency scores, narrative trackers — all computed, all
  displayed, none changing a trade. Either an analytic earns capital-control
  authority by proving out on clean data, or it is cut.

- **Don't promise what you don't instantiate.** The senate was built to "breed new
  agents like Pokémon." It only ever wrote proposal cards; no offspring ever
  traded. Build the thing, or don't claim the thing. (The tractable version of the
  dream is evolving the *parameters* of existing agents — do that.)

- **The constraint is rarely data; it is wiring.** Four paid/free API keys sit
  unused. The work is almost never "get more sources" — it is using what we have.

- **Cash doesn't compound.** A system that harvests itself into cash, or won't
  deploy, cannot beat a rising market. Stay invested unless there's a reason not to.

---

## V. How the machine is supposed to work

Ingest reality (prices, news, macro, regime) → many agents form independent views →
debate into a consensus → size and risk-filter into trade plans → execute for real →
score every call on clean data → reweight the agents by what actually worked →
repeat, forever, getting sharper. Trade, burn data, learn, train, learn, train.

The loop already turns. The job of every future update is to make each turn of it
*mean more*: cleaner inputs, decisions with teeth, learning that targets profit,
and an honest scoreboard that says — without flinching — whether we are beating the
market yet.

---

## VI. The standard for "done"

A change is done when it has been read-first, shipped as complete files, validated
(compiles/parses/proven on real data), documented with its root cause and rollback,
and — if behavioral — approved by the operator. Anything less is in progress.

---

*Alpha 0.001 — a rebirth. The machine was built to make trades, burn through data,
and learn. From here, it does that for stocks, for real, and tells the truth about
the results.*
