/* ============================================================================
   silmaril-truth.js — SILMARIL Alpha 6.3 canonical TRUTH-PRIMITIVE layer
   ----------------------------------------------------------------------------
   ONE source of truth for every derived metric, anomaly detector, and reusable
   visual used by the operator cockpit (and by future Phase V / Track C surfaces).
   * READ-ONLY. Pure compute/detect/render. No writes, no persistence, no fetch
     except Data.load (browser). Compute/Detect/Render are environment-agnostic
     (node-testable) and never touch the DOM.
   * Nothing here feeds policy/scoring/broker. Observational-only.
   Exposes global `ST` in browser and module.exports in node.
============================================================================ */
(function (root) {
  "use strict";

  // ---- Constants (static refs; update only if upstream changes) ------------
  const Const = {
    RESET_HARDCODED_ROSTER: 27,            // full_reset.yml hardcoded roster (Phase I, static)
    DAILY_CRON_UTC:   [[13,20],[8,13],[20,24],[0,7]],   // daily.yml union (Phase I)
    EVENING_CRON_UTC: [],   // evening_prep.yml retired (Alpha 0.002) — daily.yml runs the full cycle
    STALE_HI: 0.85,        // stale-rate "critical contamination" threshold
    LOW_N: 30,             // minimum sample size for statistical weight
    DORMANT_DAYS: 2,       // days-since-last-order to call an account stale
    HIGH_WIN: 0.80,        // "appears successful" win-rate threshold
    Z: 1.96,               // 95% normal quantile (Wilson)
    PHASE_I_VERIFIED: "2026-05-22"
  };

  // ---- small utils ----------------------------------------------------------
  const util = {
    dayKey: s => (s || "").slice(0, 10),
    isNum: v => typeof v === "number" && !isNaN(v),
    pct: (v, d = 1) => util.isNum(v) ? (v * 100).toFixed(d) + "%" : null,
    money: v => util.isNum(v) ? "$" + v.toFixed(2) : null,
    daysBetween: (a, b) => (a && b) ? Math.round((new Date(a) - new Date(b)) / 86400000) : null
  };

  // ===========================================================================
  // COMPUTE — pure derived metrics (no DOM, no fetch)
  // ===========================================================================
  const Compute = {
    // per-agent stale/win aggregation from raw outcomes
    staleByAgent(outcomes) {
      const A = {};
      (outcomes || []).forEach(o => {
        const a = o.agent; if (!a) return;
        const d = A[a] || (A[a] = { agent:a, n:0, wins:0, stale:0, nsN:0, nsW:0, rets:[] });
        d.n++;
        const correct = o.correct === true;
        if (correct) d.wins++;
        if (o.stale_price_suspected) { d.stale++; }
        else { d.nsN++; if (correct) d.nsW++; }
        if (util.isNum(o.return_pct)) d.rets.push(o.return_pct);
      });
      return A;
    },
    staleRate(d)        { return d && d.n ? d.stale / d.n : null; },
    staleExclWin(d)     { return d && d.nsN ? d.nsW / d.nsN : null; },
    meanRet(d)          { return d && d.rets.length ? d.rets.reduce((x,y)=>x+y,0)/d.rets.length : null; },

    // daily stale-rate trend from outcomes.scored_at
    staleByDay(outcomes) {
      const m = {};
      (outcomes || []).forEach(o => {
        const d = util.dayKey(o.scored_at); if (!d) return;
        const e = m[d] || (m[d] = { day:d, n:0, stale:0 });
        e.n++; if (o.stale_price_suspected) e.stale++;
      });
      return Object.keys(m).sort().map(k => ({ ...m[k], rate: m[k].stale/m[k].n }));
    },

    // Wilson 95% score interval for a proportion (uncertainty-honest)
    wilson(wins, n) {
      if (!n) return null;
      const z = Const.Z, p = wins / n, z2 = z*z;
      const denom = 1 + z2/n;
      const center = (p + z2/(2*n)) / denom;
      const margin = (z/denom) * Math.sqrt(p*(1-p)/n + z2/(4*n*n));
      return { p, lo: Math.max(0, center-margin), hi: Math.min(1, center+margin), n };
    },

    // realized truth for harvester agents: (equity - start) + savings
    trueRealized(p) {
      if (!p || !util.isNum(p.current_equity)) return null;
      const start = util.isNum(p.starting_equity) ? p.starting_equity : 10000;
      const sav = util.isNum(p.savings) ? p.savings : 0;
      return (p.current_equity - start) + sav;
    },

    // account state, contradiction-aware (never silently reconciles)
    accountState(state, isLegacy, today) {
      if (!state) return { present:false };
      // NOTE: orders_placed may be an EMPTY array (truthy in JS) while the
      // timestamped history lives in `orders`. Pick whichever is non-empty.
      const op = state.orders_placed, or = state.orders;
      const orders = (Array.isArray(op) && op.length) ? op : (Array.isArray(or) ? or : []);
      const days = {};
      orders.forEach(o => { const d = util.dayKey(o.timestamp); if (d) days[d] = (days[d]||0)+1; });
      const dk = Object.keys(days).sort();
      const last = dk[dk.length-1] || null;
      const since = last ? util.daysBetween(today, last) : null;
      const configured = isLegacy ? true : (state.configured === true);
      const dormant = since != null && since >= Const.DORMANT_DAYS;
      // ALPHA 0.001: an account that is actually TRADING (recent orders, not
      // dormant) is LIVE — regardless of the `configured` flag, which has a
      // known write-ordering bug (writes false on a skipped cycle even while
      // the account is placing orders). Ground truth is the order tape, not the
      // flag. We still record the mismatch (configMismatch) so it's surfaced as
      // an anomaly, but it no longer hides a live account from the live count.
      const configMismatch = !configured && !dormant && orders.length > 0;
      let cls, label;
      if (!configured && dormant)       { cls="skipped"; label="SKIPPED \u00b7 secrets unset"; }
      else if (dormant)                 { cls="stale";   label="stale "+since+"d"; }
      else                              { cls="active";   label = configMismatch ? "active (flag:config=false \u26A0)" : "active"; }
      return { present:true, configured, configMismatch, ordersTotal:orders.length, firstDay:dk[0]||null,
               lastDay:last, daysSince:since, dormant, byDay:days, cls, label,
               savings: state.savings ?? state.realized_savings ?? 0,
               tradingCapital: state.trading_capital ?? (state.account||{}).equity ?? null,
               wins: state.lifetime_realized_wins, losses: state.lifetime_realized_losses };
    },

    rosterSources(ap, rs, sc) {
      const agr = (rs && rs.agents) || {};
      const out = [
        { label:"portfolios",     n: ap ? Object.keys(ap).length : null },
        { label:"risk_state",     n: Object.keys(agr).length || null },
        { label:"scoring(track)", n: (sc && sc.summary) ? sc.summary.agents_with_track_record : null },
        { label:"reset hardcoded",n: Const.RESET_HARDCODED_ROSTER, static:true }
      ];
      out.distinct = new Set(out.map(x=>x.n).filter(v=>v!=null)).size;
      return out;
    },

    overlapHours(daily, evening) {
      daily = daily || Const.DAILY_CRON_UTC; evening = evening || Const.EVENING_CRON_UTC;
      const hit = (rs,h) => rs.some(r => h>=r[0] && h<r[1]);
      const ov = []; for (let h=0;h<24;h++) if (hit(daily,h)&&hit(evening,h)) ov.push(h);
      return ov;
    },

    frozen(rs) {
      const agr = (rs && rs.agents) || {};
      return Object.keys(agr).filter(a => agr[a] && agr[a].frozen)
        .map(a => ({ agent:a, since: agr[a].frozen_since || "?", reason: agr[a].frozen_reason || "" }))
        .sort((x,y)=> x.since>y.since?1:-1);
    },

    canonLeaderboard(sc) {
      const m = {}; (((sc||{}).summary||{}).leaderboard||[]).forEach(e=>m[e.agent]=e); return m;
    },

    // canonical raw win-rate (prefer scoring summary; fall back to raw aggregate)
    rawWin(d, canonEntry) {
      if (canonEntry && canonEntry.win_rate != null) return canonEntry.win_rate;
      return (d && d.n) ? d.wins / d.n : null;
    },

    // read-only agent classification for quarantine GROUPING (display only).
    // Never hides/deletes/alters telemetry — purely buckets for operator readability.
    //   verified       : has clean (non-stale) sample >= LOW_N
    //   artifact_risk   : scored but zero clean samples OR >=95% stale
    //   no_track_record : in portfolios but never scored
    //   frozen          : risk-frozen (takes precedence in display)
    classifyAgent(agentName, byAgentEntry, isFrozen) {
      if (isFrozen) return "frozen";
      const d = byAgentEntry;
      if (!d || !d.n) return "no_track_record";
      const stale = Compute.staleRate(d);
      if (d.nsN === 0 || (stale != null && stale >= 0.95)) return "artifact_risk";
      if (d.nsN >= Const.LOW_N) return "verified";
      return "artifact_risk"; // scored but thin clean evidence -> quarantine, not headline
    },

    // full classification map over the union of scored + portfolio agents
    classifyAll(ctx) {
      const sc = ctx.scoring || {};
      const byAgent = Compute.staleByAgent(sc.outcomes);
      const frozenSet = new Set(Compute.frozen(ctx.risk).map(f => f.agent));
      const names = new Set([...Object.keys(byAgent), ...Object.keys(ctx.portfolios || {})]);
      names.delete("_summary");
      const groups = { verified:[], artifact_risk:[], no_track_record:[], frozen:[] };
      names.forEach(a => {
        const cls = Compute.classifyAgent(a, byAgent[a], frozenSet.has(a));
        groups[cls].push(a);
      });
      Object.keys(groups).forEach(k => groups[k].sort());
      return groups;
    },

    // run cadence per day from history.runs
    runCadence(history) {
      const m = {}; (((history||{}).runs)||[]).forEach(r => {
        const d = util.dayKey(r.timestamp || r.date); if (d) m[d] = (m[d]||0)+1; });
      return Object.keys(m).sort().map(k => ({ day:k, n:m[k] }));
    },

    // system summary — pure AGGREGATION of existing Compute/Detect outputs (NOT a new
    // metric). Used for the situation-room band + narrative. Introduces no new statistic.
    systemSummary(ctx, anomalies) {
      const sc = ctx.scoring || {}, out = sc.outcomes || [];
      const totN = out.length;
      const totStale = out.reduce((s,o)=>s+(o.stale_price_suspected?1:0),0);
      const staleRate = totN ? totStale/totN : null;
      const g = Compute.classifyAll(ctx);
      const today = util.dayKey(sc.generated_at);
      const accts = [["LEGACY",ctx.legacy,true],["HARVEST_3",ctx.h3,false],["HARVEST_5",ctx.h5,false]]
        .map(([n,s,l]) => ({ name:n, st: Compute.accountState(s,l,today) }));
      const live = accts.filter(a => a.st.present && a.st.cls === "active").length;
      const present = accts.filter(a => a.st.present).length;
      const an = anomalies || Detect.anomalies(ctx);
      const sbd = Compute.staleByDay(out);
      const trend = (sbd.length >= 2)
        ? (sbd[sbd.length-1].rate > sbd[0].rate + 0.01 ? "rising"
          : sbd[sbd.length-1].rate < sbd[0].rate - 0.01 ? "falling" : "flat") : "n/a";
      return {
        staleRate, staleTrend: trend, staleCount: totStale, cleanCount: totN - totStale, totalOutcomes: totN,
        verified: g.verified, artifactRisk: g.artifact_risk.length,
        noTrackRecord: g.no_track_record.length, frozen: g.frozen.length,
        accountsLive: live, accountsPresent: present, accounts: accts,
        anomalyTotal: an.length, anomalyCritical: an.filter(a=>a.sev==="critical").length,
        topAnomaly: an[0] || null, asOf: sc.generated_at
      };
    }
  };

  // ===========================================================================
  // DETECT — the anomaly engine. ctx = loaded canonical objects. Returns ranked.
  // Each alert: {sev:'critical'|'warn'|'info', code, title, detail, track}
  // ===========================================================================
  const Detect = {
    SEV_ORDER: { critical:0, warn:1, info:2 },
    anomalies(ctx) {
      const A = [];
      const sc = ctx.scoring || {}, out = sc.outcomes || [];
      const today = util.dayKey(sc.generated_at) || new Date().toISOString().slice(0,10);
      const byAgent = Compute.staleByAgent(out);
      const canon = Compute.canonLeaderboard(sc);

      // 1) overall stale contamination
      const totN = out.length, totStale = out.reduce((s,o)=>s+(o.stale_price_suspected?1:0),0);
      if (totN) {
        const r = totStale/totN;
        A.push({ sev: r>=Const.STALE_HI?"critical":(r>=0.5?"warn":"info"),
          code:"STALE_CONTAMINATION", title:`Scoring ${util.pct(r)} stale`,
          detail:`${totStale}/${totN} outcomes flagged stale_price_suspected. Win-rates & learning inputs are contaminated.`,
          track:"Track B (stale-score gating changes scoring)" });
      }
      // 2) high win-rate but ZERO clean (non-stale) evidence
      Object.values(byAgent).forEach(d => {
        const c = canon[d.agent]; const raw = c ? c.win_rate : (d.n?d.wins/d.n:null);
        if (raw!=null && raw>=Const.HIGH_WIN && d.nsN===0)
          A.push({ sev:"critical", code:"NO_CLEAN_EVIDENCE",
            title:`${d.agent}: ${util.pct(raw)} win on ZERO clean samples`,
            detail:`All ${d.n} scored outcomes are stale → the headline win-rate has no non-stale evidence behind it.`,
            track:"SAFE NOW (display) · root cause Track B" });
      });
      // 3) negative realized despite high win-rate
      const ap = ctx.portfolios || {};
      Object.values(byAgent).forEach(d => {
        const c = canon[d.agent]; const raw = c ? c.win_rate : null;
        const tr = Compute.trueRealized(ap[d.agent]);
        if (raw!=null && raw>=Const.HIGH_WIN && tr!=null && tr<0)
          A.push({ sev:"warn", code:"WIN_VS_REALIZED",
            title:`${d.agent}: ${util.pct(raw)} win but ${util.money(tr)} realized`,
            detail:`High win-rate with negative true-realized (equity+savings). Win-rate \u2260 profit.`,
            track:"SAFE NOW (display)" });
      });
      // 4) low clean-N high win (uncertainty)
      Object.values(byAgent).forEach(d => {
        const c = canon[d.agent]; const raw = c ? c.win_rate : null;
        if (raw!=null && raw>=Const.HIGH_WIN && d.nsN>0 && d.nsN<Const.LOW_N)
          A.push({ sev:"info", code:"LOW_CLEAN_N",
            title:`${d.agent}: only ${d.nsN} clean samples`,
            detail:`High win-rate rests on <${Const.LOW_N} non-stale samples; confidence interval is wide.`,
            track:"SAFE NOW (display)" });
      });
      // 5) accounts: dormant / contradiction
      [["LEGACY",ctx.legacy,true],["HARVEST_3",ctx.h3,false],["HARVEST_5",ctx.h5,false]].forEach(([name,s,leg])=>{
        const st = Compute.accountState(s, leg, today);
        if (!st.present) return;
        if (st.cls==="skipped")
          A.push({ sev:"warn", code:"ACCOUNT_DORMANT", title:`${name} dormant ${st.daysSince}d (skipped)`,
            detail:`configured:false and no orders for ${st.daysSince}d. Account skipped each cycle (secrets unset).`,
            track:"Track B (account funding/restructure)" });
        else if (st.configMismatch)
          A.push({ sev:"warn", code:"ACCOUNT_CONTRADICTION", title:`${name}: live but configured:false`,
            detail:`Account is trading (orders within ${st.daysSince}d) so it is counted LIVE, but its state flag still says configured:false — a known write-ordering bug (the flag reflects a skipped cycle while orders persist). Reconcile the flag; the live count is correct.`,
            track:"Track B (orchestration/secrets)" });
      });
      // 6) roster drift
      const rost = Compute.rosterSources(ctx.portfolios, ctx.risk, sc);
      if (rost.distinct>1)
        A.push({ sev:"warn", code:"ROSTER_DRIFT", title:`Roster drift: ${rost.distinct} distinct counts`,
          detail: rost.map(r=>`${r.label}=${r.n==null?"\u2014":r.n}`).join(" · ")+`. A reset using the hardcoded ${Const.RESET_HARDCODED_ROSTER} would diverge.`,
          track:"Track B (reset unification / single roster)" });
      // 7) workflow overlap
      const ov = Compute.overlapHours();
      if (ov.length)
        A.push({ sev:"warn", code:"WORKFLOW_OVERLAP", title:`daily/evening_prep overlap ${ov.length}h/day`,
          detail:`Overlapping UTC hours ${ov.map(h=>String(h).padStart(2,"0")).join(", ")}. Daily runs protection every cycle, so evening_prep is largely redundant. Both share concurrency group 'silmaril-broker', so runs are serialized (not a race) — but the overlap still wastes price-API quota. Slim/eliminate evening_prep = Track B.`,
          track:"Track B (orchestration merge)" });
      // 8) equity/principal reconciliation
      const eq = ctx.equity, snaps = (eq && eq.snapshots) || [];
      if (snaps.length) {
        const base = snaps[0].equity, principal = (ctx.legacy && ctx.legacy.principal_target);
        if (util.isNum(base) && util.isNum(principal) && Math.abs(base-principal) > principal*0.5)
          A.push({ sev:"info", code:"EQUITY_BASE_MISMATCH", title:`Equity base ${util.money(base)} vs principal ${util.money(principal)}`,
            detail:`Alpaca paper base differs from SILMARIL principal_target — reconcile when reading equity curves.`,
            track:"SAFE NOW (display note)" });
      }
      // 9) frozen-agent cluster
      const fz = Compute.frozen(ctx.risk);
      if (fz.length) {
        const days = {}; fz.forEach(f=>days[f.since]=(days[f.since]||0)+1);
        const cluster = Object.entries(days).filter(([,c])=>c>=2);
        A.push({ sev:"info", code:"FROZEN_AGENTS", title:`${fz.length} agents frozen`,
          detail:`${fz.map(f=>f.agent+"("+f.since+")").join(", ")}.`+(cluster.length?` Cluster freeze on ${cluster.map(c=>c[0]).join(", ")}.`:"")+` Loop acts on low scorers — but learns from stale-contaminated scores.`,
          track:"observational" });
      }
      return A.sort((x,y)=> Detect.SEV_ORDER[x.sev]-Detect.SEV_ORDER[y.sev]);
    }
  };

  // ===========================================================================
  // RENDER — reusable visual primitives. Return HTML/SVG strings (pure).
  // ===========================================================================
  const Render = {
    nm: v => (v===null||v===undefined||(typeof v==="number"&&isNaN(v)))
      ? '<span class="st-nm">not measurable</span>' : v,
    badge: (txt, cls) => `<span class="st-badge st-${cls||'info'}">${txt}</span>`,

    tile(label, value, status, sub) {
      return `<div class="st-tile st-${status||'info'}"><div class="st-tile-v">${value}</div>`
        + `<div class="st-tile-k">${label}</div>${sub?`<div class="st-tile-s">${sub}</div>`:''}</div>`;
    },

    // paired raw-vs-clean horizontal bars (pre-attentive contamination contrast)
    pairedBar(raw, clean) {
      const bar = (v,color,lab) => {
        if (v==null) return `<div class="st-pb-row"><span class="st-pb-lab">${lab}</span><span class="st-pb-track"><i style="width:0"></i></span><span class="st-pb-val st-nm">n/a</span></div>`;
        return `<div class="st-pb-row"><span class="st-pb-lab">${lab}</span>`
          + `<span class="st-pb-track"><i style="width:${(v*100).toFixed(1)}%;background:${color}"></i></span>`
          + `<span class="st-pb-val">${(v*100).toFixed(1)}%</span></div>`;
      };
      return `<div class="st-pb">${bar(raw,'var(--st-warn)','raw')}${bar(clean,'var(--st-ok)','clean')}</div>`;
    },

    // win-rate with Wilson CI; visually flags wide/low-confidence
    ciBar(w) { // w = wilson() result
      if (!w) return '<span class="st-nm">no data</span>';
      const lo=(w.lo*100), hi=(w.hi*100), p=(w.p*100), wide=(hi-lo)>=25, spans=w.lo<0.5;
      const col = (spans||wide)?'var(--st-warn)':'var(--st-ok)';
      return `<span class="st-ci" title="95% Wilson CI">`
        + `<span class="st-ci-bar"><i style="left:${lo.toFixed(1)}%;width:${(hi-lo).toFixed(1)}%;background:${col}"></i>`
        + `<u style="left:${p.toFixed(1)}%"></u></span>`
        + `<span class="st-ci-txt">${p.toFixed(0)}% <small>[${lo.toFixed(0)}\u2013${hi.toFixed(0)}] n=${w.n}</small></span></span>`;
    },

    sparkline(vals, color, labels) {
      vals = (vals||[]).filter(util.isNum);
      if (vals.length<2) return '<span class="st-nm">need \u22652 pts</span>';
      const W=520,H=64,mx=Math.max(...vals),mn=Math.min(...vals),rng=(mx-mn)||1;
      const pts = vals.map((v,i)=>(i/(vals.length-1)*W).toFixed(1)+','+(H-((v-mn)/rng)*(H-10)-5).toFixed(1)).join(' ');
      return `<svg class="st-spark" viewBox="0 0 ${W} ${H+12}" preserveAspectRatio="none">`
        + `<polyline fill="none" stroke="${color||'var(--st-info)'}" stroke-width="2" points="${pts}"/>`
        + `<text x="0" y="${H+10}" class="st-axt">${mn.toFixed(2)}</text>`
        + `<text x="${W}" y="${H+10}" text-anchor="end" class="st-axt">${mx.toFixed(2)}</text></svg>`;
    },

    bars(data, opt) { // data:[{label,value,tag,color}]
      opt = opt||{}; const W=560,H=opt.h||110,max=opt.max||Math.max(1e-9,...data.map(d=>d.value)),bw=W/Math.max(1,data.length);
      let s=`<svg class="st-bars" viewBox="0 0 ${W} ${H+18}" preserveAspectRatio="none">`;
      data.forEach((d,i)=>{ const h=(d.value/max)*(H-20), x=i*bw+3, y=H-h;
        s+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw-6).toFixed(1)}" height="${Math.max(0,h).toFixed(1)}" rx="2" fill="${d.color||'var(--st-info)'}" opacity="0.85"/>`;
        s+=`<text x="${(x+(bw-6)/2).toFixed(1)}" y="${H+12}" class="st-axt" text-anchor="middle">${d.label}</text>`;
        if(d.tag) s+=`<text x="${(x+(bw-6)/2).toFixed(1)}" y="${(y-3).toFixed(1)}" class="st-axt" text-anchor="middle">${d.tag}</text>`;
      });
      return s+'</svg>';
    },

    timeline(ranges, color) {
      let s=''; (ranges||[]).forEach(r=>{ const x=r[0]/24*100, w=(r[1]-r[0])/24*100;
        s+=`<i style="left:${x}%;width:${w}%;background:${color}"></i>`; });
      return `<div class="st-tl">${s}</div><div class="st-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24 UTC</span></div>`;
    },

    anomalyCard(a) {
      return `<div class="st-anom st-${a.sev}"><div class="st-anom-h">`
        + `${Render.badge(a.sev.toUpperCase(), a.sev)} <b>${a.title}</b></div>`
        + `<div class="st-anom-d">${a.detail}</div>`
        + `<div class="st-anom-t">fix scope: ${a.track}</div></div>`;
    },

    // responsive table: renders <table> on wide, auto card-stacks on narrow via CSS
    table(cols, rows) {
      const head = cols.map(c=>`<th class="${c.l?'st-l':''}">${c.h}</th>`).join('');
      const body = rows.map(r=>'<tr class="'+(r._cls||'')+'">'
        + cols.map(c=>`<td class="${c.l?'st-l':''}" data-h="${c.h}">${r[c.k]!==undefined?r[c.k]:''}</td>`).join('')
        + '</tr>').join('');
      return `<div class="st-table-wrap"><table class="st-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    },

    // semicircular gauge/meter (e.g., stale% or health). value 0..1. zones risk-first.
    gauge(value, label, opt) {
      opt = opt || {};
      if (value == null || isNaN(value)) return `<div class="st-gauge"><div class="st-gauge-nm">not measurable</div><div class="st-gauge-l">${label||''}</div></div>`;
      const pct = Math.max(0, Math.min(1, value));
      // risk-first: high value = bad by default (stale/danger). invert=true => high is good.
      const good = opt.invert ? pct >= (opt.hi||0.66) : pct <= (opt.lo||0.2);
      const bad  = opt.invert ? pct <= (opt.lo||0.33) : pct >= (opt.hi||0.66);
      const col = bad ? "var(--st-bad)" : good ? "var(--st-ok)" : "var(--st-warn)";
      const ang = -90 + pct*180, R=46, cx=60, cy=58;
      const x = cx + R*Math.cos(ang*Math.PI/180), y = cy + R*Math.sin(ang*Math.PI/180);
      return `<div class="st-gauge"><svg viewBox="0 0 120 70">`
        + `<path d="M14 58 A46 46 0 0 1 106 58" fill="none" stroke="#1a2333" stroke-width="9"/>`
        + `<path d="M14 58 A46 46 0 0 1 106 58" fill="none" stroke="${col}" stroke-width="9"`
        + ` stroke-dasharray="${(pct*144).toFixed(1)} 200" stroke-linecap="round"/>`
        + `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${col}" stroke-width="2"/>`
        + `<text x="60" y="50" text-anchor="middle" class="st-gauge-v" fill="${col}">${(pct*100).toFixed(opt.dp!=null?opt.dp:1)}%</text></svg>`
        + `<div class="st-gauge-l">${label||''}</div></div>`;
    },

    // horizontal stacked composition bar. segments:[{label,value,color}]
    stackedBar(segments, opt) {
      const tot = segments.reduce((s,x)=>s+(x.value||0),0) || 1;
      const bar = segments.filter(s=>s.value>0).map(s =>
        `<i style="width:${(s.value/tot*100).toFixed(2)}%;background:${s.color}" title="${s.label}: ${s.value}"></i>`).join("");
      const legend = segments.map(s =>
        `<span class="st-leg"><b style="background:${s.color}"></b>${s.label} <em>${s.value}</em></span>`).join("");
      return `<div class="st-stack-wrap"${opt&&opt.title?` data-title="${opt.title}"`:""}>`
        + `<div class="st-stack">${bar}</div><div class="st-legend">${legend}</div></div>`;
    },

    // plain-language situation narrative from a systemSummary object (display-only)
    narrative(s) {
      if (!s) return "";
      const sp = s.staleRate!=null ? (s.staleRate*100).toFixed(1)+"%" : "n/a";
      const edge = s.verified.length
        ? `${s.verified.length} agent${s.verified.length>1?"s":""} (${s.verified.join(", ")}) classify as Verified, but none has yet proven realized edge`
        : "no agent currently classifies as Verified";
      const top = s.topAnomaly ? ` Top issue: ${s.topAnomaly.title}.` : "";
      return `Scoring is <b class="st-em-bad">${sp} stale</b> (trend ${s.staleTrend}); `
        + `${edge}. ${s.accountsLive} of ${s.accountsPresent} accounts live; ${s.frozen} frozen; `
        + `${s.artifactRisk} quarantined as artifact-risk. `
        + `<b>${s.anomalyCritical}</b> critical of ${s.anomalyTotal} anomalies.${top}`;
    },

    // edge & benchmark panel — equities-only edge study + market benchmark. Display-only, reads ctx.edge / ctx.benchmark.
    edgePanel(edge, bench) {
      const OK="var(--st-ok)", WN="var(--st-warn)", BD="var(--st-bad)", DM="var(--dim)";
      const tcol = t => (t==null||isNaN(t))?DM : (t>=2?OK : t>=1?WN : DM);
      const tnum = t => (t==null||isNaN(t))?"\u2014" : (t>0?"+":"")+Number(t).toFixed(2);
      const tspan= t => `<span style="color:${tcol(t)}">${tnum(t)}</span>`;
      const pp   = x => (x==null||isNaN(x))?"\u2014" : (x>0?"+":"")+Number(x).toFixed(2)+"%";          // edge study returns are pct-points
      const pf   = (x,d)=> (x==null||isNaN(x))?"\u2014" : (x>0?"+":"")+(Number(x)*100).toFixed(d==null?2:d)+"%"; // benchmark returns are fractions
      const wr   = x => (x==null||isNaN(x))?"\u2014" : (Number(x)*100).toFixed(1)+"%";
      const vb   = v => { const c=v==="significant"?OK:v==="suggestive"?WN:DM; return `<span style="color:${c};font-weight:600">${v||"\u2014"}</span>`; };

      if (!edge) return '<h2>Edge &amp; Benchmark</h2><div class="card st-info">Edge study not generated yet \u2014 it is written automatically after the next scoring run (look for <code>data/edge_study.json</code>). The benchmark panel also needs <code>data/benchmarking.json</code>.</div>';

      const ov  = edge.overall || {};
      const lvs = edge.long_vs_short || {}; const L = lvs.long||{}, S = lvs.short||{};
      const dil = (edge.instruments||{}).all_instruments_directional || {};
      const comp= (edge.instruments||{}).composition_clean || {};

      let h = '<h2>Edge &amp; Benchmark <span class="st-badge st-viol">derived \u00b7 early</span></h2>';
      h += '<div class="desc">The core question: is there a real, repeatable <b>stock</b> edge? Equities only, stale outcomes excluded, '
         + 'all clean data so far is RISK_ON. Significance on ~30\u2013280 clean calls is genuine but <b>early</b> \u2014 the test is whether the '
         + 't-stats hold above 2 as the clean week accrues.</div>';

      // ---- top tiles ----
      const mo = (bench&&bench.windows&&bench.windows['1mo'])||null;
      h += '<div class="strip">'
        + Render.tile('equity edge t', tnum(ov.t_stat), (ov.t_stat>=2?'ok':ov.t_stat>=1?'warn':'info'), (ov.verdict||'')+' \u00b7 N='+(ov.n||0))
        + Render.tile('equity mean / call', pp(ov.mean_return), (ov.mean_return>0?'ok':'bad'), wr(ov.win_rate)+' win-rate')
        + Render.tile('long edge t', tnum(L.t_stat), (L.t_stat>=2?'ok':L.t_stat>=1?'warn':'info'), 'short t='+tnum(S.t_stat)+' (no edge)')
        + Render.tile('vs SPY \u00b7 1mo', mo?pf(mo.alpha_vs_spy):'\u2014', (mo&&mo.alpha_vs_spy>0?'ok':'info'), 'defensive \u2014 see note')
        + '</div>';

      // ---- Card 1: stock-edge cuts ----
      h += '<div class="card"><h3>Stock edge \u2014 equities only, clean data</h3>';
      h += Render.table(
        [{h:'cut',k:'cut',l:true},{h:'N',k:'n'},{h:'mean/call',k:'m'},{h:'win',k:'w'},{h:'t-stat',k:'t'},{h:'verdict',k:'v'}],
        [
          {cut:'<b>equity directional (the mission)</b>', n:ov.n, m:pp(ov.mean_return), w:wr(ov.win_rate), t:tspan(ov.t_stat), v:vb(ov.verdict)},
          {cut:'long only',  n:L.n, m:pp(L.mean_return), w:wr(L.win_rate), t:tspan(L.t_stat), v:vb(L.verdict)},
          {cut:'short only', n:S.n, m:pp(S.mean_return), w:wr(S.win_rate), t:tspan(S.t_stat), v:vb(S.verdict)},
          {cut:'all instruments (crypto/macro mixed in)', n:dil.n, m:pp(dil.mean_return), w:wr(dil.win_rate), t:tspan(dil.t_stat), v:vb(dil.verdict), _cls:'frozen'}
        ]);
      h += '<div class="desc">Clean composition: <b>'+(comp.equity||0)+'</b> equity \u00b7 '+(comp.crypto||0)+' crypto \u00b7 '+(comp.macro||0)+' macro. '
         + 'Mixing crypto/macro in drops the edge from <b>'+pp(ov.mean_return)+' (t='+tnum(ov.t_stat)+')</b> to '+pp(dil.mean_return)+' (t='+tnum(dil.t_stat)+'). '
         + 'The mission is equities \u2014 that is the row that counts.</div></div>';

      // ---- Card 2: agents by edge ----
      const agents = (edge.by_agent||[]).slice().sort((a,b)=>(b.t_stat||0)-(a.t_stat||0));
      const sig = agents.filter(a=>a.t_stat>=2);
      h += '<div class="card"><h3>Agents by equity edge <span style="color:'+DM+';font-weight:400;font-size:11px">t \u2265 2 = build around these</span></h3>';
      h += Render.table(
        [{h:'agent',k:'a',l:true},{h:'N',k:'n'},{h:'mean/call',k:'m'},{h:'win',k:'w'},{h:'t-stat',k:'t'},{h:'verdict',k:'v'}],
        agents.length?agents.map(a=>({a:(a.t_stat>=2?'<b>'+a.key+'</b>':a.key), n:a.n, m:pp(a.mean_return), w:wr(a.win_rate), t:tspan(a.t_stat), v:vb(a.verdict)}))
                      :[{a:'\u2014',n:'',m:'',w:'',t:'',v:'no agent has enough clean equity calls yet'}]);
      h += '<div class="desc">'+(sig.length?('Statistically significant: <b>'+sig.map(a=>a.key).join(', ')+'</b> \u2014 the candidates to build future agents around.'):'No agent has crossed t=2 on clean equity data yet.')
         + ' Rows below threshold are shown for honesty, not as signal.</div></div>';

      // ---- honest caveats (straight from the study's own notes) ----
      if (edge.notes && edge.notes.length) {
        h += '<div class="card"><h3>Honest caveats</h3><ul style="margin:4px 0 0;padding-left:18px;color:var(--dim);font-size:11px;line-height:1.6">'
           + edge.notes.map(n=>'<li>'+String(n).replace(/</g,'&lt;')+'</li>').join('') + '</ul></div>';
      }

      // ---- Card 3: benchmark vs market ----
      if (bench && bench.windows) {
        const w = bench.windows, rm = bench.rolling_metrics||{};
        const row = (lab,k)=>{ const x=w[k]||{}; return {win:lab, s:pf(x.silmaril_return), spy:pf(x.spy_return),
          asp:`<span style="color:${(x.alpha_vs_spy||0)>0?OK:BD}">${pf(x.alpha_vs_spy)}</span>`, qqq:pf(x.qqq_return),
          aqq:`<span style="color:${(x.alpha_vs_qqq||0)>0?OK:BD}">${pf(x.alpha_vs_qqq)}</span>`}; };
        h += '<div class="card"><h3>vs the market <span style="color:'+DM+';font-weight:400;font-size:11px">3 paper accounts combined</span></h3>';
        h += Render.table(
          [{h:'window',k:'win',l:true},{h:'SILMARIL',k:'s'},{h:'SPY',k:'spy'},{h:'\u0394 vs SPY',k:'asp'},{h:'QQQ',k:'qqq'},{h:'\u0394 vs QQQ',k:'aqq'}],
          [row('1 day','1d'),row('1 week','1w'),row('1 month','1mo')]);
        h += '<div class="desc">Max drawdown '+(rm.max_drawdown!=null?(rm.max_drawdown*100).toFixed(2)+'%':'\u2014')+'. '
           + '<b>Read this honestly:</b> SILMARIL is ahead of SPY over 1w/1mo, but mainly because it is lightly deployed (mostly cash, under principal) '
           + 'while the market fell \u2014 that is <b>defensive positioning, not proven stock-selection alpha</b>. The agent edge above (long WEAVER/HEX) '
           + 'is the real signal; this is context.</div></div>';
      }

      // ---- what to watch ----
      h += '<div class="card st-info"><h3>What to watch this week</h3><div class="desc" style="margin:0">'
         + 'The <b>equity directional t-stat</b> (now '+tnum(ov.t_stat)+') holding \u2265 2 as clean outcomes accrue; whether <b>WEAVER/HEX</b> keep '
         + 'their edge on fresh prices; and whether long-only / regime-untested / conviction-uninformative still hold. A clean \u201cno durable edge\u201d would '
         + 'also be a real result, not a failure.</div></div>';

      return h;
    },

    // news & event intelligence panel — forward calendar + ETF regime baskets + news momentum.
    // Compartmentalized stocks (focus) vs other valuables. Reads ctx.intel. Display-only.
    // event watch panel — append-only recording of major events (SpaceX IPO).
    // Real market data only; money_flow_proxy is derived sector rotation. Reads ctx.events.
    // IPO Watch — self-rotating IPO tracker + learning layer. Reads ctx.ipo (ipo_intelligence.json).
    // Real data only; money_flow_proxy is derived sector rotation. No fabricated prediction.
    // Catalysts — forward gauntlet + clustering->volatility + IPO proximity + the
    // forward-accumulating predictiveness loop. Reads ctx.catalysts (catalyst_learning.json).
    // Deal Journal — read-only trade notes: words (news/catalyst) -> actions (order) -> numbers (outcome).
    // Reads ctx.deals (deal_journal.json). Wins AND losses kept. No live-path changes.
    dealJournalPanel(dj) {
      const OK="var(--st-ok)", BD="var(--st-bad)", WN="var(--st-warn)", DM="var(--dim)";
      const esc = t => String(t==null?"":t).replace(/</g,"&lt;");
      if (!dj) return '<h2>Deal Journal</h2><div class="card st-info">No journal yet — the daily run writes <code>data/deal_journal.json</code>.</div>';
      const sideC = s => (s==="buy"||s==="BUY")?OK : (s==="sell"||s==="SELL")?BD : DM;
      const resC = r => r==="win"?OK : r==="loss"?BD : DM;
      const classBadge = c => {
        const col = c==="ipo_related"?"var(--st-viol)" : c==="narrative_social"?WN : c==="earnings"?OK : c==="macro"?WN : DM;
        return `<span style="color:${col};font-weight:600">${esc(String(c||'unknown').replace(/_/g,' '))}</span>`;
      };

      let h = '<h2>Deal Journal <span class="st-badge st-viol">words \u2192 actions \u2192 numbers</span></h2>';
      h += '<div class="desc">Every order, with the news + catalyst class + regime around it, linked to how it actually turned out \u2014 wins and losses kept equally. Read-only: this observes the trade path, it never changes it. '+esc(dj.note||'')+'</div>';

      h += '<div class="strip">'
        + Render.tile('deals journaled', String(dj.deals_count||0), 'info', 'append-only')
        + Render.tile('live context', String(dj.live_count||0), 'info', 'news captured at trade time')
        + Render.tile('linked to outcomes', String(dj.linked_count||0), (dj.linked_count?'ok':'info'), 'wins + losses')
        + '</div>';

      // by catalyst class
      const bc = dj.by_catalyst_class||[];
      if (bc.length) {
        h += '<div class="card"><h3>By catalyst class</h3>';
        h += '<div class="desc">How trades group by what drove them, and \u2014 where outcomes exist \u2014 how each class performed. Small samples; reads as evidence, not proof.</div>';
        h += Render.table(
          [{h:'catalyst class',k:'c',l:true},{h:'deals',k:'n'},{h:'scored',k:'l'},{h:'win rate',k:'w'},{h:'avg return',k:'r'}],
          bc.map(r=>({c:classBadge(r.catalyst_class),n:r.n,l:r.linked,
            w:r.win_rate==null?'\u2014':Math.round(r.win_rate*100)+'%',
            r:r.avg_return==null?'\u2014':`<span style="color:${r.avg_return>0?OK:r.avg_return<0?BD:DM}">${r.avg_return>0?'+':''}${r.avg_return}%</span>`})));
        h += '</div>';
      }

      // news vs silence
      const nv = dj.news_vs_silence||{};
      const nb = nv.news_backed||{}, si = nv.silent||{};
      if ((nb.n||0)+(si.n||0) > 0) {
        h += '<div class="card"><h3>News-backed vs silent <span style="color:'+DM+';font-weight:400;font-size:11px">live deals \u00b7 fills forward</span></h3>';
        h += Render.table(
          [{h:'',k:'g',l:true},{h:'deals',k:'n'},{h:'scored',k:'l'},{h:'win rate',k:'w'},{h:'avg return',k:'r'}],
          [{g:'<b>news-backed</b> (had headlines)',n:nb.n||0,l:nb.linked||0,w:nb.win_rate==null?'\u2014':Math.round(nb.win_rate*100)+'%',r:nb.avg_return==null?'\u2014':(nb.avg_return>0?'+':'')+nb.avg_return+'%'},
           {g:'<b>silent</b> (no headlines)',n:si.n||0,l:si.linked||0,w:si.win_rate==null?'\u2014':Math.round(si.win_rate*100)+'%',r:si.avg_return==null?'\u2014':(si.avg_return>0?'+':'')+si.avg_return+'%'}]);
        h += '<div class="note">Does news-driven entry beat silent entry? Too few live samples to tell yet \u2014 this is the edge-in-words question, answered as the journal grows.</div></div>';
      }

      // recent deals — the trade notes
      const rec = dj.recent||[];
      h += '<div class="card"><h3>Recent deals \u2014 the notes</h3>';
      if (rec.length) {
        h += Render.table(
          [{h:'time',k:'t'},{h:'acct',k:'a'},{h:'ticker',k:'tk'},{h:'side',k:'s'},{h:'conv',k:'cv'},{h:'class',k:'c',l:true},{h:'why (news)',k:'n',l:true},{h:'result',k:'o'}],
          rec.map(d=>{
            const oc=d.outcome, hl=(d.headlines||[])[0];
            return {
              t:esc(String(d.time||'').slice(0,16).replace('T',' ')), a:esc(d.account),
              tk:'<b>'+esc(d.ticker)+'</b>'+(d.ipo_complex?` <span style="color:var(--st-viol);font-size:10px">IPO</span>`:''),
              s:`<span style="color:${sideC(d.side)};font-weight:600">${esc(d.side)}</span>`,
              cv:d.conviction!=null?Number(d.conviction).toFixed(2):'\u2014',
              c:classBadge(d.catalyst_class),
              n: hl?esc(hl.slice(0,52)):(d.context_basis==='backfill'?'<span style="color:'+DM+'">(pre-journal)</span>':'<span style="color:'+DM+'">no headlines</span>'),
              o: oc?`<span style="color:${resC(oc.result)};font-weight:600">${esc(oc.result)}</span> ${oc.return_pct!=null?((oc.return_pct>0?'+':'')+Number(oc.return_pct).toFixed(2)+'%'):''}`:'<span style="color:'+DM+'">open</span>'
            };
          }));
      } else {
        h += '<div class="note">No deals journaled yet.</div>';
      }
      h += '</div>';
      return h;
    },

    catalystPanel(c) {
      const OK="var(--st-ok)", BD="var(--st-bad)", WN="var(--st-warn)", DM="var(--dim)";
      const esc = t => String(t==null?"":t).replace(/</g,"&lt;");
      if (!c) return '<h2>Catalysts</h2><div class="card st-info">No catalyst learning yet — the daily run writes <code>data/catalyst_learning.json</code>.</div>';
      const magC = m => m==="very_high"?BD : m==="high"?WN : DM;
      const cd = d => d==null?"" : d>1?("in "+d+"d") : d===1?"tomorrow" : d===0?"today" : (Math.abs(d)+"d ago");

      let h = '<h2>Catalysts <span class="st-badge st-viol">ingest \u2192 learn \u2192 teach</span></h2>';
      h += '<div class="desc">What\u2019s coming, how it clusters, how it sits around the IPO, and \u2014 building forward \u2014 which catalyst types actually move stocks. Real events only; the predictiveness loop fills from fired-catalyst \u2192 realized-move links, never fabricated.</div>';

      // ── volatility-cluster banner ──
      const cl = c.clustering||{};
      if (cl.elevated_ahead) {
        const pw = cl.peak_window||{};
        h += '<div class="card st-warn"><b>\u26a0 Elevated volatility expected.</b> '+esc(cl.note||'')
           + (pw.start?(' Heaviest window <b>'+esc(pw.start)+' \u2192 '+esc(pw.end)+'</b> ('+pw.high_impact+' high-impact events).'):'')+'</div>';
      }

      // ── IPO proximity gauntlet ──
      const ip = c.ipo_proximity;
      if (ip && (ip.gauntlet||[]).length) {
        h += '<div class="card"><h3>IPO gauntlet \u2014 '+esc(ip.ipo.company)+(ip.ipo.ticker?(' \u00b7 '+esc(ip.ipo.ticker)):'')+'</h3>';
        h += '<div class="desc">High-impact catalysts within \u00b1'+ip.span_days+' days of the '+esc(ip.ipo.date)+' debut. This cluster is what the market is positioning for.</div>';
        h += Render.table(
          [{h:'date',k:'d'},{h:'event',k:'e',l:true},{h:'impact',k:'m'},{h:'vs debut',k:'r'}],
          ip.gauntlet.map(g=>({d:esc(g.date),e:'<b>'+esc(g.label)+'</b>',
            m:`<span style="color:${magC(g.magnitude)};font-weight:600">${esc(String(g.magnitude||'').replace('_',' '))}</span>`,
            r: g.rel_to_ipo===0?'<b>DEBUT DAY</b>':(Math.abs(g.rel_to_ipo)+'d '+(g.rel_to_ipo<0?'before':'after'))})));
        h += '</div>';
      }

      // ── upcoming gauntlet (macro + universe) ──
      const up = c.upcoming||{}, cnt = up.counts||{};
      h += '<div class="card"><h3>Upcoming \u2014 next catalysts that matter</h3>';
      h += '<div class="strip">'
        + Render.tile('market-moving', String(cnt.very_high||0)+' very-high', (cnt.very_high?'warn':'info'), 'next 30 days')
        + Render.tile('macro events', String((up.macro||[]).length), 'info', 'Fed / CPI / jobs / opex')
        + Render.tile('our universe', String((up.universe||[]).length), 'info', 'earnings on tracked names')
        + '</div>';
      if ((up.macro||[]).length) {
        h += '<h4>Market-wide</h4>';
        h += Render.table(
          [{h:'when',k:'w'},{h:'date',k:'d'},{h:'event',k:'t',l:true},{h:'impact',k:'m'}],
          up.macro.map(e=>({w:cd(e.days_until),d:esc(e.date),t:'<b>'+esc(String(e.type||'').replace('_',' '))+'</b> \u2014 '+esc((e.note||'').slice(0,46)),
            m:`<span style="color:${magC(e.magnitude)};font-weight:600">${esc(String(e.magnitude||'').replace('_',' '))}</span>`})));
      }
      if ((up.universe||[]).length) {
        h += '<h4>On our tracked names</h4>';
        h += Render.table(
          [{h:'when',k:'w'},{h:'date',k:'d'},{h:'ticker',k:'tk'},{h:'event',k:'t'},{h:'impact',k:'m'},{h:'held',k:'hd'}],
          up.universe.map(e=>({w:cd(e.days_until),d:esc(e.date),tk:'<b>'+esc(e.ticker)+'</b>',t:esc(e.type),
            m:`<span style="color:${magC(e.magnitude)};font-weight:600">${esc(String(e.magnitude||'').replace('_',' '))}</span>`,
            hd:e.held?`<span style="color:${OK}">held</span>`:'\u2014'})));
      }
      // daily load sparkline
      const dl = cl.daily_load||[];
      if (dl.length) {
        const mx = Math.max(1, ...dl.map(s=>s.load||0));
        h += '<h4>Catalyst load (next 21 days)</h4><div style="display:flex;gap:3px;align-items:flex-end;height:44px;margin:4px 0">'
          + dl.map(s=>`<div title="${esc(s.date)}: load ${s.load}, ${s.events} event(s)" style="flex:1;min-width:4px;height:${Math.round(6+38*(s.load||0)/mx)}px;background:${s.high_impact>=2?BD:'var(--accent,#6aa3ff)'};opacity:.85;border-radius:2px"></div>`).join('')
          + '</div><div class="note">Taller/red bars = heavier high-impact clustering on that day.</div>';
      }
      h += '</div>';

      // ── learning loop (predictiveness) ──
      const lr = c.learning||{};
      h += '<div class="card"><h3>What we\u2019ve learned \u2014 catalyst predictiveness</h3>';
      h += '<div class="desc">Realized moves on our universe, linked back to the catalyst that fired before them, grouped by type. '+esc(lr.note||'')+' <span style="color:'+DM+'">(ledger: '+(lr.ledger_size||0)+' fired catalysts, '+(lr.linked_outcomes||0)+' linked outcomes)</span></div>';
      if ((lr.by_type_magnitude||[]).length) {
        h += Render.table(
          [{h:'catalyst',k:'t',l:true},{h:'impact',k:'m'},{h:'n',k:'n'},{h:'avg |move|',k:'a'},{h:'avg move',k:'s'},{h:'>1% rate',k:'hr'}],
          lr.by_type_magnitude.map(r=>({t:'<b>'+esc(r.type)+'</b>',m:esc(String(r.magnitude||'').replace('_',' ')),n:r.n,
            a:r.avg_abs_move+'%',s:(r.avg_signed_move>0?'+':'')+r.avg_signed_move+'%',hr:Math.round(r.hit_rate*100)+'%'})));
      } else {
        h += '<div class="note">Empty until catalysts fire and outcomes score from here forward. The ledger starts filling on the next trading day \u2014 honest, growing, no invented numbers.</div>';
      }
      h += '</div>';

      // ── baseline ──
      const bl = c.baseline||{};
      if ((bl.by_vol_state||[]).length) {
        h += '<div class="card"><h3>Baseline \u2014 normal move distribution</h3>';
        h += '<div class="desc">The floor catalyst moves are judged against (clean outcomes). Overall avg |move| '
           + (bl.overall_avg_abs_move!=null?('<b>'+bl.overall_avg_abs_move+'%</b>'):'\u2014')
           + (bl.overall_hit_rate!=null?(' \u00b7 >1% rate <b>'+Math.round(bl.overall_hit_rate*100)+'%</b>'):'')
           + ' \u00b7 n='+(bl.n||0)+'</div>';
        h += Render.table(
          [{h:'volatility state',k:'v',l:true},{h:'n',k:'n'},{h:'avg |move|',k:'a'}],
          bl.by_vol_state.map(b=>({v:esc(String(b.vol_state||'').replace('_',' ')),n:b.n,a:b.avg_abs_move+'%'})));
        h += '</div>';
      }
      return h;
    },

    ipoWatchPanel(ipo) {
      const OK="var(--st-ok)", BD="var(--st-bad)", DM="var(--dim)";
      const esc = t => String(t==null?"":t).replace(/</g,"&lt;");
      if (!ipo) return '<h2>IPO Watch</h2><div class="card st-info">No IPO intelligence yet — the recorder + analyzer write <code>data/ipo_intelligence.json</code> each run.</div>';
      const moveC = v => v>0?OK : v<0?BD : DM;
      const sigC = s => (s==="BUY"||s==="STRONG_BUY")?OK : (s==="SELL"||s==="STRONG_SELL")?BD : DM;
      const cd = d => d==null?"date TBD" : d>1?("in "+d+" days") : d===1?"TOMORROW" : d===0?"TODAY" : d===-1?"yesterday" : (Math.abs(d)+" days ago");
      const usd = v => { if(v==null) return "\u2014"; if(v>=1e12) return "$"+(v/1e12).toFixed(2)+"T"; if(v>=1e9) return "$"+Math.round(v/1e9)+"B"; return "$"+v; };
      const pctRow = (obj) => obj?Object.keys(obj).map(k=>`<span style="margin-right:12px">${k.toUpperCase()} <b style="color:${moveC(obj[k])}">${obj[k]>0?'+':''}${obj[k]}%</b></span>`).join(''):'';

      let h = '<h2>IPO Watch <span class="st-badge st-viol">self-rotating \u00b7 append-only \u00b7 real</span></h2>';
      h += '<div class="desc">Tracking the active IPO from every angle and learning the pattern. When one finishes its window, tracking rotates automatically to the next dated IPO. The playbook turns each completed IPO into a template for the next \u2014 prediction by comparison, never a fabricated model.</div>';

      const a = ipo.active;
      if (a) {
        const arc = a.arc||{}, L = a.latest||{}, m = L.market||{};
        h += '<div class="card"><h3>'+esc(a.company)+(a.ticker?(' \u00b7 '+esc(a.ticker)):'')+'</h3>';
        h += '<div class="strip">'
          + Render.tile('countdown', cd(a.days_until), (a.days_until!=null&&a.days_until<=2&&a.days_until>=-2?'warn':'info'), (a.date||'TBD')+(a.pricing_date?(' \u00b7 prices '+a.pricing_date):''))
          + Render.tile('valuation', usd(a.valuation_usd), 'info', (a.raise_usd?('raise '+usd(a.raise_usd)):a.sector||''))
          + Render.tile('phase', String(a.phase||'').replace(/_/g,' '), 'info', a.exchange||'')
          + Render.tile('recording', a.recording?'LIVE':'idle', a.recording?'ok':'info', (a.snapshot_count||0)+' snapshots')
          + '</div>';
        if ((a.underwriters||[]).length) h += '<div class="desc" style="font-size:12px">Underwriters: '+a.underwriters.map(esc).join(', ')+'</div>';
        h += '<div class="desc">'+esc(a.note||'')+'</div>';

        // ── THE ARC (learning) ──
        const cov = arc.coverage||{};
        h += '<h4>Coverage arc <span style="color:'+DM+';font-weight:400;font-size:11px">attention build-up / decay \u00b7 '+(cov.days_recorded||0)+' day(s) recorded</span></h4>';
        h += '<div class="desc" style="font-size:12px">trend <b>'+esc(cov.trend||'\u2014')+'</b>'
           + (cov.peak?(' \u00b7 peak '+cov.peak.complex_headlines+' headlines on '+esc(cov.peak.date)):'')
           + (cov.by_phase?(' \u00b7 by phase: '+Object.keys(cov.by_phase).map(p=>esc(p.replace(/_/g,' '))+' '+cov.by_phase[p]).join(', ')):'')
           + '</div>';
        const cser = cov.series||[];
        if (cser.length){
          const mx = Math.max(1, ...cser.map(r=>r.complex_headlines||0));
          h += '<div style="display:flex;gap:3px;align-items:flex-end;height:42px;margin:6px 0">'
             + cser.map(r=>`<div title="${esc(r.date)}: ${r.complex_headlines}" style="flex:1;min-width:4px;height:${Math.round(6+36*(r.complex_headlines||0)/mx)}px;background:var(--accent,#6aa3ff);opacity:.8;border-radius:2px"></div>`).join('')
             + '</div>';
        }

        const mk = arc.market||{};
        h += '<h4>Market arc <span style="color:'+DM+';font-weight:400;font-size:11px">how the whole market is moving around it</span></h4>';
        h += '<div class="desc" style="font-size:12px">since window start: '+(pctRow(mk.change_since_window_start_pct)||'<span style="color:'+DM+'">accruing</span>')+'</div>';
        h += '<div class="desc" style="font-size:12px">1-day: '+(pctRow(mk.latest_1d)||'\u2014')+'</div>';
        h += '<div class="desc" style="font-size:12px">1-week: '+(pctRow(mk.latest_1w)||'\u2014')+'  <span style="color:'+DM+'">(the run-in / "freefall")</span></div>';
        h += '<div class="desc" style="font-size:12px">1-month: '+(pctRow(mk.latest_1mo)||'\u2014')+'</div>';

        const rot = arc.sector_rotation||{};
        if ((rot.current||[]).length){
          h += '<h4>Sector rotation <span style="color:'+DM+';font-weight:400;font-size:11px">derived \u2014 not literal dollars</span></h4>';
          if ((rot.winners||[]).length || (rot.losers||[]).length){
            h += '<div class="desc" style="font-size:12px">rotating in: '
               + (rot.winners||[]).map(w=>`<b style="color:${OK}">${esc(w.basket)}</b> +${w.delta_net}`).join(', ')
               + (((rot.losers||[]).length)?' \u00b7 rotating out: '+(rot.losers||[]).map(w=>`<b style="color:${BD}">${esc(w.basket)}</b> ${w.delta_net}`).join(', '):'')
               + '</div>';
          }
          h += Render.table(
            [{h:'basket',k:'b',l:true},{h:'ETF',k:'e'},{h:'net',k:'n'},{h:'stance',k:'s'},{h:'news',k:'hl'}],
            (rot.current||[]).map(b=>({b:esc(b.basket),e:esc(b.etf),n:(b.net_score>0?'+':'')+b.net_score,
              s:`<span style="color:${b.stance==='bullish'?OK:b.stance==='bearish'?BD:DM};font-weight:600">${esc(b.stance)}</span>`, hl:b.headline_count})));
        }

        const hp = arc.hot_persistence||[];
        if (hp.length){
          h += '<h4>Hot-name persistence <span style="color:'+DM+';font-weight:400;font-size:11px">who stays hot vs fades</span></h4>';
          h += '<div class="desc" style="font-size:12px">'
             + hp.map(x=>`<span style="margin-right:12px"><b>${esc(x.ticker)}</b> \u00d7${x.appearances} <span style="color:${x.still_hot?OK:DM}">${x.still_hot?'hot':'faded'}</span></span>`).join('')
             + '</div>';
        }

        const eng = arc.our_engagement||{};
        h += '<h4>Our engagement <span style="color:'+DM+';font-weight:400;font-size:11px">'+(eng.complex_orders_recent||0)+' recent complex orders</span></h4>';
        if (eng.by_account && Object.keys(eng.by_account).length)
          h += '<div class="desc" style="font-size:12px">'+Object.keys(eng.by_account).map(k=>esc(k)+': '+eng.by_account[k]).join(' \u00b7 ')+'</div>';

        // ── LATEST SNAPSHOT ──
        h += '<h4>Latest snapshot</h4>';
        h += '<div class="desc" style="font-size:12px">regime <b>'+esc(m.regime||'\u2014')+'</b>'
           + (m.spy_level?(' \u00b7 SPY '+m.spy_level):'') + (m.qqq_level?(' \u00b7 QQQ '+m.qqq_level):'')
           + (m.xlk_level?(' \u00b7 XLK '+m.xlk_level):'') + '</div>';
        const cx = L.complex||[];
        if (cx.length) h += Render.table(
          [{h:'ticker',k:'t',l:true},{h:'group',k:'g',l:true},{h:'price',k:'p'},{h:'signal',k:'s'},{h:'news',k:'n'},{h:'sector',k:'sc',l:true}],
          cx.map(c=>c.in_universe?({t:'<b>'+esc(c.ticker)+'</b>',g:esc(String(c.group||'').replace(/_/g,' ')),p:c.price!=null?('$'+c.price):'\u2014',
            s:`<span style="color:${sigC(c.signal)};font-weight:600">${esc(c.signal)}</span>`,n:c.headlines,sc:esc(c.sector||'')})
            :({t:'<b>'+esc(c.ticker)+'</b>',g:esc(String(c.group||'').replace(/_/g,' ')),p:'<span style="color:'+DM+'">lists '+esc(a.date||'')+'</span>',s:'\u2014',n:'\u2014',sc:'\u2014'})));
        const oa = L.our_activity||[];
        if (oa.length) { h += '<div class="desc" style="font-size:12px;margin-top:6px">recent complex orders: '
            + oa.map(o=>`<span style="margin-right:10px">${esc(o.account)} <b>${esc(o.symbol)}</b> ${esc(o.side)}${o.notional!=null?(' $'+Math.round(o.notional)):''}</span>`).join('') + '</div>'; }
        h += '</div>';
      }

      // ── PIPELINE (auto-rotating queue) ──
      const pl = ipo.pipeline||[];
      if (pl.length){
        h += '<div class="card"><h3>Pipeline \u2014 the queue</h3>';
        h += '<div class="desc">Ordered by size. Anticipated names have no fabricated date; each activates automatically once a real date is set, after the current one completes.</div>';
        h += Render.table(
          [{h:'company',k:'c',l:true},{h:'ticker',k:'t'},{h:'status',k:'st'},{h:'date',k:'d'},{h:'when',k:'w'},{h:'est. value',k:'v'},{h:'phase',k:'p',l:true}],
          pl.map(r=>({
            c:(r.is_active?'\u25b6 ':'')+'<b>'+esc(r.company)+'</b>', t:esc(r.ticker||'\u2014'),
            st:esc(r.status), d:esc(r.date||'TBD'), w:cd(r.days_until),
            v:usd(r.valuation_usd), p:esc(String(r.phase||'').replace(/_/g,' '))+(r.is_active?' \u00b7 ACTIVE':'')
          })));
        h += '</div>';
      }

      // ── PLAYBOOK ──
      const pb = ipo.playbook||[];
      h += '<div class="card"><h3>Playbook \u2014 completed IPOs</h3>';
      if (pb.length){
        h += Render.table(
          [{h:'company',k:'c',l:true},{h:'ticker',k:'t'},{h:'date',k:'d'},{h:'snapshots',k:'s'},{h:'coverage trend',k:'ct'}],
          pb.map(e=>({c:'<b>'+esc(e.company)+'</b>',t:esc(e.ticker||'\u2014'),d:esc(e.date||''),s:e.snapshot_count,
            ct:esc(((e.arc||{}).coverage||{}).trend||'\u2014')})));
      } else {
        h += '<div class="desc">None complete yet. As each IPO finishes its window, its full arc is frozen here as a template the next IPO is measured against. '+esc(ipo.learning_note||'')+'</div>';
      }
      h += '</div>';
      return h;
    },

    eventWatchPanel(ev) {
      const OK="var(--st-ok)", WN="var(--st-warn)", BD="var(--st-bad)", DM="var(--dim)", HI="var(--hi)";
      const esc = t => String(t==null?"":t).replace(/</g,"&lt;");
      if (!ev || !((ev.events)||[]).length) return '<h2>Event Watch</h2><div class="card st-info">No tracked events yet \u2014 the recorder writes <code>data/event_tracking_summary.json</code> each run; the full append-only time series lives in <code>data/event_tracking/&lt;id&gt;.json</code>.</div>';
      const moveC = v => v>0?OK : v<0?BD : DM;
      const sigC = s => (s==="BUY"||s==="STRONG_BUY")?OK : (s==="SELL"||s==="STRONG_SELL")?BD : DM;
      const countdown = d => d>1?("in "+d+" days") : d===1?"TOMORROW" : d===0?"TODAY" : d===-1?"yesterday" : (Math.abs(d)+" days ago");

      let h = '<h2>Event Watch <span class="st-badge st-viol">append-only \u00b7 real market data</span></h2>';
      h += '<div class="desc">Recording the full arc of major events from every angle \u2014 index moves, the related complex, sector rotation, the hot names, and our own orders. Append-only: every run adds a snapshot that is never overwritten.</div>';

      ((ev.events)||[]).forEach(e => {
        const L = e.latest||{}, m = L.market||{};
        h += '<div class="card"><h3>'+esc(e.label)+'</h3>';
        h += '<div class="strip">'
          + Render.tile('countdown', countdown(e.days_until), ((e.days_until<=2&&e.days_until>=-2)?'warn':'info'), e.date+(e.pricing_date?(' \u00b7 prices '+e.pricing_date):''))
          + Render.tile('phase', String(e.phase||'').replace(/_/g,' '), 'info', e.ticker)
          + Render.tile('recording', e.recording?'LIVE':'idle', (e.recording?'ok':'info'), (e.snapshot_count||0)+' snapshots')
          + Render.tile('regime', m.regime||'\u2014', 'info', 'market state')
          + '</div>';
        h += '<div class="desc">'+esc(e.note||'')+'</div>';

        const mv = (lab,lvl,chg)=> lvl==null?'' : `<span style="margin-right:14px">${lab} <b>${lvl}</b> <span style="color:${moveC(chg)}">${chg>0?'+':''}${chg==null?'':chg}%</span></span>`;
        h += '<div class="desc" style="font-size:12px">'
           + mv('SPY', m.spy_level, m.spy_1d) + mv('QQQ', m.qqq_level, m.qqq_1d)
           + mv('XLK', m.xlk_level, m.xlk_1d) + mv('XLE', m.xle_level, m.xle_1d) + '</div>';

        const cx = L.complex||[];
        if (cx.length){
          h += '<h4>The complex \u2014 names connected to this event</h4>';
          h += Render.table(
            [{h:'ticker',k:'t',l:true},{h:'group',k:'g',l:true},{h:'price',k:'p'},{h:'signal',k:'s'},{h:'news',k:'n'},{h:'sector',k:'sc',l:true}],
            cx.map(c=>c.in_universe?({
              t:'<b>'+esc(c.ticker)+'</b>', g:esc(String(c.group||'').replace(/_/g,' ')), p:c.price!=null?('$'+c.price):'\u2014',
              s:`<span style="color:${sigC(c.signal)};font-weight:600">${esc(c.signal)}</span>`, n:c.headlines, sc:esc(c.sector||'')
            }):({
              t:'<b>'+esc(c.ticker)+'</b>', g:esc(String(c.group||'').replace(/_/g,' ')), p:'<span style="color:'+DM+'">lists '+esc(e.date)+'</span>', s:'\u2014', n:'\u2014', sc:'\u2014'
            })));
        }

        const mf = L.money_flow_proxy||[];
        if (mf.length){
          h += '<h4>Money-flow proxy <span style="color:'+DM+';font-weight:400;font-size:11px">derived sector rotation \u2014 not literal dollars</span></h4>';
          h += Render.table(
            [{h:'basket',k:'b',l:true},{h:'ETF',k:'e'},{h:'net',k:'s'},{h:'stance',k:'st'},{h:'news',k:'n'}],
            mf.map(b=>({b:esc(b.basket),e:esc(b.etf),s:(b.net_score>0?'+':'')+b.net_score,
              st:`<span style="color:${b.stance==='bullish'?OK:b.stance==='bearish'?BD:DM};font-weight:600">${esc(b.stance)}</span>`, n:b.headline_count})));
        }

        const hs = L.hot_stocks||[];
        if (hs.length){
          h += '<h4>Hot right now (loudest in the news)</h4><div class="desc" style="font-size:12px">'
             + hs.map(x=>`<span style="margin-right:12px"><b>${esc(x.ticker)}</b> <span style="color:${sigC(x.signal)}">${esc(x.signal)}</span> \u00b7${x.headlines}hl</span>`).join('')
             + '</div>';
        }

        const oa = L.our_activity||[];
        h += '<h4>Our money in the complex <span style="color:'+DM+';font-weight:400;font-size:11px">'+(L.our_activity_count||0)+' recent orders</span></h4>';
        if (oa.length){
          h += Render.table(
            [{h:'account',k:'a',l:true},{h:'symbol',k:'s'},{h:'side',k:'sd'},{h:'$ notional',k:'n'},{h:'signal',k:'sg'}],
            oa.map(o=>({a:esc(o.account),s:'<b>'+esc(o.symbol)+'</b>',sd:esc(o.side),n:o.notional!=null?('$'+Math.round(o.notional)):'\u2014',sg:esc(o.signal||'')})));
        } else h += '<div class="desc">No orders in the complex yet.</div>';

        h += '<div class="desc" style="margin-top:8px"><b>'+(e.snapshot_count||0)+'</b> snapshots recorded'
           + (e.first_snapshot?(' since '+esc(String(e.first_snapshot).slice(0,16).replace('T',' '))):'')
           + '. Full time series: <code>data/event_tracking/'+esc(e.id)+'.json</code>.</div></div>';
      });
      return h;
    },

    intelPanel(intel) {
      const OK="var(--st-ok)", WN="var(--st-warn)", BD="var(--st-bad)", DM="var(--dim)", HI="var(--hi)";
      const esc = t => String(t==null?"":t).replace(/</g,"&lt;");
      if (!intel) return '<h2>News &amp; Event Intelligence</h2><div class="card st-info">Not generated yet \u2014 written each run as <code>data/news_intelligence.json</code> by the intelligence layer.</div>';
      const cal = intel.event_calendar || {}, cc = cal.counts || {}, sm = intel.summary || {};
      const magC = m => m==="very_high"?BD : m==="high"?WN : DM;
      const stanceC = s => s==="bullish"?OK : s==="bearish"?BD : DM;

      let h = '<h2>News &amp; Event Intelligence <span class="st-badge st-viol">derived \u00b7 words \u2192 thesis</span></h2>';
      h += '<div class="desc">'+esc(intel.thesis||'')+'</div>';

      const nhi = cal.next_high_impact;
      h += '<div class="strip">'
        + Render.tile('stocks tracked', sm.stocks_tracked||0, 'info', (sm.other_tracked||0)+' other valuables')
        + Render.tile('names in the news', sm.names_in_news||0, (sm.names_in_news>0?'ok':'info'), 'today')
        + Render.tile('events ahead', cc.total_dated||0, 'info', 'out to '+(cc.furthest_days||0)+' days')
        + Render.tile('next high-impact', nhi?('+'+nhi.days_until+'d'):'\u2014', (nhi&&nhi.days_until<=3?'warn':'info'), nhi?esc((nhi.note||'').slice(0,26)):'')
        + '</div>';

      // ── event calendar ──
      h += '<div class="card"><h3>Event calendar \u2014 dated, way ahead</h3>';
      h += '<div class="desc">Real ingested catalysts + a curated forward registry (FOMC/jobs/OPEX verified; IPOs anticipated, dates TBD). '
         + (cc.from_feed||0)+' from feed \u00b7 '+(cc.curated_ahead||0)+' curated ahead \u00b7 '+(cc.very_high||0)+' high-impact.</div>';
      const ev = (cal.dated||[]).slice(0, 18);
      h += Render.table(
        [{h:'date',k:'d',l:true},{h:'in',k:'u'},{h:'impact',k:'m'},{h:'type',k:'t'},{h:'ticker',k:'k'},{h:'what',k:'n',l:true}],
        ev.map(e=>({
          d:e.date, u:'+'+e.days_until+'d',
          m:`<span style="color:${magC(e.magnitude)};font-weight:600">${e.magnitude==='very_high'?'HIGH':e.magnitude}</span>`,
          t:esc(e.type), k:esc(e.ticker||'\u2014'), n:esc((e.note||'').slice(0,52))
        })));
      if ((cal.dated||[]).length>18) h+='<div class="desc">+ '+((cal.dated||[]).length-18)+' more dated events through +'+(cc.furthest_days||0)+' days.</div>';
      if ((cal.watchlist||[]).length){
        h += '<h4>Anticipated catalysts (date TBD \u2014 tracked, not invented)</h4>'
           + '<ul style="margin:4px 0 0;padding-left:18px;color:var(--dim);font-size:11px;line-height:1.6">'
           + (cal.watchlist||[]).map(w=>'<li><b style="color:'+HI+'">'+esc(w.label)+'</b> \u2014 '+esc(w.note)+'</li>').join('')
           + '</ul>';
      }
      h += '</div>';

      // ── per-side (stocks / other) ──
      const renderSide = (side, title, focus) => {
        if (!side) return '';
        let s = '<div class="card"><h3>'+title+(focus?' <span style="color:'+DM+';font-weight:400;font-size:11px">the focus</span>':'')+'</h3>';
        const bk = side.baskets||[];
        if (bk.length){
          s += '<h4>Regime baskets ('+bk.length+')</h4>';
          s += Render.table(
            [{h:'basket',k:'b',l:true},{h:'ETF',k:'e'},{h:'n',k:'n'},{h:'net',k:'s'},{h:'stance',k:'st'},{h:'news',k:'h'}],
            bk.slice(0,12).map(b=>({
              b:esc(b.basket), e:esc(b.etf), n:b.members,
              s:(b.net_score>0?'+':'')+b.net_score,
              st:`<span style="color:${stanceC(b.stance)};font-weight:600">${b.stance}</span>`,
              h:b.headline_count
            })));
        } else s += '<div class="desc">No baskets in this group.</div>';
        const mo = side.momentum||[];
        if (mo.length){
          s += '<h4>Loudest in the news (volume \u00d7 direction)</h4>';
          s += Render.table(
            [{h:'ticker',k:'k',l:true},{h:'sector',k:'sc'},{h:'headlines',k:'h'},{h:'signal',k:'sg'},{h:'momentum',k:'m'},{h:'news',k:'ns'}],
            mo.slice(0,10).map(m=>({
              k:'<b>'+esc(m.ticker)+'</b>', sc:esc(m.sector), h:m.headlines, sg:esc(m.signal),
              m:`<span style="color:${m.momentum>0?OK:m.momentum<0?BD:DM}">${m.momentum>0?'+':''}${m.momentum}</span>`,
              ns:esc(m.news_state)
            })));
        } else s += '<div class="desc">No names carrying headlines in this group right now.</div>';
        return s + '</div>';
      };
      h += renderSide(intel.stocks, 'Stocks', true);
      h += renderSide(intel.other, 'Other valuables (crypto / tokens)', false);

      h += '<div class="card st-info"><div class="desc" style="margin:0"><b>Phase 1 \u2014 intelligence layer (display-only).</b> '
         + 'This SEES the words and events. Phase 2 gives it teeth: a news snapshot written into each trade deal (when + why), '
         + 'a news-informed regime, and basket-aware positioning \u2014 built after Monday confirms clean data.</div></div>';
      return h;
    },

    // canonical glossary — static educational text (NO metrics). For tooltips/explainers.
    GLOSSARY: {
      stale: "stale_price_suspected: the scorer saw ~no price move (entry≈exit) for this outcome. A 'win' on a stale outcome is an artifact, not edge. ~90% of outcomes are stale.",
      wilson: "Wilson 95% CI: the plausible range for the true win-rate given the sample size. A wide bar = few samples = low confidence. A 92% on N=25 is far less trustworthy than on N=1200.",
      verified: "Verified: an agent with clean (non-stale) sample N ≥ 30. Only these are headline-eligible. It is NOT a claim of profit — only of sufficient clean evidence to start judging.",
      artifact_risk: "Artifact-risk: scored but with ZERO clean samples or ≥95% stale. High win-rates here are artifacts. Quarantined out of the headline; telemetry untouched.",
      true_realized: "True realized = (current_equity − starting) + savings. Harvester agents sweep gains into savings, so current_equity≈10000 hides real performance; this column is the truth.",
      clean_n: "Clean N: count of non-stale outcomes. The only sample that can support an edge claim. Small clean N = treat any win-rate with suspicion.",
      raw_vs_clean: "Raw vs clean: canonical win% (all outcomes) vs stale-excluded win%. A large gap means the headline number is inflated by stale artifacts."
    },
    explain(term) { return Render.GLOSSARY[term] || ""; },
    help(term) { const t = Render.GLOSSARY[term]; return t ? `<span class="st-help" title="${t.replace(/"/g,'&quot;')}">?</span>` : ""; }
  };

  // ===========================================================================
  // DATA — browser-only canonical loaders (graceful null). Not used in node tests.
  // ===========================================================================
  const Data = {
    base: "data/",
    async load(file) {
      try { const r = await fetch(Data.base + file + "?_=" + Date.now()); if (!r.ok) return null; return await r.json(); }
      catch (e) { return null; }
    },
    async loadAll() {
      const [scoring, portfolios, risk, legacy, h3, h5, history, equity, bills, edge, benchmark, intel, events, ipo, catalysts, deals] = await Promise.all([
        Data.load("scoring.json"), Data.load("agent_portfolios.json"), Data.load("risk_state.json"),
        Data.load("alpaca_paper_state.json"), Data.load("alpaca_h3_state.json"), Data.load("alpaca_h5_state.json"),
        Data.load("history.json"), Data.load("alpaca_equity_curve.json"), Data.load("bills_paid_leaderboard.json"),
        Data.load("edge_study.json"), Data.load("benchmarking.json"), Data.load("news_intelligence.json"),
        Data.load("event_tracking_summary.json"), Data.load("ipo_intelligence.json"), Data.load("catalyst_learning.json"), Data.load("deal_journal.json")
      ]);
      return { scoring, portfolios, risk, legacy, h3, h5, history, equity, bills, edge, benchmark, intel, events, ipo, catalysts, deals };
    }
  };

  const ST = { Const, util, Compute, Detect, Render, Data, VERSION: "S5.0" };
  if (typeof module !== "undefined" && module.exports) module.exports = ST;
  root.ST = ST;
})(typeof window !== "undefined" ? window : globalThis);
