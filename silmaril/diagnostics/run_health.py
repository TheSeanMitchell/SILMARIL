"""silmaril.diagnostics.run_health — One file, one source of truth.

Every Daily Run writes docs/data/run_health.json at the very end with a
complete picture of what happened:
  - Which agents ran, which were silent, why
  - Alpaca account ID, equity, last cycle outcome
  - Catalyst source status (which APIs worked, which failed)
  - Signal counts: total debates, BUY/SELL/HOLD counts, eligible-for-Alpaca
  - Any tools that errored

If you ever wonder "is the system healthy right now?", you read this file.
That's it. No more grep'ing through 12 different state files.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def collect_run_health(
    out_dir: Path,
    debate_dicts: List[Dict[str, Any]],
    portfolios: Optional[Dict[str, Any]] = None,
    alpaca_state: Optional[Dict[str, Any]] = None,
    catalysts_diag: Optional[Dict[str, Any]] = None,
    main_agents: Optional[List[str]] = None,
    today_iso: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the run_health dict. Caller writes it to disk."""

    now = datetime.now(timezone.utc)
    today_iso = today_iso or now.date().isoformat()

    # ── Signal stats ─────────────────────────────────────────────────
    signal_counts = {"BUY": 0, "STRONG_BUY": 0, "HOLD": 0, "SELL": 0, "STRONG_SELL": 0}
    for d in debate_dicts:
        sig = (d.get("consensus") or {}).get("signal", "HOLD")
        signal_counts[sig] = signal_counts.get(sig, 0) + 1

    # Eligible for Alpaca = BUY/STRONG_BUY with conviction >= 0.40
    eligible_for_alpaca = []
    for d in debate_dicts:
        cons = d.get("consensus") or {}
        sig = cons.get("signal", "HOLD")
        conv = float(cons.get("avg_conviction") or 0)
        if sig in ("BUY", "STRONG_BUY") and conv >= 0.40:
            eligible_for_alpaca.append({
                "ticker": d.get("ticker"),
                "signal": sig,
                "conviction": round(conv, 3),
                "score": cons.get("score"),
            })
    eligible_for_alpaca.sort(key=lambda x: -(x.get("score") or 0))

    # ── Per-agent status ─────────────────────────────────────────────
    agent_status: List[Dict[str, Any]] = []
    if portfolios and main_agents:
        for agent in main_agents:
            p = portfolios.get(agent)
            entry = {"agent": agent}
            if p is None:
                entry["status"] = "MISSING"
                entry["reason"] = "No portfolio for this agent"
                agent_status.append(entry)
                continue

            # Today's history entries for this agent
            history = getattr(p, "history", None) or []
            todays = [h for h in history if h.get("date") == today_iso]
            entry["entries_today"] = len(todays)

            if not todays:
                entry["status"] = "SILENT"
                entry["reason"] = "No history entries written today (agent never executed)"
            else:
                last = todays[-1]
                entry["status"] = last.get("action", "UNKNOWN")
                entry["reason"] = last.get("reason", "")
                entry["last_timestamp"] = last.get("timestamp", "")

            # Position
            pos = getattr(p, "current_position", None)
            if pos:
                entry["position"] = {
                    "ticker": pos.get("ticker"),
                    "qty": pos.get("qty"),
                    "entry_price": pos.get("entry_price"),
                }
            else:
                entry["position"] = None

            entry["cash"] = round(getattr(p, "cash", 0) or 0, 2)
            entry["savings"] = round(getattr(p, "savings", 0) or 0, 2)
            agent_status.append(entry)

    silent_count = sum(1 for a in agent_status if a.get("status") == "SILENT")

    # ── Alpaca summary ───────────────────────────────────────────────
    alpaca_summary = {"enabled": False, "reason": "Alpaca state not provided"}
    if alpaca_state:
        acct = alpaca_state.get("account") or {}
        last_cycle = alpaca_state.get("last_cycle_summary") or {}
        alpaca_summary = {
            "enabled": bool(alpaca_state.get("enabled")),
            "account_id": acct.get("account_number") or acct.get("account_id"),
            "equity": acct.get("equity"),
            "cash": acct.get("cash"),
            "savings": alpaca_state.get("savings", 0),
            "principal_target": alpaca_state.get("principal_target"),
            "last_cycle": {
                "opened": last_cycle.get("opened", 0),
                "closed": last_cycle.get("closed", 0),
                "open_after": last_cycle.get("open_after", 0),
                "tickers": last_cycle.get("tickers_traded", []),
            },
            "lifetime_wins": alpaca_state.get("lifetime_realized_wins", 0),
            "lifetime_losses": alpaca_state.get("lifetime_realized_losses", 0),
            "reason": alpaca_state.get("reason", ""),
            "errors": alpaca_state.get("errors", [])[-5:],
        }

    # ── Catalyst summary ─────────────────────────────────────────────
    catalyst_summary = {"loaded": False}
    if catalysts_diag:
        catalyst_summary = {
            "loaded": True,
            "raw_count": catalysts_diag.get("raw_event_count", 0),
            "filtered_count": catalysts_diag.get("filtered_count", 0),
            "sources": catalysts_diag.get("sources", {}),
        }

    # ── Final health verdict ─────────────────────────────────────────
    issues: List[str] = []
    if not alpaca_summary.get("enabled"):
        issues.append(
            f"Alpaca disabled: {alpaca_summary.get('reason') or 'unknown reason'}"
        )
    if silent_count > 0:
        silent_names = [a["agent"] for a in agent_status if a.get("status") == "SILENT"]
        issues.append(f"{silent_count} agent(s) silent: {silent_names[:5]}")
    if eligible_for_alpaca == [] and signal_counts.get("BUY", 0) > 0:
        issues.append("BUY signals exist but none meet the 0.40 conviction floor")
    if catalyst_summary.get("loaded") and catalyst_summary.get("raw_count", 0) == 0:
        issues.append("Catalyst aggregator returned zero events from all sources")
    if errors:
        issues.extend(errors[:5])

    verdict = "HEALTHY" if not issues else "DEGRADED"
    if not alpaca_summary.get("enabled") or silent_count > 5:
        verdict = "BROKEN"

    return {
        "generated_at": now.isoformat(),
        "today_iso": today_iso,
        "verdict": verdict,
        "issues": issues,
        "signals": {
            "total_debates": len(debate_dicts),
            "by_signal": signal_counts,
            "eligible_for_alpaca": len(eligible_for_alpaca),
            "top_eligible": eligible_for_alpaca[:10],
        },
        "agents": {
            "total": len(agent_status),
            "silent": silent_count,
            "by_agent": agent_status,
        },
        "alpaca": alpaca_summary,
        "catalysts": catalyst_summary,
    }


def write_run_health(
    out_dir: Path,
    debate_dicts: List[Dict[str, Any]],
    portfolios: Optional[Dict[str, Any]] = None,
    alpaca_state: Optional[Dict[str, Any]] = None,
    catalysts_diag: Optional[Dict[str, Any]] = None,
    main_agents: Optional[List[str]] = None,
    today_iso: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: build + write run_health.json. Returns the dict."""
    health = collect_run_health(
        out_dir=out_dir,
        debate_dicts=debate_dicts,
        portfolios=portfolios,
        alpaca_state=alpaca_state,
        catalysts_diag=catalysts_diag,
        main_agents=main_agents,
        today_iso=today_iso,
        errors=errors,
    )
    path = out_dir / "run_health.json"
    try:
        path.write_text(json.dumps(health, indent=2, default=str))
    except Exception as e:
        print(f"[run_health] write failed: {e}")

    # Also print a one-line summary to CI logs
    print()
    print("=" * 60)
    print(f"RUN HEALTH: {health['verdict']}")
    print(f"  Debates:           {health['signals']['total_debates']}")
    print(f"  Eligible for Alpaca: {health['signals']['eligible_for_alpaca']}")
    print(f"  Alpaca enabled:    {health['alpaca'].get('enabled')}")
    if health['alpaca'].get('account_id'):
        print(f"  Alpaca account:    {health['alpaca']['account_id']}")
    if health['alpaca'].get('equity') is not None:
        print(f"  Alpaca equity:     ${health['alpaca']['equity']:,.2f}")
    last = health['alpaca'].get('last_cycle') or {}
    print(f"  Last cycle:        opened={last.get('opened',0)} "
          f"closed={last.get('closed',0)} open_after={last.get('open_after',0)}")
    print(f"  Silent agents:     {health['agents']['silent']} of {health['agents']['total']}")
    print(f"  Catalysts:         {health['catalysts'].get('raw_count', 0)} raw, "
          f"{health['catalysts'].get('filtered_count', 0)} shown")
    if health['issues']:
        print(f"  Issues ({len(health['issues'])}):")
        for issue in health['issues'][:5]:
            print(f"    - {issue}")
    print("=" * 60)

    return health


__all__ = ["collect_run_health", "write_run_health"]
