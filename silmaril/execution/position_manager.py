"""silmaril.execution.position_manager — Alpha 5.1 active position management.

What it does
────────────
The master directive: "Real profitability comes from scaling, partial
exits, trailing behavior, adaptive harvesting, intelligent trimming,
position management."

This module is **directive-emitting**, not directly executing. It reads
the live multi_account_results + capital_efficiency + setup classifications,
and emits per-position directives that the executor (alpaca_paper.py)
already understands or will read out of the policy:

  - SCALE_IN          partial entry to strengthen a winning position
  - SCALE_OUT         partial exit at intermediate profit targets
  - TIGHTEN_STOP      raise trailing stop after gain
  - BREAK_EVEN_STOP   move stop to entry after first profit target hit
  - WIDEN_STOP        loosen stop in volatile early phase of a trend
  - PROFIT_LOCK       hard sell trigger on giveback from peak
  - MOMENTUM_DECAY    full exit when momentum decisively rolls
  - INTRADAY_EXHAUSTION   exit late-stage intraday extension

Each directive has explicit, deterministic firing conditions. The
executor consumes them via `execution_policy.position_directives` so
existing exit logic remains the SOURCE OF TRUTH; this engine merely
provides additional, well-explained triggers.

Output (docs/data/position_directives.json)
───────────────────────────────────────────
{
  "version": "5.1", "generated_at": "...",
  "directives": [
     {
       "owner":"LEGACY", "ticker":"NVDA", "action":"SCALE_OUT",
       "size_pct":0.25,
       "trigger":"unrealized_plpc>=0.03",
       "rationale":"first profit target +3% reached; trim 25%",
       "priority":2
     }, ...
  ],
  "summary": { "directives": 5, "by_action": {...} }
}

Each directive has:
  - owner, ticker         (which account/position)
  - action                (one of the canonical actions above)
  - size_pct              (qty fraction to act on, 0..1; for stop actions, n/a)
  - new_stop_pct          (for TIGHTEN_STOP / WIDEN_STOP: % below current)
  - trigger               (precise firing rule, human readable + machine readable)
  - rationale             (operator-readable why)
  - priority              (1 = highest; PROFIT_LOCK is always priority 1)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "5.1"
FILENAME = "position_directives.json"

# Tunable scaling ladder for partial profit-take.
PROFIT_TARGETS = [
    {"target_pct": 0.03, "trim_pct": 0.25, "label": "first target"},
    {"target_pct": 0.06, "trim_pct": 0.25, "label": "second target"},
    {"target_pct": 0.10, "trim_pct": 0.30, "label": "third target"},
]

# Stop policy
BREAK_EVEN_AFTER_PCT = 0.025
TIGHTEN_AFTER_PCT    = 0.05
TIGHTEN_STOP_FROM_PEAK_PCT = 0.025
PROFIT_LOCK_GIVEBACK_PCT   = 0.05   # 5% drop from peak after we're up

# Scaling-in policy (size up winners, never losers).
SCALE_IN_MIN_GAIN_PCT      = 0.015
SCALE_IN_REQUIRE_MOMENTUM  = 0.55     # capital_efficiency.momentum threshold
SCALE_IN_SIZE_PCT          = 0.20     # add 20% of current qty
SCALE_IN_REQUIRE_HOLD      = "HOLD"   # only if recommendation is HOLD

# Momentum decay full-exit threshold
MOMENTUM_DECAY_FLOOR   = 0.30
MOMENTUM_DECAY_GIVEBACK = 0.04


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


def _build_eff_lookup(cap_eff: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in (cap_eff.get("positions") or []):
        key = f"{p.get('owner','')}::{(p.get('ticker') or '').upper()}"
        out[key] = p
    return out


def _build_setup_lookup(setup_clf: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in (setup_clf.get("classifications") or []):
        t = (c.get("ticker") or "").upper()
        if t:
            out[t] = c
    return out


def _compute_intraday_exhaustion(p: Dict[str, Any]) -> bool:
    """Late-stage intraday extension: peak/current/avg gap large in same day."""
    cur = _safe_f(p.get("current_price"))
    peak = _safe_f(p.get("peak_price"))
    avg = _safe_f(p.get("avg_entry_price"))
    if cur <= 0 or peak <= 0 or avg <= 0:
        return False
    extension = (peak - avg) / avg if avg > 0 else 0.0
    giveback  = (peak - cur) / peak if peak > 0 else 0.0
    # 5%+ run above entry AND we've given back 3%+ of the peak → exhaustion
    return (extension >= 0.05) and (giveback >= 0.03)


def _directives_for_position(
    owner: str,
    pos: Dict[str, Any],
    eff: Optional[Dict[str, Any]],
    setup: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sym = (pos.get("symbol") or pos.get("ticker") or "").upper()
    if not sym or sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
        return out
    qty = _safe_f(pos.get("qty"))
    if qty <= 0:
        return out

    avg = _safe_f(pos.get("avg_entry_price"))
    cur = _safe_f(pos.get("current_price"))
    peak = _safe_f(pos.get("peak_price"))
    upl_pct = _safe_f(pos.get("unrealized_plpc"))
    momentum_score = _safe_f((eff or {}).get("components", {}).get("momentum"))
    recommendation = (eff or {}).get("recommendation")

    # ── 1. PROFIT_LOCK — peak giveback after we were significantly up ─
    if peak > 0 and cur > 0 and avg > 0:
        peak_gain_pct = (peak - avg) / avg if avg > 0 else 0.0
        giveback_pct  = (peak - cur) / peak if peak > 0 else 0.0
        if peak_gain_pct >= 0.04 and giveback_pct >= PROFIT_LOCK_GIVEBACK_PCT:
            out.append({
                "owner":     owner,
                "ticker":    sym,
                "action":    "PROFIT_LOCK",
                "size_pct":  1.0,
                "trigger":   f"peak_gain≥4% AND giveback≥{PROFIT_LOCK_GIVEBACK_PCT*100:.0f}%",
                "rationale": (f"peaked {peak_gain_pct*100:.1f}% above entry, "
                                 f"now back {giveback_pct*100:.1f}% from peak — lock"),
                "priority":  1,
            })
            return out  # PROFIT_LOCK is exclusive; no further directives

    # ── 2. MOMENTUM_DECAY — momentum has rolled while still in profit ─
    if upl_pct >= 0.01 and momentum_score and momentum_score <= MOMENTUM_DECAY_FLOOR:
        # And we've given back a meaningful chunk from peak
        if peak > 0 and cur > 0:
            giveback_pct = (peak - cur) / peak if peak > 0 else 0.0
            if giveback_pct >= MOMENTUM_DECAY_GIVEBACK:
                out.append({
                    "owner":     owner,
                    "ticker":    sym,
                    "action":    "MOMENTUM_DECAY",
                    "size_pct":  1.0,
                    "trigger":   f"momentum≤{MOMENTUM_DECAY_FLOOR} AND giveback≥{MOMENTUM_DECAY_GIVEBACK*100:.0f}%",
                    "rationale": (f"momentum decisively rolled ({momentum_score:.2f}); "
                                     "exit before round-trip"),
                    "priority":  1,
                })
                return out

    # ── 3. INTRADAY_EXHAUSTION ──────────────────────────────────────
    if _compute_intraday_exhaustion(pos):
        out.append({
            "owner":     owner,
            "ticker":    sym,
            "action":    "INTRADAY_EXHAUSTION",
            "size_pct":  0.50,
            "trigger":   "extension≥5% AND giveback≥3% same session",
            "rationale": "late-stage intraday extension — trim half",
            "priority":  2,
        })

    # ── 4. SCALE_OUT at intermediate targets ────────────────────────
    for tgt in PROFIT_TARGETS:
        already_fired_key = f"scale_out_{int(tgt['target_pct']*100)}"
        # Position metadata may track which targets we already fired.
        meta_fired = (pos.get("scale_out_history") or {}).get(already_fired_key)
        if meta_fired:
            continue
        if upl_pct >= tgt["target_pct"]:
            out.append({
                "owner":     owner,
                "ticker":    sym,
                "action":    "SCALE_OUT",
                "size_pct":  tgt["trim_pct"],
                "trigger":   f"unrealized_plpc≥{tgt['target_pct']*100:.0f}%",
                "rationale": f"{tgt['label']} +{tgt['target_pct']*100:.0f}% reached; trim {int(tgt['trim_pct']*100)}%",
                "priority":  3,
                "tag":       already_fired_key,
            })
            break  # one scale_out per cycle

    # ── 5. Stop management ──────────────────────────────────────────
    # 5a. BREAK_EVEN_STOP after first target band
    if upl_pct >= BREAK_EVEN_AFTER_PCT and \
       not pos.get("stop_at_break_even"):
        out.append({
            "owner":     owner,
            "ticker":    sym,
            "action":    "BREAK_EVEN_STOP",
            "new_stop_pct": 0.0,
            "trigger":   f"unrealized_plpc≥{BREAK_EVEN_AFTER_PCT*100:.0f}%",
            "rationale": "move stop to entry — risk-free trade established",
            "priority":  4,
        })

    # 5b. TIGHTEN_STOP after second band
    if upl_pct >= TIGHTEN_AFTER_PCT:
        out.append({
            "owner":     owner,
            "ticker":    sym,
            "action":    "TIGHTEN_STOP",
            "new_stop_pct": TIGHTEN_STOP_FROM_PEAK_PCT,
            "trigger":   f"unrealized_plpc≥{TIGHTEN_AFTER_PCT*100:.0f}%",
            "rationale": (f"+{TIGHTEN_AFTER_PCT*100:.0f}% reached; tighten trailing stop "
                             f"to {TIGHTEN_STOP_FROM_PEAK_PCT*100:.1f}% below peak"),
            "priority":  4,
        })

    # ── 6. SCALE_IN — only on healthy momentum + HOLD recommendation ─
    if upl_pct >= SCALE_IN_MIN_GAIN_PCT \
       and momentum_score >= SCALE_IN_REQUIRE_MOMENTUM \
       and recommendation == SCALE_IN_REQUIRE_HOLD:
        # Refuse if setup archetype prefers concentrated single-shot
        archetype = (setup or {}).get("archetype")
        if archetype not in ("GAP_AND_GO", "INTRADAY_REVERSAL"):
            out.append({
                "owner":     owner,
                "ticker":    sym,
                "action":    "SCALE_IN",
                "size_pct":  SCALE_IN_SIZE_PCT,
                "trigger":   (f"unrealized_plpc≥{SCALE_IN_MIN_GAIN_PCT*100:.1f}% "
                                 f"AND momentum≥{SCALE_IN_REQUIRE_MOMENTUM:.2f} "
                                 f"AND recommendation=HOLD"),
                "rationale": (f"healthy winner ({upl_pct*100:.1f}%, momentum "
                                 f"{momentum_score:.2f}); add 20% size"),
                "priority":  5,
            })

    return out


def build_position_directives(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist position directives for every open position."""
    n_now = now or datetime.now(timezone.utc)
    cap_eff   = _load_json(data_dir / "capital_efficiency.json") or {}
    setup_clf = _load_json(data_dir / "setup_classifications.json") or {}
    eff_lookup = _build_eff_lookup(cap_eff)
    setup_lookup = _build_setup_lookup(setup_clf)

    directives: List[Dict[str, Any]] = []
    if isinstance(multi_account_results, dict):
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict) or not astate.get("enabled"):
                continue
            for p in (astate.get("positions_snapshot") or []):
                sym = (p.get("symbol") or p.get("ticker") or "").upper()
                key = f"{aid}::{sym}"
                eff = eff_lookup.get(key)
                setup = setup_lookup.get(sym)
                directives.extend(_directives_for_position(aid, p, eff, setup))

    directives.sort(key=lambda d: (d.get("priority", 9),
                                       d.get("owner", ""), d.get("ticker", "")))

    by_action: Dict[str, int] = {}
    for d in directives:
        by_action[d["action"]] = by_action.get(d["action"], 0) + 1

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "directives":   directives,
        "summary": {
            "directives": len(directives),
            "by_action":  by_action,
        },
        "rationale": (
            f"{len(directives)} directives issued"
            + (f" — {by_action.get('PROFIT_LOCK', 0)} profit-locks" if by_action.get("PROFIT_LOCK") else "")
            + (f" · {by_action.get('SCALE_OUT', 0)} scale-outs"     if by_action.get("SCALE_OUT")    else "")
            + (f" · {by_action.get('SCALE_IN', 0)} scale-ins"        if by_action.get("SCALE_IN")     else "")
        ),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[position_manager] write failed: {e}")
    return payload


def load_position_directives(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "directives": [],
             "summary": {"directives": 0, "by_action": {}}}


__all__ = [
    "VERSION", "PROFIT_TARGETS",
    "build_position_directives", "load_position_directives",
]
