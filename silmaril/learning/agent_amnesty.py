"""
silmaril.learning.agent_amnesty — stale-era convictions, re-judged on clean evidence.

Agents were frozen by weight multipliers computed during the contaminated
period (e.g. FORGE: "0.83x < 0.85x after 152 scored calls" — most of those
calls scored against stale prices). The freeze itself was correct policy on
the data it had; the data was poisoned. This pass re-opens every frozen
case using ONLY clean outcomes (stale_price_suspected excluded):

  - clean calls < 25            -> RELEASED (insufficient clean evidence —
                                   no one stays frozen on a poisoned record)
  - clean hit-rate >= 0.48 or
    clean avg directional ret>0 -> RELEASED (clean record clears them)
  - otherwise                   -> STAYS FROZEN (clean record confirms it)

Every decision is appended to an amnesty_log inside risk_state.json and the
permanent archive. Runs weekly before the senate (senate.yml) and on demand:
    python -m silmaril.learning.agent_amnesty docs/data
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _clean_stats(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    try:
        sc = json.loads((data_dir / "scoring.json").read_text())
    except Exception:
        return {}
    per: Dict[str, Dict[str, Any]] = {}
    for o in sc.get("outcomes") or []:
        if o.get("stale_price_suspected"):
            continue
        r = o.get("return_pct")
        if not isinstance(r, (int, float)):
            continue
        if str(o.get("signal", "")).endswith("SELL"):
            r = -r
        d = per.setdefault(str(o.get("agent")), {"n": 0, "wins": 0, "sum": 0.0})
        d["n"] += 1
        d["wins"] += 1 if r > 0 else 0
        d["sum"] += r
    return per


def run_amnesty(data_dir: Path) -> Dict[str, Any]:
    path = Path(data_dir) / "risk_state.json"
    try:
        state = json.loads(path.read_text())
    except Exception:
        return {"error": "risk_state.json unreadable", "released": 0}
    agents = state.get("agents") or {}
    stats = _clean_stats(Path(data_dir))
    now = datetime.now(timezone.utc).isoformat()
    log = state.setdefault("amnesty_log", [])
    released, upheld = [], []

    for name, a in agents.items():
        if not (isinstance(a, dict) and a.get("frozen")):
            continue
        s = stats.get(name) or {"n": 0, "wins": 0, "sum": 0.0}
        n = s["n"]
        hit = (s["wins"] / n) if n else None
        avg = (s["sum"] / n) if n else None
        if n < 25:
            verdict, why = "RELEASED", (f"insufficient clean evidence "
                                        f"(clean n={n}) — stale-era "
                                        f"conviction overturned")
        elif (hit is not None and hit >= 0.48) or (avg is not None and avg > 0):
            verdict, why = "RELEASED", (f"clean record clears them: n={n}, "
                                        f"hit={hit:.0%}, avg {avg:+.2f}%")
        else:
            verdict, why = "UPHELD", (f"clean record confirms freeze: n={n}, "
                                      f"hit={hit:.0%}, avg {avg:+.2f}%")
        entry = {"ts": now, "agent": name, "verdict": verdict, "reason": why,
                 "clean_n": n,
                 "prior_reason": a.get("frozen_reason"),
                 "frozen_since": a.get("frozen_since")}
        log.append(entry)
        if verdict == "RELEASED":
            a["frozen"] = False
            a["frozen_reason"] = f"AMNESTY {now[:10]}: {why}"
            a["frozen_cycles"] = 0
            released.append(name)
        else:
            upheld.append(name)
        print(f"[amnesty] {name}: {verdict} — {why}")

    state["amnesty_log"] = log[-200:]
    path.write_text(json.dumps(state, indent=2, default=str))
    try:
        from ..analytics.archive import archive_rows
        archive_rows(Path(data_dir), "amnesty_log",
                     [e for e in log if e["ts"] == now])
    except Exception:
        pass
    return {"released": released, "upheld": upheld,
            "frozen_remaining": len(upheld)}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(run_amnesty(base), indent=2))
