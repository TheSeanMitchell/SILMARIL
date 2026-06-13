"""
silmaril.learning.edge_study — Where is the edge, actually?

A read-only analytic over the CLEAN (non-stale) scored outcomes. For every
directional call (BUY/SELL family) it computes the signed realized return —
the % you'd have made following that call over the scoring window — and slices
it by agent, signal type, market regime, conviction, and news state, each with
a t-statistic so we don't mistake noise for edge.

This writes docs/data/edge_study.json. It changes NO trading and NO scoring —
it is pure measurement, safe to run every cycle. Its whole job is to answer the
only question that matters: is there a repeatable stock edge here, and where?

Significance convention (two-sided, rough):
  |t| > 2.0  -> "significant"   (unlikely to be luck on this sample)
  |t| > 1.5  -> "suggestive"
  else       -> "none"
HOLD/ABSTAIN calls are excluded — they generate no tradeable P&L.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BUY = {"BUY", "STRONG_BUY"}
_SELL = {"SELL", "STRONG_SELL"}

# Minimum samples before a slice is allowed a verdict (below this it's noise).
MIN_N_AGENT = 20
MIN_N_SLICE = 10

# Non-equity instruments. The mission is STOCK edge, and crypto/forex/commodity
# calls were diluting it badly (mixing them in dropped the directional edge from
# +0.31% t=2.29 to +0.15% t=1.60). The edge study measures equities-only as the
# headline and reports the dilution separately so it stays visible.
_FOREX_TICKERS = {"UUP", "FXE", "FXY", "FXF", "FXB", "FXC", "FXA", "CYB", "UDN", "USDU"}
_COMMODITY_TICKERS = {"GLD", "SLV", "IAU", "GDX", "GDXJ", "USO", "UNG", "DBC", "PDBC", "DBA", "CPER"}


def _instrument_kind(ticker: Optional[str]) -> str:
    """Classify a ticker as 'equity', 'crypto', or 'macro' (forex/commodity).

    Crypto is detected structurally (``-USD`` / ``USDT`` style pairs) so it
    catches the compounder coin universes (BONK-USD, DOGE-USD, ...) that are not
    in the main equity universe. Forex/commodity ETFs are listed explicitly."""
    t = (ticker or "").upper()
    if not t:
        return "equity"
    if t.endswith("-USD") or t.endswith("-USDT") or t.endswith("USDT") or "-USD" in t:
        return "crypto"
    if t in _FOREX_TICKERS or t in _COMMODITY_TICKERS:
        return "macro"
    return "equity"


def _is_equity(o: Dict[str, Any]) -> bool:
    return _instrument_kind(o.get("ticker")) == "equity"


def _signed_return(o: Dict[str, Any]) -> Optional[float]:
    """Realized % if you followed the call. BUY -> +move, SELL -> -move,
    HOLD/other -> None (no directional P&L)."""
    sig = o.get("signal")
    r = o.get("return_pct")
    if r is None:
        return None
    r = float(r)
    if sig in _BUY:
        return r
    if sig in _SELL:
        return -r
    return None


def _stats(xs: List[float]) -> Dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean_return": 0.0, "win_rate": 0.0, "t_stat": 0.0, "verdict": "none"}
    mean = sum(xs) / n
    sd = (sum((x - mean) ** 2 for x in xs) / n) ** 0.5 if n > 1 else 0.0
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else 0.0
    wr = sum(1 for x in xs if x > 0) / n
    verdict = "significant" if abs(t) > 2.0 else ("suggestive" if abs(t) > 1.5 else "none")
    return {
        "n": n,
        "mean_return": round(mean, 4),
        "win_rate": round(wr, 4),
        "t_stat": round(t, 3),
        "verdict": verdict,
    }


def _slice(pairs: List[Tuple[Dict[str, Any], float]], keyfn, min_n: int) -> List[Dict[str, Any]]:
    groups: Dict[str, List[float]] = defaultdict(list)
    for o, s in pairs:
        k = keyfn(o)
        if k is None:
            continue
        groups[str(k)].append(s)
    rows = []
    for k, xs in groups.items():
        st = _stats(xs)
        if st["n"] >= min_n:
            row = {"key": k}
            row.update(st)
            rows.append(row)
    rows.sort(key=lambda r: r["mean_return"], reverse=True)
    return rows


def build_edge_study(outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute the full edge study from a list of outcome dicts (clean+stale;
    stale is filtered here). The headline and all slices are EQUITIES-ONLY —
    the stock mission — with the crypto/macro dilution reported separately."""
    clean = [o for o in outcomes if not o.get("stale_price_suspected")]

    # All directional pairs (any instrument) — kept only for the dilution view.
    all_pairs: List[Tuple[Dict[str, Any], float]] = []
    for o in clean:
        s = _signed_return(o)
        if s is not None:
            all_pairs.append((o, s))

    # Equities-only directional pairs — these drive every headline number.
    pairs = [(o, s) for o, s in all_pairs if _is_equity(o)]

    # Instrument composition + the all-vs-equity comparison (proves the dilution).
    from collections import Counter as _Counter
    composition = dict(_Counter(_instrument_kind(o.get("ticker")) for o in clean))
    instruments = {
        "composition_clean": composition,
        "all_instruments_directional": _stats([s for _, s in all_pairs]),
        "equity_directional": _stats([s for _, s in pairs]),
    }

    overall = _stats([s for _, s in pairs])

    def conv_bucket(o):
        c = float(o.get("conviction", 0) or 0)
        return "hi(>=0.7)" if c >= 0.7 else ("mid(0.5-0.7)" if c >= 0.5 else "lo(<0.5)")

    def tag(name):
        return lambda o: (o.get("tags") or {}).get(name)

    by_agent = _slice(pairs, lambda o: o.get("agent"), MIN_N_AGENT)
    by_signal = _slice(pairs, lambda o: o.get("signal"), MIN_N_SLICE)
    by_regime = _slice(pairs, tag("market_regime"), MIN_N_SLICE)
    by_conviction = _slice(pairs, conv_bucket, MIN_N_SLICE)
    by_news = _slice(pairs, tag("news_state"), MIN_N_SLICE)
    by_trend = _slice(pairs, tag("trend_state"), MIN_N_SLICE)

    long_rows = [s for o, s in pairs if o.get("signal") in _BUY]
    short_rows = [s for o, s in pairs if o.get("signal") in _SELL]
    long_vs_short = {"long": _stats(long_rows), "short": _stats(short_rows)}

    # Honest auto-notes
    notes: List[str] = []
    notes.append(
        "Equities-only (the stock mission). %d of %d directional calls were "
        "non-equity (crypto/macro) and are excluded from all numbers below."
        % (len(all_pairs) - len(pairs), len(all_pairs))
    )
    ai = instruments["all_instruments_directional"]
    eq = instruments["equity_directional"]
    if ai["n"] and eq["n"] and ai["n"] != eq["n"]:
        notes.append(
            "Crypto/macro dilution: with them mixed in the edge is %+.3f%% (t=%+.2f); "
            "equities-only it is %+.3f%% (t=%+.2f)."
            % (ai["mean_return"], ai["t_stat"], eq["mean_return"], eq["t_stat"])
        )
    sig_agents = [r["key"] for r in by_agent if r["verdict"] == "significant"]
    if sig_agents:
        notes.append("Statistically significant equity edge: " + ", ".join(sig_agents) + ".")
    else:
        notes.append("No single agent shows a statistically significant equity edge yet.")
    ls = long_vs_short
    if ls["long"]["n"] >= MIN_N_SLICE and ls["short"]["n"] >= MIN_N_SLICE:
        if ls["long"]["mean_return"] > 0 and ls["short"]["mean_return"] <= 0:
            notes.append("Edge is long-only: BUY signals positive, SELL signals not.")
    convs = {r["key"]: r["mean_return"] for r in by_conviction}
    if "lo(<0.5)" in convs and "hi(>=0.7)" in convs and convs["lo(<0.5)"] >= convs["hi(>=0.7)"]:
        notes.append("Conviction is NOT informative system-wide (low-conviction >= high-conviction).")
    news_keys = {r["key"] for r in by_news}
    if news_keys and news_keys.issubset({"NORMAL"}):
        notes.append("news_state never varies (all NORMAL) — news is not yet learnable.")
    regime_keys = {r["key"] for r in by_regime}
    if regime_keys and regime_keys.issubset({"RISK_ON"}):
        notes.append("All clean data is RISK_ON — regime-specific claims are untested (wait for risk-off).")

    return {
        "version": "0.001",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "equities_only",
        "n_clean_outcomes": len(clean),
        "n_directional": len(pairs),
        "n_directional_all_instruments": len(all_pairs),
        "instruments": instruments,
        "overall": overall,
        "long_vs_short": long_vs_short,
        "by_agent": by_agent,
        "by_signal": by_signal,
        "by_market_regime": by_regime,
        "by_trend_state": by_trend,
        "by_conviction": by_conviction,
        "by_news_state": by_news,
        "thresholds": {"min_n_agent": MIN_N_AGENT, "min_n_slice": MIN_N_SLICE},
        "notes": notes,
    }


def write_edge_study(out_dir: Path, outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build and write docs/data/edge_study.json. Returns the study dict."""
    study = build_edge_study(outcomes)
    path = Path(out_dir) / "edge_study.json"
    path.write_text(json.dumps(study, indent=2))
    return study
