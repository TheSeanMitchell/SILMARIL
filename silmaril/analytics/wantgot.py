"""
silmaril.analytics.wantgot — Wantgot truth v2 (ALPHA 1.0 item #2).

THE QUESTION IT ANSWERS
"What did each book WANT this cycle, what did it actually GET, what does it
actually HOLD — and for every gap, WHY?" This kills the "stale third account"
confusion class for good: an account showing $0 deployed is no longer a
mystery — wantgot says, per name, whether the book never wanted anything
(no intents), wanted and was gated (which gate), wanted and submitted but the
order is pending/unfilled, or filled and holds it.

INPUTS (all read-only, already on disk — no network, never gated)
  alpaca_*_state.json   cycle_intents (written at finalize by alpaca_paper:
                        every BUY intent with outcome + first-gate reason),
                        orders_placed (broker response incl. status/filled_qty),
                        positions_snapshot (held truth), last_cycle_summary.
  decision_ledger.json  fallback reason source for accounts running a state
                        written before cycle_intents existed.

OUTPUT  docs/data/wantgot.json
  per-account: rows[{ticker, intended_notional, conviction, originated,
                     submitted, order_status, filled_notional_est,
                     held_market_value, verdict, reason}],
               totals{intended, submitted, held, deployment_gap},
               held_no_intent[] (positions the cycle didn't re-justify —
               normal for swing holds; listed so nothing is invisible),
               narrative (one honest sentence per book).

VERDICTS (per intended name)
  FILLED_AND_HELD   submitted; broker shows the position
  SUBMITTED_PENDING submitted; order not (yet) reflected in holdings —
                    pending limit, partial, or async market fill
  DEFERRED          submission deferred (market closed / order-quality)
  BLOCKED:<gate>    a gate stopped it; reason carried verbatim
  NOT_REACHED       loop ended first (position cap / halt)

Fills-or-it-didn't-happen law: "filled" here is positions_snapshot truth,
not order acceptance. Order status is shown but never counted as held.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VERSION = "wantgot-2.0"

ACCOUNT_FILES = (
    ("LEGACY", "alpaca_paper_state.json"),
    ("HARVEST_3", "alpaca_h3_state.json"),
    ("HARVEST_5", "alpaca_h5_state.json"),
)

DEFERRED_CATEGORIES = {
    "deferred_submit_market_closed", "deferred_order_quality",
    # off-session runs: the session hard-gate (the off-hours-incident fix)
    # correctly parks orders until the bell — that is DEFERRED, not an
    # error, and the UI was wrongly painting it as a scary BLOCK.
    "blocked_no_session_match",
}

# decisions that are NOT entry verdicts (exit-side or bookkeeping logs the
# per-cycle sink also catches); they must never masquerade as the reason a
# BUY intent failed.
NON_INTENT_CATEGORIES = {
    "blocked_signal_not_buy", "harvest_below_fee_floor",
    "blocked_vault_reserved",
}

FRIENDLY_REASON = {
    "blocked_no_session_match": ("off-session run — the session hard-gate "
                                  "parks orders until the next open (the "
                                  "off-hours-incident law working as "
                                  "designed)"),
}


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


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _ledger_reason(ledger_rows: List[dict], account_id: str,
                   ticker: str) -> str:
    """Newest decision-ledger reason for (account, ticker) — the fallback
    when a state predates cycle_intents."""
    for r in reversed(ledger_rows):
        if (r.get("account_id") == account_id
                and str(r.get("ticker") or "").upper() == ticker):
            return f"{r.get('category')}: {r.get('reason')}"[:160]
    return "no decision recorded"


def _account_wantgot(state: Dict[str, Any], account_id: str,
                     ledger_rows: List[dict]) -> Dict[str, Any]:
    ci = state.get("cycle_intents") or {}
    intents: List[dict] = ci.get("buy_intents") or []
    held = {str(p.get("symbol") or p.get("ticker") or "").upper(): p
            for p in (state.get("positions_snapshot") or [])}
    held.pop("", None)

    rows: List[dict] = []
    tot_intended = tot_submitted = 0.0
    for it in intents:
        t = str(it.get("ticker") or "").upper()
        outcome = str(it.get("outcome") or "")
        intended = _f(it.get("intended_notional"))
        tot_intended += intended
        pos = held.get(t)
        held_mv = _f((pos or {}).get("market_value"))
        submitted = outcome == "submitted"
        if submitted:
            tot_submitted += intended
            if pos is not None:
                verdict = "FILLED_AND_HELD"
                reason = (f"order {str(it.get('order_status') or 'submitted')}; "
                          f"broker holds ${held_mv:.2f}")
            else:
                verdict = "SUBMITTED_PENDING"
                reason = (f"order status '{it.get('order_status')}' but not in "
                          f"holdings yet — pending limit, partial, or async fill"
                          f" (fills-or-it-didn't-happen: not counted as held)")
        elif outcome in DEFERRED_CATEGORIES:
            verdict = "DEFERRED"
            reason = FRIENDLY_REASON.get(outcome) or it.get("reason") or outcome
        elif outcome in NON_INTENT_CATEGORIES:
            # an exit-side/bookkeeping log won the first-block race — the
            # honest read is that no entry gate actually fired
            verdict = "NOT_REACHED"
            reason = ("no entry gate fired (a non-entry decision was "
                      "logged for this name this cycle)")
        elif outcome == "not_reached":
            verdict = "NOT_REACHED"
            reason = it.get("reason") or "loop ended first"
        elif outcome:
            verdict = f"BLOCKED:{outcome}"
            reason = it.get("reason") or outcome
        else:
            verdict = "UNKNOWN"
            reason = _ledger_reason(ledger_rows, account_id, t)
        rows.append({
            "ticker": t,
            "signal": it.get("signal"),
            "conviction": it.get("conviction"),
            "originated": bool(it.get("originated")),
            "intended_notional": round(intended, 2),
            "submitted": submitted,
            "order_status": it.get("order_status"),
            "held_market_value": round(held_mv, 2) if pos else 0.0,
            "verdict": verdict,
            "reason": str(reason)[:200],
        })

    # Positions the cycle did NOT re-justify — swing holds, prior-cycle
    # entries. Normal, but listed so nothing held is ever invisible.
    intent_names = {r["ticker"] for r in rows}
    held_no_intent = [{
        "ticker": t,
        "market_value": round(_f(p.get("market_value")), 2),
        "unrealized_pl": round(_f(p.get("unrealized_pl")), 2),
        "first_seen": p.get("first_seen"),
        "note": "held from a prior cycle — no fresh BUY intent this cycle",
    } for t, p in sorted(held.items()) if t not in intent_names]

    tot_held = round(sum(_f(p.get("market_value")) for p in held.values()), 2)
    equity = _f((state.get("account") or {}).get("equity"))

    # The honest one-liner per book.
    if not intents and not held:
        if state.get("mode") == "wordsmith":
            ws = state.get("wordsmith") or {}
            n_cand = len(ws.get("candidates") or [])
            fed = ws.get("fed_debate_rows")
            narrative = (f"book is EMPTY and wanted NOTHING this cycle — "
                         f"wordsmith filter saw {fed if fed is not None else '?'} "
                         f"debate rows and approved {n_cand} name(s); if fed=0 "
                         f"the word engine is starved, not silent")
        else:
            narrative = ("book is empty and produced no BUY intents this "
                         "cycle — check plans_offered and the halt flag")
    elif not intents:
        narrative = (f"no fresh intents; riding {len(held)} prior position(s) "
                     f"worth ${tot_held:.2f}")
    else:
        n_fill = sum(1 for r in rows if r["verdict"] == "FILLED_AND_HELD")
        n_pend = sum(1 for r in rows if r["verdict"] == "SUBMITTED_PENDING")
        n_blk = sum(1 for r in rows if r["verdict"].startswith("BLOCKED"))
        n_def = sum(1 for r in rows if r["verdict"] == "DEFERRED")
        narrative = (f"wanted {len(rows)} name(s) (${tot_intended:.0f}): "
                     f"{n_fill} filled+held, {n_pend} pending, "
                     f"{n_blk} gated, {n_def} deferred")

    return {
        "account_id": account_id,
        "mode": state.get("mode"),
        "cycle_at": ci.get("at") or state.get("last_run"),
        "session_open": ci.get("session_open"),
        "composite_halt": ci.get("composite_halt"),
        "halt_reason": ci.get("halt_reason"),
        "has_cycle_intents": bool(ci),
        "rows": rows,
        "held_no_intent": held_no_intent,
        "totals": {
            "intended": round(tot_intended, 2),
            "submitted": round(tot_submitted, 2),
            "held": tot_held,
            "equity": round(equity, 2),
            "deployment_gap": round(tot_intended - tot_held, 2),
        },
        "narrative": narrative,
    }


def build_wantgot(out_dir) -> Dict[str, Any]:
    out = Path(out_dir)
    ledger_rows = (_load(out / "decision_ledger.json", {}) or {}).get("rows") or []
    accounts: Dict[str, Any] = {}
    pre_intents = []
    for account_id, fn in ACCOUNT_FILES:
        state = _load(out / fn, {})
        if not state:
            accounts[account_id] = {"account_id": account_id,
                                    "narrative": f"{fn} missing/unreadable"}
            continue
        accounts[account_id] = _account_wantgot(state, account_id, ledger_rows)
        if not accounts[account_id].get("has_cycle_intents"):
            pre_intents.append(account_id)

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": accounts,
        "note": ("intended vs filled vs held, with the FIRST gate that "
                 "stopped each name. Fills law: 'held' is broker "
                 "positions_snapshot truth, never order acceptance."
                 + (f" Accounts pending first post-install cycle "
                    f"(no cycle_intents yet): {', '.join(pre_intents)}"
                    if pre_intents else "")),
    }
    _dump(out / "wantgot.json", payload)
    return {a: accounts[a].get("narrative", "")[:60] for a, _ in ACCOUNT_FILES}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_wantgot(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
