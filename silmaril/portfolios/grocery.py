"""
silmaril.portfolios.grocery — The Grocery Money Engine.

Every compounder and agent portfolio races to generate spendable,
harvested, never-redeployed cash. The question is simple:

  "Who fed their family this week?"

Weekly target: $250.00
  $50   groceries
  $40   gas
  $75   utilities
  $35   phone
  $50   internet
  ───────────────
  $250  total

Harvest tiers (aggressive — poor people can't afford to be patient):
  MINI:  position up  3–5%  → harvest 40% of unrealized gain
  MID:   position up  6–9%  → harvest 60% of unrealized gain
  FULL:  position up 10%+   → harvest 80% of unrealized gain, keep 20% deployed
  WEEK:  every Sunday       → sweep ALL profit above principal regardless

The leaderboard ranks every compounder + every $10K agent portfolio
by weekly harvest efficiency: dollars harvested per dollar deployed.
A compounder generating $250 from $10K beats an agent generating $300 from $50K.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ─── Weekly bill targets ──────────────────────────────────────────
WEEKLY_TARGET = 250.00

BILLS: Dict[str, float] = {
    "groceries":  50.00,
    "gas":        40.00,
    "utilities":  75.00,
    "phone":      35.00,
    "internet":   50.00,
}

# ─── Harvest tiers ────────────────────────────────────────────────
# User-tunable aggression. Each tuple is (min_gain_threshold, harvest_pct, label).
# Tiers are checked in order; first match wins.
#
# TINY 1.5% tier ("trench warfare"):
#   Per the user's spec: "1.5% gain above all movement fees should ALWAYS
#   be harvested." Round-trip fee model is ~0.10–0.20% (1–2 bps spread +
#   FINRA TAF ~0.0166% on sells + spread). So 1.5% gross gain is ~1.30–1.40%
#   net of fees — comfortably above the friction floor. We harvest 100%
#   of the gain above the 1.5% line, leaving the principal still deployed.
#   This is the "always pocket money once you're a clean 1.5% up" rule.
#
# To make harvesting LOOSER (less aggressive — let winners run further):
#   - raise the TINY threshold (0.015 → 0.025) or remove the TINY row
#   - lower the harvest_pct on each tier (0.50 → 0.30 etc.)
# To make harvesting TIGHTER (more aggressive — pocket faster):
#   - lower TINY threshold (0.015 → 0.010)
#   - raise harvest_pct on TINY (0.50 → 0.80) — but be aware that at
#     0.5% gross the round-trip fees may eat half the harvest.
HARVEST_TIERS = [
    (0.10, 0.80, "FULL"),    # 10%+ gain → harvest 80% (let 20% ride)
    (0.06, 0.60, "MID"),     # 6-9% gain → harvest 60%
    (0.03, 0.40, "MINI"),    # 3-5% gain → harvest 40%
    (0.015, 0.50, "TINY"),   # 1.5–2.9% gain → harvest 50% (trench warfare)
]

# Net-of-fees harvest floor. Only TINY tier checks this; the other tiers
# are far enough above fees that it's a no-op for them.
HARVEST_NET_FEE_FLOOR = 0.013   # ~1.3% net after typical round-trip fees

# ─── Starting capital for compounders ─────────────────────────────
COMPOUNDER_STARTING_CAPITAL = 10_000.00
REINCARNATION_THRESHOLD     = 5_000.00   # 50% drawdown = new life


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()

def _week_start() -> str:
    """ISO date of the most recent Monday."""
    d = datetime.now(timezone.utc).date()
    return (d - timedelta(days=d.weekday())).isoformat()


# ─── Harvest trigger math ─────────────────────────────────────────

def compute_harvest(
    entry_price: float,
    current_price: float,
    qty: float,
    principal: float,
) -> Tuple[float, float, str]:
    """
    Given a position, compute how much to harvest right now.

    Returns: (harvest_amount, remaining_notional, tier_label)
    harvest_amount   — dollars to sweep into grocery bucket
    remaining_notional — how much stays deployed
    tier_label       — MINI / MID / FULL / NONE
    """
    if not entry_price or entry_price <= 0 or not current_price or qty <= 0:
        return 0.0, qty * (current_price or 0), "NONE"

    gain_pct = (current_price - entry_price) / entry_price

    for min_gain, harvest_pct, label in HARVEST_TIERS:
        if gain_pct >= min_gain:
            unrealized_gain = (current_price - entry_price) * qty
            # TINY tier: per user spec, only harvest the portion of the
            # gain ABOVE the net-of-fees floor. Below the floor would mean
            # round-trip fees eat the win. Above it = pure trench-warfare
            # money to pocket.
            if label == "TINY":
                effective_gain_pct = gain_pct - HARVEST_NET_FEE_FLOOR
                if effective_gain_pct <= 0:
                    return 0.0, qty * current_price, "NONE"
                harvest_dollars = effective_gain_pct * entry_price * qty * harvest_pct
            else:
                harvest_dollars = unrealized_gain * harvest_pct
            # How many shares to sell to realize harvest_dollars
            shares_to_sell  = harvest_dollars / current_price
            shares_to_sell  = min(shares_to_sell, qty)
            remaining       = (qty - shares_to_sell) * current_price
            return round(harvest_dollars, 4), round(remaining, 4), label

    return 0.0, qty * current_price, "NONE"


def should_harvest(entry_price: float, current_price: float) -> bool:
    """Quick check: is the position in harvest territory?"""
    if not entry_price or entry_price <= 0: return False
    # Mirror the lowest tier in HARVEST_TIERS so 'should_harvest' stays
    # consistent with what compute_harvest will actually do.
    return (current_price - entry_price) / entry_price >= 0.015


# ─── Grocery Ledger ───────────────────────────────────────────────

@dataclass
class GroceryLedger:
    """
    Tracks harvested cash for one compounder or agent portfolio.
    This money never goes back into trades.
    """
    harvester:           str
    principal:           float = COMPOUNDER_STARTING_CAPITAL
    lifetime_harvested:  float = 0.0
    weekly_harvested:    float = 0.0
    week_start:          str   = field(default_factory=_week_start)
    best_week:           float = 0.0
    best_week_date:      str   = ""
    harvest_history:     List[Dict] = field(default_factory=list)

    def _roll_week_if_needed(self) -> None:
        """If it's a new week, archive current week and reset counter."""
        current_week = _week_start()
        if self.week_start != current_week:
            if self.weekly_harvested > self.best_week:
                self.best_week      = self.weekly_harvested
                self.best_week_date = self.week_start
            self.weekly_harvested = 0.0
            self.week_start       = current_week

    def harvest(self, amount: float, reason: str = "", source_ticker: str = "") -> float:
        """Add harvested cash. Returns amount actually harvested."""
        if amount <= 0:
            return 0.0
        self._roll_week_if_needed()
        self.weekly_harvested  += amount
        self.lifetime_harvested += amount
        self.harvest_history.append({
            "date":              _today(),
            "timestamp":         _now(),
            "amount":            round(amount, 4),
            "reason":            reason,
            "ticker":            source_ticker,
            "weekly_total":      round(self.weekly_harvested, 4),
            "lifetime_total":    round(self.lifetime_harvested, 4),
        })
        self.harvest_history = self.harvest_history[-500:]
        return amount

    def set_lifetime(self, lifetime_total: float, reason: str = "") -> float:
        """
        ANCHOR variant of harvest(): set lifetime_harvested to an absolute
        ground-truth value, then derive the weekly delta from it.

        Used for ALPACA, where the truth is "current_equity − principal_target"
        — a single number Alpaca itself reports. We don't want to keep
        adding fake increments on every cycle; we want the leaderboard to
        always equal what Alpaca says is real.

        Behavior:
          - If lifetime_total < current self.lifetime_harvested → drawdown:
            lifetime is overwritten down, weekly stays flat (no negative
            harvest event, just truth-up). Logged as DRAWDOWN.
          - If lifetime_total > current self.lifetime_harvested → growth:
            the delta is added to weekly_harvested as a real harvest event.
          - If equal → no-op.
        """
        if lifetime_total < 0:
            lifetime_total = 0.0
        self._roll_week_if_needed()
        delta = round(lifetime_total - self.lifetime_harvested, 4)
        if abs(delta) < 0.01:
            return 0.0
        if delta > 0:
            # New cash got pocketed since last cycle — count it weekly
            self.weekly_harvested += delta
        # If delta < 0 we don't subtract from weekly — drawdowns shouldn't
        # erase progress already recorded earlier this week. We just truth
        # the lifetime number.
        self.lifetime_harvested = round(lifetime_total, 4)
        self.harvest_history.append({
            "date":              _today(),
            "timestamp":         _now(),
            "amount":            delta,
            "reason":            reason or ("ANCHOR (growth)" if delta > 0 else "ANCHOR (drawdown)"),
            "ticker":            "",
            "weekly_total":      round(self.weekly_harvested, 4),
            "lifetime_total":    round(self.lifetime_harvested, 4),
            "kind":              "anchor",
        })
        self.harvest_history = self.harvest_history[-500:]
        return delta

    def weekly_progress_pct(self) -> float:
        self._roll_week_if_needed()
        return min(100.0, round(self.weekly_harvested / WEEKLY_TARGET * 100, 1))

    def bills_paid(self) -> Dict[str, Any]:
        """Which bills does this week's harvest cover? Returns status per bill."""
        self._roll_week_if_needed()
        remaining = self.weekly_harvested
        paid: Dict[str, Any] = {}
        for bill, cost in BILLS.items():
            if remaining >= cost:
                covered = cost
                status = "PAID"
                remaining -= cost
            elif remaining > 0:
                covered = round(remaining, 2)
                status = "PARTIAL"
                remaining = 0.0
            else:
                covered = 0.0
                status = "UNPAID"
            # Alpha 3.1: emit BOTH legacy keys (status/cost/covered) AND
            # dashboard-friendly keys (paid_pct/amount/target) so the
            # bills bars in docs/index.html render correctly. Previously
            # the dashboard read b.paid_pct which didn't exist, so every
            # bar stayed empty. Keeping legacy keys preserves any
            # downstream consumer that reads cost/covered/status.
            paid[bill] = {
                "status":   status,
                "cost":     cost,
                "covered":  covered,
                "target":   cost,
                "amount":   covered,
                "paid_pct": round((covered / cost) * 100.0, 1) if cost > 0 else 0.0,
            }
        return {
            "bills":            paid,
            "weekly_harvested": round(self.weekly_harvested, 2),
            "weekly_target":    WEEKLY_TARGET,
            "progress_pct":     self.weekly_progress_pct(),
            "surplus":          round(max(0, self.weekly_harvested - WEEKLY_TARGET), 2),
            "shortfall":        round(max(0, WEEKLY_TARGET - self.weekly_harvested), 2),
            "week_start":       self.week_start,
        }

    def efficiency(self) -> float:
        """Harvest efficiency: lifetime_harvested / principal. Normalized leaderboard metric."""
        if self.principal <= 0: return 0.0
        return round(self.lifetime_harvested / self.principal, 6)

    def to_dict(self) -> Dict:
        self._roll_week_if_needed()
        return {
            "harvester":          self.harvester,
            "principal":          self.principal,
            "lifetime_harvested": round(self.lifetime_harvested, 4),
            "weekly_harvested":   round(self.weekly_harvested, 4),
            "weekly_target":      WEEKLY_TARGET,
            "progress_pct":       self.weekly_progress_pct(),
            "week_start":         self.week_start,
            "best_week":          round(self.best_week, 4),
            "best_week_date":     self.best_week_date,
            "bills_paid":         self.bills_paid(),
            "efficiency":         self.efficiency(),
            "harvest_history":    self.harvest_history[-25:],
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "GroceryLedger":
        ledger = cls(
            harvester=data.get("harvester", "UNKNOWN"),
            principal=data.get("principal", COMPOUNDER_STARTING_CAPITAL),
        )
        ledger.lifetime_harvested = data.get("lifetime_harvested", 0.0)
        ledger.weekly_harvested   = data.get("weekly_harvested", 0.0)
        ledger.week_start         = data.get("week_start", _week_start())
        ledger.best_week          = data.get("best_week", 0.0)
        ledger.best_week_date     = data.get("best_week_date", "")
        ledger.harvest_history    = data.get("harvest_history", [])
        ledger._roll_week_if_needed()
        return ledger


# ─── Leaderboard ─────────────────────────────────────────────────

def build_leaderboard(data_dir: Path) -> Dict:
    """
    Read all grocery ledgers and rank by weekly harvest efficiency.
    Writes grocery_leaderboard.json.
    """
    grocery_path = data_dir / "grocery_ledgers.json"
    if not grocery_path.exists():
        return {"leaderboard": [], "generated_at": _now()}

    try:
        raw = json.loads(grocery_path.read_text())
    except Exception:
        return {"leaderboard": [], "generated_at": _now()}

    entries = []
    for harvester, ledger_data in raw.items():
        if not isinstance(ledger_data, dict): continue
        ledger = GroceryLedger.from_dict(ledger_data)
        bills  = ledger.bills_paid()
        entries.append({
            "rank":             0,
            "harvester":        harvester,
            "weekly_harvested": round(ledger.weekly_harvested, 2),
            "weekly_target":    WEEKLY_TARGET,
            "progress_pct":     ledger.weekly_progress_pct(),
            "lifetime_harvested": round(ledger.lifetime_harvested, 2),
            "efficiency":       ledger.efficiency(),
            "principal":        ledger.principal,
            "best_week":        round(ledger.best_week, 2),
            "bills_status":     {b: v["status"] for b, v in bills["bills"].items()},
            "surplus":          bills["surplus"],
            "shortfall":        bills["shortfall"],
            "fed_family":       bills["progress_pct"] >= 100.0,
        })

    # Sort by weekly harvest descending (raw dollars — who fed their family)
    entries.sort(key=lambda e: e["weekly_harvested"], reverse=True)
    for i, e in enumerate(entries):
        e["rank"] = i + 1

    total_weekly = sum(e["weekly_harvested"] for e in entries)
    result = {
        "leaderboard":       entries,
        "total_weekly_all":  round(total_weekly, 2),
        "weekly_target":     WEEKLY_TARGET,
        "combined_progress": round(min(100.0, total_weekly / WEEKLY_TARGET * 100), 1),
        "families_fed":      sum(1 for e in entries if e["fed_family"]),
        "generated_at":      _now(),
    }
    (data_dir / "grocery_leaderboard.json").write_text(
        json.dumps(result, indent=2, default=str))
    return result


# ─── Ledger persistence ───────────────────────────────────────────

def load_ledger(data_dir: Path, harvester: str,
                principal: float = COMPOUNDER_STARTING_CAPITAL) -> GroceryLedger:
    path = data_dir / "grocery_ledgers.json"
    if path.exists():
        try:
            raw = json.loads(path.read_text())
            if harvester in raw:
                return GroceryLedger.from_dict(raw[harvester])
        except Exception:
            pass
    return GroceryLedger(harvester=harvester, principal=principal)


def save_ledger(data_dir: Path, ledger: GroceryLedger) -> None:
    path = data_dir / "grocery_ledgers.json"
    raw: Dict = {}
    if path.exists():
        try: raw = json.loads(path.read_text())
        except Exception: pass
    raw[ledger.harvester] = ledger.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, default=str))
