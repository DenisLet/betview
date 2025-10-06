// /js/charts.js
// Использует window.Chart, window['chartjs-plugin-annotation'],
// window.__GE_STATE__ (STAT_TYPE, HA_MODE, PATTERN_K, TOL, HANDICAP_MODE, getTeamNames, getSeasonsAll)
// и window.__GE_API__ (ensureHistoryLoaded, getSuperProgForecast)

function color(i){
  const p = ['#6EE7B7','#93C5FD','#FCA5A5','#FCD34D','#A78BFA','#A7F3D0','#F9A8D4','#FDBA74','#34D399','#60A5FA','#F87171','#FBBF24','#C4B5FD','#F472B6','#FB923C'];
  return p[i % p.length];
}

function toNum(x){ const n = Number(x); return Number.isFinite(n) ? n : null; }
function median(arr){ const a = arr.map(toNum).filter(v => v !== null).sort((x,y)=>x-y); const n=a.length; if(!n) return null; return n%2 ? a[(n-1)/2] : (a[n/2-1]+a[n/2])/2; }
function mean(arr){ const a = arr.map(toNum).filter(v => v !== null); const n=a.length; if(!n) return null; return a.reduce((s,v)=>s+v,0)/n; }

/* ======== базовая метрика + спец-ключи для форы ======== */
function metricValue(p, metricKey){
  if (metricKey in p) return p[metricKey]; // уже предрасчитано в API

  // goals
  if (metricKey === 'goal_diff') {
    const gf = toNum(p.goals_for), ga = toNum(p.goals_against);
    return (gf==null||ga==null)? null : (gf - ga);
  }
  if (metricKey === 'goals_against_neg') {
    const ga = toNum(p.goals_against);
    return (ga==null) ? null : -ga;
  }

  // corners
  if (metricKey === 'corner_diff') {
    const cf = toNum(p.corners_for), ca = toNum(p.corners_against);
    return (cf==null||ca==null)? null : (cf - ca);
  }
  if (metricKey === 'corners_against_neg') {
    const ca = toNum(p.corners_against);
    return (ca==null) ? null : -ca;
  }

  // cards (yellow)
  if (metricKey === 'cards_diff') {
    const cf = toNum(p.cards_for), ca = toNum(p.cards_against);
    return (cf==null||ca==null)? null : (cf - ca);
  }
  if (metricKey === 'cards_against_neg') {
    const ca = toNum(p.cards_against);
    return (ca==null) ? null : -ca;
  }

  // shots
  if (metricKey === 'shots_diff') {
    const sf = toNum(p.shots_for), sa = toNum(p.shots_against);
    return (sf==null||sa==null)? null : (sf - sa);
  }
  if (metricKey === 'shots_against_neg') {
    const sa = toNum(p.shots_against);
    return (sa==null) ? null : -sa;
  }

  // shots on target
  if (metricKey === 'sot_diff') {
    const tf = toNum(p.sot_for), ta = toNum(p.sot_against);
    return (tf==null||ta==null)? null : (tf - ta);
  }
  if (metricKey === 'sot_against_neg') {
    const ta = toNum(p.sot_against);
    return (ta==null) ? null : -ta;
  }

  return null;
}

/* ======== серия значений (включая форные производные) ======== */
function seriesFor(points, seasonLabel, teamId, haMode, metricKey){
  const rows = (Array.isArray(points) ? points : []).filter(p=>{
    if(p.team_id !== teamId) return false;
    if(seasonLabel && p.season !== seasonLabel) return false;
    if(haMode === 'home' && p.ha !== 'H') return false;
    if(haMode === 'away' && p.ha !== 'A') return false;
    return true;
  }).slice().sort((a,b)=> a.date < b.date ? -1 : 1);

  // выбираем пару (за/против)
  function pairByType(p, typ){
    switch(typ){
      case 'goals':   return [toNum(p.goals_for),   toNum(p.goals_against)];
      case 'corners': return [toNum(p.corners_for), toNum(p.corners_against)];
      case 'cards':   return [toNum(p.cards_for),   toNum(p.cards_against)];
      case 'shots':   return [toNum(p.shots_for),   toNum(p.shots_against)];
      case 'sot':     return [toNum(p.sot_for),     toNum(p.sot_against)];
      default:        return [null, null];
    }
  }

  const STAT_TYPE = (window.__GE_STATE__ && window.__GE_STATE__.STAT_TYPE) || 'goals';
  const isHandicapDerived = (
    metricKey.endsWith('_diff')   ||
    metricKey.endsWith('_roll3')  ||
    metricKey.endsWith('_ewma')   ||
    metricKey.endsWith('_against_neg')
  );

  // для форных ключей — всегда берём пару по текущему STAT_TYPE
  // для «обычных» — используем metricValue (тоталы и т.п.)
  let baseDiff = null, roll3 = null, ewma = null;

  if (isHandicapDerived) {
    const diffs = rows.map(p=>{
      const [vf, va] = pairByType(p, STAT_TYPE);
      if (vf===null || va===null) return null;
      return vf - va;
    });

    baseDiff = diffs;

    // rolling-3
    roll3 = [];
    for(let i=0;i<diffs.length;i++){
      const windowVals = diffs.slice(Math.max(0,i-2), i+1).filter(v=>v!==null);
      roll3.push(windowVals.length ? windowVals.reduce((s,v)=>s+v,0)/windowVals.length : null);
    }

    // EWMA: HL = 5 матчей
    ewma = [];
    {
      const alpha = 1 - Math.pow(0.5, 1/5);
      let prev = null;
      for(let i=0;i<diffs.length;i++){
        const x = diffs[i];
        if(x===null){ ewma.push(prev); continue; }
        prev = (prev===null) ? x : (alpha*x + (1-alpha)*prev);
        ewma.push(prev);
      }
    }
  }

  function yFor(p, idx){
    if (metricKey.endsWith('_diff'))   return baseDiff ? baseDiff[idx] : null;
    if (metricKey.endsWith('_roll3'))  return roll3 ? roll3[idx] : null;
    if (metricKey.endsWith('_ewma'))   return ewma ? ewma[idx] : null;
    return metricValue(p, metricKey); // обычные (тоталы/for/against)
  }

  return rows.map((p,i)=>({
    x:i+1,
    y: yFor(p, i),
    date:p.date, ha:p.ha,
    match_home:p.match_home, match_away:p.match_away, score:p.score,
    // для Skellam по голам
    goals_for: toNum(p.goals_for),
    goals_against: toNum(p.goals_against),
  }));
}

/* ======== статистики по готовой серии ======== */
function computeStat(points, seasonLabel, teamId, metricKey, kind, haMode){
  const s = seriesFor(points, seasonLabel, teamId, haMode, metricKey)
              .map(r=>toNum(r.y))
              .filter(v=>v!==null);
  if (!s.length) return null;
  return (kind === 'mean') ? mean(s) : median(s);
}

function maxYFromDatasets(dsets){
  let m = 0;
  for(const ds of (dsets || [])){
    for(const p of (ds.data||[])){ const v = toNum(p.y); if(v!==null && v>m) m=v; }
  }
  return m;
}

/* === простые прогнозы (▲, ◆) === */
function predictPatternK(currentRows, historyRows, K=2, tol=1){
  if(currentRows.length < K) return { value:null, count:0 };
  const pat = currentRows.slice(-K).map(r => toNum(r.y));
  if(pat.some(v=>v===null)) return { value:null, count:0 };

  // разделим на сезоны по x==1
  const seasons = []; let cur = [];
  for(const r of historyRows){ if(r.x===1 && cur.length){ seasons.push(cur); cur=[]; } cur.push(r); }
  if(cur.length) seasons.push(cur);

  const tau = (tol === 0) ? 0.20 : 0.90;

  let num=0, den=0, cnt=0;
  for(const s of seasons){
    const vals = s.map(r => toNum(r.y));
    for(let i=0; i + K < vals.length; i++){
      let ok = true, d2 = 0;
      for(let j=0;j<K;j++){
        const a = vals[i+j], b = pat[j];
        if(a===null || b===null){ ok=false; break; }
        if(tol===0 ? (a!==b) : (Math.abs(a-b)>tol)){ ok=false; break; }
        d2 += (a-b)*(a-b);
      }
      if(!ok) continue;
      const nxt = vals[i+K];
      if(nxt===null) continue;
      const w = Math.exp(- d2 / (2*tau*tau));
      num += w * nxt; den += w; cnt++;
    }
  }
  if(den>0) return { value: num/den, count: cnt };
  return { value:null, count:0 };
}

/* === kernel-прогноз === */
function kernelForecast(currentRows, historyRows, metricKey, tol){
  const base = {
    // goals — фора
    goal_diff:{k:3,sigma0:0.35,sigma1:1.20},
    goal_diff_roll3:{k:3,sigma0:0.35,sigma1:1.20},
    goal_diff_ewma:{k:3,sigma0:0.35,sigma1:1.20},
    goals_against_neg:{k:2,sigma0:0.30,sigma1:0.95},

    // corners — фора
    corner_diff:{k:3,sigma0:0.55,sigma1:1.60},
    corner_diff_roll3:{k:3,sigma0:0.55,sigma1:1.60},
    corner_diff_ewma:{k:3,sigma0:0.55,sigma1:1.60},
    corners_against_neg:{k:2,sigma0:0.45,sigma1:1.30},

    // cards — фора
    cards_diff:{k:3,sigma0:0.40,sigma1:1.10},
    cards_diff_roll3:{k:3,sigma0:0.40,sigma1:1.10},
    cards_diff_ewma:{k:3,sigma0:0.40,sigma1:1.10},
    cards_against_neg:{k:2,sigma0:0.35,sigma1:0.95},

    // shots — фора
    shots_diff:{k:3,sigma0:1.8,sigma1:4.5},
    shots_diff_roll3:{k:3,sigma0:1.8,sigma1:4.5},
    shots_diff_ewma:{k:3,sigma0:1.8,sigma1:4.5},
    shots_against_neg:{k:2,sigma0:1.4,sigma1:3.5},

    // SOT — фора
    sot_diff:{k:3,sigma0:0.6,sigma1:1.6},
    sot_diff_roll3:{k:3,sigma0:0.6,sigma1:1.6},
    sot_diff_ewma:{k:3,sigma0:0.6,sigma1:1.6},
    sot_against_neg:{k:2,sigma0:0.55,sigma1:1.4},

    // тоталы/обычные
    total_goals:{k:3,sigma0:0.35,sigma1:1.20},
    goals_for:{k:2,sigma0:0.30,sigma1:0.95},
    goals_against:{k:2,sigma0:0.30,sigma1:0.95},

    total_corners:{k:3,sigma0:0.55,sigma1:1.60},
    corners_for:{k:2,sigma0:0.45,sigma1:1.30},
    corners_against:{k:2,sigma0:0.45,sigma1:1.30},

    total_cards:{k:3,sigma0:0.40,sigma1:1.10},
    cards_for:{k:2,sigma0:0.35,sigma1:0.95},
    cards_against:{k:2,sigma0:0.35,sigma1:0.95},

    total_shots:{k:3,sigma0:1.8,sigma1:4.5},
    shots_for:{k:2,sigma0:1.4,sigma1:3.5},
    shots_against:{k:2,sigma0:1.4,sigma1:3.5},

    total_sot:{k:3,sigma0:0.6,sigma1:1.6},
    sot_for:{k:2,sigma0:0.55,sigma1:1.4},
    sot_against:{k:2,sigma0:0.55,sigma1:1.4},
  };
  const cfg = base[metricKey] || { k:2, sigma0:0.35, sigma1:1.0 };
  const sigma = (tol === 0) ? cfg.sigma0 : cfg.sigma1;
  const k = cfg.k;

  if(currentRows.length < k) return { value:null, weight:0 };
  const pat = currentRows.slice(-k).map(p => toNum(p.y));
  if(pat.some(v => v===null)) return { value:null, weight:0 };

  let num = 0, den = 0;
  for (let i=0; i + k < historyRows.length; i++) {
    const wwin = historyRows.slice(i, i+k).map(p => toNum(p.y));
    if(wwin.some(v => v===null)) continue;

    let d2 = 0;
    for (let t=0; t<k; t++) d2 += (wwin[t] - pat[t])**2;
    const w = Math.exp(- d2 / (2 * sigma * sigma));

    const next = toNum(historyRows[i+k].y);
    if (w > 1e-9 && next !== null) { num += w * next; den += w; }
  }
  if (den === 0) return { value:null, weight:0 };
  return { value: num / den, weight: den };
}

/* ===== Байес: Пуассон (тоталы/обычные) и Skellam (фора по голам) ===== */
function gammaFromMoments(m, v){
  if(!(isFinite(m) && m>0) || !(isFinite(v) && v>0)) return {alpha: 1, beta: 1/Math.max(m,1e-6)};
  if(v <= m + 1e-6){ const a=1e6, b=a/Math.max(m,1e-6); return { alpha:a, beta:b }; }
  const alpha = (m*m) / (v - m);
  const beta  = alpha / m;
  if(!isFinite(alpha) || !isFinite(beta) || alpha<=0 || beta<=0){
    return { alpha: 1, beta: 1/Math.max(m,1e-6) };
  }
  return { alpha, beta };
}

function bayesPoissonForecast(curSeries, leagueHistVals){
  const A = leagueHistVals.map(toNum).filter(v=>v!==null);
  if(A.length === 0){ return { value:null, alpha:0, beta:0 }; }
  const m = mean(A);
  const v = (()=>{ const mu=m; const dif=A.map(x=> (x-mu)*(x-mu) ); return dif.reduce((s,x)=>s+x,0)/(A.length-1||1); })();
  const { alpha, beta } = gammaFromMoments(m, v);

  const cur = curSeries.map(r=>toNum(r.y)).filter(v=>v!==null);
  const sumy = cur.reduce((s,x)=>s+x,0);
  const n = cur.length;

  const alphaPost = alpha + sumy;
  const betaPost  = beta  + n;
  const lambdaHat = alphaPost / betaPost;

  return { value: lambdaHat, alpha: alphaPost, beta: betaPost };
}

function bayesSkellamForecast(curRowsGfGa, leagueRowsGfGa){
  const toPairs = rows => rows.map(r=>({
    gf: toNum(r.goals_for),
    ga: toNum(r.goals_against)
  })).filter(q=>q.gf!==null && q.ga!==null);

  const L = toPairs(leagueRowsGfGa);
  if(!L.length) return { value:null };

  const meanVar = arr => {
    const a = arr.filter(v=>v!==null);
    if(!a.length) return {m:0.8, v:1.2};
    const m = a.reduce((s,x)=>s+x,0)/a.length;
    const v = a.reduce((s,x)=>s+(x-m)*(x-m),0)/Math.max(1,a.length-1);
    return { m: Math.max(m, 0.01), v: Math.max(v, 0.02) };
  };
  const { m:mf, v:vf } = meanVar(L.map(q=>q.gf));
  const { m:ma, v:va } = meanVar(L.map(q=>q.ga));
  const { alpha:af, beta:bf } = gammaFromMoments(mf, vf);
  const { alpha:aa, beta:ba } = gammaFromMoments(ma, va);

  const C = toPairs(curRowsGfGa);
  const sumGF = C.reduce((s,q)=>s+q.gf,0);
  const sumGA = C.reduce((s,q)=>s+q.ga,0);
  const n = C.length;

  const alphaF = af + sumGF;
  const betaF  = bf + n;
  const alphaA = aa + sumGA;
  const betaA  = ba + n;

  const lambdaF = alphaF / betaF;
  const lambdaA = alphaA / betaA;

  return { value: lambdaF - lambdaA, lambdaF, lambdaA, alphaF, betaF, alphaA, betaA };
}

/* ===== UI построение ===== */
export function buildSeasonShell(seasonLabel, idx){
  const holder = document.createElement('div');
  holder.className = 'season-card';

  const title = document.createElement('div');
  title.className = 'season-title';

  const { STAT_TYPE, HANDICAP_MODE } = window.__GE_STATE__;
  const typeLabel =
    STAT_TYPE === 'corners' ? ' (Угловые)'
  : STAT_TYPE === 'cards'   ? ' (Жёлтые карточки)'
  : STAT_TYPE === 'shots'   ? ' (Удары)'
  : STAT_TYPE === 'sot'     ? ' (Удары в створ)'
  : STAT_TYPE === 'goals' && HANDICAP_MODE ? ' (Голы — фора)'
  : '';

  title.textContent = `Сезон ${seasonLabel}${typeLabel}`;

  const nav = document.createElement('div');
  nav.className = 'season-navbar';
  const prevBtn = document.createElement('button');
  prevBtn.className = 'arrow'; prevBtn.title = 'Предыдущий сезон'; prevBtn.innerHTML = '◀ предыдущий';
  const nextBtn = document.createElement('button');
  nextBtn.className = 'arrow'; nextBtn.title = 'Следующий сезон'; nextBtn.innerHTML = 'следующий ▶';
  nav.appendChild(prevBtn);
  nav.appendChild(nextBtn);

  const seasonsAll = window.__GE_STATE__.getSeasonsAll();
  const isOldest = idx === seasonsAll.length - 1;
  const isNewest = idx === 0;
  if(isOldest) prevBtn.setAttribute('disabled', 'true');
  if(isNewest) nextBtn.setAttribute('disabled', 'true');

  prevBtn.addEventListener('click', () => window.dispatchEvent(new CustomEvent('GE_SEASON_DELTA', { detail:+1 })));
  nextBtn.addEventListener('click', () => window.dispatchEvent(new CustomEvent('GE_SEASON_DELTA', { detail:-1 })));

  const stack = document.createElement('div'); stack.className = 'stack';

  const METRICS =
    window.__GE_STATE__.HANDICAP_MODE ? (
      STAT_TYPE === 'goals' ? [
        { key:'goal_diff',          title:'Фора (GF − GA)' },
        { key:'goal_diff_roll3',    title:'Фора: роллинг средняя (3)' },
        { key:'goal_diff_ewma',     title:'Фора: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'corners' ? [
        { key:'corner_diff',        title:'Фора по угловым (CF − CA)' },
        { key:'corner_diff_roll3',  title:'Фора угловые: роллинг (3)' },
        { key:'corner_diff_ewma',   title:'Фора угловые: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'cards' ? [
        { key:'cards_diff',         title:'Фора по карточкам (CF − CA)' },
        { key:'cards_diff_roll3',   title:'Фора карточки: роллинг (3)' },
        { key:'cards_diff_ewma',    title:'Фора карточки: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'shots' ? [
        { key:'shots_diff',         title:'Фора по ударам (SF − SA)' },
        { key:'shots_diff_roll3',   title:'Фора удары: роллинг (3)' },
        { key:'shots_diff_ewma',    title:'Фора удары: EWMA (HL=5)' }
      ]
    : /* sot */ [
        { key:'sot_diff',           title:'Фора по ударам в створ (SoTF − SoTA)' },
        { key:'sot_diff_roll3',     title:'Фора в створ: роллинг (3)' },
        { key:'sot_diff_ewma',      title:'Фора в створ: EWMA (HL=5)' }
      ]
    ) : (
      STAT_TYPE === 'corners' ? [
        { key:'total_corners',   title:'Всего угловых (CF+CA)' },
        { key:'corners_for',     title:'Подаёт команда (CF)' },
        { key:'corners_against', title:'Подаёт соперник (CA)' }
      ]
    : STAT_TYPE === 'cards' ? [
        { key:'total_cards',   title:'Всего карточек (CF+CA)' },
        { key:'cards_for',     title:'Карточки команды (CF)' },
        { key:'cards_against', title:'Карточки соперника (CA)' }
      ]
    : STAT_TYPE === 'shots' ? [
        { key:'total_shots',   title:'Всего ударов (SF+SA)' },
        { key:'shots_for',     title:'Удары команды (SF)' },
        { key:'shots_against', title:'Удары соперника (SA)' }
      ]
    : STAT_TYPE === 'sot' ? [
        { key:'total_sot',   title:'Всего в створ (SoTF+SoTA)' },
        { key:'sot_for',     title:'В створ команды (SoTF)' },
        { key:'sot_against', title:'В створ соперника (SoTA)' }
      ]
    : [
        { key:'total_goals',   title:'Всего в матче (GF+GA)' },
        { key:'goals_for',     title:'Забитые (GF)' },
        { key:'goals_against', title:'Пропущенные (GA)' }
      ]);

  const legendText = `<span class="meta"><span class="tri"></span>prog &nbsp;&nbsp; <span class="dia"></span>kprog &nbsp;&nbsp; <span class="star">★</span>bprog &nbsp;&nbsp; <span>◈ sprog</span></span>`;

  const chartObjs = {};
  METRICS.forEach(m => {
    const box = document.createElement('div'); box.className = 'chartbox';
    const ttl = document.createElement('div'); ttl.className = 'charttitle';
    ttl.innerHTML = `<span>${m.title}</span>${legendText}`;

    const wrap = document.createElement('div'); wrap.className = 'chartwrap';
    const canvas = document.createElement('canvas');

    const info = document.createElement('div'); info.className='infopanel'; info.textContent='Кликни точку на графике';
    const tech = document.createElement('div'); tech.className='techline'; tech.textContent='';

    wrap.appendChild(canvas); box.appendChild(ttl); box.appendChild(wrap);
    box.appendChild(info); box.appendChild(tech); stack.appendChild(box);

    const chart = new Chart(canvas.getContext('2d'), {
      type:'line',
      data:{ datasets:[] },
      options:{
        responsive:true, maintainAspectRatio:false, parsing:false, animation:false,
        layout:{ padding:{ top:36, bottom:22, left:8, right:64 } },
        scales:{
          x:{ type:'linear', title:{display:true,text:'Номер матча',color:'#bbb'},
              grid:{color:'#222'}, ticks:{color:'#bbb', stepSize:1} },
          y:{ beginAtZero: !HANDICAP_MODE, suggestedMin: HANDICAP_MODE ? undefined : 0,
              title:{display:true,text:'Значение метрики',color:'#bbb'},
              ticks:{color:'#bbb', stepSize:1}, grid:{color:'#222'} }
        },
        plugins:{
          legend:{ position:'bottom', labels:{ color:'#ddd' } },
          tooltip:{ enabled:false },
          annotation:{ annotations:{}, clip:false }
        },
        elements:{ point:{ radius:5, hitRadius:12 } },
        interaction:{ mode:'nearest', intersect:false, axis:'xy' }
      }
    });

    if (HANDICAP_MODE) {
      chart.options.scales.y.beginAtZero = false;
      chart.options.scales.y.suggestedMin = undefined;
    }

    canvas.addEventListener('click', (evt) => {
      const elems = chart.getElementsAtEventForMode(evt, 'nearest', { intersect:false, axis:'xy' }, true);
      if(!elems.length){ return; }
      const { datasetIndex, index } = elems[0];
      const dp = chart.data.datasets[datasetIndex].data[index];
      const teamLabel = chart.data.datasets[datasetIndex].label.split(' (')[0];
      const ha = dp.ha === 'H' ? 'дом' : (dp.ha === 'A' ? 'выезд' : '—');
      const valStr = Number.isFinite(dp.y) ? String(dp.y) : '-';
      const scoreLine = (dp.match_home && dp.match_away && dp.score) ? `Матч: ${dp.match_home} ${dp.score} ${dp.match_away}` : 'Матч: — — —';
      const dateLine  = dp.date ? dp.date : '—';
      const haLine    = (ha === '—') ? '—' : `${ha}`;
      info.textContent = [
        `${teamLabel}: ${valStr}`,
        scoreLine,
        `${haLine}, дата: ${dateLine}`
      ].join('\n');
    });

    chartObjs[m.key] = { chart, info, tech, teamColorById:{} };
  });

  holder.appendChild(title);
  holder.appendChild(nav);
  holder.appendChild(stack);
  const root = document.getElementById('seasonView');
  root.appendChild(holder);
  return chartObjs;
}

export async function fillChartsForSeason(seasonLabel, chartObjs, points){
  const { HA_MODE, STAT_TYPE, HANDICAP_MODE, getTeamNames } = window.__GE_STATE__;
  const teamNames = getTeamNames();
  const teamsToShow = (() => {
    const sel1 = document.getElementById('team1')?.value;
    const sel2 = document.getElementById('team2')?.value;
    const ids = [];
    if (sel1) ids.push(Number(sel1));
    if (sel2 && sel2 !== sel1) ids.push(Number(sel2));
    const vis = [];
    if (ids[0] && document.getElementById('showTeam1')?.checked) vis.push(ids[0]);
    if (ids[1] && document.getElementById('showTeam2')?.checked) vis.push(ids[1]);
    return vis;
  })();

  const METRICS =
    HANDICAP_MODE ? (
      STAT_TYPE === 'goals' ? [
        { key:'goal_diff',          title:'Фора (GF − GA)' },
        { key:'goal_diff_roll3',    title:'Фора: роллинг средняя (3)' },
        { key:'goal_diff_ewma',     title:'Фора: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'corners' ? [
        { key:'corner_diff',        title:'Фора по угловым (CF − CA)' },
        { key:'corner_diff_roll3',  title:'Фора угловые: роллинг (3)' },
        { key:'corner_diff_ewma',   title:'Фора угловые: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'cards' ? [
        { key:'cards_diff',         title:'Фора по карточкам (CF − CA)' },
        { key:'cards_diff_roll3',   title:'Фора карточки: роллинг (3)' },
        { key:'cards_diff_ewma',    title:'Фора карточки: EWMA (HL=5)' }
      ]
    : STAT_TYPE === 'shots' ? [
        { key:'shots_diff',         title:'Фора по ударам (SF − SA)' },
        { key:'shots_diff_roll3',   title:'Фора удары: роллинг (3)' },
        { key:'shots_diff_ewma',    title:'Фора удары: EWMA (HL=5)' }
      ]
    : /* sot */ [
        { key:'sot_diff',           title:'Фора по ударам в створ (SoTF − SoTA)' },
        { key:'sot_diff_roll3',     title:'Фора в створ: роллинг (3)' },
        { key:'sot_diff_ewma',      title:'Фора в створ: EWMA (HL=5)' }
      ]
    ) : (
      STAT_TYPE === 'corners' ? [
        { key:'total_corners',   title:'Всего угловых (CF+CA)' },
        { key:'corners_for',     title:'Подаёт команда (CF)' },
        { key:'corners_against', title:'Подаёт соперник (CA)' }
      ]
    : STAT_TYPE === 'cards' ? [
        { key:'total_cards',   title:'Всего карточек (CF+CA)' },
        { key:'cards_for',     title:'Карточки команды (CF)' },
        { key:'cards_against', title:'Карточки соперника (CA)' }
      ]
    : STAT_TYPE === 'shots' ? [
        { key:'total_shots',   title:'Всего ударов (SF+SA)' },
        { key:'shots_for',     title:'Удары команды (SF)' },
        { key:'shots_against', title:'Удары соперника (SA)' }
      ]
    : STAT_TYPE === 'sot' ? [
        { key:'total_sot',   title:'Всего в створ (SoTF+SoTA)' },
        { key:'sot_for',     title:'В створ команды (SoTF)' },
        { key:'sot_against', title:'В створ соперника (SoTA)' }
      ]
    : [
        { key:'total_goals',   title:'Всего в матче (GF+GA)' },
        { key:'goals_for',     title:'Забитые (GF)' },
        { key:'goals_against', title:'Пропущенные (GA)' }
      ]);

  const perTeamSeries = {};
  teamsToShow.forEach(tid => {
    perTeamSeries[tid] = {};
    METRICS.forEach(m => { perTeamSeries[tid][m.key] = seriesFor(points, seasonLabel, tid, HA_MODE, m.key); });
  });

  teamsToShow.forEach((tid,i)=>{
    METRICS.forEach(m => chartObjs[m.key].teamColorById[tid] = color(i));
  });

  for(const m of METRICS){
    const { chart, teamColorById, info, tech } = chartObjs[m.key];
    chart.data.datasets = [];
    chart.options.plugins.annotation.annotations = {};
    info.textContent = 'Кликни точку на графике';
    tech.textContent = '';

    // ряды
    teamsToShow.forEach((tid)=>{
      const series = perTeamSeries[tid][m.key];
      chart.data.datasets.push({
        label: `${teamNames[tid] || ('Team '+tid)} (${seasonLabel})`,
        data: series,
        borderColor: teamColorById[tid],
        backgroundColor: 'transparent',
        pointRadius: 5,
        tension: 0.25
      });
    });

    // медиана/среднее (по готовым сериям!)
    teamsToShow.forEach((tid)=>{
      const col = teamColorById[tid];
      if(document.getElementById('showMedian')?.checked){
        const vMed = computeStat(points, seasonLabel, tid, m.key, 'median', HA_MODE);
        if(vMed !== null){
          chart.options.plugins.annotation.annotations[`med_${m.key}_${tid}`] = {
            type:'line', yMin:vMed, yMax:vMed, borderColor: col, borderDash:[8,6], borderWidth:2,
            label:{ enabled:true, content:`${teamNames[tid]} median ${Number(vMed).toFixed(2)}`, position:'end', yAdjust:-8, backgroundColor:'#000a', color:'#ddd' }
          };
        }
      }
      if(document.getElementById('showMean')?.checked){
        const vMean = computeStat(points, seasonLabel, tid, m.key, 'mean', HA_MODE);
        if(vMean !== null){
          chart.options.plugins.annotation.annotations[`mean_${m.key}_${tid}`] = {
            type:'line', yMin:vMean, yMax:vMean, borderColor: col, borderDash:[2,4], borderWidth:2,
            label:{ enabled:true, content:`${teamNames[tid]} mean ${(Math.round(vMean*10)/10).toFixed(1)}`, position:'start', yAdjust:12, backgroundColor:'#000a', color:'#ddd' }
          };
        }
      }
    });

    // шкала
    if (HANDICAP_MODE) {
      const mAbs = maxYFromDatasets(chart.data.datasets);
      chart.options.scales.y.beginAtZero = false;
      chart.options.scales.y.suggestedMin = -Math.max(1, Math.ceil(mAbs + 0.5));
    } else {
      chart.options.scales.y.beginAtZero = true;
      chart.options.scales.y.suggestedMin = 0;
    }

    const techParts = [];

    // прогнозные точки ▲ ◆ ★ ◈
    for(const tid of teamsToShow){
      const col = teamColorById[tid];
      const curSeries = perTeamSeries[tid][m.key];
      if(curSeries.length < 2) continue;

      const hist = await window.__GE_API__.ensureHistoryLoaded(tid);
      const allHist = (hist.pointsAllSeasons || []).filter(p => p.season !== seasonLabel);
      const histRows = seriesFor(allHist, null, tid, HA_MODE, m.key);
      const xNext = curSeries.length + 1;

      let progText = '', kText = '', bText = '', sText = '';

      // ▲ prog
      if(document.getElementById('showForecast')?.checked){
        const r1 = predictPatternK(curSeries, histRows, window.__GE_STATE__.PATTERN_K, window.__GE_STATE__.TOL);
        if(r1.value !== null){
          const y1 = r1.value;
          const rounded = (Math.round(y1*10)/10).toFixed(1);
          chart.data.datasets.push({
            label: `${(teamNames[tid]||'') } prog`,
            data: [{ x: xNext, y: y1, date:'—', ha:'—', match_home:'—', match_away:'—', score:'—' }],
            borderColor: col, backgroundColor: col, showLine:false,
            pointRadius:8, pointStyle:'triangle', borderWidth:0, clip:false
          });
          chart.options.plugins.annotation.annotations[`prog_${m.key}_${tid}`] = {
            type:'label', xValue:xNext, yValue:y1,
            backgroundColor:'#000c', color:'#eee', content:`${rounded}`,
            xAdjust:-14, yAdjust:-16, padding:6
          };
          progText = `▲ prog`;
        }
      }

      // ◆ kprog
      if(document.getElementById('showKernel')?.checked){
        const { value: y2 } = kernelForecast(curSeries, histRows, m.key, window.__GE_STATE__.TOL);
        if(y2 !== null){
          const rounded = (Math.round(y2*10)/10).toFixed(1);
          chart.data.datasets.push({
            label: `${(teamNames[tid]||'') } kprog`,
            data: [{ x: xNext, y: y2, date:'—', ha:'—', match_home:'—', match_away:'—', score:'—' }],
            borderColor: col, backgroundColor: col, showLine:false,
            pointRadius:9, pointStyle:'rectRot', borderWidth:0, clip:false
          });
          chart.options.plugins.annotation.annotations[`kprog_${m.key}_${tid}`] = {
            type:'label', xValue:xNext, yValue:y2,
            backgroundColor:'#000c', color:'#eee', content:`${rounded}`,
            xAdjust:-14, yAdjust:-16, padding:6
          };
          kText = `◆ kprog`;
        }
      }

      // ★ bprog
      if(document.getElementById('showBayes')?.checked){
        let y3 = null;

        // Skellam — только для goal_diff (голы)
        if (STAT_TYPE === 'goals' && HANDICAP_MODE && m.key === 'goal_diff') {
          const curPairs = perTeamSeries[tid]['goal_diff'].map((_, i) => ({
            goals_for: perTeamSeries[tid]['goals_for']?.[i]?.y ?? null,
            goals_against: perTeamSeries[tid]['goals_against']?.[i]?.y ?? null
          }));
          const histPairs = (hist.pointsAllSeasons || []).filter(p => p.team_id===tid)
            .map(p => ({ goals_for: toNum(p.goals_for), goals_against: toNum(p.goals_against) }));
          const b = bayesSkellamForecast(curPairs, histPairs);
          if (b && b.value !== null) y3 = b.value;
        } else {
          const leagueVals = histRows.map(r=>toNum(r.y)).filter(v=>v!==null);
          const b = bayesPoissonForecast(curSeries, leagueVals);
          if (b && b.value !== null) y3 = b.value;
        }

        if(y3 !== null){
          const rounded = (Math.round(y3*10)/10).toFixed(1);
          chart.data.datasets.push({
            label: `${(teamNames[tid]||'') } bprog`,
            data: [{ x: xNext, y: y3, date:'—', ha:'—', match_home:'—', match_away:'—', score:'—' }],
            backgroundColor: col,
            borderColor:'#000', borderWidth:1.2,
            showLine:false, pointRadius:10, pointHoverRadius:11,
            pointStyle:'star', clip:false
          });
          chart.options.plugins.annotation.annotations[`bprog_${m.key}_${tid}`] = {
            type:'label', xValue:xNext, yValue:y3,
            backgroundColor:'#000c', color:'#eee', content:`${rounded}`,
            xAdjust:-14, yAdjust:-16, padding:6
          };
          bText = `★ bprog`;
        }
      }

      // ◈ sprog (бек)
      if (document.getElementById('showSuper')?.checked && window.__GE_API__.getSuperProgForecast) {
        const s = await window.__GE_API__.getSuperProgForecast({ teamId: tid, seasonLabel, metricKey: m.key });
        if (s && Number.isFinite(s.value)) {
          const y4 = s.value;
          const rounded = (Math.round(y4*10)/10).toFixed(1);
          chart.data.datasets.push({
            label: `${(teamNames[tid]||'') } sprog`,
            data: [{ x: xNext, y: y4, date:'—', ha:'—', match_home:'—', match_away:'—', score:'—' }],
            borderColor: col, backgroundColor: col, showLine:false,
            pointRadius:8, pointStyle:'crossRot', borderWidth:2, clip:false
          });
          chart.options.plugins.annotation.annotations[`sprog_${m.key}_${tid}`] = {
            type:'label', xValue:xNext, yValue:y4,
            backgroundColor:'#000c', color:'#eee', content:`${rounded}`,
            xAdjust:-14, yAdjust:-16, padding:6
          };
          sText = `◈ sprog`;
        }
      }

      const parts = [progText, kText, bText, sText].filter(Boolean).join('  ·  ');
      if(parts) techParts.push(`${teamNames[tid]}: ${parts}`);
    }

    chart.update();
    tech.textContent = techParts.join('     |     ');
  }
}
