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

    Strategy field tells the frontend whether the LLM accepts a URL-param
    pre-fill (instant) or whether the user must paste from clipboard.
    """
    encoded = quote(prompt)

    handoffs: List[Handoff] = [
        # ── Tier 1: full URL pre-fill ────────────────────────────
        Handoff(
            llm="chatgpt", display_name="ChatGPT",
            icon="assets/icons/chatgpt.svg",
            url=f"https://chatgpt.com/?q={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="perplexity", display_name="Perplexity",
            icon="assets/icons/perplexity.svg",
            url=f"https://www.perplexity.ai/?q={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="grok", display_name="Grok",
            icon="assets/icons/grok.svg",
            url=f"https://x.com/i/grok?text={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="duckai", display_name="DuckDuckGo AI",
            icon="assets/icons/duckai.svg",
            url=f"https://duckduckgo.com/?q={encoded}&ia=chat",
            strategy="url_param",
        ),

        # ── Tier 2: copy-and-go (open homepage, paste from clipboard) ─
        Handoff(
            llm="claude", display_name="Claude",
            icon="assets/icons/claude.svg",
            url="https://claude.ai/new",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="gemini", display_name="Gemini",
            icon="assets/icons/gemini.svg",
            url="https://gemini.google.com/app",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="copilot", display_name="Copilot",
            icon="assets/icons/copilot.svg",
            url="https://copilot.microsoft.com/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="meta_ai", display_name="Meta AI",
            icon="assets/icons/meta.svg",
            url="https://www.meta.ai/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="mistral", display_name="Le Chat",
            icon="assets/icons/mistral.svg",
            url="https://chat.mistral.ai/chat",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="deepseek", display_name="DeepSeek",
            icon="assets/icons/deepseek.svg",
            url="https://chat.deepseek.com/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="qwen", display_name="Qwen",
            icon="assets/icons/qwen.svg",
            url="https://chat.qwen.ai/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="kimi", display_name="Kimi",
            icon="assets/icons/kimi.svg",
            url="https://www.kimi.com/",
            strategy="copy_and_go",
        ),
    ]
    return [h.to_dict() for h in handoffs]
