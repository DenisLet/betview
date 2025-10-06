// числа
export function toNum(x){ const n = Number(x); return Number.isFinite(n) ? n : null; }
export function mean(arr){ const a = arr.map(toNum).filter(v=>v!==null); const n=a.length; if(!n) return null; return a.reduce((s,v)=>s+v,0)/n; }

// Паттерн-K с допуском (tol=0 — строго, tol=1 — в пределах ±1) + «мягкие» веса по расстоянию
export function predictPatternK(currentRows, historyRows, K=2, tol=1){
  if(currentRows.length < K) return { value:null, count:0 };
  const pat = currentRows.slice(-K).map(r => toNum(r.y));
  if(pat.some(v=>v===null)) return { value:null, count:0 };

  // разбивка на сезоны по x==1
  const seasons = []; let cur = [];
  for(const r of historyRows){ if(r.x===1 && cur.length){ seasons.push(cur); cur=[]; } cur.push(r); }
  if(cur.length) seasons.push(cur);

  // чем меньше tau, тем резче штраф несхожести
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

// Ядровой сосед (гауссово ядро), σ — шире при tol=1, уже при tol=0
export function kernelForecast(currentRows, historyRows, metricKey, tol){
  const base = { total_goals:{k:3,sigma0:0.35,sigma1:1.20}, goals_for:{k:2,sigma0:0.30,sigma1:0.95}, goals_against:{k:2,sigma0:0.30,sigma1:0.95} };
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

// Байесовский Пуассон с Gamma-приором по лиге
function gammaFromMoments(m, v){
  if(!(isFinite(m) && m>0) || !(isFinite(v) && v>0)) return {alpha: 1, beta: 1/Math.max(m,1e-6)};
  if(v <= m + 1e-6){
    const alpha = 1e6, beta = alpha / Math.max(m,1e-6);
    return { alpha, beta };
  }
  const alpha = (m*m) / (v - m);
  const beta  = alpha / m;
  if(!isFinite(alpha) || !isFinite(beta) || alpha<=0 || beta<=0){
    return { alpha: 1, beta: 1/Math.max(m,1e-6) };
  }
  return { alpha, beta };
}
export function bayesPoissonForecast(curSeries, leagueHistVals){
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
