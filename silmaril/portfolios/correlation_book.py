"""silmaril.portfolios.correlation_book — Alpha 6.0 portfolio-level correlation map.

What it does
────────────
The master directive flagged "correlation stacking" — overlapping
exposure, duplicated sector bets, hidden concentration risk. This
module builds a deterministic, explainable correlation snapshot of
every active position across every account.

Inputs:
  - multi_account_results (live positions per account)
  - sector_lookup (ticker → sector mapping)
  - correlation_history.json (90-day rolling correlation matrix, when
    available — graceful fallback to sector-pair heuristics)

Output (docs/data/correlation_book.json)
────────────────────────────────────────
{
  "version": "6.0", "generated_at": "...",
  "clusters": [
    {
      "name": "Semis",
      "members":      ["NVDA","AMD","TSM","ASML"],
      "total_exposure_usd": 6820,
      "system_pct":   0.232,
      "max_pair_corr": 0.84,
      "concentration_severity": "HIGH",
      "rationale": "4 semi names · 23.2% of book · max pair-corr 0.84"
    }, ...
  ],
  "summary": {
    "system_equity":       29343.42,
    "tracked_positions":   12,
    "cluster_count":       3,
    "high_severity":       1,
    "max_single_sector":   0.31
  },
  "suppression_hints": {
    "NEW_OPEN_BLOCKED":   ["NVDA","AMD","ASML"],
    "TRIM_RECOMMENDED":   ["TSM"]
  }
}

Severity thresholds:
  - LOW:     cluster < 12% of book
  - MEDIUM:  12-22% of book
  - HIGH:    >22% of book OR max_pair_corr > 0.80 with 3+ members
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "6.0"
FILENAME = "correlation_book.json"

LOW_BAND      = 0.12
MEDIUM_BAND   = 0.22
HIGH_CORR_THR = 0.80


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


# Built-in sector cluster definitions for sub-sector grouping. Used when
# correlation_history.json doesn't have enough samples yet.
_SUBCLUSTERS: Dict[str, List[str]] = {
    "Semis":          ["NVDA","AMD","ASML","TSM","INTC","MU","AMAT","LRCX","KLAC","AVGO"],
    "Mega-cap Tech":  ["AAPL","MSFT","GOOGL","GOOG","AMZN","META"],
    "Software":       ["CRM","ORCL","ADBE","NOW","SNOW","DDOG","NET","SHOP","CRWD","PANW"],
    "Banks-Big":      ["JPM","BAC","WFC","C","GS","MS"],
    "Crypto-proxy":   ["COIN","MSTR","HOOD","RIOT","MARA","CLSK","WULF","BTBT","HIVE"],
    "EV":             ["TSLA","NIO","RIVN","LCID","XPEV","LI"],
    "Pharma-large":   ["LLY","PFE","JNJ","MRK","NVO","ABBV","BMY"],
    "Defense":        ["LMT","RTX","NOC","GD","BA"],
    "Oil-Major":      ["XOM","CVX","SHEL","BP"],
    "Oil-Service":    ["SLB","HAL","BKR","NOV"],
    "Retail":         ["WMT","COST","TGT","HD","LOW","DG","DLTR"],
    "Discount":       ["DG","DLTR","FIVE","BIG","OLLI"],
    "Streaming":      ["NFLX","DIS","PARA","WBD","ROKU"],
}


def _cluster_for(ticker: str) -> Optional[str]:
    u = (ticker or "").upper()
    for name, syms in _SUBCLUSTERS.items():
        if u in syms:
            return name
    return None


def _aggregate_positions(
    multi_account_results: Optional[Dict[str, Dict[str, Any]]],
    sector_lookup: Optional[Dict[str, str]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(multi_account_results, dict):
        return out
    vault = {"SGOV","BIL","SHY","TFLO","USFR"}
    for aid, astate in multi_account_results.items():
        if not isinstance(astate, dict) or not astate.get("enabled"):
            continue
        for p in (astate.get("positions_snapshot") or []):
            sym = (p.get("symbol") or p.get("ticker") or "").upper()
            if not sym or sym in vault:
                continue
            mv = _safe_f(p.get("market_value")) or (
                  _safe_f(p.get("qty")) * _safe_f(p.get("current_price")))
            if mv <= 0:
                continue
            sec = (sector_lookup or {}).get(sym) or "Unknown"
            sub = _cluster_for(sym)
            out.append({
                "owner":  aid,
                "ticker": sym,
                "market_value": mv,
                "sector": sec,
                "subcluster": sub,
            })
    return out


def _max_pair_correlation(
    members: List[str],
    correlation_matrix: Optional[Dict[str, Dict[str, float]]],
) -> float:
    if not correlation_matrix or len(members) < 2:
        return 0.85    # heuristic high if grouped by known sub-cluster
    best = 0.0
    for i, a in enumerate(members):
        for b in members[i+1:]:
            row_a = correlation_matrix.get(a) or {}
            v = _safe_f(row_a.get(b))
            best = max(best, abs(v))
    return best if best > 0 else 0.70


def _severity(system_pct: float, max_corr: float, n_members: int) -> str:
    if system_pct >= MEDIUM_BAND:
        return "HIGH"
    if max_corr >= HIGH_CORR_THR and n_members >= 3:
        return "HIGH"
    if system_pct >= LOW_BAND:
        return "MEDIUM"
    return "LOW"


def build_correlation_book(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist correlation_book.json."""
    n_now = now or datetime.now(timezone.utc)

    positions = _aggregate_positions(multi_account_results, sector_lookup)
    system_equity = sum(p["market_value"] for p in positions)

    # Load existing correlation matrix if present (used by learning.correlation_matrix)
    corr_history = _load_json(data_dir / "correlation_history.json") or {}
    corr_matrix: Dict[str, Dict[str, float]] = {}
    if isinstance(corr_history, dict):
        snaps = corr_history.get("snapshots") or []
        if snaps:
            latest = snaps[-1] if isinstance(snaps[-1], dict) else {}
            corr_matrix = latest.get("matrix") or {}

    # Group by subcluster first, then by sector for the leftovers.
    by_sub: Dict[str, List[Dict[str, Any]]] = {}
    by_sector: Dict[str, List[Dict[str, Any]]] = {}
    for p in positions:
        sub = p.get("subcluster")
        if sub:
            by_sub.setdefault(sub, []).append(p)
        else:
            by_sector.setdefault(p.get("sector") or "Unknown", []).append(p)

    clusters_out: List[Dict[str, Any]] = []

    def _emit(name: str, members: List[Dict[str, Any]], kind: str) -> None:
        if not members or len(members) < 2:
            return
        names = sorted({m["ticker"] for m in members})
        total = sum(m["market_value"] for m in members)
        pct = total / system_equity if system_equity > 0 else 0.0
        max_c = _max_pair_correlation(names, corr_matrix)
        sev = _severity(pct, max_c, len(names))
        clusters_out.append({
            "name":                  name,
            "kind":                  kind,
            "members":               names,
            "total_exposure_usd":    round(total, 2),
            "system_pct":            round(pct, 4),
            "max_pair_corr":         round(max_c, 4),
            "concentration_severity": sev,
            "rationale": (f"{len(names)} names · {pct*100:.1f}% of book · "
                            f"max pair-corr {max_c:.2f}"),
        })

    for sub, members in by_sub.items():
        _emit(sub, members, "subcluster")
    for sec, members in by_sector.items():
        # Skip sectors with single position (already handled by global limits)
        if len(members) >= 2:
            _emit(sec, members, "sector")

    clusters_out.sort(key=lambda c: -c["system_pct"])

    # Suppression hints
    new_blocked: List[str] = []
    trim_rec:    List[str] = []
    for c in clusters_out:
        if c["concentration_severity"] == "HIGH":
            new_blocked.extend(c["members"])
            if c["system_pct"] >= MEDIUM_BAND * 1.3:
                # Pick the lowest-conviction member (heuristic: last in list)
                trim_rec.append(c["members"][-1])

    # Max single sector
    sector_pcts: Dict[str, float] = {}
    for p in positions:
        s = p["sector"] or "Unknown"
        sector_pcts[s] = sector_pcts.get(s, 0.0) + p["market_value"]
    max_sector_pct = 0.0
    if system_equity > 0:
        max_sector_pct = max(sector_pcts.values(), default=0.0) / system_equity

    summary = {
        "system_equity":       round(system_equity, 2),
        "tracked_positions":   len(positions),
        "cluster_count":       len(clusters_out),
        "high_severity":       sum(1 for c in clusters_out if c["concentration_severity"] == "HIGH"),
        "medium_severity":     sum(1 for c in clusters_out if c["concentration_severity"] == "MEDIUM"),
        "max_single_sector":   round(max_sector_pct, 4),
    }

    payload = {
        "version":           VERSION,
        "generated_at":      n_now.isoformat(),
        "clusters":          clusters_out,
        "summary":           summary,
        "sector_percentages": {s: round(v / system_equity, 4) if system_equity > 0 else 0.0
                                for s, v in sector_pcts.items()},
        "suppression_hints": {
            "NEW_OPEN_BLOCKED":   sorted(set(new_blocked)),
            "TRIM_RECOMMENDED":   sorted(set(trim_rec)),
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[correlation_book] write failed: {e}")
    return payload


def load_correlation_book(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "clusters": [], "summary": {}}


def is_open_blocked(data_dir: Path, ticker: str) -> Tuple[bool, str]:
    body = load_correlation_book(data_dir)
    blocked = set((body.get("suppression_hints") or {}).get("NEW_OPEN_BLOCKED") or [])
    u = (ticker or "").upper()
    if u in blocked:
        # Find the cluster
        for c in (body.get("clusters") or []):
            if u in (c.get("members") or []) and c.get("concentration_severity") == "HIGH":
                return (True, f"concentration ({c.get('name','?')}: {c.get('system_pct',0)*100:.0f}% of book)")
        return (True, "concentration cluster")
    return (False, "")


__all__ = [
    "VERSION", "build_correlation_book", "load_correlation_book",
    "is_open_blocked",
]
