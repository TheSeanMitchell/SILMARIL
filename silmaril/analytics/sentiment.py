"""
silmaril.analytics.sentiment — Lexicon + phrase + event-tag scoring.

Zero LLM calls. Zero external service. Pure deterministic pattern matching
over a finance-tuned vocabulary. Three layers, each more specific than the last:

  1. WORDS    — single-token polarity (beat, plunge, ...), strong terms count 2x.
  2. PHRASES  — multi-word buy/sell signals ("raised guidance", "cut to sell",
                "profit warning", "price target raised"). Phrases are where the
                real directional signal lives; they outweigh single words.
  3. EVENTS   — classify WHAT the headline is about (earnings, guidance, analyst
                rating, M&A, legal/regulatory, product, leadership, capital
                return, clinical, macro). Tags drive the briefing's "how the news
                moved" view and are available to downstream tagging/learning.

Backward compatible: score_text() and aggregate_ticker_sentiment() keep their
original signatures and meaning; they just see more vocabulary now.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Layer 1 — single-word lexicon
POSITIVE = {
    "beat", "beats", "beating", "smashed", "crushed", "exceeded", "topped", "tops",
    "record", "all-time-high", "ath", "milestone", "highs",
    "surge", "surges", "surging", "soared", "soars", "jumped", "jumps", "spike", "spikes",
    "rally", "rallies", "rallied", "rebound", "rebounds", "rebounded", "recovers", "recovery",
    "strong", "stronger", "strongest", "robust", "solid", "outperform", "outperformed", "outperforms",
    "upgrade", "upgraded", "upgrades", "upbeat", "bullish", "optimistic", "confidence",
    "profit", "profits", "profitable", "growth", "growing", "expansion", "accelerating",
    "launch", "launched", "launches", "breakthrough", "innovative", "unveils", "unveiled",
    "partnership", "partners", "deal", "wins", "won", "secures", "secured", "awarded",
    "acquired", "acquires", "acquisition", "approved", "approval", "cleared", "greenlight",
    "raised", "raises", "raising", "lifted", "boosted", "boosts", "buyback", "repurchase",
    "dividend", "expands", "expanding", "demand", "momentum", "tailwind", "tailwinds",
    "blowout", "stellar", "surpassed", "surpasses",
}

NEGATIVE = {
    "miss", "missed", "misses", "missing", "disappointed", "disappointing", "disappoints",
    "plunge", "plunged", "plunges", "tumble", "tumbled", "tumbles", "sink", "sinks", "sinking",
    "slump", "slumped", "slumps", "crash", "crashed", "crashes", "collapse", "collapsed",
    "drop", "dropped", "drops", "fall", "fell", "falls", "falling", "decline", "declined", "declines",
    "weak", "weaker", "weakest", "soft", "softer", "sluggish", "underperform", "underperformed",
    "downgrade", "downgraded", "downgrades", "bearish", "pessimistic", "caution", "cautious",
    "loss", "losses", "losing", "loses", "unprofitable", "writedown", "impairment",
    "layoff", "layoffs", "cut", "cuts", "cutting", "slashed", "slashes", "slash", "halve",
    "investigation", "lawsuit", "sued", "sues", "fraud", "scandal", "misconduct",
    "recall", "recalled", "halted", "halt", "warning", "warned", "warns", "warn",
    "probe", "subpoena", "scrutiny", "fine", "fined", "penalty", "sanction", "sanctioned",
    "lowered", "lowers", "reduced", "reduces", "suspends", "suspended", "delays", "delayed",
    "recession", "inflation", "selloff", "sell-off", "panic", "fears", "headwind", "headwinds",
    "bankruptcy", "default", "downturn", "glut", "oversupply", "shortfall",
}

NEGATORS = {"not", "no", "never", "without", "avoid", "avoided", "fails", "failed", "failing", "fail"}

STRONG_POSITIVE = {
    "smashed", "crushed", "soared", "soars", "surge", "surges", "surging", "spike", "blowout",
    "record", "breakthrough", "all-time-high", "ath", "milestone", "stellar", "surpassed",
}
STRONG_NEGATIVE = {
    "plunge", "plunged", "plunges", "crash", "crashed", "crashes", "collapse", "collapsed",
    "fraud", "scandal", "halted", "investigation", "lawsuit", "subpoena", "recall", "bankruptcy",
}

# Layer 2 — multi-word phrases (regex, weight in word-equivalents)
_P = re.compile
POSITIVE_PHRASES: List[Tuple["re.Pattern", float]] = [
    # vocab round 5 (Alpha 0.007) — commodities / crypto / macro
    (_P(r"\b(rally|rallies|rallying|surge[sd]?|soar(s|ed)?)\b"), 1.5),
    (_P(r"\bsafe.?haven (bid|demand|buying)\b"), 2.0),
    (_P(r"\b(etf|fund) inflows?\b"), 2.0),
    (_P(r"\binventory (draw|drawdown)\b"), 2.0),
    (_P(r"\b(opec\+? (cut|cuts|curbs)|supply (cut|disruption))\b"), 2.0),
    (_P(r"\b(halving|hash.?rate (record|high)|institutional adoption)\b"), 1.8),
    (_P(r"\brate cut (hopes?|bets?|expectations?)\b"), 1.5),
    # vocab round 4 (Alpha 0.007) — IPO debut tape
    (_P(r"\b(opens?|opened|indicated to open)\s+(sharply\s+)?(higher|above)\b"), 2.0),
    (_P(r"\bpops?\s+\d{1,3}\s*%"), 2.0),
    (_P(r"\b(oversubscribed|order book .{0,12}covered)\b"), 2.5),
    (_P(r"\babove (the )?(ipo|issue|offer) price\b"), 2.0),
    (_P(r"\bmost.active|record (debut|volume)\b"), 1.5),
    # vocab round 3 — options flow
    (_P(r"\b(unusual|heavy|aggressive)\s+call\s+(buying|activity|volume)\b"), 2.0),
    (_P(r"\b(call sweeps?|bullish (options? )?flow)\b"), 2.0),
    # vocab round 3 — holders / 13F language
    (_P(r"\b(rais(e|es|ed)|boost(s|ed)?|increas(e|es|ed)|builds?|built)[^.]{0,14}\bstakes?\b"), 2.5),
    (_P(r"\b(discloses?|reveals?|takes?)[^.]{0,12}\b(new |activist )?(stake|position)\b"), 2.5),
    # vocab round 3 — supply chain
    (_P(r"\b(ramps?( up)?|expand(s|ing)?|boost(s|ing)?)[^.]{0,14}\b(production|capacity|output)\b"), 2.0),
    (_P(r"\bsupply (chain )?(constraints?|pressures?|issues?)\s+(eas(e|es|ing)|improv(e|es|ing))\b"), 2.0),
    (_P(r"\bresum(e|es|ed|ing)\s+(production|operations|shipments?)\b"), 2.0),
    (_P(r"\b(ceo|cfo|chairman|director|insider)s?[^.]{0,18}\b(buys?|bought|purchas(e|es|ed))\b[^.]{0,14}(shares?|stock)\b"), 2.5),
    (_P(r"\b(added to|joins?|inclusion in)[^.]{0,16}\b(s&p ?500|nasdaq[- ]?100|russell|dow|index)\b"), 2.5),
    (_P(r"\b(initiates?|declares? first)\s+dividend\b"), 2.0),
    (_P(r"\b(announces?|plans?|approves?)[^.]{0,12}\bstock split\b"), 2.0),
    (_P(r"\b(ipo|debut|listing)[^.]{0,22}\b(above (the )?range|oversubscribed|raises? (the )?range|prices? above)\b"), 3.0),
    (_P(r"\b(multi[- ]?year|landmark|record|major)\s+(contract|order|deal)\b"), 2.0),
    (_P(r"\b(beat|top(s|ped)?|exceed(s|ed)?|above)\s+(estimates|expectations|forecasts?|views?)\b"), 2.5),
    (_P(r"\b(rais(e|es|ed)|hik(e|es|ed)|boost(s|ed)?|lift(s|ed)?)\s+(guidance|outlook|forecast|target|estimates?)\b"), 3.0),
    (_P(r"\bguides?\s+(higher|above|up)\b"), 3.0),
    (_P(r"\b(price target|pt)\s+(rais(e|ed)|hik(e|ed)|increase[d]?|up)\b"), 2.5),
    (_P(r"\b(upgrad(e|es|ed)|initiat(e|es|ed)|rais(e|es|ed))[^.]{0,18}\b(buy|overweight|outperform)\b"), 3.0),
    (_P(r"\b(double upgrade|top pick|best idea|conviction buy)\b"), 3.0),
    (_P(r"\b(record)\s+(revenue|profit|earnings|sales|quarter|backlog)\b"), 3.0),
    (_P(r"\b(share )?(buyback|repurchase)\b"), 2.0),
    (_P(r"\b(rais(e|es|ed)|hik(e|es|ed)|increas(e|es|ed)|special)\s+dividend\b"), 2.0),
    (_P(r"\b(wins?|secur(e|es|ed)|land(s|ed)?|award(ed)?)[^.]{0,18}\b(contract|deal|order|approval)\b"), 2.5),
    (_P(r"\b(fda|regulatory)\s+(approval|clears?|cleared|approves?)\b"), 3.0),
    (_P(r"\b(phase\s*3|pivotal)[^.]{0,18}\b(success|met|positive|hit)\b"), 3.0),
    (_P(r"\b(strong|robust|surging|accelerating)\s+demand\b"), 2.0),
]
NEGATIVE_PHRASES: List[Tuple["re.Pattern", float]] = [
    # vocab round 5 (Alpha 0.007) — commodities / crypto / macro
    (_P(r"\b(plunge[sd]?|tumble[sd]?|slump[sd]?|crater(s|ed)?)\b"), 1.5),
    (_P(r"\b(etf|fund) outflows?\b"), 2.0),
    (_P(r"\binventory build\b"), 2.0),
    (_P(r"\b(demand (worries|concerns|slowdown)|glut)\b"), 1.8),
    (_P(r"\b(depeg(ged|s)?|exchange hack|liquidation cascade)\b"), 2.5),
    (_P(r"\bsafe.?haven (unwind|selling)\b"), 1.8),
    # vocab round 4 (Alpha 0.007) — IPO debut tape
    (_P(r"\bbreaks? (the )?(ipo|issue|offer) price\b"), 2.5),
    (_P(r"\bbelow (the )?(ipo|issue|offer) price\b"), 2.0),
    (_P(r"\b(opens?|opened|indicated to open)\s+(sharply\s+)?(lower|below)\b"), 2.0),
    (_P(r"\b(lock.?up (expiry|expiration)|insiders? (can|free to) sell)\b"), 1.5),
    (_P(r"\bhalted (for|on) volatility\b"), 1.5),
    # vocab round 3 — options flow
    (_P(r"\b(unusual|heavy|aggressive)\s+put\s+(buying|activity|volume)\b"), 2.0),
    (_P(r"\b(put sweeps?|bearish (options? )?flow)\b"), 2.0),
    # vocab round 3 — holders / 13F language
    (_P(r"\b(cut(s)?|trims?|trimmed|slash(es|ed)?|reduc(e|es|ed))[^.]{0,14}\bstakes?\b"), 2.5),
    (_P(r"\b(exit(s|ed)?|dump(s|ed)?|sold|sells?)[^.]{0,12}\b(entire |whole )?(stake|position)\b"), 2.5),
    # vocab round 3 — supply chain
    (_P(r"\b(halts?|suspend(s|ed)?|shut(s)? down|idles?)[^.]{0,14}\b(production|plant|operations|factory)\b"), 2.5),
    (_P(r"\bsupply (chain )?(disruption|woes|crunch|snarls?|bottlenecks?)\b"), 2.0),
    (_P(r"\b(chip|parts?|component|labor)\s+shortage\b"), 2.0),
    (_P(r"\b(inventory (glut|correction|overhang)|channel inventory)\b"), 2.0),
    (_P(r"\b(ceo|cfo|chairman|director|insider)s?[^.]{0,18}\b(sells?|sold|dump(s|ed)?|unload(s|ed)?)\b[^.]{0,14}(shares?|stock)\b"), 2.5),
    (_P(r"\b(short[- ]?seller|hindenburg|muddy waters|citron|grizzly)[^.]{0,24}\b(report|target|alleg|attack)"), 3.0),
    (_P(r"\b(removed|dropped|deleted)\s+from[^.]{0,16}\b(s&p|nasdaq|russell|dow|index)\b"), 2.5),
    (_P(r"\b(secondary|share|equity|stock)\s+offering\b|\bdilut(ion|ive)\b"), 2.5),
    (_P(r"\b(moody'?s|fitch|s&p)[^.]{0,18}\bdowngrad|\bcredit (rating )?downgrade\b"), 2.5),
    (_P(r"\b(data breach|cyber ?attack|ransomware|hacked)\b"), 2.5),
    (_P(r"\b(workers?|labor|union)[^.]{0,12}\b(strike|walkout)\b"), 2.0),
    (_P(r"\b(withdraws?|pull(s|ed)?|suspends?)[^.]{0,12}\b(guidance|outlook|forecast)\b"), 3.0),
    (_P(r"\b(ipo|debut|listing)[^.]{0,22}\b(below (the )?range|cuts? (the )?range|delay(s|ed)?|postpon(e|es|ed))\b"), 3.0),
    (_P(r"\b(miss(es|ed)?|below|short of|fell short)\s+(estimates|expectations|forecasts?|views?)\b"), 2.5),
    (_P(r"\b(cut(s|ting)?|lower(s|ed)?|slash(es|ed)?|reduc(e|es|ed)|trim(s|med)?)\s+(guidance|outlook|forecast|estimates?|target)\b"), 3.0),
    (_P(r"\bguides?\s+(lower|below|down)\b"), 3.0),
    (_P(r"\bprofit\s+warning\b"), 3.5),
    (_P(r"\b(price target|pt)\s+(cut|lower(ed)?|reduc(e|ed)|slash(ed)?|down)\b"), 2.5),
    (_P(r"\b(downgrad(e|es|ed)|cut|initiat(e|es|ed)|lower(s|ed)?)[^.]{0,18}\b(sell|underweight|underperform|neutral|hold)\b"), 3.0),
    (_P(r"\b(going concern|chapter 11|bankrupt(cy)?|delist(ing|ed)?|default)\b"), 3.5),
    (_P(r"\b(cut|suspend(s|ed)?|eliminat(e|es|ed)|slash(es|ed)?)\s+(its )?dividend\b"), 2.5),
    (_P(r"\b(sec|ftc|doj|antitrust|regulator[sy]?)\s+(prob(e|es)|investigat|sue[sd]?|charge[sd]?|fine[sd]?)\b"), 3.0),
    (_P(r"\b(fda)\s+(reject(s|ed)?|declin(e|es|ed)|crl|complete response)\b"), 3.5),
    (_P(r"\b(clinical|trial)\s+(hold|fail(s|ed|ure)?|miss(es|ed)?)\b"), 3.0),
    (_P(r"\b(recall(s|ed)?|safety probe)\b"), 2.5),
    (_P(r"\b(weak|soft|slowing|declining|falling)\s+demand\b"), 2.5),
    (_P(r"\b(ceo|cfo|coo|founder)\s+(resign(s|ed)?|step(s|ped)? down|out|depart(s|ed|ure)?|fired)\b"), 2.0),
]

# Layer 3 — event-type tagging
EVENT_PATTERNS: Dict[str, List["re.Pattern"]] = {
    "insider":    [_P(r"\b(insider|10b5-1|form 4)\b|\b(ceo|cfo|chairman|director)s?[^.]{0,18}\b(buys?|bought|sells?|sold)\b")],
    "index":      [_P(r"\b(s&p ?500|nasdaq[- ]?100|russell ?[12]000|dow jones|index (inclusion|add|removal))\b")],
    "short_report":[_P(r"\b(short[- ]?seller|hindenburg|muddy waters|citron|grizzly|short report)\b")],
    "security":   [_P(r"\b(data breach|cyber ?attack|ransomware|hacked|hack)\b")],
    "ipo":        [_P(r"\b(ipo|public debut|going public|lists? on (the )?(nyse|nasdaq)|direct listing)\b")],
    "earnings":   [_P(r"\b(earnings|eps|revenue|results|q[1-4]\b|quarter(ly)?|top[- ]?line|bottom[- ]?line|profit|sales)\b")],
    "guidance":   [_P(r"\b(guidance|outlook|forecast|guides?|full[- ]?year|fy\d{2}|raises view|cuts view)\b")],
    "analyst":    [_P(r"\b(upgrad|downgrad|price target|\bpt\b|initiat|reiterat|overweight|underweight|outperform|underperform|buy rating|sell rating|analyst|coverage)\b")],
    "m_and_a":    [_P(r"\b(acqui|merger|merge[sd]?|buyout|takeover|stake|deal to buy|in talks|bid for|tender offer|spin[- ]?off|divest)\b")],
    "legal_reg":  [_P(r"\b(lawsuit|sued|sues|investigation|prob(e|es)|subpoena|sec\b|ftc|doj|antitrust|fine[sd]?|settle(ment|s|d)?|fraud|recall|regulator|sanction)\b")],
    "product":    [_P(r"\b(launch|unveil|introduc|partnership|partners|collaborat|contract|integrat|rollout|chip|model|platform|product)\b")],
    "leadership": [_P(r"\b(ceo|cfo|coo|chairman|founder|appoint|names?\b|resign|steps down|hire[sd]?|board)\b")],
    "capital":    [_P(r"\b(buyback|repurchase|dividend|split|offering|raises? capital|debt|refinanc)\b")],
    "clinical":   [_P(r"\b(fda|phase\s*[123]|trial|drug|therapy|clinical|approval|crl)\b")],
    "macro":      [_P(r"\b(fed|fomc|rate(s)?|inflation|cpi|ppi|jobs|payroll|gdp|tariff|recession|treasury|yield|dollar)\b")],
}

# ── anticipation tier: FORWARD-LOOKING language (prediction fuel) ─────
# These phrases speak about what is EXPECTED to happen, not what happened.
# Signed weight: + bullish anticipation, - bearish anticipation. Scores feed
# news_history per day per stock — the raw word-based feature for prediction
# models (most shops predict with numbers; our ethos is predicting with words
# and using numbers only to act).
ANTICIPATION_PHRASES = [
    (_P(r"\b(expected|likely|poised|set|on track)\s+to\s+(beat|top|exceed|rise|rally|surge|jump|gain|outperform)\b"), 1.0),
    (_P(r"\b(expected|likely|poised|set|on track)\s+to\s+(miss|fall|drop|decline|disappoint|underperform)\b"), -1.0),
    (_P(r"\b(could|may|might)\s+(surge|soar|rally|jump|double|rebound|break ?out)\b"), 0.8),
    (_P(r"\b(could|may|might)\s+(plunge|crash|tumble|sink|stall|slide)\b"), -0.8),
    (_P(r"\banalysts?\s+(see|expect|forecast|project)[^.]{0,18}\b(upside|gains?|growth|beat)\b"), 0.9),
    (_P(r"\banalysts?\s+(see|expect|forecast|project)[^.]{0,18}\b(downside|losses?|weakness|miss)\b"), -0.9),
    (_P(r"\b(ahead of|braces? for|countdown to|eyes|awaits?)[^.]{0,14}\b(earnings|results|fomc|fed|cpi|ipo|debut|launch|decision)\b"), 0.15),
    (_P(r"\b(price target implies|implies upside|room to run|undervalued)\b"), 0.8),
    (_P(r"\b(overvalued|priced for perfection|stretched valuation|due for a pullback|risk of)\b"), -0.7),
    (_P(r"\b(buy the dip|buying opportunity|attractive entry)\b"), 0.7),
    (_P(r"\b(take profits|sell into strength|time to trim)\b"), -0.7),
]


def anticipation_score(text: str) -> float:
    """Signed forward-looking score in [-1,1] for one headline; 0 = no
    anticipation language. Captures EXPECTATION, distinct from sentiment
    about what already happened."""
    if not text:
        return 0.0
    tl = text.lower()
    hits = [w for pat, w in ANTICIPATION_PHRASES if pat.search(tl)]
    if not hits:
        return 0.0
    s = sum(hits) / len(hits)
    return max(-1.0, min(1.0, round(s, 3)))


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z\-']+")


def _phrase_hits(text_l: str) -> Tuple[float, float]:
    pos = sum(w for pat, w in POSITIVE_PHRASES if pat.search(text_l))
    neg = sum(w for pat, w in NEGATIVE_PHRASES if pat.search(text_l))
    return pos, neg


def score_text(text: str) -> float:
    """Sentiment score in [-1.0, +1.0]. Phrases (layer 2) folded in with words (layer 1)."""
    if not text:
        return 0.0
    text_l = text.lower()
    words = [w.lower() for w in _WORD_RE.findall(text)]
    pos_hits, neg_hits = _phrase_hits(text_l)
    for i, word in enumerate(words):
        negated = any(words[j] in NEGATORS for j in (i - 1, i - 2) if j >= 0)
        if word in POSITIVE:
            weight = 2.0 if word in STRONG_POSITIVE else 1.0
            if negated:
                neg_hits += weight
            else:
                pos_hits += weight
        elif word in NEGATIVE:
            weight = 2.0 if word in STRONG_NEGATIVE else 1.0
            if negated:
                pos_hits += weight
            else:
                neg_hits += weight
    if pos_hits == 0 and neg_hits == 0:
        return 0.0
    return (pos_hits - neg_hits) / (pos_hits + neg_hits)


def tag_events(text: str) -> List[str]:
    """Event-type tags a headline matches (earnings, analyst, m_and_a, ...)."""
    if not text:
        return []
    text_l = text.lower()
    return [ev for ev, pats in EVENT_PATTERNS.items() if any(p.search(text_l) for p in pats)]


def tag_headline(text: str) -> Dict[str, object]:
    """Per-headline {score, direction, events} — enriches recent_headlines."""
    s = score_text(text)
    a = anticipation_score(text)
    return {"score": round(s, 3),
            "direction": "+" if s > 0.12 else "-" if s < -0.12 else "0",
            "anticipation": (a if a else None),
            "events": tag_events(text)}


# ── catalyst detection ───────────────────────────────────────────────
# A "catalyst" is a single decisive, directional event — the kind that moves a
# stock in a day on its own (an analyst rating change, a guidance cut/raise, a
# profit warning, M&A, an FDA decision, a dividend action). We surface it so a
# lone decisive headline isn't averaged away by neutral filler around it.
STRONG_PHRASE_MIN = 2.5


def _strong_phrase_signal(text_l: str) -> float:
    """Signed magnitude of the strongest directional PHRASE in a headline
    (>= STRONG_PHRASE_MIN). 0.0 if none. Positive = bullish phrase, negative = bearish."""
    pos = max((w for pat, w in POSITIVE_PHRASES if w >= STRONG_PHRASE_MIN and pat.search(text_l)),
              default=0.0)
    neg = max((w for pat, w in NEGATIVE_PHRASES if w >= STRONG_PHRASE_MIN and pat.search(text_l)),
              default=0.0)
    if pos == 0.0 and neg == 0.0:
        return 0.0
    return pos if pos >= neg else -neg


def _catalyst_label(text: str, score: float) -> str:
    """Human label for a catalyst headline, from its dominant event + direction."""
    evs = tag_events(text)
    up = score >= 0
    if "short_report" in evs: return "short-seller attack"
    if "insider" in evs:   return "insider buying" if up else "insider selling"
    if "index" in evs:     return "index inclusion" if up else "index removal"
    if "ipo" in evs:       return "IPO strength" if up else "IPO weakness"
    if "security" in evs and not up: return "cyber incident"
    if "analyst" in evs:   return "analyst upgrade" if up else "analyst downgrade"
    if "guidance" in evs:  return "guidance raised" if up else "guidance cut"
    if "m_and_a" in evs:   return "M&A / takeover"
    if "clinical" in evs:  return "FDA/trial win" if up else "FDA/trial setback"
    if "capital" in evs:   return "buyback / dividend raise" if up else "dividend / capital cut"
    if "earnings" in evs:  return "earnings beat" if up else "earnings miss"
    if "legal_reg" in evs: return "regulatory positive" if up else "legal / regulatory hit"
    return "positive catalyst" if up else "negative catalyst"


def aggregate_ticker_sentiment(article_titles: List[str]) -> Tuple[float, int]:
    """Backward-compatible: (avg_score, article_count)."""
    scores = [score_text(t) for t in article_titles if t]
    if not scores:
        return 0.0, 0
    return sum(scores) / len(scores), len(scores)


_FIN_CONTEXT = ("stock", "shares", "earnings", "revenue", "guidance",
                "price target", "analyst", "upgrade", "downgrade", "dividend",
                "market", "trading", "nasdaq", "nyse", "ipo", "merger",
                "acquisition", "ceo", "quarterly", "forecast", "outlook",
                "buyback", "sec", "etf", "rally", "selloff", "valuation")
_AMBIGUOUS_TICKERS = {"A", "ALL", "SO", "KEY", "ON", "IT", "BY", "ANY",
                      "NOW", "REAL", "NICE", "FAST", "PLAY", "OPEN", "LOVE",
                      "COST", "CAT", "GAP", "SEE", "BRO", "WELL", "MAIN"}


def headline_relevance(title: str, ticker: str) -> float:
    """0.0 = almost certainly NOT about this stock (same-name collision),
    1.0 = explicit ($TKR / (TKR) / exchange tag), 0.6 = ticker token plus
    finance context. Ambiguous common-word tickers need the explicit form or
    heavy context — 'Key West vacation deals' must never feed KEY's read."""
    if not title or not ticker:
        return 0.0
    t = ticker.upper()
    import re as _re
    if _re.search(rf"(\${t}\b|\({t}\)|(NYSE|NASDAQ)[:\s]+{t}\b)", title,
                  _re.I):
        return 1.0
    if not _re.search(rf"\b{_re.escape(t)}\b", title):
        # ticker absent as an uppercase token — provider tagged it
        low = title.lower()
        ctx0 = sum(1 for k in _FIN_CONTEXT if k in low)
        if t in _AMBIGUOUS_TICKERS:
            # 'Key West vacation deals' must never feed KEY's read
            return 0.4 if ctx0 >= 2 else 0.0
        return 0.6 if ctx0 else 0.4
    low = title.lower()
    ctx = sum(1 for k in _FIN_CONTEXT if k in low)
    if t in _AMBIGUOUS_TICKERS:
        return 0.6 if ctx >= 2 else 0.0
    return 0.6 if ctx >= 1 else 0.3


_SRC_W_CACHE = {"mtime": None, "w": {}}


def _source_weight(name) -> float:
    """Live multiplier earned by each outlet's own predictive record
    (source_rankings.json). PROVEN 1.2x · FADE 0.8x · default 1.0. Clamped,
    cached by mtime, silent 1.0 on any failure."""
    if not name:
        return 1.0
    try:
        from pathlib import Path as _P
        import json as _j
        p = _P("docs/data/source_rankings.json")
        m = p.stat().st_mtime
        if _SRC_W_CACHE["mtime"] != m:
            data = _j.loads(p.read_text())
            _SRC_W_CACHE["w"] = {b.get("source"): float(b.get("weight") or 1.0)
                                 for b in (data.get("all") or [])}
            _SRC_W_CACHE["mtime"] = m
        return max(0.75, min(1.25, float(_SRC_W_CACHE["w"].get(name, 1.0))))
    except Exception:
        return 1.0


def aggregate_ticker_news(article_titles: List[str],
                          sources=None) -> Dict[str, object]:
    """Richer aggregate: avg sentiment, count, event histogram, dominant event,
    and how many headlines carried an explicit buy/sell phrase. Additive."""
    _srcs = list(sources or [])
    pairs = [(t, (_srcs[i] if i < len(_srcs) else ""))
             for i, t in enumerate(article_titles) if t]
    titles = [t for t, _ in pairs]
    if not titles:
        return {"sentiment": 0.0, "count": 0, "events": {}, "dominant_event": None,
                "pos_phrases": 0, "neg_phrases": 0}
    scores, ev_hist = [], {}
    pos_ph = neg_ph = 0
    antic = []
    cat_score, cat_label = 0.0, None
    for t, _sname in pairs:
        s = score_text(t) * _source_weight(_sname)
        scores.append(s)
        tl = t.lower()
        p, n = _phrase_hits(tl)
        pos_ph += 1 if p else 0
        neg_ph += 1 if n else 0
        for ev in tag_events(t):
            ev_hist[ev] = ev_hist.get(ev, 0) + 1
        _a = anticipation_score(t)
        if _a:
            antic.append(_a)
        # catalyst = the most decisive headline that carries a strong directional phrase
        if _strong_phrase_signal(tl) != 0.0 and abs(s) > abs(cat_score):
            cat_score, cat_label = s, _catalyst_label(t, s)
    dominant = max(ev_hist.items(), key=lambda kv: kv[1])[0] if ev_hist else None
    return {"sentiment": round(sum(scores) / len(scores), 4), "count": len(titles),
            "events": ev_hist, "dominant_event": dominant,
            "pos_phrases": pos_ph, "neg_phrases": neg_ph,
            "anticipation": (round(sum(antic)/len(antic), 3) if antic else 0.0),
            "forward_count": len(antic),
            "catalyst": (round(cat_score, 3) if cat_score != 0.0 else None),
            "catalyst_label": cat_label}
