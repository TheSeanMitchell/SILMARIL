"""
silmaril.handoff.deeplinks — One-click LLM handoffs.

Each supported LLM gets a deep-link builder. Where the LLM supports
pre-filling a prompt via URL parameter, we use that. Where it doesn't,
we emit a clipboard-copy + open-in-tab pattern (handled on the frontend).

The frontend reads each link's `strategy`:
  "url_param"    → clicking opens the URL directly with prompt pre-loaded
  "copy_and_go"  → clicking copies prompt to clipboard, then opens the URL

All supported LLMs are the user's own account. SILMARIL neither hosts
nor proxies any LLM call. Privacy is simple: we never see the prompt
leave the user's browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from urllib.parse import quote


@dataclass
class Handoff:
    """One LLM handoff option for a single Handoff Block."""
    llm: str                # "chatgpt" | "claude" | "gemini" | "perplexity" | "grok"
    display_name: str       # "ChatGPT", "Claude", etc.
    icon: str               # path to icon file (served from assets/icons/)
    url: str                # the target URL
    strategy: str           # "url_param" or "copy_and_go"

    def to_dict(self) -> Dict[str, str]:
        return {
            "llm": self.llm,
            "display_name": self.display_name,
            "icon": self.icon,
            "url": self.url,
            "strategy": self.strategy,
        }


def build_handoffs(prompt: str) -> List[Dict[str, str]]:
    """
    Build the full set of deep-links for a given prompt.
    Returns a list of serialized Handoff dicts, ready to embed in JSON.
    """
    encoded = quote(prompt)

    handoffs: List[Handoff] = [
        # ChatGPT: supports ?q= pre-fill via https://chatgpt.com/?q=...
        Handoff(
            llm="chatgpt",
            display_name="ChatGPT",
            icon="assets/icons/chatgpt.svg",
            url=f"https://chatgpt.com/?q={encoded}",
            strategy="url_param",
        ),
        # Claude: no reliable URL pre-fill; clipboard + open
        Handoff(
            llm="claude",
            display_name="Claude",
            icon="assets/icons/claude.svg",
            url="https://claude.ai/new",
            strategy="copy_and_go",
        ),
        # Gemini: no reliable URL pre-fill; clipboard + open
        Handoff(
            llm="gemini",
            display_name="Gemini",
            icon="assets/icons/gemini.svg",
            url="https://gemini.google.com/app",
            strategy="copy_and_go",
        ),
        # Perplexity: supports ?q= pre-fill
        Handoff(
            llm="perplexity",
            display_name="Perplexity",
            icon="assets/icons/perplexity.svg",
            url=f"https://www.perplexity.ai/?q={encoded}",
            strategy="url_param",
        ),
        # Grok: supports ?q= pre-fill on x.com/i/grok
        Handoff(
            llm="grok",
            display_name="Grok",
            icon="assets/icons/grok.svg",
            url=f"https://x.com/i/grok?text={encoded}",
            strategy="url_param",
        ),
    ]
    return [h.to_dict() for h in handoffs]
