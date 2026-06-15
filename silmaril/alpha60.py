"""silmaril.alpha60 — Alpha 6.0 master wiring module.

Single-call integration point for the Alpha 6.0 brain-to-hands work.
cli.py imports `run_alpha60_post_cycle` and `run_alpha60_pre_cycle`
and that's it. All new sidecars are built/consumed through here so
the cli surface area stays tiny.

The pre-cycle hook runs BEFORE multi_account (so the executor sees
fresh hard-stops/order-quality data). The post-cycle hook runs AFTER
multi_account (to rebuild directives for the NEXT cycle).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def run_alpha60_pre_cycle(
    out_dir: Path,
    multi_account_results: Optional[Dict[str, Any]] = None,
    contexts: Optional[List[Any]] = None,
    plans: Optional[List[Dict[str, Any]]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run Alpha 6.0 sidecars that the executor will read THIS cycle.

    These are computed from the PREVIOUS cycle's multi_account_results
    state files plus fresh market context. The executor will read
    deployment_floor, hard_stops, order_quality, and correlation_book
    via multi_account.py's policy injection.

    Returns a report dict for logging.
    """
    report: Dict[str, Any] = {"errors": [], "ran": []}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Hard stops — read prior multi_account state files for equity
    try:
        import json as _json
        # Build a minimal multi_account_results from prior state files.
        prior_accounts: Dict[str, Any] = {}
        _state_files = {
            "LEGACY":    "alpaca_paper_state.json",
            "HARVEST_3": "alpaca_h3_state.json",
            "HARVEST_5": "alpaca_h5_state.json",
        }
        for aid, fname in _state_files.items():
            p = out / fname
            if not p.exists():
                continue
            try:
                body = _json.loads(p.read_text()) or {}
                if body.get("enabled"):
                    prior_accounts[aid] = body
            except Exception:
                pass
        from .risk.hard_stops import build_hard_stops as _bhs
        _bhs_payload = _bhs(out, multi_account_results=prior_accounts)
        report["ran"].append("hard_stops")
        report["hard_stops_summary"] = {
            "accounts_halted":   [aid for aid, v in (_bhs_payload.get("accounts") or {}).items()
                                    if v.get("halt_opens")],
            "cohort_safe_mode":  bool((_bhs_payload.get("system") or {}).get("cohort_safe_mode")),
        }
    except Exception as e:
        report["errors"].append(f"hard_stops: {e}")

    # 2. Order quality — score the plans for entry execution quality
    try:
        from .portfolios.order_quality import build_order_quality as _boq
        _oq_payload = _boq(out, contexts=contexts, plans=plans or [])
        report["ran"].append("order_quality")
        report["order_quality_summary"] = _oq_payload.get("summary") or {}
    except Exception as e:
        report["errors"].append(f"order_quality: {e}")

    # 3. Correlation book — concentration map from prior positions
    try:
        from .portfolios.correlation_book import (
            build_correlation_book as _bcb,
        )
        import json as _json2
        _ma_results: Dict[str, Any] = {}
        for aid, fname in {
            "LEGACY":    "alpaca_paper_state.json",
            "HARVEST_3": "alpaca_h3_state.json",
            "HARVEST_5": "alpaca_h5_state.json",
        }.items():
            p = out / fname
            if not p.exists():
                continue
            try:
                body = _json2.loads(p.read_text()) or {}
                if body.get("enabled"):
                    _ma_results[aid] = body
            except Exception:
                pass
        _cb_payload = _bcb(out, multi_account_results=_ma_results,
                            sector_lookup=sector_lookup)
        report["ran"].append("correlation_book")
        report["correlation_book_summary"] = _cb_payload.get("summary") or {}
    except Exception as e:
        report["errors"].append(f"correlation_book: {e}")

    return report


def run_alpha60_post_cycle(
    out_dir: Path,
    multi_account_results: Optional[Dict[str, Any]] = None,
    contexts: Optional[List[Any]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run Alpha 6.0 sidecars AFTER the executor has run.

    These produce intelligence for the NEXT cycle:
      - hard_stops          (refreshed with this cycle's equity)
      - correlation_book    (refreshed with new positions)
      - cross_agent_learning
      - agent_evolution_offspring  (if monthly cadence hits)
      - system_audit
    """
    report: Dict[str, Any] = {"errors": [], "ran": []}
    out = Path(out_dir)

    # 1. Refresh hard_stops with this cycle's results
    try:
        from .risk.hard_stops import build_hard_stops as _bhs
        _bhs(out, multi_account_results=multi_account_results or {})
        report["ran"].append("hard_stops")
    except Exception as e:
        report["errors"].append(f"hard_stops_post: {e}")

    # 2. Refresh correlation_book
    try:
        from .portfolios.correlation_book import (
            build_correlation_book as _bcb,
        )
        _bcb(out, multi_account_results=multi_account_results or {},
             sector_lookup=sector_lookup)
        report["ran"].append("correlation_book")
    except Exception as e:
        report["errors"].append(f"correlation_book_post: {e}")

    # 3. Cross-agent learning
    try:
        from .learning.cross_agent_learning import (
            build_cross_agent_learning as _bcal,
        )
        cal_payload = _bcal(out)
        report["ran"].append("cross_agent_learning")
        report["cross_agent_learning_summary"] = cal_payload.get("summary") or {}
    except Exception as e:
        report["errors"].append(f"cross_agent_learning: {e}")

    # 4. Pokémon-style offspring proposal (monthly cadence)
    try:
        from datetime import datetime as _dt
        from .learning.agent_evolution import write_offspring_proposal as _woffspring
        import json as _json
        cards_doc = {}
        scoring_doc = {}
        try:
            cards_path = out / "agent_evolution_cards.json"
            if cards_path.exists():
                cards_doc = _json.loads(cards_path.read_text()) or {}
        except Exception:
            pass
        try:
            sc_path = out / "scoring.json"
            if sc_path.exists():
                scoring_doc = _json.loads(sc_path.read_text()) or {}
        except Exception:
            pass
        cross_agent_payload = {}
        try:
            cap_path = out / "cross_agent_learning.json"
            if cap_path.exists():
                cross_agent_payload = _json.loads(cap_path.read_text()) or {}
        except Exception:
            pass
        # Always emit a proposal record (or NO_ELIGIBLE_PAIR) so the UI shows status
        proposal = _woffspring(
            out,
            cards=cards_doc,
            scoring_raw=scoring_doc,
            cross_agent=cross_agent_payload,
            existing_agent_names=list(cards_doc.keys()),
        )
        report["ran"].append("agent_evolution")
        report["offspring_status"] = proposal.get("status", "?")
    except Exception as e:
        report["errors"].append(f"agent_evolution: {e}")

    # 5. System audit — overall green/yellow/red
    try:
        from .diagnostics.system_audit import build_system_audit as _bsa
        audit = _bsa(out)
        report["ran"].append("system_audit")
        report["system_audit_summary"] = {
            "overall_status": audit.get("overall_status", "?"),
            "rationale":      audit.get("rationale", ""),
        }
    except Exception as e:
        report["errors"].append(f"system_audit: {e}")

    return report


__all__ = [
    "run_alpha60_pre_cycle",
    "run_alpha60_post_cycle",
]
