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
