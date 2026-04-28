"""Manual multi-LLM consensus prompt builders for SILMARIL v2.

Design contract
---------------
1. Zero API calls. Every function returns a string.
2. Self-contained prompts. The external LLM sees the asset, the
   cohort, the indicators -- everything it needs to render a useful
   second opinion in one shot.
3. Token-conscious. We trim cohort detail to what matters and skip
   indicators that don't apply to the asset class.
4. Variants are short. Four flavors, each ~600-1200 tokens, so even
   free-tier daily limits don't bite.

Usage from the dashboard
------------------------
The user clicks a "Get second opinion" button on a verdict tile.
The frontend calls the appropriate builder, copies the result to
the clipboard, and the user pastes it into ChatGPT / Gemini / Grok
/ a fresh Claude tab. They paste the response back into the log
note. Done.

Variants
--------
- consensus  : "Rate the cohort's reasoning. Flag what they missed."
- red_team   : "Argue against this verdict. What's the bear case?"
- catalyst   : "Which upcoming catalyst most threatens the verdict?"
- summary    : "One-paragraph plain-English summary."
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

PROMPT_VARIANTS = ("consensus", "red_team", "catalyst", "summary")

# ----------------------------------------------------------------------
# Internal formatters
# ----------------------------------------------------------------------

_SIGNAL_MARKERS = {
    "STRONG_BUY": "++",
    "BUY": "+ ",
    "HOLD": ". ",
    "ABSTAIN": ". ",
    "SELL": "- ",
    "STRONG_SELL": "--",
}


def _fmt_pct(x, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(x, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _format_cohort(verdicts: Iterable[dict]) -> str:
    """Render the agent verdicts as compact rows, no leading indent."""
    rows = []
    for v in verdicts:
        agent = v.get("agent", "?")
        signal = v.get("signal", "HOLD")
        marker = _SIGNAL_MARKERS.get(signal, "??")
        conv = v.get("conviction", 0.0)
        rat = (v.get("rationale") or "").strip().replace("\n", " ")
        if len(rat) > 140:
            rat = rat[:137] + "..."
        rows.append(f"  [{marker}] {agent:<14} conv={conv:.2f}  {rat}")
    return "\n".join(rows) if rows else "  (no verdicts)"


def _format_indicators(market_state: dict, asset_class: str) -> str:
    """Render the technical/macro snapshot, trimmed by asset class."""
    if not market_state:
        return "  (no indicators provided)"

    lines: list[str] = []

    def add(label: str, key: str, formatter=_fmt_num):
        if key in market_state and market_state[key] is not None:
            lines.append(f"  {label:<22} {formatter(market_state[key])}")

    add("price", "price")
    add("SMA20", "sma20")
    add("SMA50", "sma50")
    add("SMA200", "sma200")
    add("RSI(14)", "rsi14")
    add("ATR(14)", "atr14")
    add("Bollinger width", "bb_width", _fmt_pct)
    add("MACD histogram", "macd_hist")
    add("20d momentum", "momentum_20d", _fmt_pct)
    add("20d volatility", "volatility_20d", _fmt_pct)

    if asset_class in {"equity", "etf"}:
        add("VIX", "vix")
        add("10Y yield", "tnx", _fmt_pct)
        add("SPY 20d momentum", "spy_mom_20d", _fmt_pct)
    elif asset_class == "crypto":
        add("BTC dominance", "btc_dominance", _fmt_pct)
        add("funding rate", "funding_rate", _fmt_pct)
    elif asset_class == "fx":
        add("DXY", "dxy")

    return "\n".join(lines) if lines else "  (no indicators provided)"


def _format_catalysts(catalysts: Iterable[dict] | None) -> str:
    if not catalysts:
        return "  (no upcoming catalysts in window)"
    rows = []
    for c in catalysts:
        date = c.get("date", "?")
        ctype = c.get("type", "?")
        title = (c.get("title") or "").strip()
        if len(title) > 100:
            title = title[:97] + "..."
        rows.append(f"  {date} [{ctype}] {title}")
    return "\n".join(rows)


def _header(ticker: str, asset_class: str, regime: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"Ticker: {ticker}\n"
        f"Asset class: {asset_class}\n"
        f"Date (UTC): {today}\n"
        f"Detected regime: {regime}\n"
    )


# ----------------------------------------------------------------------
# Public prompt builders
# ----------------------------------------------------------------------

def build_consensus_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    market_state: dict | None = None,
    catalysts: Iterable[dict] | None = None,
    cohort_signal: str | None = None,
    cohort_score: float | None = None,
) -> str:
    """The 'rate the cohort' prompt -- primary use case."""

    cohort_line = ""
    if cohort_signal:
        cohort_line = f"Cohort verdict: {cohort_signal}"
        if cohort_score is not None:
            cohort_line += f" (composite score {cohort_score:+.2f})"
        cohort_line += "\n"

    parts = [
        "You are reviewing the output of SILMARIL, a multi-agent trading",
        "decision system. Below is the live state of the asset, the verdicts",
        "of every agent in the cohort, and the upcoming catalysts in the",
        "next two weeks. Your job is to rate the cohort's collective",
        "reasoning and tell us what they missed.",
        "",
        "Be concise. Be honest. We don't want a hedge-everything answer.",
        "",
        "===== ASSET SNAPSHOT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line.rstrip("\n"))
    parts += [
        "",
        "===== INDICATORS =====",
        _format_indicators(market_state or {}, asset_class),
        "",
        "===== AGENT COHORT VERDICTS =====",
        "Signal key:  ++ STRONG_BUY   + BUY   . HOLD/ABSTAIN   - SELL   -- STRONG_SELL",
        "",
        _format_cohort(verdicts),
        "",
        "===== UPCOMING CATALYSTS (next ~14 days) =====",
        _format_catalysts(catalysts),
        "",
        "===== YOUR TASK =====",
        "Answer in this exact format:",
        "",
        "1) STRONGEST_AGENT: <name> -- one sentence why their reasoning is the most defensible.",
        "2) WEAKEST_AGENT:   <name> -- one sentence why their reasoning is suspect.",
        "3) MISSING_ANGLE:   <1-3 bullet points> -- things no agent considered.",
        "4) RISK_FLAG:       <a single specific risk to the cohort verdict>.",
        "5) YOUR_CALL:       <STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL> with confidence 0.00-1.00.",
        "6) ONE_LINE_REASON: <one sentence summary of your call>.",
        "",
        "Do not add any text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_red_team_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    market_state: dict | None = None,
    catalysts: Iterable[dict] | None = None,
    cohort_signal: str | None = None,
) -> str:
    """The adversarial prompt -- make the LLM argue the other side."""

    cohort_line = f"Cohort verdict: {cohort_signal}" if cohort_signal else ""

    parts = [
        "You are the red team for SILMARIL, a multi-agent trading system.",
        "The cohort below has reached a verdict. Your only job is to argue",
        "against it as strongly and specifically as you can. Do not hedge.",
        "Do not give a balanced view. Find the cracks.",
        "",
        "===== ASSET SNAPSHOT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line)
    parts += [
        "",
        "===== INDICATORS =====",
        _format_indicators(market_state or {}, asset_class),
        "",
        "===== AGENT COHORT VERDICTS =====",
        _format_cohort(verdicts),
        "",
        "===== UPCOMING CATALYSTS =====",
        _format_catalysts(catalysts),
        "",
        "===== YOUR TASK =====",
        "Build the strongest possible counter-case to the cohort's verdict.",
        "Format:",
        "",
        "1) THESIS_AGAINST: One paragraph (4 sentences max) stating why",
        "   the cohort is wrong.",
        "2) THREE_FACTS:    Three specific data points or facts that",
        "   support the counter-case. Cite from the indicator snapshot",
        "   or catalyst list above when possible.",
        "3) WHAT_WOULD_PROVE_YOU_RIGHT: One concrete observable that, if",
        "   it happened in the next 5 trading days, would confirm the",
        "   counter-case.",
        "4) WHAT_WOULD_PROVE_YOU_WRONG: One observable that would kill",
        "   the counter-case.",
        "",
        "Do not add text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_catalyst_review_prompt(
    ticker: str,
    asset_class: str,
    catalysts: Iterable[dict],
    cohort_signal: str | None = None,
) -> str:
    """Catalyst-focused review -- which event most threatens the verdict."""

    cat_list = list(catalysts)
    if not cat_list:
        return (
            f"No upcoming catalysts found for {ticker} in the next 14 days.\n"
            f"Cohort verdict: {cohort_signal or 'unspecified'}.\n"
            "Question: is there a known event in the wider market in the next\n"
            "two weeks that should make us reconsider this verdict?\n"
            "Answer in 3 sentences max.\n"
        )

    cohort_line = f"Cohort verdict: {cohort_signal}" if cohort_signal else ""
    parts = [
        f"Review the upcoming catalysts for {ticker} ({asset_class}) and rank",
        "them by how strongly each could invalidate the cohort verdict.",
        "Be specific.",
        "",
    ]
    if cohort_line:
        parts.append(cohort_line)
        parts.append("")
    parts += [
        "===== UPCOMING CATALYSTS =====",
        _format_catalysts(cat_list),
        "",
        "===== YOUR TASK =====",
        "Answer in this format:",
        "",
        "1) MOST_DANGEROUS:   <date + event> -- one sentence on why.",
        "2) SECOND_DANGEROUS: <date + event> -- one sentence on why.",
        "3) IGNORE:           <date + event or 'none'> -- events the",
        "   cohort can safely disregard.",
        "4) HEDGE_IDEA:       One concrete way to hedge against the most",
        "   dangerous event without exiting the position.",
        "",
        "Do not add text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_summary_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    cohort_signal: str | None = None,
    cohort_score: float | None = None,
) -> str:
    """Plain-English one-paragraph summary -- cheapest prompt."""

    cohort_line = ""
    if cohort_signal:
        cohort_line = f"Cohort verdict: {cohort_signal}"
        if cohort_score is not None:
            cohort_line += f" (composite score {cohort_score:+.2f})"

    parts = [
        "Translate this trading decision into one paragraph a smart",
        "non-trader could understand. No jargon. No bullet points. No",
        "disclaimers. 4-5 sentences.",
        "",
        "===== INPUT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line)
    parts += [
        "",
        "Agents that voted:",
        _format_cohort(verdicts),
        "",
        "Write the paragraph now.",
        "",
    ]
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Self-check
# ----------------------------------------------------------------------

if __name__ == "__main__":
    sample_verdicts = [
        {
            "agent": "AEGIS",
            "signal": "BUY",
            "conviction": 0.72,
            "rationale": "Price above all three SMAs, RSI 58, bullish MACD cross last week.",
        },
        {
            "agent": "FORGE",
            "signal": "BUY",
            "conviction": 0.65,
            "rationale": "Breakout above 50-day high on rising volume.",
        },
        {
            "agent": "KESTREL+",
            "signal": "ABSTAIN",
            "conviction": 0.0,
            "rationale": "Hurst 0.58 - trender, mean-reversion logic does not apply.",
        },
        {
            "agent": "ATLAS",
            "signal": "HOLD",
            "conviction": 0.4,
            "rationale": "Macro neutral, VIX 18, 10Y stable. No tilt.",
        },
    ]
    sample_state = {
        "price": 432.10,
        "sma20": 425.0,
        "sma50": 418.0,
        "sma200": 401.0,
        "rsi14": 58.2,
        "atr14": 6.4,
        "bb_width": 0.034,
        "macd_hist": 1.2,
        "momentum_20d": 0.041,
        "volatility_20d": 0.011,
        "vix": 18.1,
        "tnx": 0.0421,
        "spy_mom_20d": 0.025,
    }
    sample_cats = [
        {"date": "2026-05-01", "type": "earnings", "title": "Q1 earnings, AMC, consensus EPS $2.18"},
        {"date": "2026-05-07", "type": "fomc", "title": "FOMC rate decision"},
        {"date": "2026-05-15", "type": "opex", "title": "Monthly options expiration"},
    ]

    for variant in PROMPT_VARIANTS:
        print(f"\n{'=' * 60}")
        print(f"VARIANT: {variant}")
        print(f"{'=' * 60}\n")
        if variant == "consensus":
            print(build_consensus_prompt("SPY", "etf", "BULL", sample_verdicts,
                                         sample_state, sample_cats, "BUY", 0.62))
        elif variant == "red_team":
            print(build_red_team_prompt("SPY", "etf", "BULL", sample_verdicts,
                                        sample_state, sample_cats, "BUY"))
        elif variant == "catalyst":
            print(build_catalyst_review_prompt("SPY", "etf", sample_cats, "BUY"))
        elif variant == "summary":
            print(build_summary_prompt("SPY", "etf", "BULL", sample_verdicts, "BUY", 0.62))
