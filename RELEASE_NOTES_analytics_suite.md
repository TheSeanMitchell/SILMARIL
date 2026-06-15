# SILMARIL — Analytics Suite drop (read-only, additive, SAFE NOW)

7 files. All additive except daily.yml (whole-file replacement). No trading,
scoring, or account-state code is touched. Drag each into place via the GitHub
web UI, preserving paths.

## Files (destination paths)
1. silmaril/learning/sentiment_ledger.py        NEW  — sentiment calibration over time
2. silmaril/learning/agent_scorecard.py         NEW  — brutally honest per-agent grades
3. silmaril/execution/broker_reconciliation.py  NEW  — Alpaca-vs-truth position sync check
4. silmaril/diagnostics/debug_stream.py         NEW  — unified event stream
5. silmaril/analytics/suite.py                  NEW  — post-cycle runner
6. docs/debug.html                              NEW  — live debug console (STREAM/SCORECARD/SENTIMENT/SYNC)
7. .github/workflows/daily.yml                  REPLACE — adds one analytics-suite step

## What runs, when
daily.yml now runs `python -m silmaril.analytics.suite` immediately after the
live cycle. It writes four NEW files into docs/data (committed by the existing
git-add step):
  sentiment_calibration.json   agent_scorecard.json
  broker_reconciliation.json   debug_stream.json
plus it maintains an accumulating store: sentiment_ledger.json

The suite always exits 0; a failure in any analytic can never break the trade run.

## See it
After the next daily run, open:  theseanmitchell.github.io/SILMARIL/debug.html

## Verified before delivery
- py_compile on all 5 modules: OK
- full suite run against real docs/data: 4/4 OK
- all 4 output JSONs parse; ledger dedup idempotent (2nd run records 0)
- daily.yml valid YAML; debug.html JS passes `node --check`
- no circular imports; reads only confirmed real data shapes
