"""
silmaril.analytics.narrative_lifecycle — Start/Accel/Peak/Decay (ALPHA 1.0,
June 12 operator directive: "tracking Narrative Start, Acceleration,
Peak, Decay").

A narrative is attention with direction. This organ reads each name's
news_history series (per-day sentiment + catalyst + event rows the word
engine already writes) and labels TODAY's phase of its story:

  QUIET         no meaningful coverage signal
  START         signal appears after >=3 quiet days — a story is born
  ACCELERATION  attention/heat rising vs the name's own recent baseline
  PEAK          today's heat is the rolling-window maximum (live PEAKs
                are CANDIDATES by definition — a top is only proven by
                the decline after it, and we say so)
  DECAY         two consecutive declines from a recent local max

Heat = |sentiment| + |anticipation| + (1 if catalyst else 0): direction-
agnostic attention intensity from data already on disk. Phases append to
narrative_lifecycle_history.json (permanent, join_key=date) so the
WHEN-study can condition on story phase exactly like regime axes —
"does FABLEBOY_5 earn in ACCELERATION and bleed in DECAY?" becomes an
answerable query. Honesty: <4 rows of history -> WARMING; never a fake
phase. Read-only, offline, suite step.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "narrative-lifecycle-1.0"
MIN_ROWS = 4
QUIET_HEAT = 0.15
LOCAL_WINDOW = 10


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


def _heat(row: dict) -> float:
    try:
        s = abs(float(row.get("sent") or 0.0))
        a = abs(float(row.get("antic") or 0.0))
        c = 1.0 if row.get("cat") is not None else 0.0
        return round(s + a + c, 4)
    except Exception:
        return 0.0


def classify_phase(heats: List[float]) -> Dict[str, Any]:
    """Pure phase classifier over a chronological heat series (today last)."""
    n = len(heats)
    if n < MIN_ROWS:
        return {"phase": "WARMING",
                "why": f"{n}/{MIN_ROWS} days of story history"}
    today = heats[-1]
    window = heats[-LOCAL_WINDOW:]
    prior = heats[:-1][-3:]                     # the 3 days before today
    quiet_streak = 0
    for h in reversed(heats[:-1]):
        if h <= QUIET_HEAT:
            quiet_streak += 1
        else:
            break
    if today <= QUIET_HEAT:
        # falling silent after a hot stretch is DECAY, not QUIET
        if max(prior, default=0.0) > QUIET_HEAT * 2 and n >= MIN_ROWS:
            return {"phase": "DECAY", "why": "story went silent off a hot "
                                             "stretch", "heat": today}
        return {"phase": "QUIET", "heat": today}
    if quiet_streak >= 3:
        return {"phase": "START",
                "why": f"signal after {quiet_streak} quiet days",
                "heat": today}
    if today >= max(window):
        return {"phase": "PEAK",
                "why": ("rolling-window max — a CANDIDATE peak; only the "
                        "decline after proves a top, and tomorrow will say"),
                "heat": today}
    if (n >= 3 and heats[-1] < heats[-2] < heats[-3]
            and max(window[:-2], default=0.0) > QUIET_HEAT * 2):
        return {"phase": "DECAY",
                "why": "two consecutive declines off a local max",
                "heat": today}
    base = sum(prior) / len(prior) if prior else 0.0
    if base > 0 and today >= base * 1.4:
        return {"phase": "ACCELERATION",
                "why": f"heat {today:.2f} vs 3d base {base:.2f} (x"
                       f"{today / base:.1f})", "heat": today}
    return {"phase": "STEADY", "heat": today}


def build_narrative_lifecycle(out_dir,
                              today: Optional[str] = None) -> Dict[str, Any]:
    out = Path(out_dir)
    today = today or datetime.now(timezone.utc).date().isoformat()
    nh = _load(out / "news_history.json", {}) or {}
    per_name: Dict[str, Any] = {}
    counts: Dict[str, int] = {}
    for ticker, rows in nh.items():
        if not isinstance(rows, list) or not rows:
            continue
        rows = sorted(rows, key=lambda r: str(r.get("date") or ""))
        heats = [_heat(r) for r in rows]
        res = classify_phase(heats)
        res["last_date"] = rows[-1].get("date")
        res["days_tracked"] = len(rows)
        per_name[ticker] = res
        counts[res["phase"]] = counts.get(res["phase"], 0) + 1

    hist: List[dict] = _load(out / "narrative_lifecycle_history.json", [])
    if not isinstance(hist, list):
        hist = []
    hrow = {"date": today,
            "phases": {t: r["phase"] for t, r in per_name.items()},
            "counts": counts}
    hist = [r for r in hist if r.get("date") != today] + [hrow]
    _dump(out / "narrative_lifecycle_history.json", hist[-1000:])

    _dump(out / "narrative_lifecycle.json", {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "names": per_name,
        "counts": counts,
        "heat_definition": ("|sentiment| + |anticipation| + 1[catalyst] "
                            "per day — attention intensity, direction-"
                            "agnostic"),
        "join_key": "date",
        "law": ("phases append daily forever; live PEAKs are candidates "
                "by definition; <4 days of story = WARMING, never faked"),
    })
    return {"names": len(per_name), **counts}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_narrative_lifecycle(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
