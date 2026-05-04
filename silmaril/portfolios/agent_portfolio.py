"""silmaril.portfolios.agent_portfolio — v3: trailing stop + specialist fallback + date/timestamp pair."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from silmaril.portfolios.momentum_exit import (
        check_exit_conditions, update_peak_price,
        record_price_snapshot, get_agent_config,
    )
    _MOMENTUM_EXIT_AVAILABLE = True
except Exception:
    _MOMENTUM_EXIT_AVAILABLE = False

try:
    from silmaril.ingestion.price_format import safe_price, round_price
    _PRICE_FORMAT_AVAILABLE = True
except Exception:
    _PRICE_FORMAT_AVAILABLE = False
    def safe_price(p, ticker="", min_price=1e-12):
        if p is None or p <= 0: return None
        return p
    def round_price(p, ticker=""): return round(p or 0, 6)

STARTING_EQUITY = 10000.0

SPECIALIST_DOMAINS: Dict[str, set] = {
    "BARON": {"XOM","CVX","COP","VLO","MPC","PSX","DVN","OXY","HAL","SLB","EOG",
              "XLE","XOP","OIH","USO","BNO","UCO","SCO","DRIP","GUSH","UNG","BOIL","KOLD","AMLP"},
    "STEADFAST": {"AAPL","MSFT","GOOGL","AMZN","BRK-B","JNJ","JPM","V","MA","PG",
                  "KO","WMT","COST","HD","GS","MS","WFC","BAC","DIS","NKE","MCD",
                  "CAT","MMM","IBM","VZ","T","CVX","XOM","PFE","MRK"},
}

def _hist_stamps(today_iso: Optional[str] = None) -> Dict[str, str]:
    now = datetime.now(timezone.utc)
    return {"date": today_iso or now.date().isoformat(),
            "timestamp": now.isoformat()}


@dataclass
class AgentPortfolio:
    agent: str
    starting_equity: float = STARTING_EQUITY
    current_equity: float = STARTING_EQUITY
    cash: float = STARTING_EQUITY
    current_position: Optional[Dict] = None
    history: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    inception_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat())

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity == 0: return 0.0
        return (self.current_equity - self.starting_equity) / self.starting_equity

    def total_equity(self, mark_price: Optional[float] = None) -> float:
        if self.current_position is None: return self.cash
        qty = self.current_position.get("qty", 0) or 0
        price = mark_price if mark_price is not None else self.current_position.get("entry_price", 0)
        return self.cash + qty * (price or 0)

    def open_position(self, ticker: str, qty: float, entry_price: float, signal: str) -> None:
        cost = qty * entry_price
        if cost > self.cash: return
        self.cash -= cost
        now = datetime.now(timezone.utc)
        self.current_position = {
            "ticker": ticker, "qty": qty, "entry_price": entry_price,
            "peak_price": entry_price,
            "entry_date": now.date().isoformat(),
            "signal": signal,
            "opened_at": now.isoformat(),
            "price_snapshots": [entry_price],
        }
        self.history.append({
            **_hist_stamps(), "action": "OPEN", "ticker": ticker,
            "qty": qty, "price": entry_price, "signal": signal,
        })

    def close_position(self, exit_price: float, reason: str = "") -> Optional[float]:
        if not self.current_position: return None
        validated = safe_price(exit_price, self.current_position.get("ticker", ""))
        if validated is None:
            self.history.append({
                **_hist_stamps(), "action": "HOLD",
                "ticker": self.current_position.get("ticker", ""),
                "reason": f"Refused close at invalid price {exit_price}",
            })
            return None
        exit_price = validated
        qty = self.current_position["qty"]
        entry = self.current_position["entry_price"]
        signal = self.current_position.get("signal", "BUY")
        if signal in ("SELL", "STRONG_SELL"):
            pnl = (entry - exit_price) * qty
            proceeds = qty * entry + pnl
        else:
            pnl = (exit_price - entry) * qty
            proceeds = qty * exit_price
        self.cash += proceeds
        self.current_equity = self.cash
        ticker = self.current_position["ticker"]
        self.history.append({
            **_hist_stamps(), "action": "CLOSE", "ticker": ticker,
            "qty": qty, "price": exit_price, "pnl": pnl,
            "reason": reason or "Consensus flip",
        })
        self.current_position = None
        return pnl

    def snapshot_equity(self) -> None:
        now = datetime.now(timezone.utc)
        self.equity_curve.append({
            "date": now.date().isoformat(),
            "timestamp": now.isoformat(),
            "equity": self.current_equity, "cash": self.cash,
            "in_position": self.current_position is not None,
        })
        self.equity_curve = self.equity_curve[-2000:]

    def to_dict(self) -> Dict: return asdict(self)


def _find_specialist_buy(agent: str, debate_dicts: List[Dict]) -> Optional[Dict]:
    domain = SPECIALIST_DOMAINS.get(agent)
    if not domain: return None
    best = None; best_score = -999.0
    for d in debate_dicts:
        if d.get("ticker") not in domain: continue
        cons = d.get("consensus") or {}
        if cons.get("signal") not in ("BUY", "STRONG_BUY"): continue
        score = float(cons.get("score") or 0)
        if score > best_score:
            best_score = score; best = d
    return best


def agent_portfolio_act(portfolio: AgentPortfolio, debate_dicts: List[Dict],
                         prices: Dict[str, float]) -> AgentPortfolio:
    today_iso = datetime.now(timezone.utc).date().isoformat()
    agent = portfolio.agent

    if portfolio.current_position:
        held_ticker = portfolio.current_position["ticker"]
        current_price = safe_price(prices.get(held_ticker), held_ticker)
        if current_price:
            qty = portfolio.current_position.get("qty", 0) or 0
            portfolio.current_equity = portfolio.cash + qty * current_price
            if _MOMENTUM_EXIT_AVAILABLE:
                portfolio.current_position = update_peak_price(portfolio.current_position, current_price)
                portfolio.current_position = record_price_snapshot(portfolio.current_position, current_price)
                cfg = get_agent_config(agent)
                should_exit, exit_reason = check_exit_conditions(
                    portfolio.current_position, current_price, today_iso,
                    trailing_stop_pct=cfg["trailing_stop_pct"],
                    max_hold_days=cfg["max_hold_days"],
                    momentum_stall_threshold=cfg["momentum_stall_threshold"])
                if should_exit:
                    portfolio.close_position(current_price, reason=exit_reason)
                    return portfolio
        held_debate = next((d for d in debate_dicts if d.get("ticker") == held_ticker), None)
        if held_debate:
            cons_signal = held_debate.get("consensus", {}).get("signal", "HOLD")
            if cons_signal in ("SELL", "STRONG_SELL", "HOLD") and current_price:
                portfolio.close_position(current_price,
                    reason=f"Consensus on {held_ticker} flipped to {cons_signal}")
                portfolio.history.append({
                    **_hist_stamps(today_iso), "action": "HOLD",
                    "reason": f"Closed {held_ticker} — consensus {cons_signal}",
                    "equity": round(portfolio.total_equity(), 2),
                })
                return portfolio
        portfolio.history.append({
            **_hist_stamps(today_iso), "action": "HOLD",
            "ticker": held_ticker,
            "equity": round(portfolio.total_equity(current_price), 2),
        })
        return portfolio

    best_debate = None; best_score = -999.0
    agent_appears_in_verdicts = False
    for d in debate_dicts:
        verdicts = d.get("verdicts", [])
        if any(v.get("agent") == agent for v in verdicts):
            agent_appears_in_verdicts = True
        agent_vote = next((v for v in verdicts if v.get("agent") == agent and
                           v.get("signal") in ("BUY", "STRONG_BUY")), None)
        if agent_vote is None: continue
        cons_signal = d.get("consensus", {}).get("signal", "HOLD")
        if cons_signal in ("SELL", "STRONG_SELL"): continue
        score = d.get("consensus", {}).get("score", 0) or 0
        if score > best_score:
            best_score = score; best_debate = d

    if best_debate is None and not agent_appears_in_verdicts:
        best_debate = _find_specialist_buy(agent, debate_dicts)
        if best_debate:
            print(f"[portfolio:{agent}] specialist domain → {best_debate.get('ticker')}")

    if best_debate is None:
        portfolio.history.append({
            **_hist_stamps(today_iso), "action": "HOLD",
            "reason": "No qualifying BUY signal found for this agent",
            "equity": round(portfolio.total_equity(), 2),
        })
        return portfolio

    ticker = best_debate["ticker"]
    entry_price = safe_price(prices.get(ticker), ticker)
    if not entry_price:
        portfolio.history.append({
            **_hist_stamps(today_iso), "action": "HOLD",
            "reason": f"No valid price available for {ticker}",
            "equity": round(portfolio.total_equity(), 2),
        })
        return portfolio

    position_value = min(portfolio.total_equity() * 0.10, portfolio.cash * 0.95)
    if position_value < 1.0: return portfolio
    qty = position_value / entry_price
    portfolio.open_position(ticker, qty, entry_price, "BUY")
    portfolio.current_equity = portfolio.total_equity(entry_price)
    return portfolio


_FIELD_ALIASES: Dict[str, str] = {"balance": "cash"}
_KNOWN_FIELDS = set(AgentPortfolio.__dataclass_fields__.keys())


def _coerce_agent_record(raw_record: Dict) -> Dict:
    record: Dict = {}
    for k, v in raw_record.items():
        record[_FIELD_ALIASES.get(k, k)] = v
    clean = {k: v for k, v in record.items() if k in _KNOWN_FIELDS}
    if "cash" not in clean: clean["cash"] = STARTING_EQUITY
    if "current_equity" not in clean: clean["current_equity"] = clean["cash"]
    if "starting_equity" not in clean: clean["starting_equity"] = STARTING_EQUITY
    return clean


def load_portfolios(path: Path) -> Dict[str, AgentPortfolio]:
    if not path.exists(): return {}
    try: raw = json.loads(path.read_text())
    except Exception: return {}
    if not isinstance(raw, dict): return {}
    agent_map = raw.get("portfolios")
    if not isinstance(agent_map, dict):
        agent_map = {k: v for k, v in raw.items() if isinstance(v, dict)}
    out: Dict[str, AgentPortfolio] = {}
    for agent, record in agent_map.items():
        if not isinstance(record, dict): continue
        try:
            kwargs = _coerce_agent_record(record)
            kwargs["agent"] = agent
            out[agent] = AgentPortfolio(**kwargs)
        except Exception:
            continue
    return out


def save_portfolios(path: Path, portfolios: Dict[str, AgentPortfolio],
                    prices: Optional[Dict[str, float]] = None) -> None:
    if prices:
        for p in portfolios.values():
            if p.current_position:
                mark = prices.get(p.current_position.get("ticker", ""))
                if mark:
                    qty = p.current_position.get("qty", 0) or 0
                    p.current_equity = p.cash + qty * mark
    out = {agent: asdict(p) for agent, p in portfolios.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))


def ensure_all_agents_have_portfolios(portfolios: Dict[str, AgentPortfolio],
                                       all_agent_names: List[str]) -> Dict[str, AgentPortfolio]:
    for name in all_agent_names:
        if name not in portfolios:
            portfolios[name] = AgentPortfolio(agent=name)
    return portfolios
