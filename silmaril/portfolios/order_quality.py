"""silmaril.portfolios.order_quality — Alpha 6.0 entry execution quality.

What it does
────────────
The master directive flagged: "Current system chases volatility, buys
peaks, enters during spread expansion. Implement limit order logic,
VWAP-aware entries, spread-aware entries, opening volatility filters,
liquidity quality scoring."

This module produces a per-ticker entry quality scorecard that the
executor consults BEFORE submitting market opens. The output guides:

  • use_limit_order:        true/false (skip market in bad conditions)
  • suggested_limit_pct:    how far below/above market for limit
  • defer_to_next_cycle:    true/false (spread too wide or volatile to enter)
  • opening_volatility:     ATR-vs-price ratio (>0.04 = avoid first 15min)
  • liquidity_score:        0..1 (volume vs 30d avg)

Output (docs/data/order_quality.json)
─────────────────────────────────────
{
  "version": "6.0", "generated_at": "...",
  "tickers": {
    "NVDA": {
      "use_limit_order": true,
      "limit_buffer_bps": 25,
      "defer_to_next_cycle": false,
      "opening_volatility": 0.022,
      "liquidity_score": 0.85,
      "rationale": "healthy liquidity, modest vol — limit 25bps under"
    }, ...
  },
  "summary": { "tickers": 24, "deferred": 1, "limit_recommended": 12 }
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "6.0"
FILENAME = "order_quality.json"

# Thresholds
ATR_DEFER_RATIO    = 0.05      # ATR/price > 5% → (now) limit, not skip
ATR_LIMIT_RATIO    = 0.025     # ATR/price > 2.5% → use limit
LIQUIDITY_DEFER    = 0.30      # below 30% of 30-day avg → (now) limit, not skip
LIMIT_BUFFER_BASE_BPS = 30     # base limit-order buffer
# Alpha 6.1 — only an OUTRIGHT SKIP above these (genuinely untradeable). Moderate
# volatility / thinness now routes to a limit order so chosen trades still reach
# the broker instead of being stranded (the cash-idle bug in a volatile tape).
ATR_HARD_DEFER_RATIO = 0.09    # skip only above ~9% ATR/price
LIQUIDITY_HARD_DEFER = 0.10    # skip only below 10% of 30d avg (with real volume)


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


def _timing_fingerprints() -> Dict[str, Any]:
    """Cached read of the per-stock intraday clock (timing_fingerprint.json).
    Confident fingerprints steer ENTRY style: never market-buy a name sitting
    in its own typical daily-high window. Empty dict if not yet built."""
    global _TIMING_CACHE
    try:
        if _TIMING_CACHE is None:
            doc = _load_json(Path("docs/data/timing_fingerprint.json")) or {}
            _TIMING_CACHE = doc.get("fingerprints") or {}
    except Exception:
        _TIMING_CACHE = {}
    return _TIMING_CACHE


_TIMING_CACHE: Optional[Dict[str, Any]] = None


def _et_bucket_now() -> Optional[str]:
    """Current 30-min ET bucket label ('09:30'...'16:00'), None off-session.
    Matches timing_fingerprint's bucketing (EDT = UTC-4)."""
    from datetime import datetime, timezone, timedelta
    et = datetime.now(timezone.utc) + timedelta(hours=-4)
    mins = et.hour * 60 + et.minute
    if mins < 9 * 60 + 30 or mins > 16 * 60:
        return None
    b = (mins // 30) * 30
    return f"{b // 60:02d}:{b % 60:02d}"


def compute_quality_for(
    ticker: str,
    *,
    price: float,
    atr_14: Optional[float],
    volume: Optional[float],
    avg_volume_30d: Optional[float],
    rsi_14: Optional[float] = None,
    change_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Score one ticker's entry conditions."""
    px = _safe_f(price)
    atr = _safe_f(atr_14)
    vol = _safe_f(volume)
    avgv = _safe_f(avg_volume_30d)

    atr_ratio = (atr / px) if px > 0 else 0.0
    liquidity = (vol / avgv) if avgv > 0 else 0.5
    liquidity = max(0.0, min(2.0, liquidity))
    # Normalize: 1.0 = at average, capped 2x.
    liquidity_score = min(1.0, liquidity / 1.2)

    defer = False
    defer_reasons: List[str] = []
    has_vol = avgv > 0
    # Outright SKIP only when truly untradeable. Moderate volatility/thinness
    # falls through to a limit order below, so the chosen trade still reaches
    # the broker instead of being stranded.
    if atr_ratio >= ATR_HARD_DEFER_RATIO:
        defer = True
        defer_reasons.append(f"ATR/price {atr_ratio*100:.1f}% ≥ {ATR_HARD_DEFER_RATIO*100:.0f}% — untradeable")
    if has_vol and liquidity < LIQUIDITY_HARD_DEFER:
        defer = True
        defer_reasons.append(f"liquidity {liquidity*100:.0f}% < {LIQUIDITY_HARD_DEFER*100:.0f}% of 30d avg — illiquid")

    # Limit-order conditions — ENTER, don't skip.
    use_limit = False
    limit_buffer = LIMIT_BUFFER_BASE_BPS
    extension_warning = False
    if rsi_14 is not None and _safe_f(rsi_14) >= 78 and _safe_f(change_pct) >= 0.03:
        use_limit = True
        limit_buffer = 60      # wait for a 60bps pullback before filling
        extension_warning = True
    elif atr_ratio >= ATR_LIMIT_RATIO:
        use_limit = True
        # Scale: 2.5% ATR → ~37bps; 5% ATR → ~55bps; 8% ATR → ~76bps buffer
        limit_buffer = int(20 + atr_ratio * 700)
    elif has_vol and liquidity < LIQUIDITY_DEFER:
        # Thin but tradeable — use a limit rather than a market order.
        use_limit = True
        limit_buffer = max(limit_buffer, 40)

    # ── Each stock's clock (timing fingerprint) ───────────────────────
    # If we've LEARNED this name's intraday rhythm (>=3 days), respect it:
    # in its typical daily-HIGH window we refuse to market-buy the top and
    # demand a pullback limit; in its typical daily-LOW window we note the
    # favorable entry. Learning/unknown names are untouched.
    timing_note: Optional[str] = None
    fp = _timing_fingerprints().get((ticker or "").upper()) or {}
    bucket = _et_bucket_now()
    if bucket and fp and not fp.get("learning", True):
        if fp.get("best_sell_window") == bucket:
            use_limit = True
            limit_buffer = max(limit_buffer, 45)
            timing_note = (f"now is {ticker}'s typical daily-HIGH window "
                           f"({bucket} ET) — limit only, refusing to market-buy its top")
        elif fp.get("best_buy_window") == bucket:
            timing_note = (f"now is {ticker}'s typical daily-LOW window "
                           f"({bucket} ET) — historically favorable entry")
        elif (fp.get("best_buy_window")
              and isinstance(fp.get("floor"), (int, float))
              and isinstance(fp.get("current_price"), (int, float))
              and fp["current_price"] > fp["floor"] > 0
              and (fp.get("band_pos") is None or fp["band_pos"] > 0.55)):
            # RESTING AT HIS FLOOR (Alpha 0.007): free-tier cron can't hit a
            # minute, but PRICE can stand in for TIME — his daily-LOW window
            # is elsewhere today and we're in the upper band, so rest a limit
            # partway down toward his floor instead of paying the top now.
            _gap_bps = int((fp["current_price"] - fp["floor"])
                           / fp["current_price"] * 10000)
            if _gap_bps >= 35:
                use_limit = True
                limit_buffer = max(limit_buffer, min(150, int(_gap_bps * 0.6)))
                timing_note = (f"resting toward {ticker}'s ~{fp['floor']} floor "
                               f"(his low window is {fp.get('best_buy_window')} ET) "
                               f"— limit {limit_buffer}bps below")
        # CLOSING-BELL PSYCHOLOGY (Alpha 0.007): a position born at 15:52 has
        # no window left to be managed — final-minutes entries rest well below
        # and only fill on a gift; otherwise tomorrow's open decides.
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            _et = _dt.now(_tz.utc) + _td(hours=-4)
            _left = (16 * 60) - (_et.hour * 60 + _et.minute)
            if 0 < _left <= 10:
                use_limit = True
                limit_buffer = max(limit_buffer, 80)
                timing_note = (f"{_left}m to the bell — entry rests 80bps "
                               f"below; fills on a gift or waits for the open")
        except Exception:
            pass

    bits: List[str] = []
    if defer:
        bits.append("DEFER: " + "; ".join(defer_reasons))
    if extension_warning:
        bits.append(f"overbought (RSI {_safe_f(rsi_14):.0f}) + extended +{_safe_f(change_pct)*100:.1f}% — limit only")
    if use_limit and not extension_warning and not defer:
        bits.append(f"limit {limit_buffer}bps · ATR/px {atr_ratio*100:.1f}% · liq {liquidity_score:.2f}")
    if timing_note:
        bits.append(timing_note)
    if not bits:
        bits.append(f"clean entry · ATR/px {atr_ratio*100:.1f}% · liq {liquidity_score:.2f}")

    return {
        "ticker":               (ticker or "").upper(),
        "use_limit_order":      bool(use_limit),
        "limit_buffer_bps":     int(limit_buffer),
        "defer_to_next_cycle":  bool(defer),
        "opening_volatility":   round(atr_ratio, 4),
        "liquidity_score":      round(liquidity_score, 4),
        "extension_warning":    bool(extension_warning),
        "timing_window":        (timing_note or None),
        "rationale":            " · ".join(bits),
    }


def build_order_quality(
    data_dir: Path,
    contexts: Optional[List[Any]] = None,
    plans: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist order_quality.json for every plan ticker."""
    n_now = now or datetime.now(timezone.utc)

    # Build ctx lookup
    by_ticker: Dict[str, Any] = {}
    if contexts:
        for c in contexts:
            t = (getattr(c, "ticker", "") or "").upper()
            if t:
                by_ticker[t] = c

    plans = plans or []
    rows: Dict[str, Dict[str, Any]] = {}
    deferred = 0
    limit_count = 0
    for p in plans:
        t = (p.get("ticker") or "").upper()
        if not t or t in rows:
            continue
        ctx = by_ticker.get(t)
        if ctx is None:
            # No context — assume neutral, fall through with market order
            rows[t] = {
                "ticker": t,
                "use_limit_order": False,
                "limit_buffer_bps": LIMIT_BUFFER_BASE_BPS,
                "defer_to_next_cycle": False,
                "opening_volatility": 0.0,
                "liquidity_score": 0.5,
                "extension_warning": False,
                "rationale": "no context available — default market order",
            }
            continue
        row = compute_quality_for(
            t,
            price=_safe_f(getattr(ctx, "price", None)),
            atr_14=getattr(ctx, "atr_14", None),
            volume=getattr(ctx, "volume", None),
            avg_volume_30d=getattr(ctx, "avg_volume_30d", None),
            rsi_14=getattr(ctx, "rsi_14", None),
            change_pct=getattr(ctx, "change_pct", None),
        )
        rows[t] = row
        if row["defer_to_next_cycle"]:
            deferred += 1
        if row["use_limit_order"]:
            limit_count += 1

    summary = {
        "tickers":            len(rows),
        "deferred":           deferred,
        "limit_recommended":  limit_count,
        "market_orders_ok":   len(rows) - deferred - limit_count,
    }

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "tickers":      rows,
        "summary":      summary,
        "config": {
            "atr_defer_ratio":  ATR_DEFER_RATIO,
            "atr_limit_ratio":  ATR_LIMIT_RATIO,
            "liquidity_defer":  LIQUIDITY_DEFER,
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[order_quality] write failed: {e}")
    return payload


def load_order_quality(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "tickers": {}, "summary": {"tickers": 0}}


def get_quality(data_dir: Path, ticker: str) -> Dict[str, Any]:
    body = load_order_quality(data_dir)
    return (body.get("tickers") or {}).get((ticker or "").upper(), {})


__all__ = [
    "VERSION", "compute_quality_for", "build_order_quality",
    "load_order_quality", "get_quality",
]
