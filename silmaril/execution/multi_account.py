"""silmaril.execution.multi_account — Alpha 6.0 multi-account orchestrator.

Runs alpaca_paper.execute_consensus_signals for each configured account
(LEGACY, HARVEST_3, HARVEST_5). Compared to 3.x:

  * Injects per-account `deployment_floor`, `forced_rotations`,
    `position_directives`, `hard_stops`, `orchestrator`, and
    `order_quality` blocks into the policy view passed to the executor.
  * Reads the prior cycle's deployment_floor.json AND hard_stops.json
    to populate caps + halts BEFORE the executor sees them.
  * Audits post-cycle for the same violations as before plus the
    Alpha 6.0 NEGATIVE_CASH / MARGIN_USED checks.

Back-compat: if any of the new sidecar files are missing, the executor
falls through to legacy behavior. Existing accounts keep running.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class HarvestAccountConfig:
    account_id:           str
    state_filename:       str
    env_key_var:          str
    env_secret_var:       str
    principal_target:     float
    min_harvest_gain_pct: float
    profit_take_pct:      float
    trailing_stop_pct:    float
    max_position_pct:     float
    label:                str
    notes:                str = ""
    mode:                 str = "consensus"   # or "wordsmith" (headlines-only)


HARVEST_ACCOUNTS: List[HarvestAccountConfig] = [
    HarvestAccountConfig(
        account_id="LEGACY",
        state_filename="alpaca_paper_state.json",
        env_key_var="ALPACA_API_KEY",
        env_secret_var="ALPACA_API_SECRET",
        principal_target=10_000.0,
        min_harvest_gain_pct=0.015,
        profit_take_pct=0.03,
        trailing_stop_pct=0.025,
        max_position_pct=0.08,
        label="1.5% Trench-Warfare Harvester (legacy)",
        notes="Untouched migration. Existing positions, savings, history continue.",
    ),
    HarvestAccountConfig(
        account_id="HARVEST_3",
        state_filename="alpaca_h3_state.json",
        env_key_var="ALPACA_API_KEY_H3",
        env_secret_var="ALPACA_API_SECRET_H3",
        principal_target=10_000.0,
        min_harvest_gain_pct=0.03,
        profit_take_pct=0.04,
        trailing_stop_pct=0.03,
        max_position_pct=0.10,
        label="3% Disciplined Harvester",
        notes="Skips TINY tier. Patient, concentrated (10%/position).",
    ),
    HarvestAccountConfig(
        account_id="HARVEST_5",
        state_filename="alpaca_h5_state.json",
        env_key_var="ALPACA_API_KEY_H5",
        env_secret_var="ALPACA_API_SECRET_H5",
        principal_target=10_000.0,
        min_harvest_gain_pct=0.05,
        profit_take_pct=0.06,
        trailing_stop_pct=0.04,
        max_position_pct=0.12,
        label="Headlines-Only Book (Fableboy 5)",
        notes=("PROJECT WORDSMITH: this account trades ONLY what the words "
               "say — entries require a FABLEBOY_5 BUY/STRONG_BUY (the pure "
               "word-engine agent). Same safety rails as everyone (session "
               "gates, trailing, giveback). The cleanest possible test of "
               "'headlines are the secret', isolated in its own book."),
        mode="wordsmith",
    ),
]


def _account_configured(cfg: HarvestAccountConfig) -> bool:
    key = os.environ.get(cfg.env_key_var, "").strip()
    sec = os.environ.get(cfg.env_secret_var, "").strip()
    return bool(key) and bool(sec)


def _with_temp_env(env_key_var: str, env_secret_var: str):
    class _Ctx:
        def __enter__(self):
            self._prev_key = os.environ.get("ALPACA_API_KEY", "")
            self._prev_sec = os.environ.get("ALPACA_API_SECRET", "")
            os.environ["ALPACA_API_KEY"] = os.environ.get(env_key_var, "")
            os.environ["ALPACA_API_SECRET"] = os.environ.get(env_secret_var, "")
            return self
        def __exit__(self, *args):
            os.environ["ALPACA_API_KEY"] = self._prev_key
            os.environ["ALPACA_API_SECRET"] = self._prev_sec
    return _Ctx()


def _load_json(data_dir: Path, fname: str) -> Dict[str, Any]:
    import json as _json
    p = data_dir / fname
    if not p.exists():
        return {}
    try:
        body = _json.loads(p.read_text())
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _safe_f(x, default=0.0):
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def run_all_harvest_accounts(
    plans: List[Dict[str, Any]],
    out_dir: Path,
    all_debate_signals: Optional[Dict[str, str]] = None,
    debate_dicts: Optional[List[Dict[str, Any]]] = None,
    execute_fn: Optional[Callable] = None,
    policy: Optional[Dict[str, Any]] = None,
    plans_by_account: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    contexts_by_ticker: Optional[Dict[str, Any]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Run each configured account's execute_consensus_signals call.

    Alpha 6.0: every account receives a policy view augmented with
    deployment_floor, hard_stops, position_directives, forced_rotations,
    orchestrator, order_quality, and correlation_book blocks.
    """
    if execute_fn is None:
        from .alpaca_paper import execute_consensus_signals
        execute_fn = execute_consensus_signals

    # Alpha 5.1+ sidecars
    floor_doc        = _load_json(out_dir, "deployment_floor.json")
    floor_contracts  = (floor_doc.get("contracts") or {})
    # Alpha 6.0 sidecars
    hard_stops_doc   = _load_json(out_dir, "hard_stops.json")
    hard_stops_accs  = (hard_stops_doc.get("accounts") or {})
    cohort_safe_mode = bool((hard_stops_doc.get("system") or {})
                              .get("cohort_safe_mode"))
    conviction_doc   = _load_json(out_dir, "conviction_ranking.json")
    forced_rotations = (conviction_doc.get("forced_rotation_directives") or [])
    pos_dir_doc      = _load_json(out_dir, "position_directives.json")
    position_directives = (pos_dir_doc.get("directives") or [])
    orch_doc         = _load_json(out_dir, "orchestrator.json")
    orch_directive   = (orch_doc.get("directive") or {})
    order_quality_doc = _load_json(out_dir, "order_quality.json")
    corr_book_doc    = _load_json(out_dir, "correlation_book.json")
    corr_blocked     = ((corr_book_doc.get("suppression_hints") or {})
                         .get("NEW_OPEN_BLOCKED") or [])
    corr_trim        = ((corr_book_doc.get("suppression_hints") or {})
                         .get("TRIM_RECOMMENDED") or [])

    results: Dict[str, Dict[str, Any]] = {}

    for cfg in HARVEST_ACCOUNTS:
        if not _account_configured(cfg):
            results[cfg.account_id] = {
                "enabled": False,
                "account_id": cfg.account_id,
                "reason": (f"{cfg.env_key_var}/{cfg.env_secret_var} not "
                           f"configured — account skipped"),
                "label": cfg.label,
                "principal_target": cfg.principal_target,
                "min_harvest_gain_pct": cfg.min_harvest_gain_pct,
                "configured": False,
            }
            continue

        state_path = out_dir / cfg.state_filename
        account_plans = (plans_by_account or {}).get(cfg.account_id)
        if account_plans is None:
            account_plans = plans

        # Build per-account policy view
        account_policy: Dict[str, Any] = dict(policy or {})
        prior_contract = floor_contracts.get(cfg.account_id) or {}
        # deployment_floor keyed by account_id so the executor picks
        # this account's contract
        account_policy["deployment_floor"] = {
            cfg.account_id: {
                "deployment_base":            cfg.principal_target,
                "harvest_threshold":          cfg.principal_target * (
                    1.0 + cfg.min_harvest_gain_pct),
                "min_harvest_gain_pct":       cfg.min_harvest_gain_pct,
                "max_sweep_today":            _safe_f(prior_contract.get(
                    "max_sweep_today"), 0.0),
                "redeploy_from_sgov_amount":  _safe_f(prior_contract.get(
                    "redeploy_from_sgov_amount"), 0.0),
                "is_underdeployed":           bool(prior_contract.get(
                    "is_underdeployed")),
                "must_redeploy_today":        bool(prior_contract.get(
                    "must_redeploy_today")),
                "objective_today":            prior_contract.get(
                    "objective_today", "STEADY_STATE"),
            }
        }
        # hard_stops keyed by account_id + cohort_safe_mode at top
        account_policy["hard_stops"] = {
            cfg.account_id:     hard_stops_accs.get(cfg.account_id) or {},
            "cohort_safe_mode": cohort_safe_mode,
        }
        account_policy["position_directives"]  = position_directives
        account_policy["forced_rotations"]     = forced_rotations
        account_policy["orchestrator"]         = orch_directive
        account_policy["order_quality"]        = order_quality_doc
        account_policy["correlation_book"]     = {
            "blocked": corr_blocked,
            "trim":    corr_trim,
        }

        # Capture pre-cycle SGOV + cash for audit
        try:
            import json as _json2
            if state_path.exists():
                pre_state = _json2.loads(state_path.read_text()) or {}
            else:
                pre_state = {}
            pre_sgov = _safe_f(((pre_state.get("savings_vault") or {})
                                  .get("total_market_value")), 0.0)
            pre_equity = _safe_f((pre_state.get("account") or {}).get(
                "equity"), 0.0)
            pre_cash = _safe_f((pre_state.get("account") or {}).get("cash"), 0.0)
        except Exception:
            pre_sgov, pre_equity, pre_cash = 0.0, 0.0, 0.0

        try:
            with _with_temp_env(cfg.env_key_var, cfg.env_secret_var):
                state = execute_fn(
                    plans=account_plans,
                    state_path=state_path,
                    max_position_pct=cfg.max_position_pct,
                    min_consensus_conviction=0.40,
                    max_total_positions=15,
                    enable_shorts=True,
                    all_debate_signals=all_debate_signals,
                    debate_dicts=debate_dicts,
                    profit_take_pct=cfg.profit_take_pct,
                    trailing_stop_pct=cfg.trailing_stop_pct,
                    principal_target=cfg.principal_target,
                    min_harvest_gain_pct=cfg.min_harvest_gain_pct,
                    account_id=cfg.account_id,
                    mode=getattr(cfg, 'mode', 'consensus'),
                    policy=account_policy,
                    contexts_by_ticker=contexts_by_ticker,
                    sector_lookup=sector_lookup,
                )
            state["account_id"] = cfg.account_id
            state["label"] = cfg.label
            state["min_harvest_gain_pct"] = cfg.min_harvest_gain_pct
            state["configured"] = True

            # ── Post-cycle audit ────────────────────────────────────
            try:
                from ..portfolios.deployment_floor import (
                    compute_contract as _compute_contract,
                )
                post_sgov = _safe_f(((state.get("savings_vault") or {})
                                       .get("total_market_value")), 0.0)
                post_equity = _safe_f((state.get("account") or {}).get(
                    "equity"), pre_equity)
                post_cash   = _safe_f((state.get("account") or {}).get(
                    "cash"), 0.0)
                post_contract = _compute_contract(
                    account_id=cfg.account_id,
                    mode=getattr(cfg, 'mode', 'consensus'),
                    all_debate_signals=all_debate_signals,
                    equity=post_equity, cash=post_cash, sgov_value=post_sgov,
                    pre_cycle_sgov_value=pre_sgov,
                )
                state["deployment_floor_audit"] = post_contract
                if post_contract.get("violation_flags"):
                    state.setdefault("alerts", []).append({
                        "level":   "WARN",
                        "kind":    "deployment_floor_violation",
                        "flags":   post_contract["violation_flags"],
                        "detail":  post_contract.get("rationale", ""),
                    })
            except Exception:
                pass

            # Persist the live flags. execute_consensus_signals() wrote the
            # state file BEFORE multi_account set configured=True above, so
            # without this re-write the file keeps the stale
            # configured:false / "Awaiting first run" — the write-ordering bug
            # the cockpit flags on H3/H5. The account fetched fine (real equity
            # in state["account"]), so it IS configured; reflect that on disk.
            state["enabled"] = True
            if (not state.get("reason")) or ("Awaiting first run" in str(state.get("reason", ""))):
                state["reason"] = (f"Live \u2014 configured; last run "
                                   f"{str(state.get('last_run', ''))[:19]}")
            try:
                _sp_tmp = str(state_path) + ".tmp"
                with open(_sp_tmp, "w") as _spf:
                    _json2.dump(state, _spf, indent=2, default=str)
                os.replace(_sp_tmp, str(state_path))
            except Exception:
                pass

            results[cfg.account_id] = state
        except Exception as e:
            import traceback as _tb
            tb_short = "".join(_tb.format_exception_only(type(e), e)).strip()
            results[cfg.account_id] = {
                "enabled": False,
                "account_id": cfg.account_id,
                "configured": True,
                "label": cfg.label,
                "principal_target": cfg.principal_target,
                "reason": f"Bridge raised exception: {tb_short}",
                "errors": [{"msg": tb_short}],
            }

    return results


def configured_accounts() -> List[Dict[str, Any]]:
    out = []
    for cfg in HARVEST_ACCOUNTS:
        out.append({
            "account_id":           cfg.account_id,
            "label":                cfg.label,
            "configured":           _account_configured(cfg),
            "env_key_var":          cfg.env_key_var,
            "env_secret_var":       cfg.env_secret_var,
            "principal_target":     cfg.principal_target,
            "min_harvest_gain_pct": cfg.min_harvest_gain_pct,
        })
    return out


__all__ = [
    "HarvestAccountConfig",
    "HARVEST_ACCOUNTS",
    "run_all_harvest_accounts",
    "configured_accounts",
]
