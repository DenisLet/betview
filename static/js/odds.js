// /js/odds.js — 1X2 + Totals; у рядов OPEN нет маркеров и их нет в тултипе
import { getLeagues, getTeams } from '/js/api.js?v=3';

console.log('[odds] v15 (hide markers + tooltips for OPEN)');

const els = {
  league:  document.getElementById('league'),
  home:    document.getElementById('home'),
  away:    document.getElementById('away'),
  status:  document.getElementById('status'),
  c1x2:    document.getElementById('chart1x2'),
  cou:     document.getElementById('chartOU'),
  chkBoth: document.getElementById('chkBoth'),
  chkOpen: document.getElementById('chkOpen'),
};

let leagueId = null;
let teamNames = {};
let chart1x2 = null;
let chartOU  = null;

// helpers
function setStatus(msg, isErr=false){
  if(!els.status) return;
  els.status.textContent = msg || '';
  els.status.style.color = isErr ? '#ff9a9a' : '';
}
async function fetchJSON(url){
  const r = await fetch(url);
  if(!r.ok){ const t = await r.text().catch(()=> ''); throw new Error(`${r.status} ${t||'Request failed'}`); }
  return await r.json();
}
function hex2rgba(hex, a=1){
  if(!hex) return `rgba(255,255,255,${a})`;
  const v = hex.replace('#','');
  const n = parseInt(v.length===3 ? v.split('').map(c=>c+c).join('') : v, 16);
  const R=(n>>16)&255,G=(n>>8)&255,B=n&255; return `rgba(${R},${G},${B},${a})`;
}

// markers ✓ ✗ — ИСПОЛЬЗУЕМ ТОЛЬКО ДЛЯ CLOSE
const markers = (() => {
  const mk = (type) => {
    const c = document.createElement('canvas'); c.width = c.height = 18;
    const g = c.getContext('2d'); g.lineWidth = 2.5; g.lineCap = 'round'; g.translate(9, 9);
    if (type === 'check') { g.strokeStyle = '#34d399'; g.beginPath(); g.moveTo(-5,1); g.lineTo(-1,5); g.lineTo(6,-4); g.stroke(); }
    else { g.strokeStyle = '#f87171'; g.beginPath(); g.moveTo(-5,-5); g.lineTo(5,5); g.moveTo(5,-5); g.lineTo(-5,5); g.stroke(); }
    return c;
  };
  return { check: mk('check'), cross: mk('cross') };
})();

// colors
const COLORS = {
  one:   '#60a5fa', // 1
  draw:  '#fbbf24', // X
  two:   '#f472b6', // 2
  over:  '#34d399', // O
  under: '#f87171', // U
};

// data loading
async function populateLeagues(){
  try{
    setStatus('Загрузка лиг…');
    const leagues = await getLeagues();
    if(!Array.isArray(leagues) || leagues.length===0){ setStatus('Нет лиг (проверь /api/leagues)', true); return; }
    els.league.innerHTML = leagues.map(l => `<option value="${l.id}">${l.country} — ${l.name}</option>`).join('');
    leagueId = Number(els.league.value);
    setStatus('');
  }catch(e){ console.error(e); setStatus('Ошибка загрузки лиг', true); }
}
async function populateTeams(){
  if(!Number.isInteger(leagueId) || leagueId<=0) return;
  try{
    setStatus('Загрузка команд…');
    const teams = await getTeams(leagueId);
    teamNames = {}; (teams||[]).forEach(t => (teamNames[t.id]=t.name));
    const opts = (teams||[]).slice().sort((a,b)=>a.name.localeCompare(b.name)).map(t=>`<option value="${t.id}">${t.name}</option>`).join('');
    const head = `<option value="">— выбери —</option>`;
    els.home.innerHTML = head + opts; els.away.innerHTML = head + opts;
    setStatus('Готово: выбери две команды.');
  }catch(e){ console.error(e); setStatus('Ошибка загрузки команд', true); }
}

function destroyCharts(){ if(chart1x2){chart1x2.destroy(); chart1x2=null;} if(chartOU){chartOU.destroy(); chartOU=null;} }

function validParams(){
  const h = Number(els.home.value), a = Number(els.away.value);
  if(!Number.isInteger(leagueId)||leagueId<=0||!Number.isInteger(h)||!h||!Number.isInteger(a)||!a) return null;
  if(h===a){ setStatus('Дом и выезд не могут быть одной командой', true); return null; }
  return { h, a };
}

// chart factory
function buildLineChart(ctx, labels, datasets){
  const GRID='rgba(158,203,255,0.12)', BORDER='rgba(158,203,255,0.35)', TICK='#cfd3dc', LEGEND='#e5e7ee', TT_BG='rgba(15,22,35,0.95)', TT_TXT='#e5e7ee';
  return new Chart(ctx, {
    type:'line',
    data:{ labels, datasets },
    options:{
      responsive:true, maintainAspectRatio:false, spanGaps:true,
      interaction:{ mode:'index', intersect:false },
      elements:{
        line:{ tension:0.25 },
        point:{
          // ⛔ Для OPEN — никаких маркеров; для CLOSE — ✓/✗
          pointStyle(c){
            const ds=c.dataset, i=c.dataIndex;
            if (ds._isOpen) return false; // открытые серии без маркеров
            const v=ds.data?.[i]; if(v==null) return false;
            const w=ds._win?.[i]; return w?markers.check:markers.cross;
          },
          radius(c){
            const ds=c.dataset, i=c.dataIndex;
            if (ds._isOpen) return 0; // точки OPEN скрыты
            const v=ds.data?.[i]; return v==null?0:7;
          },
          hoverRadius:8,
          backgroundColor(c){
            const ds=c.dataset, i=c.dataIndex;
            if (ds._isOpen) return 'transparent';
            const w=ds._win?.[i]; return w?'#34d399':'#f87171';
          },
          borderColor(c){
            const ds=c.dataset, i=c.dataIndex;
            if (ds._isOpen) return 'transparent';
            const w=ds._win?.[i]; return w?'#34d399':'#f87171';
          },
          borderWidth(c){ return c.dataset._isOpen ? 0 : 1; }
        }
      },
      scales:{
        x:{ ticks:{ maxRotation:0, autoSkip:true, color:TICK },
            grid:{ display:true, drawOnChartArea:true, drawTicks:false, color:GRID, borderColor:BORDER, borderWidth:1 } },
        y:{ beginAtZero:false, ticks:{ color:TICK },
            grid:{ display:true, drawOnChartArea:true, drawTicks:false, color:GRID, borderColor:BORDER, borderWidth:1 } }
      },
      plugins:{
        legend:{ position:'top', labels:{ color:LEGEND } },
        tooltip:{
          backgroundColor:TT_BG, titleColor:TT_TXT, bodyColor:TT_TXT,
          // ⛔ Полностью убираем OPEN из тултипа
          filter(item){ return !item.dataset._isOpen; },
          callbacks:{
            label(ctx){
              const v = ctx.parsed.y; const ds = ctx.dataset;
              const open = ds._open?.[ctx.dataIndex];
              let s = `${ds.label}: ${v}`;
              if(open!=null && v!=null){
                const pct = (v-open)/open*100; const sign = pct>0?'+':'';
                s += `  (Open→Close: ${open} → ${v}, ${sign}${pct.toFixed(1)}%)`;
              }
              const win = ds._win?.[ctx.dataIndex];
              if(win!=null) s += win ? ' ✓' : ' ✗';
              return s;
            },
            afterBody(items){
              const it=items?.[0]; if(!it) return '';
              const ds=it.dataset,i=it.dataIndex; const score=ds._score?.[i];
              return score?`Score: ${score}`:'';
            }
          }
        }
      }
    }
  });
}

// 1X2
async function draw1x2(){
  if(chart1x2){ chart1x2.destroy(); chart1x2=null; }
  const p = validParams(); if(!p) return;

  const url = `/api/h2h_odds?league_id=${leagueId}&home_team_id=${p.h}&away_team_id=${p.a}&line=2.5&line_tol=0.05&orientation=strict&include_open=true`;
  const data = await fetchJSON(url);
  const pts = Array.isArray(data.points) ? data.points : [];
  if(pts.length===0){ setStatus('Нет H2H (строго «дом→гость») или котировок для 1X2.', false); return; }

  const labels   = pts.map(p => p.date ?? '');
  const scoreArr = pts.map(p => p.score || '');
  const d1  = pts.map(p => p.one  ?? null);
  const dX  = pts.map(p => p.draw ?? null);
  const d2  = pts.map(p => p.two  ?? null);
  const o1  = pts.map(p => p.one_open  ?? null);
  const oX  = pts.map(p => p.draw_open ?? null);
  const o2  = pts.map(p => p.two_open  ?? null);

  const outcome = scoreArr.map(s => { const m=s?.match?.(/^(\d+)[–-](\d+)$/); if(!m) return null;
    const hg=+m[1], ag=+m[2]; return hg>ag?'1':(hg<ag?'2':'X'); });
  const win1 = d1.map((v,i)=> v!=null && outcome[i]==='1');
  const winX = dX.map((v,i)=> v!=null && outcome[i]==='X');
  const win2 = d2.map((v,i)=> v!=null && outcome[i]==='2');

  const showOpen = !!els.chkOpen?.checked && (o1.some(v=>v!=null)||oX.some(v=>v!=null)||o2.some(v=>v!=null));

  const datasets = [
    // CLOSE — с маркерами ✓/✗ и в тултипе
    { label:'1 (close)', data:d1, _open:o1, _score:scoreArr, _win:win1,
      borderColor:COLORS.one, backgroundColor:'transparent', borderWidth:2, fill:false, showLine:true },
    { label:'X (close)', data:dX, _open:oX, _score:scoreArr, _win:winX,
      borderColor:COLORS.draw, backgroundColor:'transparent', borderWidth:2, fill:false, showLine:true, borderDash:[6,4] },
    { label:'2 (close)', data:d2, _open:o2, _score:scoreArr, _win:win2,
      borderColor:COLORS.two, backgroundColor:'transparent', borderWidth:2, fill:false, showLine:true },
    // OPEN — без маркеров и НЕ в тултипе
    ...(showOpen ? [
      { label:'1 (open)', data:o1, _open:o1, _score:scoreArr, _isOpen:true,
        borderColor:hex2rgba(COLORS.one,0.6), backgroundColor:'transparent', borderWidth:1, fill:false, showLine:true, borderDash:[3,3],
        pointRadius:0, pointHitRadius:6 },
      { label:'X (open)', data:oX, _open:oX, _score:scoreArr, _isOpen:true,
        borderColor:hex2rgba(COLORS.draw,0.6), backgroundColor:'transparent', borderWidth:1, fill:false, showLine:true, borderDash:[3,3],
        pointRadius:0, pointHitRadius:6 },
      { label:'2 (open)', data:o2, _open:o2, _score:scoreArr, _isOpen:true,
        borderColor:hex2rgba(COLORS.two,0.6), backgroundColor:'transparent', borderWidth:1, fill:false, showLine:true, borderDash:[3,3],
        pointRadius:0, pointHitRadius:6 },
    ] : [])
  ];

  chart1x2 = buildLineChart(els.c1x2, labels, datasets);
}

// Totals (OU)
async function drawTotals(){
  if(chartOU){ chartOU.destroy(); chartOU=null; }
  const p = validParams(); if(!p) return;

  const orientation = els.chkBoth?.checked ? 'both' : 'strict';
  const url = `/api/h2h_odds?league_id=${leagueId}&home_team_id=${p.h}&away_team_id=${p.a}&line=2.5&line_tol=0.05&orientation=${orientation}&include_open=true`;
  const data = await fetchJSON(url);
  const allPts = Array.isArray(data.points) ? data.points : [];
  const pts = allPts.filter(pt => pt.over != null || pt.under != null || pt.over_open != null || pt.under_open != null);
  if(pts.length===0){
    setStatus(orientation==='both' ? 'Нет OU котировок (оба направления).' : 'Нет OU котировок (строго дом→гость).', false);
    return;
  }

  const labels   = pts.map(p => p.date ?? '');
  const scoreArr = pts.map(p => p.score || '');
  const over     = pts.map(p => p.over  ?? null);
  const under    = pts.map(p => p.under ?? null);
  const over_o   = pts.map(p => p.over_open  ?? null);
  const under_o  = pts.map(p => p.under_open ?? null);

  const totals = scoreArr.map(s => { const m=s?.match?.(/^(\d+)[–-](\d+)$/); if(!m) return null; return (+m[1])+(+m[2]); });
  const winOver  = totals.map((t,i)=> over[i]!=null  && t!=null && t>=3);
  const winUnder = totals.map((t,i)=> under[i]!=null && t!=null && t<=2);

  const showOpen = !!els.chkOpen?.checked && (over_o.some(v=>v!=null)||under_o.some(v=>v!=null));

  const datasets = [
    // CLOSE — с маркерами ✓/✗ и в тултипе
    { label:'Over 2.5 (close)',  data:over,  _open:over_o,  _score:scoreArr, _win:winOver,
      borderColor:COLORS.over,  backgroundColor:'transparent', borderWidth:4, fill:false, showLine:true },
    { label:'Under 2.5 (close)', data:under, _open:under_o, _score:scoreArr, _win:winUnder,
      borderColor:COLORS.under, backgroundColor:'transparent', borderWidth:4, fill:false, showLine:true },
    // OPEN — без маркеров и НЕ в тултипе
    ...(showOpen ? [
      { label:'Over 2.5 (open)',  data:over_o,  _open:over_o,  _score:scoreArr, _isOpen:true,
        borderColor:hex2rgba(COLORS.over,0.6),  backgroundColor:'transparent', borderWidth:2, fill:false, showLine:true, borderDash:[3,3],
        pointRadius:0, pointHitRadius:6 },
      { label:'Under 2.5 (open)', data:under_o, _open:under_o, _score:scoreArr, _isOpen:true,
        borderColor:hex2rgba(COLORS.under,0.6), backgroundColor:'transparent', borderWidth:2, fill:false, showLine:true, borderDash:[3,3],
        pointRadius:0, pointHitRadius:6 },
    ] : [])
  ];

  chartOU = buildLineChart(els.cou, labels, datasets);
}

async function redrawAll(){
  try{
    setStatus('Загрузка…');
    await draw1x2();
    await drawTotals();
    const h=Number(els.home.value), a=Number(els.away.value);
    setStatus(`Ок: ${(teamNames[h]||`Home ${h}`)} vs ${(teamNames[a]||`Away ${a}`)}`);
  }catch(e){ console.error(e); setStatus(`Ошибка: ${e.message||e}`, true); }
}

// events
els.league.addEventListener('change', async (e)=>{ const v=Number(e.target.value);
  if(!Number.isInteger(v)||v<=0) return; leagueId=v; await populateTeams(); destroyCharts(); });
els.home.addEventListener('change', redrawAll);
els.away.addEventListener('change', redrawAll);
els.chkBoth && els.chkBoth.addEventListener('change', drawTotals);
els.chkOpen && els.chkOpen.addEventListener('change', redrawAll);

// boot
(async function init(){
  await populateLeagues();
  await populateTeams();
  setStatus('Готово: выбери две команды.');
})();
