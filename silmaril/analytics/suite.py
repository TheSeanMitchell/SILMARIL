"""
silmaril.analytics.suite — Post-cycle analytics, run as one step.

After the main `python -m silmaril --live` cycle writes its state, this runs the
new read-only analytics over the fresh on-disk data:

    sentiment_ledger        accumulate + grade sentiment -> sentiment_calibration.json
    agent_scorecard         brutally honest per-agent grades -> agent_scorecard.json
    broker_reconciliation   Alpaca-vs-truth diff -> broker_reconciliation.json
    debug_stream            unified event feed -> debug_stream.json

Every builder is wrapped: one failing can never stop the others, and the suite
always exits 0 so it can never fail a workflow. Wire it into daily.yml as a
step right after the live run (it reads what the cycle just wrote), or call
run_suite(Path("docs/data")) from anywhere.

Read-only with respect to trading/scoring/account state. The four output files
are committed by the existing daily.yml "git add docs/data/" step automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def run_suite(out_dir: Path) -> Dict[str, Any]:
    out = Path(out_dir)
    results: Dict[str, Any] = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out),
        "steps": {},
    }

    def _step(name: str, fn) -> None:
        try:
            results["steps"][name] = {"ok": True, "summary": fn(out)}
            print(f"  [suite] {name}: OK — {results['steps'][name]['summary']}")
        except Exception as e:  # noqa: BLE001
            results["steps"][name] = {"ok": False, "error": str(e)}
            print(f"  [suite] {name}: FAILED — {e}")

    # ── ALPHA 1.0 item #1: per-domain clocks ────────────────────────
    # Network-fetching steps consult the domain clock so the external cron
    # can run 24/7 without burning quota off-window. A clock-skipped step
    # counts OK (its JSON simply keeps its last committed value) — the suite
    # stays green and the skip is visible in the step summary + api_health
    # budget counters. Fail-open: if the clock errors, the step runs.
    def _gated_step(name: str, domain: str, fn) -> None:
        try:
            from ..analytics.domain_clock import domain_clock
            allowed = domain_clock(domain, out)
        except Exception as e:  # noqa: BLE001
            print(f"  [suite] domain clock error ({e}) — running {name} anyway")
            allowed = True
        if not allowed:
            results["steps"][name] = {
                "ok": True,
                "summary": {"skipped": f"domain clock: {domain} closed"}}
            print(f"  [suite] {name}: SKIPPED — domain clock: {domain} closed")
            return
        _step(name, fn)

    # Imported lazily so an import error in one module doesn't sink the rest.
    def _sentiment(o):
        from ..learning.sentiment_ledger import build_sentiment_ledger
        return build_sentiment_ledger(o)

    def _scorecard(o):
        from ..learning.agent_scorecard import build_agent_scorecard
        return build_agent_scorecard(o)

    def _recon(o):
        from ..execution.broker_reconciliation import build_broker_reconciliation
        return build_broker_reconciliation(o)

    def _stream(o):
        from ..diagnostics.debug_stream import build_debug_stream
        return build_debug_stream(o)

    def _leaders(o):
        from ..ingestion.market_leaders import build_market_leaders
        return build_market_leaders(o)

    def _timing(o):
        from ..analytics.timing_fingerprint import build_timing
        return build_timing(o)

    def _newsfp(o):
        from ..analytics.news_fingerprint import build_news_fingerprint
        return build_news_fingerprint(o)

    def _apih(o):
        from ..analytics.api_health import build_api_health
        return build_api_health(o)

    def _realized(o):
        from ..analytics.realized_attribution import build_realized_attribution
        return build_realized_attribution(o)

    def _ipocal(o):
        from ..analytics.ipo_calendar import build_ipo_calendar
        return build_ipo_calendar(o)

    _step("timing_fingerprint", _timing)
    _step("news_fingerprint", _newsfp)
    _step("api_health", _apih)
    _step("realized_attribution", _realized)
    _gated_step("ipo_calendar", "stocks", _ipocal)

    def _strange(o):
        from ..analytics.dr_strange import build_dr_strange
        return build_dr_strange(o)

    _step("dr_strange", _strange)

    def _rcard(o):
        from ..analytics.report_card import build_report_card
        return build_report_card(o)

    def _sentinel(o):
        from ..analytics.sentinel import build_sentinel
        return build_sentinel(o)

    _step("sentinel", _sentinel)

    def _valuables(o):
        from ..analytics.valuables import build_valuables
        return build_valuables(o)

    _step("valuables", _valuables)

    def _duel(o):
        from ..analytics.duel import build_duel
        return build_duel(o)

    _step("duel", _duel)

    _step("report_card", _rcard)

    def _edgar(o):
        from ..analytics.edgar_watch import build_edgar_watch
        return build_edgar_watch(o)

    _gated_step("edgar_watch", "edgar", _edgar)

    def _social(o):
        from ..analytics.social_pulse import build_social_pulse
        return build_social_pulse(o)

    _gated_step("social_pulse", "social", _social)

    def _spcx(o):
        from ..analytics.spcx_debut import build_spcx_console
        return build_spcx_console(o)

    _step("spcx_console", _spcx)

    def _srcrank(o):
        from ..analytics.source_fingerprint import build_source_rankings
        return build_source_rankings(o)

    _step("source_rankings", _srcrank)

    def _harvtruth(o):
        from ..analytics.harvest_truth import build_harvest_truth
        return build_harvest_truth(o)

    _step("harvest_truth", _harvtruth)

    def _wantgot(o):
        from ..analytics.wantgot import build_wantgot
        return build_wantgot(o)

    _step("wantgot", _wantgot)

    def _fees(o):
        from ..analytics.fees_truth import build_fees_truth
        return build_fees_truth(o)

    _step("fees_truth", _fees)

    def _vsmkt(o):
        from ..analytics.vs_market import build_vs_market
        return build_vs_market(o)

    _step("vs_market", _vsmkt)

    def _debutrot(o):
        from ..analytics.debut_rotation import build_debut_rotation
        return build_debut_rotation(o)

    _step("debut_rotation", _debutrot)

    def _breeding(o):
        from ..senate.breeding import run_breeding
        return run_breeding(o)

    _step("breeding", _breeding)

    def _mkttruth(o):
        from ..analytics.market_truth import build_market_truth
        return build_market_truth(o)

    _step("market_truth", _mkttruth)

    def _narrlife(o):
        from ..analytics.narrative_lifecycle import build_narrative_lifecycle
        return build_narrative_lifecycle(o)

    _step("narrative_lifecycle", _narrlife)
    _step("market_leaders", _leaders)
    _step("sentiment_ledger", _sentiment)
    _step("agent_scorecard", _scorecard)
    _step("broker_reconciliation", _recon)
    _step("debug_stream", _stream)

    ok = sum(1 for s in results["steps"].values() if s.get("ok"))
    print(f"  [suite] complete: {ok}/{len(results['steps'])} steps OK")
    return results


def main() -> None:  # pragma: no cover
    import argparse
    p = argparse.ArgumentParser(description="SILMARIL post-cycle analytics suite")
    p.add_argument("--output", default="docs/data", help="data directory")
    args = p.parse_args()
    res = run_suite(Path(args.output))
    # Always exit 0 — analytics must never fail the trading workflow.
    print(json.dumps({k: (v.get("ok") if isinstance(v, dict) else v)
                      for k, v in res["steps"].items()}, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
