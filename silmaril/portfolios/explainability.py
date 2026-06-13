"""silmaril.portfolios.explainability — Alpha 3.2 decision ledger.

What it does
────────────
The operator's recurring complaint: SILMARIL declines to take trades
and there's no auditable reason why. This module is the central place
every "we didn't trade X because Y" decision gets logged, so the
dashboard can answer "why did we NOT take this trade?" without anyone
having to grep stdout.

The ledger is append-only and capped (last 500 rows). It mirrors the
shape of `verified_harvest_ledger.json` so dashboard renderers can
re-use the same row table.

Categories of decision recorded:
  - rejected_by_risk          (R:R, drawdown, kill switch)
  - rejected_by_three_month   (downtrend filter)
  - blocked_safe_mode         (cohort kill switch)
  - blocked_position_cap      (max positions reached)
  - blocked_vault_reserved    (SGOV/BIL/etc.)
  - blocked_already_held      (no double-add path)
  - blocked_low_conviction
  - sgov_sweep_cap_applied    (we wanted to sweep $X, capped at $Y)
  - bleed_exit_fired
  - news_boost_fired
  - stale_close_fired
  - instant_sweep_fired

JSON path: docs/data/decision_ledger.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


LEDGER_FILENAME = "decision_ledger.json"
MAX_ROWS = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(data_dir: Path) -> Dict[str, Any]:
    p = data_dir / LEDGER_FILENAME
    if not p.exists():
        return {"version": "3.2", "rows": [], "by_category": {}, "by_ticker": {}}
    try:
        body = json.loads(p.read_text())
        if not isinstance(body, dict):
            return {"version": "3.2", "rows": [], "by_category": {}, "by_ticker": {}}
        body.setdefault("rows", [])
        body.setdefault("by_category", {})
        body.setdefault("by_ticker", {})
        return body
    except Exception:
        return {"version": "3.2", "rows": [], "by_category": {}, "by_ticker": {}}


def _save(data_dir: Path, body: Dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    # Trim
    rows = body.get("rows", [])
    if len(rows) > MAX_ROWS:
        try:
            from ..analytics.archive import archive_then_trim as _att
            body["rows"] = _att(data_dir, "decision_ledger", rows, MAX_ROWS)
        except Exception:
            body["rows"] = rows[-MAX_ROWS:]
    body["updated_at"] = _now_iso()
    try:
        (data_dir / LEDGER_FILENAME).write_text(
            json.dumps(body, indent=2, default=str))
    except Exception as e:
        print(f"[explainability] save failed: {e}")


def log_decision(
    data_dir: Optional[Path],
    category: str,
    ticker: Optional[str] = None,
    reason: str = "",
    *,
    account_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Record one decision. Safe to call defensively — returns None on any
    error rather than raising.

    `category` is a short stable token (see module docstring). `reason` is
    the human-readable string the dashboard will show. `detail` is an
    optional payload of extra fields (numbers, IDs, snapshots).
    """
    if not data_dir:
        return None
    try:
        body = _load(data_dir)
        row = {
            "ts": _now_iso(),
            "category": category,
            "ticker": (ticker or "").upper() or None,
            "account_id": account_id,
            "reason": reason or "",
            "detail": detail or {},
        }
        body["rows"].append(row)
        # Update aggregates (last 7 days, simple counters)
        body["by_category"][category] = body["by_category"].get(category, 0) + 1
        if ticker:
            tu = ticker.upper()
            body["by_ticker"].setdefault(tu, 0)
            body["by_ticker"][tu] += 1
        _save(data_dir, body)
        return row
    except Exception as e:
        print(f"[explainability] log_decision({category}) failed: {e}")
        return None


def log_rejection(
    data_dir: Optional[Path],
    ticker: str,
    reason: str,
    *,
    category: str = "rejected",
    account_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Alias / convenience for the most common case: a buy was blocked."""
    return log_decision(
        data_dir, category=category, ticker=ticker, reason=reason,
        account_id=account_id, detail=detail,
    )


def recent_rows(
    data_dir: Path,
    n: int = 50,
    category: Optional[str] = None,
    ticker: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read the most recent `n` rows, optionally filtered. Used by the
    dashboard renderer."""
    body = _load(data_dir)
    rows = body.get("rows", [])
    if category:
        rows = [r for r in rows if r.get("category") == category]
    if ticker:
        tu = ticker.upper()
        rows = [r for r in rows if (r.get("ticker") or "").upper() == tu]
    return rows[-n:]


__all__ = [
    "LEDGER_FILENAME",
    "log_decision",
    "log_rejection",
    "recent_rows",
]
