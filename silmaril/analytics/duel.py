"""
silmaril.analytics.duel — the accounts COMPETE (Alpha 0.007).

Doctrine: three books, three philosophies, one future live slot. LEGACY runs
full consensus, HARVEST_3 the 3%% tier, HARVEST_5 the headlines-only word
book. This organ keeps the official scoreboard so the eventual handoff is one
sentence: "plug account-N's method into live."

Per account, per run: equity, return vs $10K principal, deployment, broker-
confirmed harvest flow, pending orders — appended to an internal daily series
so trend, peak, and drawdown grow from today forward. Leaderboard ranks by
return; verdict names the current champion and how long it has led.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict

BOOKS = (
    ("LEGACY", "alpaca_paper_state.json", "full consensus"),
    ("HARVEST_3", "alpaca_h3_state.json", "3% tier harvester"),
    ("HARVEST_5", "alpaca_h5_state.json", "headlines-only (Wordsmith)"),
)
PRINCIPAL = 10000.0


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def build_duel(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    prev = _load(out / "duel.json", {})
    series: Dict[str, list] = prev.get("series") or {}
    ht = _load(out / "harvest_truth.json", {}).get("accounts") or {}
    now = datetime.now(timezone.utc)
    day = (now + timedelta(hours=-4)).strftime("%Y-%m-%d")

    board = []
    for name, fn, method in BOOKS:
        st = _load(out / fn, {}) or {}
        acct = st.get("account") or {}
        eq = float(acct.get("equity") or 0)
        cash = float(acct.get("cash") or 0)
        if eq <= 0:
            continue
        ret = round((eq / PRINCIPAL - 1) * 100, 2)
        srs = series.setdefault(name, [])
        if not srs or srs[-1].get("d") != day:
            srs.append({"d": day, "eq": round(eq, 2)})
        else:
            srs[-1]["eq"] = round(eq, 2)
        series[name] = srs[-260:]
        peak = max(r["eq"] for r in srs)
        dd = round((eq / peak - 1) * 100, 2) if peak else 0.0
        pend = sum(1 for o in (st.get("orders") or [])
                   if str(o.get("status")) in ("new", "accepted",
                                               "pending_new"))
        h = (ht.get(name) or {}).get("totals") or {}
        board.append({
            "account": name, "method": method,
            "equity": round(eq, 2), "ret_pct": ret,
            "deployed_pct": round((eq - cash) / eq * 100, 1),
            "drawdown_from_peak_pct": dd,
            "days_tracked": len(srs),
            "pending_orders": pend,
            "harvest_confirmed_usd":
                h.get("harvest_sells_confirmed_usd", 0.0),
        })

    board.sort(key=lambda b: -b["ret_pct"])
    champ = board[0] if board else None
    streak = prev.get("champion_streak") or {}
    if champ:
        if streak.get("account") == champ["account"]:
            streak["days"] = streak.get("days", 0) + (
                0 if streak.get("last") == day else 1)
        else:
            streak = {"account": champ["account"], "days": 1}
        streak["last"] = day

    payload = {
        "generated_at": now.isoformat(),
        "principal_each": PRINCIPAL,
        "board": board,
        "champion": (None if not champ else {
            "account": champ["account"], "method": champ["method"],
            "lead_days": streak.get("days", 1),
            "handoff": (f"if live started today: plug {champ['account']}'s "
                        f"method ({champ['method']}) into the live account"),
        }),
        "champion_streak": streak,
        "series": series,
        "note": ("books compete, not cooperate — the live slot goes to the "
                 "method with the longest honest lead"),
    }
    (out / "duel.json").write_text(json.dumps(payload, indent=2))
    return {"books": len(board),
            "champion": champ["account"] if champ else None,
            "spread_pct": (round(board[0]["ret_pct"] - board[-1]["ret_pct"], 2)
                           if len(board) > 1 else 0.0)}
