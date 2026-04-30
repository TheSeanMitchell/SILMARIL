# INDEX.HTML — Alpha 2.0 Update Guide

These are the find-and-replace edits to apply to `docs/index.html` after
dropping in the rest of the package. Use VS Code dev mode (press `.` in
GitHub) and its built-in find-and-replace to apply each block.

If you'd rather skip these for now, the package still works — you'll
just be missing four UI niceties. The new standalone pages
(`stress_test.html`, `correlation_matrix.html`, `evolution_cards.html`)
work without any index.html changes; you just access them by URL.

---

## Edit 1 — Agent display name map (renames)

Add this snippet near the top of `<script>` in index.html (search for
"const agents" or another existing constant):

```javascript
const AGENT_DISPLAY_NAMES = {
  "AEGIS": "Guardian",       "FORGE": "Tech Momentum", "THUNDERHEAD": "Crypto Momentum",
  "JADE": "Biotech",         "VEIL": "Sentiment",      "KESTREL": "Oversold",
  "KESTREL+": "Reverter",    "KESTREL_PLUS": "Reverter",
  "OBSIDIAN": "Commodity",   "ZENITH": "Trend Follower", "WEAVER": "Correlator",
  "HEX": "Bear Watch",       "SYNTH": "Decorrelate",   "SPECK": "Small Cap",
  "VESPA": "Pre-Earnings",   "MAGUS": "Macroscope",    "TALON": "Breadth",
  "CICADA": "Post-Earnings", "NIGHTSHADE": "Insider",  "BARNACLE": "Whale Follow",
  "NOMAD": "ADR Arbitrage",  "ATLAS": "Regime Tagger",
  "GUARDIAN": "Guardian",    "TECH_MOMENTUM": "Tech Momentum",
  "CRYPTO_MOMENTUM": "Crypto Momentum", "BIOTECH": "Biotech",
  "SENTIMENT": "Sentiment",  "OVERSOLD": "Oversold",
  "REVERTER": "Reverter",    "COMMODITY": "Commodity",
  "TREND_FOLLOWER": "Trend Follower", "CORRELATOR": "Correlator",
  "BEAR_WATCH": "Bear Watch", "DECORRELATE": "Decorrelate",
  "SMALL_CAP": "Small Cap",  "PRE_EARNINGS": "Pre-Earnings",
  "MACROSCOPE": "Macroscope", "BREADTH": "Breadth",
  "POST_EARNINGS": "Post-Earnings", "INSIDER": "Insider",
  "WHALE_FOLLOW": "Whale Follow", "ADR_ARB": "ADR Arbitrage",
  "REGIME_TAGGER": "Regime Tagger",
  "BARON": "Baron",          "STEADFAST": "Steadfast",
  "SCROOGE": "Scrooge",      "MIDAS": "Midas",
  "CRYPTOBRO": "Crypto Bro", "JRR_TOKEN": "JRR Token",
  "SPORTS_BRO": "Sports Bro",
  "CONTRARIAN": "Contrarian", "SHORT_ALPHA": "Short Alpha",
};
function displayAgent(codename) {
  return AGENT_DISPLAY_NAMES[codename] || codename;
}
```

Then anywhere a codename is rendered into HTML, wrap it: `displayAgent(name)`.
A safer global swap: search for `\$\{[a-z]+\.agent\}` and replace with
`\${displayAgent($&)}` — but read each match first, since some are inside
HTML attributes.

---

## Edit 2 — Trade history timestamps (fix the "all show 17:00" bug)

Search for `entry.date.slice(5)` or a string like `${entry.date.slice(5)} 17:00`.

```javascript
// OLD (bug — date-only with hardcoded 17:00):
const stamp = `${entry.date.slice(5)} 17:00`;

// NEW (use real timestamp if available):
const stamp = entry.timestamp
  ? new Date(entry.timestamp).toLocaleString('en-US', {
      month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false
    })
  : entry.date.slice(5);
```

The backend writes `timestamp` on every history append. The frontend just
needs to use it.

---

## Edit 3 — Consolidated News Feed sort by time only

Search for the news rendering section (look for "newsItems" or "news_feed").

```javascript
// OLD: grouped by ticker
// NEW: flat sort by published_at desc, capped at 200
const sortedNews = (newsItems || [])
  .filter(n => n.published_at)
  .sort((a, b) => new Date(b.published_at) - new Date(a.published_at))
  .slice(0, 200);

sortedNews.forEach(item => {
  const ago = humanTimeAgo(item.published_at);
  const tag = `<span class="ticker-tag">${item.ticker || 'GENERAL'}</span>`;
  // ... existing row render
});
```

---

## Edit 4 — Add navigation to new pages

Find the existing nav bar / header. Add three links:

```html
<a href="evolution_cards.html">🎴 Evolution Cards</a>
<a href="stress_test.html">🧪 Stress Test</a>
<a href="correlation_matrix.html">🔗 Correlation Matrix</a>
```

---

## Edit 5 — User profiles ranked alongside agents on leaderboard

The user said "Profile · YOU" entries should rank inline among agent
entries, not separated. Find the leaderboard rendering. The simplest fix:
when building the rows, merge the `user_profiles` array with the
`agent_portfolios` map BEFORE sorting by total_return_pct.

```javascript
const allEntries = [
  ...Object.entries(agent_portfolios).map(([k, v]) => ({...v, kind: 'agent', name: displayAgent(k)})),
  ...(user_profiles || []).map(p => ({...p, kind: 'user', name: 'Profile · ' + p.name})),
];
allEntries.sort((a, b) => (b.total_return_pct || 0) - (a.total_return_pct || 0));
```

---

## Edit 6 — Expand Learn the System

Search for an existing `<details>` block in the Learn the System section.
Add these new entries inline:

```html
<details><summary>What is "training that never resets"?</summary>
  <p>Every agent's belief state, evolution card, regime bandits, and
  counterfactual log live in dedicated files on a protected list. No
  workflow — daily, backtest, reset, or any other — is permitted to
  delete those files. Reset only wipes the cosmetic daily artifacts.
  Learning is sacred and continuously accumulates.</p>
</details>

<details><summary>What is Thompson sampling?</summary>
  <p>An exploration-vs-exploitation algorithm. Each agent has a
  confidence band on its win rate (Beta distribution). On each debate,
  we sample from that band rather than using the point estimate.
  Confident agents get stable voice; uncertain agents get variable
  voice while the system explores whether they have edge.</p>
</details>

<details><summary>What is the GUARDIAN veto and when does it apply?</summary>
  <p>GUARDIAN can override bullish consensus and force a HOLD. The veto
  fires only when GUARDIAN has earned the right: rolling 30-day win
  rate ≥ 50% AND high conviction (≥ 0.65). A losing defensive agent
  cannot suppress winning offensive ones.</p>
</details>

<details><summary>What is hysteresis?</summary>
  <p>A buffer that prevents flipping. SELL fires when RSI &gt; 70 but
  doesn't reset until RSI &lt; 65. The 5-point gap stops oscillation
  on borderline values — critical at 10-minute cadence.</p>
</details>

<details><summary>What is a counterfactual?</summary>
  <p>When consensus overrules a minority dissent, we log what would
  have happened if we'd listened to the dissenter. After 90+ days,
  this tells us which dissents are signal vs noise.</p>
</details>

<details><summary>What is a pre-mortem?</summary>
  <p>Before any high-conviction call, the agent is forced to articulate
  "what would have to be true for me to be wrong?" — explicit kill
  criteria written into the rationale. Cognitive-bias mitigation used
  by institutional analysts.</p>
</details>

<details><summary>What is the adversarial stress test?</summary>
  <p>A manual-trigger workflow that re-runs recent signals through
  hostile-market scenarios where prices move 1-3% against consensus
  before fills. If the strategy still wins under aggressive
  front-running, the edge is robust. Run it weekly.</p>
</details>

<details><summary>How does Alpaca paper trading work here?</summary>
  <p>After the consensus phase, every BUY/SELL signal at conviction
  ≥ 0.60 becomes a real-shaped market order in your free Alpaca
  paper account. Position sizing is capped at 5% per name. Shorts
  are enabled if your account supports them. The system never
  touches real money — base URL is hardcoded to paper-only.</p>
</details>
```
