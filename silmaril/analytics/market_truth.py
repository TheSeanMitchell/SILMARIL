"""
silmaril.analytics.market_truth — the metadata spine (ALPHA 1.0, June 12
operator directive: regime labeling, benchmark-relative measurement,
narrative lifecycle, catalyst taxonomy guarantee).

WHEN an agent works determines everything — and WHEN needs three things
the system was missing: regime labels that VARY, benchmark returns per
trade, and a permanent daily log to join them by date. This organ is all
three. Every run it:

1. BENCHMARK PRICE LOG (benchmark_price_log.json, permanent, one row/day)
   SPY, QQQ, VIX, the 11 sector SPDRs, plus universe advancers/decliners
   vs the prior logged day and a leaders-share proxy. Self-building:
   day 1 logs prices; day 2 onward every derived stat is real.

2. REGIME AXES v2 (regime_axes.json + regime_history.json, permanent)
   classify_regime_axes() over the log: market / volatility / breadth /
   liquidity(proxy) / defensive-rotation / composite. Learning rows join
   this BY DATE — the WHEN-study's conditioning table. The old single
   RISK_ON label stops being the only light in the room.

3. TRADE BENCHMARKS (trade_benchmarks.json)
   For every CLOSE in every account's order history with entry/exit
   prices: trade_return, spy_return, qqq_return, sector_etf_return over
   the SAME window (joined from the log), alpha (= excess return vs SPY),
   excess_vs_sector, relative_strength. Trades predating the log are
   marked benchmark_unavailable — measured honestly, never invented.
   Going forward, EVERY trade carries its benchmark-relative truth.

4. CATALYST TAXONOMY GUARANTEE (inside regime_axes.json payload)
   The canonical nine — earnings, guidance, IPO, macro, analyst,
   product_launch, regulatory, M&A, unknown — with a normalizer mapping
   every observed catalyst label into exactly one bucket, so the study
   layer can pivot on a closed vocabulary forever.

Join key for ALL conditioning: the date column. Offline-safe, read-only
over states, additive, suite step.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "market-truth-1.0"
LOG_FILE = "benchmark_price_log.json"
SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU",
               "XLB", "XLRE", "XLC")
SECTOR_TO_ETF = {
    "Technology": "XLK", "Financials": "XLF", "Energy": "XLE",
    "Healthcare": "XLV", "Industrials": "XLI", "Discretionary": "XLY",
    "Staples": "XLP", "Utilities": "XLU", "Materials": "XLB",
    "Real Estate": "XLRE", "Communication": "XLC",
}

CANONICAL_CATALYSTS = ("earnings", "guidance", "ipo", "macro", "analyst",
                       "product_launch", "regulatory", "ma", "unknown")
_CATALYST_KEYWORDS = {
    "earnings": ("earnings", "beat", "miss", "quarterly", "results", "eps",
                 "revenue"),
    "guidance": ("guidance", "outlook", "forecast", "raises", "lowers",
                 "cuts forecast", "reaffirm"),
    "ipo": ("ipo", "debut", "listing", "s-1", "424b", "prices offering",
            "public offering", "direct listing"),
    "macro": ("fed", "cpi", "inflation", "jobs", "rate", "fomc", "gdp",
              "tariff", "treasury", "macro"),
    "analyst": ("upgrade", "downgrade", "initiat", "price target", "rating",
                "overweight", "underweight", "buy rating", "sell rating"),
    "product_launch": ("launch", "unveil", "announces new", "introduc",
                       "release", "debuts product", "rollout"),
    "regulatory": ("fda", "sec ", "doj", "ftc", "antitrust", "approval",
                   "probe", "lawsuit", "fine", "regulat", "investigation",
                   "recall"),
    "ma": ("acquire", "acquisition", "merger", "buyout", "takeover",
           "to buy ", "stake in", "deal to"),
}


def canonical_catalyst(label) -> str:
    """Map ANY observed catalyst/event label into the canonical nine."""
    t = str(label or "").lower()
    if not t.strip():
        return "unknown"
    for canon, kws in _CATALYST_KEYWORDS.items():
        if any(k in t for k in kws):
            return canon
    return "unknown"


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _f(x) -> Optional[float]:
    try:
        v = float(x)
        return None if v != v else v
    except Exception:
        return None


# ── 1) the daily log ───────────────────────────────────────────────────

def _today_prices(signals: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for d in signals.get("debates") or []:
        t = str(d.get("ticker") or "").upper()
        px = _f(d.get("price"))
        if t and px:
            out[t] = px
    return out


def _append_log(out: Path, signals: Dict[str, Any],
                today: str) -> List[dict]:
    log: List[dict] = _load(out / LOG_FILE, [])
    if not isinstance(log, list):
        log = []
    px = _today_prices(signals)
    prev = log[-1] if log else None
    prev_px: Dict[str, float] = (prev or {}).get("universe_px") or {}

    adv = dec = 0
    big_moves: List[float] = []
    for t, p in px.items():
        if t.endswith("-USD") or t in ("^VIX",):
            continue
        q = prev_px.get(t)
        if q:
            r = p / q - 1.0
            if r > 0:
                adv += 1
            elif r < 0:
                dec += 1
            big_moves.append(abs(r))
    total = adv + dec
    advancers_pct = (adv / total) if total else None
    # leaders-share proxy: share of total absolute movement carried by
    # the 10 biggest movers — a thin tape concentrates its action
    leaders_share = None
    if big_moves and sum(big_moves) > 0:
        big_moves.sort(reverse=True)
        leaders_share = round(sum(big_moves[:10]) / sum(big_moves), 4)

    sectors = {s: px.get(s) for s in SECTOR_ETFS}
    sector_ret = {}
    if prev:
        for s in SECTOR_ETFS:
            a, b = px.get(s), (prev.get("sectors") or {}).get(s)
            sector_ret[s] = (a / b - 1.0) if (a and b) else None

    spy, qqq = px.get("SPY"), px.get("QQQ")
    vix = px.get("^VIX") or _f((signals.get("vix") or {}).get("level")
                               if isinstance(signals.get("vix"), dict)
                               else signals.get("vix"))
    spy_ret_1d = None
    if prev and spy and _f(prev.get("spy")):
        spy_ret_1d = spy / float(prev["spy"]) - 1.0

    row = {"date": today, "spy": spy, "qqq": qqq, "vix": vix,
           "sectors": sectors, "sector_ret_1d": sector_ret,
           "advancers_pct": (round(advancers_pct, 4)
                             if advancers_pct is not None else None),
           "leaders_share": leaders_share,
           "spy_ret_1d": (round(spy_ret_1d, 5)
                          if spy_ret_1d is not None else None),
           "universe_px": px,
           "recorded_at": datetime.now(timezone.utc).isoformat()}
    log = [r for r in log if r.get("date") != today] + [row]
    # permanence vs repo weight: full fidelity for 400 rows (~1.6 trading
    # years); beyond that the repo history is the archive — additive law.
    log = log[-400:]
    _dump(out / LOG_FILE, log)
    return log


# ── 2) regime axes over the log ────────────────────────────────────────

def _sma(vals: List[float], n: int) -> Optional[float]:
    vals = [v for v in vals if v is not None]
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _axes_from_log(log: List[dict]) -> Dict[str, Any]:
    from .regime import classify_regime_axes
    spys = [_f(r.get("spy")) for r in log]
    cur = log[-1] if log else {}
    prev = log[-2] if len(log) > 1 else {}
    return classify_regime_axes(
        spy_price=_f(cur.get("spy")),
        spy_sma_50=_sma(spys, 50),
        spy_sma_200=_sma(spys, 200),
        vix=_f(cur.get("vix")),
        prev_vix=_f(prev.get("vix")),
        spy_ret_1d=_f(cur.get("spy_ret_1d")),
        advancers_pct=_f(cur.get("advancers_pct")),
        leaders_share=_f(cur.get("leaders_share")),
        sector_returns_1d=cur.get("sector_ret_1d") or {},
    )


# ── 3) per-trade benchmark joins ───────────────────────────────────────

_ACCOUNTS = (("LEGACY", "alpaca_paper_state.json"),
             ("HARVEST_3", "alpaca_h3_state.json"),
             ("HARVEST_5", "alpaca_h5_state.json"))


def _log_px_on(log_by_date: Dict[str, dict], date: str,
               key: str, sector_etf: Optional[str] = None) -> Optional[float]:
    row = log_by_date.get(date)
    if not row:
        return None
    if key == "sector" and sector_etf:
        return _f((row.get("sectors") or {}).get(sector_etf))
    return _f(row.get(key))


def _trade_rows(out: Path, log: List[dict],
                sector_lookup: Dict[str, str]) -> List[dict]:
    log_by_date = {r.get("date"): r for r in log}
    rows: List[dict] = []
    for account_id, fn in _ACCOUNTS:
        st = _load(out / fn, {})
        for o in (st.get("orders") or []):
            if not str(o.get("action", "")).startswith("CLOSE"):
                continue
            sym = str(o.get("symbol") or "").upper()
            entry = _f(o.get("entry_price"))
            exit_ = _f(o.get("exit_price"))
            t_exit = str(o.get("timestamp") or o.get("time") or "")[:10]
            t_entry = str(o.get("entry_date")
                          or o.get("entry_time") or "")[:10]
            if not (sym and entry and exit_):
                continue
            trade_ret = exit_ / entry - 1.0
            etf = SECTOR_TO_ETF.get(sector_lookup.get(sym, ""), None)
            row: Dict[str, Any] = {
                "account": account_id, "symbol": sym,
                "entry_date": t_entry or None, "exit_date": t_exit or None,
                "trade_return": round(trade_ret, 5),
                "sector_etf": etf,
            }
            spy0 = _log_px_on(log_by_date, t_entry, "spy")
            spy1 = _log_px_on(log_by_date, t_exit, "spy")
            qqq0 = _log_px_on(log_by_date, t_entry, "qqq")
            qqq1 = _log_px_on(log_by_date, t_exit, "qqq")
            se0 = _log_px_on(log_by_date, t_entry, "sector", etf)
            se1 = _log_px_on(log_by_date, t_exit, "sector", etf)
            if spy0 and spy1:
                spy_ret = spy1 / spy0 - 1.0
                row["spy_return"] = round(spy_ret, 5)
                row["alpha"] = round(trade_ret - spy_ret, 5)
                row["excess_return"] = row["alpha"]
                row["relative_strength"] = round(
                    (1 + trade_ret) / (1 + spy_ret), 5)
            else:
                row["benchmark_unavailable"] = (
                    "trade window predates the benchmark log — measured "
                    "honestly as unavailable, never invented")
            if qqq0 and qqq1:
                row["qqq_return"] = round(qqq1 / qqq0 - 1.0, 5)
            if se0 and se1:
                sr = se1 / se0 - 1.0
                row["sector_etf_return"] = round(sr, 5)
                row["excess_vs_sector"] = round(trade_ret - sr, 5)
            rows.append(row)
    return rows


# ── the suite step ─────────────────────────────────────────────────────

def build_market_truth(out_dir, today: Optional[str] = None) -> Dict[str, Any]:
    out = Path(out_dir)
    signals = _load(out / "signals.json", {})
    today = today or datetime.now(timezone.utc).date().isoformat()

    log = _append_log(out, signals, today)
    axes = _axes_from_log(log)

    hist: List[dict] = _load(out / "regime_history.json", [])
    if not isinstance(hist, list):
        hist = []
    hrow = {"date": today, **{k: axes[k] for k in
            ("market_regime", "breadth_regime", "composite")},
            "volatility": axes["volatility_regime"],
            "liquidity": axes["liquidity_regime"],
            "defensive_rotation": axes["defensive_rotation"]}
    hist = [r for r in hist if r.get("date") != today] + [hrow]
    _dump(out / "regime_history.json", hist[-1000:])

    sector_lookup: Dict[str, str] = {}
    for d in signals.get("debates") or []:
        t = str(d.get("ticker") or "").upper()
        if t and d.get("sector"):
            sector_lookup[t] = str(d.get("sector"))
    trades = _trade_rows(out, log, sector_lookup)
    benched = sum(1 for r in trades if "alpha" in r)
    _dump(out / "trade_benchmarks.json", {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trades": trades,
        "benchmarked": benched,
        "unavailable": len(trades) - benched,
        "law": ("every CLOSE carries trade/SPY/QQQ/sector returns + alpha "
                "+ relative strength once its window is inside the log; "
                "history before the log is marked unavailable, never "
                "invented"),
    })

    _dump(out / "regime_axes.json", {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "axes": axes,
        "log_days": len(log),
        "warming_note": ("sma50/200 + breadth need history: day 1 logs "
                         "prices, day 2 breadth goes live, day 50/200 the "
                         "trend axes sharpen — UNKNOWN until then, by law"),
        "catalyst_taxonomy": {
            "canonical": list(CANONICAL_CATALYSTS),
            "note": ("canonical_catalyst() maps every observed label into "
                     "exactly one bucket; study layers pivot on this "
                     "closed vocabulary, joined to learning rows by date"),
        },
        "join_key": "date",
    })
    return {"composite": axes["composite"],
            "market": axes["market_regime"],
            "breadth": axes["breadth_regime"],
            "log_days": len(log),
            "trades_benchmarked": f"{benched}/{len(trades)}"}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_market_truth(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
