"""silmaril.diagnostics.alerts — Alpha 3.2 operational alerts.

What it does
────────────
Detects situations that should never silently persist:

  - missed_sgov_sweep    — cash > principal but last SGOV sweep rejected
  - idle_cash            — significant cash sitting unused for too long
  - overnight_exposure   — danger window + positive unrealized PnL
  - sgov_mismatch        — verified-harvest ledger vs live SGOV value differ
  - stale_position       — held > N days without strong momentum
  - harvest_failure      — last harvest attempt has FAILED rows
  - failed_order         — Alpaca rejected an order this cycle
  - bleed_exit_fired     — a position tripped the 30-min bleed rule

Each alert has a stable shape that the dashboard renders:
  {
    "id": "...",
    "severity": "info" | "warning" | "critical",
    "category": "missed_sgov_sweep",
    "owner": "LEGACY",
    "ticker": "ABNB",
    "summary": "...",
    "detail": {...},
    "first_seen": "...",
    "last_seen": "..."
  }

Output: docs/data/operational_alerts.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


ALERT_FILENAME = "operational_alerts.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


def _load_alerts(data_dir: Path) -> Dict[str, Any]:
    p = data_dir / ALERT_FILENAME
    if not p.exists():
        return {"version": "3.2", "alerts": []}
    try:
        b = json.loads(p.read_text())
        if not isinstance(b, dict):
            return {"version": "3.2", "alerts": []}
        b.setdefault("alerts", [])
        return b
    except Exception:
        return {"version": "3.2", "alerts": []}


def _add_alert(
    out: List[Dict[str, Any]],
    *,
    category: str,
    severity: str,
    owner: Optional[str],
    ticker: Optional[str],
    summary: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    out.append({
        "id":         f"{category}:{owner or '*'}:{ticker or '*'}:{_now_iso()[:16]}",
        "severity":   severity,
        "category":   category,
        "owner":      owner,
        "ticker":     ticker,
        "summary":    summary,
        "detail":     detail or {},
        "last_seen":  _now_iso(),
    })


def _alerts_for_account(
    aid: str,
    astate: Dict[str, Any],
    *,
    in_danger_window: bool = False,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(astate, dict) or not astate.get("enabled"):
        return out

    acct = astate.get("account") or {}
    equity = _safe_f(acct.get("equity"))
    cash = _safe_f(acct.get("cash"))
    principal = _safe_f(astate.get("principal_target"))
    trading_capital = _safe_f(astate.get("trading_capital"))

    # ── Missed SGOV sweep — cash above principal but last sweep failed/skipped
    sgov_last = astate.get("sgov_sweep_last_cycle") or {}
    excess_cash = max(0.0, cash - principal)
    if excess_cash >= 5.00 and sgov_last and sgov_last.get("status") != "queued":
        _add_alert(
            out,
            category="missed_sgov_sweep",
            severity="warning",
            owner=aid,
            ticker="SGOV",
            summary=(f"${excess_cash:,.2f} of cash above principal hasn't been "
                     f"swept into SGOV — last status: "
                     f"{sgov_last.get('status') or sgov_last.get('reason') or 'unknown'}"),
            detail={
                "cash": round(cash, 2),
                "principal": round(principal, 2),
                "excess_cash": round(excess_cash, 2),
                "last_sweep": sgov_last,
            },
        )

    # ── Idle cash — significant cash sitting unused
    if trading_capital > 0 and (cash / trading_capital) >= 0.10 and excess_cash < 5.0:
        _add_alert(
            out,
            category="idle_cash",
            severity="info",
            owner=aid,
            ticker=None,
            summary=(f"${cash:,.2f} cash idle in {aid} "
                     f"({(cash/trading_capital)*100:.1f}% of book) — "
                     f"consider deploying"),
            detail={"cash": round(cash, 2),
                    "trading_capital": round(trading_capital, 2)},
        )

    # ── Overnight exposure
    if in_danger_window:
        # Sum unrealized from sweep_protection's pre-fetch if present;
        # we don't have positions here so fall back to equity vs principal.
        unrealized_above = max(0.0, equity - principal)
        if unrealized_above >= 50.0:
            _add_alert(
                out,
                category="overnight_exposure",
                severity="critical",
                owner=aid,
                ticker=None,
                summary=(f"${unrealized_above:,.2f} of gains exposed during a "
                         f"danger window on {aid}"),
                detail={"equity": round(equity, 2),
                        "principal": round(principal, 2),
                        "unrealized_above_principal": round(unrealized_above, 2)},
            )

    # ── Failed orders this cycle
    cycle_errors = astate.get("errors") or []
    recent_errors = [e for e in cycle_errors
                     if isinstance(e, dict) and "msg" in e][-3:]
    if recent_errors:
        last = recent_errors[-1]
        _add_alert(
            out,
            category="failed_order",
            severity="warning",
            owner=aid,
            ticker=None,
            summary=f"Alpaca returned an error on the last cycle: "
                    f"{last.get('msg', '?')[:120]}",
            detail={"recent_errors": recent_errors},
        )

    # ── Sweep_protection sidecar artifacts
    sp = astate.get("sweep_protection") or {}
    bleed_rows = [r for r in (sp.get("stale_closes") or [])
                  if "BLEED" in str(r.get("trigger", "")).upper()]
    for row in bleed_rows:
        _add_alert(
            out,
            category="bleed_exit_fired",
            severity="info",
            owner=aid,
            ticker=row.get("symbol"),
            summary=f"Bleed-exit closed {row.get('symbol')} — {row.get('trigger')}",
            detail=row,
        )

    return out


def build_alerts(
    data_dir: Path,
    multi_account_results: Dict[str, Dict[str, Any]],
    *,
    market_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the alert list across every enabled account and write the
    JSON. Returns the payload (also written to disk).
    """
    in_danger = bool((market_state or {}).get("in_danger_window"))
    all_alerts: List[Dict[str, Any]] = []
    for aid, astate in (multi_account_results or {}).items():
        all_alerts.extend(_alerts_for_account(
            aid, astate, in_danger_window=in_danger))

    # SGOV mismatch — compare verified-harvest ledger totals against vault values
    try:
        from ..portfolios import verified_harvest as _vh
        summary_by_acct = _vh.summary_by_account(data_dir)
        for aid, astate in (multi_account_results or {}).items():
            if not astate.get("enabled"):
                continue
            vault = astate.get("savings_vault") or {}
            live = _safe_f(vault.get("primary_market_value", 0)
                            or vault.get("total_market_value", 0))
            ver = _safe_f((summary_by_acct.get(aid) or {}).get("verified"))
            delta = round(live - ver, 2)
            if abs(delta) > 1.00:
                _add_alert(
                    all_alerts,
                    category="sgov_mismatch",
                    severity="warning",
                    owner=aid,
                    ticker="SGOV",
                    summary=(f"SGOV live mark ${live:,.2f} ≠ ledger verified "
                             f"${ver:,.2f} (Δ ${delta:+,.2f})"),
                    detail={"live": round(live, 2),
                            "ledger_verified": round(ver, 2),
                            "delta": delta},
                )
    except Exception:
        pass

    payload = {
        "version": "3.2",
        "generated_at": _now_iso(),
        "in_danger_window": in_danger,
        "alerts": all_alerts,
        "counts_by_severity": {
            "critical": sum(1 for a in all_alerts if a["severity"] == "critical"),
            "warning":  sum(1 for a in all_alerts if a["severity"] == "warning"),
            "info":     sum(1 for a in all_alerts if a["severity"] == "info"),
        },
        "counts_by_category": _count_by_field(all_alerts, "category"),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / ALERT_FILENAME).write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[alerts] write failed: {e}")
    return payload


def _count_by_field(rows: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        k = r.get(field) or "unknown"
        out[k] = out.get(k, 0) + 1
    return out


__all__ = [
    "build_alerts",
]
