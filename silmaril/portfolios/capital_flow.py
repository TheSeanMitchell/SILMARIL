"""silmaril.portfolios.capital_flow — Alpha 5.0 capital-flow rollup.

What it does
────────────
The master directive identifies an operator gap: "the operator cannot
instantly understand where money currently is". This module produces a
single JSON payload the dashboard can render as a Sankey-style flow:

  Market Opportunities → Position Opens → Profitable Positions → Harvest
       → SGOV Vault → Redeployment

It draws from existing JSON sidecars only (no Alpaca calls):
  - harvest_accounts.json       — per-account equity, vault, idle cash
  - verified_harvest_ledger.json — actual harvest events (VERIFIED rows)
  - decision_ledger.json        — recent opens/closes for "in motion"
  - execution_policy.json       — current pressure + redeploy hint

Output (docs/data/capital_flow.json)
────────────────────────────────────
{
  "version": "5.0",
  "generated_at": "...",
  "totals": {
     "trading_capital_total": 28_500.0,
     "deployed_total":        24_200.0,
     "idle_total":             4_300.0,
     "sgov_vault_total":       9_400.0,
     "harvested_today":          312.0,
     "harvested_lifetime":     4_812.0,
     "principal_target_total": 30_000.0,
     "deployment_ratio":          0.84
  },
  "nodes": [
     {"id":"market","label":"Market Opportunities","value":1.0},
     {"id":"opens","label":"Position Opens","value":24200},
     {"id":"profit","label":"Profitable Positions","value":1200},
     {"id":"harvest","label":"Harvest Extraction","value":312},
     {"id":"sgov","label":"SGOV Vault","value":9400},
     {"id":"redeploy","label":"Redeployment","value":0}
  ],
  "links": [
     {"source":"market","target":"opens","value":24200},
     {"source":"opens","target":"profit","value":1200},
     {"source":"profit","target":"harvest","value":312},
     {"source":"harvest","target":"sgov","value":312},
     {"source":"sgov","target":"redeploy","value":0}
  ],
  "by_account": {
     "LEGACY":    {"deployed": 9100, "idle": 900, "sgov": 1300, "harvest_today": 50},
     "HARVEST_3": {...},
     "HARVEST_5": {...}
  },
  "recent_flows": [
     {"ts":"...","kind":"open","ticker":"NVDA","account":"HARVEST_5","amount":1200},
     {"ts":"...","kind":"close","ticker":"AAPL","account":"LEGACY","amount":-870},
     {"ts":"...","kind":"sweep","account":"LEGACY","amount":-150,"to":"SGOV"},
     {"ts":"...","kind":"redeploy","account":"LEGACY","amount":+200,"from":"SGOV"}
  ],
  "rationale": "..."
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.0"
FILENAME = "capital_flow.json"

# Ledger lookback for recent_flows tail.
RECENT_FLOW_HOURS = 72
MAX_RECENT_FLOWS  = 30


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _harvested_today(verified_ledger: Optional[Dict[str, Any]]) -> float:
    """Sum VERIFIED harvest rows dated today across all accounts."""
    if not isinstance(verified_ledger, dict):
        return 0.0
    today = _today_iso()
    total = 0.0
    rows = verified_ledger.get("rows") or verified_ledger.get("entries") or []
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        ts = r.get("verified_at") or r.get("ts") or r.get("when") or ""
        if not str(ts).startswith(today):
            continue
        if (r.get("status") or "").upper() not in ("VERIFIED", "RECONCILED"):
            continue
        total += _safe_f(r.get("amount") or r.get("usd") or r.get("notional"))
    return round(total, 2)


def _harvested_lifetime(harvest_accounts: Optional[Dict[str, Any]]) -> float:
    if not isinstance(harvest_accounts, dict):
        return 0.0
    totals = harvest_accounts.get("totals") or {}
    return round(_safe_f(totals.get("verified_all")), 2)


def _account_breakdown(
    harvest_accounts: Optional[Dict[str, Any]],
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    """Return (by_account_dict, totals_dict).

    `by_account` rows: deployed, idle, sgov, harvest_today, equity, principal.
    `totals` is the system-wide rollup used by the Sankey nodes.
    """
    by_account: Dict[str, Dict[str, float]] = {}
    accounts: List[Dict[str, Any]] = []

    if isinstance(harvest_accounts, dict):
        accounts = list(harvest_accounts.get("accounts") or [])

    # Fall back to multi_account_results when harvest_accounts hasn't been
    # produced yet (e.g. cold cycle).
    if not accounts and isinstance(multi_account_results, dict):
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict) or not astate.get("enabled"):
                continue
            acct = astate.get("account") or {}
            vault = astate.get("savings_vault") or {}
            accounts.append({
                "account_id":       aid,
                "equity":           _safe_f(acct.get("equity")),
                "cash":             _safe_f(acct.get("cash")),
                "principal_target": _safe_f(astate.get("principal_target"), 10000.0),
                "verified_harvested": _safe_f(vault.get("total_market_value")),
                "configured":       True,
                "enabled":          True,
            })

    tc_total = 0.0
    cash_total = 0.0
    sgov_total = 0.0
    eq_total = 0.0
    pr_total = 0.0
    for a in accounts:
        if not isinstance(a, dict):
            continue
        if not a.get("configured") or not a.get("enabled"):
            continue
        aid = a.get("account_id") or "?"
        eq = _safe_f(a.get("equity"))
        cash = _safe_f(a.get("cash"))
        sgov = _safe_f(a.get("verified_harvested")
                        or (a.get("live_vault") or {}).get("total_market_value"))
        pr  = _safe_f(a.get("principal_target"), 10_000.0)
        # Deployed = equity - cash - sgov (clamped at 0).
        deployed = max(0.0, eq - cash - sgov)
        harvest_today = _safe_f((a.get("today") or {}).get("harvest")
                                  or a.get("today_harvest"))
        by_account[aid] = {
            "deployed":         round(deployed, 2),
            "idle":             round(cash, 2),
            "sgov":             round(sgov, 2),
            "equity":           round(eq, 2),
            "principal_target": round(pr, 2),
            "harvest_today":    round(harvest_today, 2),
        }
        tc_total  += deployed + cash         # "trading capital" = deployed + idle
        cash_total += cash
        sgov_total += sgov
        eq_total += eq
        pr_total += pr

    totals = {
        "trading_capital_total": round(tc_total, 2),
        "deployed_total":        round(tc_total - cash_total, 2),
        "idle_total":            round(cash_total, 2),
        "sgov_vault_total":      round(sgov_total, 2),
        "equity_total":          round(eq_total, 2),
        "principal_target_total": round(pr_total, 2),
        "deployment_ratio":      round((tc_total - cash_total) / tc_total, 4)
                                  if tc_total > 0 else 0.0,
    }
    return by_account, totals


def _profitable_positions_value(
    multi_account_results: Optional[Dict[str, Dict[str, Any]]],
    profit_at_risk: Optional[Dict[str, Any]],
) -> float:
    """Sum of unrealized gains across all enabled accounts.

    Pulls from positions_snapshot first; falls back to profit_at_risk
    aggregate when snapshots aren't present.
    """
    if isinstance(multi_account_results, dict):
        total = 0.0
        any_pos = False
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict) or not astate.get("enabled"):
                continue
            for p in (astate.get("positions_snapshot") or []):
                any_pos = True
                upl = _safe_f(p.get("unrealized_pl"))
                if upl > 0:
                    total += upl
        if any_pos:
            return round(total, 2)
    # Profit_at_risk aggregate fallback
    if isinstance(profit_at_risk, dict):
        return round(_safe_f((profit_at_risk.get("totals") or {})
                                .get("unrealized_pl_positive", 0.0)), 2)
    return 0.0


def _recent_flows(decision_ledger: Optional[Dict[str, Any]],
                   now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Pull recent open/close/sweep events for the timeline strip."""
    if not isinstance(decision_ledger, dict):
        return []
    rows = decision_ledger.get("rows") or []
    n = now or datetime.now(timezone.utc)
    cutoff = n - timedelta(hours=RECENT_FLOW_HOURS)
    out: List[Dict[str, Any]] = []
    open_cats   = {"open_executed", "open_placed", "rotation_opened",
                    "elite_opened", "news_boost_fired"}
    close_cats  = {"close_executed", "close_placed", "stale_close_fired",
                    "bleed_exit_fired"}
    sweep_cats  = {"instant_sweep_fired", "sgov_sweep_cap_applied",
                    "sweep_executed"}
    redeploy_cats = {"sgov_redeployed", "redeploy_sgov"}
    for r in rows:
        if not isinstance(r, dict):
            continue
        ts = _parse_iso(r.get("ts"))
        if ts and ts < cutoff:
            continue
        cat = r.get("category") or ""
        detail = r.get("detail") or {}
        amount = _safe_f(detail.get("notional")
                          or detail.get("amount")
                          or detail.get("usd")
                          or r.get("amount"))
        kind = None
        signed = amount
        if cat in open_cats:
            kind = "open"
        elif cat in close_cats:
            kind = "close"
            signed = -abs(amount)
        elif cat in sweep_cats:
            kind = "sweep"
            signed = -abs(amount)
        elif cat in redeploy_cats:
            kind = "redeploy"
            signed = abs(amount)
        else:
            continue
        out.append({
            "ts":      r.get("ts"),
            "kind":    kind,
            "ticker":  r.get("ticker"),
            "account": r.get("account_id"),
            "amount":  round(signed, 2),
            "reason":  (r.get("reason") or "")[:120],
        })
    out = sorted(out, key=lambda d: d.get("ts") or "", reverse=True)
    return out[:MAX_RECENT_FLOWS]


# ─── Public API ────────────────────────────────────────────────────

def build_capital_flow(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the full capital-flow rollup.

    Reads JSON sidecars defensively; safe to call before all sidecars exist.
    """
    n_now = now or datetime.now(timezone.utc)

    harvest_accounts = _load_json(data_dir / "harvest_accounts.json") or {}
    verified_ledger  = _load_json(data_dir / "verified_harvest_ledger.json") or {}
    profit_at_risk   = _load_json(data_dir / "profit_at_risk.json") or {}
    decision_ledger  = _load_json(data_dir / "decision_ledger.json") or {}
    policy           = _load_json(data_dir / "execution_policy.json") or {}

    by_account, totals = _account_breakdown(harvest_accounts,
                                              multi_account_results)
    totals["harvested_today"]    = _harvested_today(verified_ledger)
    totals["harvested_lifetime"] = _harvested_lifetime(harvest_accounts)
    totals["profitable_positions_value"] = _profitable_positions_value(
        multi_account_results, profit_at_risk
    )

    # Sankey-friendly nodes + links
    deployed = totals["deployed_total"]
    profit_val = totals["profitable_positions_value"]
    harvest_today = totals["harvested_today"]
    sgov_total = totals["sgov_vault_total"]
    redeploy_hint = _safe_f(((policy.get("sweep") or {})
                              .get("redeploy_sgov") or {}).get("amount_hint"))

    nodes = [
        {"id": "market",   "label": "Market Opportunities",  "value": 1.0},
        {"id": "opens",    "label": "Position Opens",        "value": round(deployed, 2)},
        {"id": "profit",   "label": "Profitable Positions",   "value": round(profit_val, 2)},
        {"id": "harvest",  "label": "Harvest Extraction",     "value": round(harvest_today, 2)},
        {"id": "sgov",     "label": "SGOV Vault",             "value": round(sgov_total, 2)},
        {"id": "redeploy", "label": "Redeployment",            "value": round(redeploy_hint, 2)},
    ]
    links = [
        {"source": "market",   "target": "opens",    "value": max(1.0, deployed)},
        {"source": "opens",    "target": "profit",   "value": max(0.0, profit_val)},
        {"source": "profit",   "target": "harvest",  "value": max(0.0, harvest_today)},
        {"source": "harvest",  "target": "sgov",     "value": max(0.0, harvest_today)},
        {"source": "sgov",     "target": "redeploy", "value": max(0.0, redeploy_hint)},
    ]

    recent_flows = _recent_flows(decision_ledger, now=n_now)

    bits: List[str] = []
    bits.append(f"deployed ${totals['deployed_total']:,.0f}")
    bits.append(f"idle ${totals['idle_total']:,.0f}")
    bits.append(f"SGOV ${totals['sgov_vault_total']:,.0f}")
    if harvest_today > 0:
        bits.append(f"+${harvest_today:,.0f} today")
    if redeploy_hint > 0:
        bits.append(f"redeploy hint ${redeploy_hint:,.0f}")
    rationale = " · ".join(bits)

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "totals":       totals,
        "nodes":        nodes,
        "links":        links,
        "by_account":   by_account,
        "recent_flows": recent_flows,
        "policy_actions": (policy.get("deployment_pressure") or {}).get("actions") or [],
        "rationale":    rationale,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[capital_flow] write failed: {e}")
    return payload


def load_capital_flow(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "totals": {}, "nodes": [], "links": [],
             "by_account": {}, "recent_flows": [],
             "rationale": "no capital flow file"}


__all__ = [
    "VERSION", "build_capital_flow", "load_capital_flow",
]
