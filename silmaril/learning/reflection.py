"""
silmaril.learning.reflection

Manual end-of-day reflection injection.

Workflow:
  1. After market close, you (the operator) read the day's outcomes
  2. You write 1-3 sentences of reflection into docs/data/reflections.json
  3. The next daily run reads this file and injects it into every agent's context
  4. The reflection is treated as a "rule of thumb" the agents should consider

You can also run this through Perplexity or Grok manually:
  - Copy the day's signals.json + scoring.json
  - Paste into Perplexity/Grok with prompt:
      "Given today's calls and outcomes, what 2-3 sentence rule should
       the trading agents internalize for tomorrow?"
  - Paste the response into reflections.json's "current" block

Storage: docs/data/reflections.json (PROTECTED — never reset)
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional


def load_reflection(reflections_path: Path) -> Optional[str]:
    if not reflections_path.exists():
        return None
    try:
        data = json.loads(reflections_path.read_text())
    except Exception:
        return None
    current = data.get("current", {})
    text = (current.get("text") or "").strip()
    return text if text else None


def format_reflection_for_context(reflection: Optional[str]) -> str:
    if not reflection:
        return ""
    return f"\n=== OPERATOR REFLECTION (apply as a rule of thumb) ===\n{reflection}\n"


def append_reflection(
    reflections_path: Path,
    text: str,
    author: str = "Operator",
) -> None:
    today = date.today().isoformat()
    if reflections_path.exists():
        try:
            data = json.loads(reflections_path.read_text())
        except Exception:
            data = {"current": {}, "history": []}
    else:
        data = {"current": {}, "history": []}

    cur = data.get("current") or {}
    if cur.get("text"):
        data.setdefault("history", []).append(cur)

    data["current"] = {"date": today, "author": author, "text": text}
    reflections_path.parent.mkdir(parents=True, exist_ok=True)
    reflections_path.write_text(json.dumps(data, indent=2))


# ─────────────────────────────────────────────────────────────────────
# Autonomous deterministic reflection (Alpha 6.x)
#
# The manual workflow above (operator pastes an LLM summary) left the
# reflection EMPTY on most days, so agents received no rule of thumb. This
# composes a deterministic 2–4 sentence rule from the day's real data —
# no LLM, fully explainable — so the learning loop is self-sustaining.
# Every clause is gated on data being present; missing inputs are skipped.
# ─────────────────────────────────────────────────────────────────────

def _rj(data_dir: Path, name: str):
    try:
        return json.loads((data_dir / name).read_text())
    except Exception:
        return None


def generate_auto_reflection(data_dir: Path) -> str:
    """Compose a deterministic end-of-day rule-of-thumb from real data.

    Reads narrative_tracker, catalyst_learning, scoring, deal_journal and the
    account states. Returns a short string suitable for injection into agent
    context. Pure/deterministic: the same inputs always yield the same text.
    """
    clauses = []

    # 1) Narrative + sector tilt -------------------------------------------
    nt = _rj(data_dir, "narrative_tracker.json") or {}
    dom = nt.get("dominant_narrative")
    shift = nt.get("regime_shift")
    sp = nt.get("sector_pressure") or {}
    if dom and (nt.get("headline_count") or 0) > 0:
        ents = sorted(((k, v) for k, v in sp.items() if abs(v) > 0.001),
                      key=lambda kv: kv[1], reverse=True)
        lead = [k for k, v in ents[:2] if v > 0]
        fade = [k for k, v in ents[-2:] if v < 0]
        nl = str(dom).replace("_", " ")
        sh = {"RISK_ON": "risk-on", "RISK_OFF": "risk-off",
              "ROTATION": "rotating", "NEUTRAL": "mixed"}.get(shift, "")
        s = f"News reads as {nl}" + (f" with the tape {sh}" if sh else "")
        if lead:
            s += f"; {', '.join(lead)} leading"
            if fade:
                s += f" and {', '.join(fade)} fading"
            s += " — favor relative strength and lighten fading sectors"
        clauses.append(s + ".")

    # 2) Volatility / catalyst gauntlet ------------------------------------
    cl = _rj(data_dir, "catalyst_learning.json") or {}
    clu = cl.get("clustering") or {}
    if clu.get("elevated_ahead"):
        macro = (cl.get("upcoming") or {}).get("macro") or []
        nearest = macro[0].get("type") if macro and isinstance(macro[0], dict) else None
        hi = (clu.get("peak_window") or {}).get("high_impact")
        s = "A higher-volatility stretch is ahead"
        if hi:
            s += f" ({hi} major catalysts cluster" + (f", nearest {nearest}" if nearest else "") + ")"
        elif nearest:
            s += f" (nearest catalyst: {nearest})"
        clauses.append(s + " — size cautiously and respect stops.")

    # 3) IPO-complex discipline --------------------------------------------
    dj = _rj(data_dir, "deal_journal.json") or {}
    for row in (dj.get("by_catalyst_class") or []):
        if row.get("catalyst_class") == "ipo_related" and row.get("win_rate") is not None:
            wr = round(row["win_rate"] * 100)
            if wr < 45 and (row.get("n") or 0) >= 5:
                clauses.append(
                    f"IPO-adjacent names have lagged ({wr}% win recently) as the market "
                    f"de-risks into the SpaceX listing — don't chase the complex.")
            break

    # 4) Clean-data discipline (always-on anchor) --------------------------
    sc = _rj(data_dir, "scoring.json") or {}
    outs = sc.get("outcomes") or []
    if outs:
        clean = [o for o in outs if not o.get("stale_price_suspected")]
        if clean:
            wins = sum(1 for o in clean if o.get("correct"))
            wr = round(100 * wins / len(clean))
            clauses.append(
                f"Only clean-data outcomes count toward learning "
                f"({len(clean)} clean, {wr}% correct so far); ignore stale-flagged reads.")

    if not clauses:
        return ""
    return " ".join(clauses[:4])


def write_auto_reflection(data_dir: Path) -> str:
    """Generate and persist the auto-reflection as the current rule of thumb.

    Preserves any prior operator-authored reflection into history (handled by
    append_reflection). Returns the text written (empty string if no data)."""
    text = generate_auto_reflection(data_dir)
    if text:
        append_reflection(data_dir / "reflections.json", text,
                           author="SILMARIL (auto)")
    return text
