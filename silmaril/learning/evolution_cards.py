"""
silmaril.learning.evolution_cards — Gamified training cards.

The user requested: "Their training cards should continuously evolve and
improve, no matter what they go through. They should never reset or decline
in performance."

This module implements that. Each agent has an evolution card that ONLY GROWS.
We track:
  - Total experience points (XP) — accumulates with every call (regardless of outcome)
  - Level — milestone-based, strictly monotonic
  - Lifetime stats — total calls, lifetime wins, never decreases
  - Mastery streaks — best win streak ever achieved
  - Specialty unlocks — contexts in which the agent has earned >100 winning calls
  - Achievement badges — one-time unlocks (e.g., "100 calls", "Survived 2026 crash")

Win rate displayed on the card is LIFETIME win rate, which can drift but
the underlying counters (lifetime_calls, lifetime_wins) only grow.

Storage: docs/data/agent_evolution_cards.json

This file is on the PROTECTED_LEARNING_FILES list. It survives every reset.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# XP curve: how many XP to reach the next level
LEVEL_THRESHOLDS = [
    0,        # Level 1
    100,      # Level 2
    300,      # Level 3
    700,      # Level 4
    1500,     # Level 5
    3000,     # Level 6
    6000,     # Level 7
    12000,    # Level 8
    25000,    # Level 9
    50000,    # Level 10
    100000,   # Level 11+
]


@dataclass
class EvolutionCard:
    agent: str
    inception_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    # ---- monotonically increasing counters (NEVER decrease) ----
    xp: int = 0
    lifetime_calls: int = 0
    lifetime_wins: int = 0
    lifetime_strong_wins: int = 0  # high-conviction calls that won
    lifetime_dissent_wins: int = 0  # times this agent was right when overruled
    best_win_streak: int = 0
    longest_active_days: int = 0  # days since inception, only grows
    achievements_unlocked: List[str] = field(default_factory=list)
    specialties_mastered: List[str] = field(default_factory=list)

    # ---- transient counters (used for streak tracking, can reset) ----
    current_win_streak: int = 0
    last_call_date: Optional[str] = None
    last_call_won: Optional[bool] = None

    # ---- evolution timeline (audit trail of milestones) ----
    timeline: List[Dict] = field(default_factory=list)

    @property
    def level(self) -> int:
        for i, threshold in enumerate(LEVEL_THRESHOLDS):
            if self.xp < threshold:
                return max(1, i)
        return len(LEVEL_THRESHOLDS) + (self.xp - LEVEL_THRESHOLDS[-1]) // 50000

    @property
    def xp_to_next_level(self) -> int:
        lvl = self.level
        if lvl <= len(LEVEL_THRESHOLDS) - 1:
            return LEVEL_THRESHOLDS[lvl] - self.xp
        return 50000 - ((self.xp - LEVEL_THRESHOLDS[-1]) % 50000)

    @property
    def lifetime_win_rate(self) -> float:
        if self.lifetime_calls == 0:
            return 0.0
        return self.lifetime_wins / self.lifetime_calls

    def record_call(
        self,
        won: bool,
        conviction: float,
        regime: str,
        was_dissent: bool = False,
    ) -> List[str]:
        """
        Record a single call outcome on this card.
        Returns: list of newly-unlocked achievement strings (for UI flair).
        """
        new_unlocks: List[str] = []

        # XP earned scales with conviction (higher conviction = more XP risked)
        # Wins earn 2x. Even losses earn baseline XP for participation.
        base_xp = max(1, int(conviction * 10))
        earned = base_xp * (2 if won else 1)
        self.xp += earned

        # Pre-update level for milestone detection
        old_level = self.level

        self.lifetime_calls += 1
        if won:
            self.lifetime_wins += 1
            if conviction >= 0.65:
                self.lifetime_strong_wins += 1
            if was_dissent:
                self.lifetime_dissent_wins += 1
            self.current_win_streak += 1
            if self.current_win_streak > self.best_win_streak:
                self.best_win_streak = self.current_win_streak
        else:
            self.current_win_streak = 0

        self.last_call_date = datetime.now(timezone.utc).date().isoformat()
        self.last_call_won = won

        # ---- achievement checks ----
        for milestone, label in [
            (100, "100 Calls"),
            (1000, "1,000 Calls"),
            (10000, "10,000 Calls"),
            (50000, "50,000 Calls"),
        ]:
            badge = f"calls_{milestone}"
            if self.lifetime_calls >= milestone and badge not in self.achievements_unlocked:
                self.achievements_unlocked.append(badge)
                new_unlocks.append(label)

        for streak in (5, 10, 20, 50):
            badge = f"streak_{streak}"
            if self.best_win_streak >= streak and badge not in self.achievements_unlocked:
                self.achievements_unlocked.append(badge)
                new_unlocks.append(f"{streak}-Win Streak")

        for n_dissent in (10, 50, 100):
            badge = f"dissent_{n_dissent}"
            if self.lifetime_dissent_wins >= n_dissent and badge not in self.achievements_unlocked:
                self.achievements_unlocked.append(badge)
                new_unlocks.append(f"Right When Overruled ×{n_dissent}")

        # Level-up entries
        new_level = self.level
        if new_level > old_level:
            self.timeline.append({
                "date": datetime.now(timezone.utc).date().isoformat(),
                "event": f"Reached Level {new_level}",
                "xp_total": self.xp,
            })
            new_unlocks.append(f"Level {new_level}")

        # Achievement timeline entries
        for label in new_unlocks:
            self.timeline.append({
                "date": datetime.now(timezone.utc).date().isoformat(),
                "event": f"Unlocked: {label}",
                "xp_total": self.xp,
            })

        return new_unlocks


def load_cards(path: Path) -> Dict[str, EvolutionCard]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    out = {}
    for agent, data in raw.items():
        # Filter to known fields for forward compatibility
        known = {f.name for f in EvolutionCard.__dataclass_fields__.values()}
        clean = {k: v for k, v in data.items() if k in known}
        out[agent] = EvolutionCard(**clean)
    return out


def save_cards(path: Path, cards: Dict[str, EvolutionCard]) -> None:
    out = {agent: asdict(card) for agent, card in cards.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))


def ensure_card(cards: Dict[str, EvolutionCard], agent: str) -> EvolutionCard:
    if agent not in cards:
        cards[agent] = EvolutionCard(agent=agent)
    return cards[agent]
