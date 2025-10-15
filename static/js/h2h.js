// /js/h2h.js
console.log('[h2h] loaded');

const els = {
  league: document.getElementById('league'),
  home:   document.getElementById('home'),
  away:   document.getElementById('away'),
  status: document.getElementById('status'),
  wrap:   document.querySelector('.wrap-narrow'),
};

function setStatus(msg, isErr=false){
  if(!els.status) return;
  els.status.textContent = msg || '';
  els.status.style.color = isErr ? '#ff9a9a' : '';
}

function ensureUI(){
  // кнопка и контейнер под графики
  if(document.getElementById('btnShowH2H')) return;

  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <div class="row" style="display:flex;gap:10px;align-items:center;">
      <button id="btnShowH2H" class="btn">Показать графики очных котировок</button>
      <span id="h2hNote" class="muted"></span>
    </div>
    <div id="chartsWrap" style="margin-top:12px;">
      <div style="display:grid;grid-template-columns:1fr;gap:14px">
        <div class="card">
          <h3 style="margin:0 0 8px 0;">1–X–2 (Pinnacle, закрытие)</h3>
          <canvas id="chart1x2" height="120"></canvas>
        </div>
        <div class="card">
          <h3 style="margin:0 0 8px 0;">Total 2.5 (Pinnacle, закрытие)</h3>
          <canvas id="chartOU" height="120"></canvas>
        </div>
      </div>
    </div>
  `;
  els.wrap.appendChild(card);

  document.getElementById('btnShowH2H').addEventListener('click', runH2HCharts);
}

async function runH2HCharts(){
  const league_id = Number(els.league.value);
  const home_id = Number(els.home.value);
  const away_id = Number(els.away.value);
  if(!league_id || !home_id || !away_id){
    setStatus('Выбери лигу и обе команды', true);
    return;
  }
  setStatus('Загрузка очных котировок…');

  const params = new URLSearchParams({
    league_id: String(league_id),
    home_team_id: String(home_id),
    away_team_id: String(away_id),
    line: '2.5',
    line_tol: '0.05'
  });
  const resp = await fetch(`/api/h2h_series?${params.toString()}`);
  if(!resp.ok){
    setStatus(`Ошибка API: ${resp.status}`, true);
    return;
  }
  const data = await resp.json();
  const series = Array.isArray(data.series) ? data.series : [];
  if(series.length === 0){
    setStatus('Нет матчей для выбранной пары (home vs away) в этой лиге.', true);
    return;
  }

  // подготовка массивов
  const labels = series.map(p => p.date);
  const H = series.map(p => p.H ?? null);
  const D = series.map(p => p.D ?? null);
  const A = series.map(p => p.A ?? null);

  const OU_over  = series.map(p => p.OU_over ?? null);
  const OU_under = series.map(p => p.OU_under ?? null);
  const OU_line  = series.map(p => p.OU_line ?? null);

  draw1x2(labels, H, D, A);
  drawOU(labels, OU_line, OU_over, OU_under);

  setStatus('Готово.');
}

let ch1, ch2;

function draw1x2(labels, H, D, A){
  const ctx = document.getElementById('chart1x2').getContext('2d');
  if(ch1){ ch1.destroy(); }
  ch1 = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Home', data: H, spanGaps:true },
        { label: 'Draw', data: D, spanGaps:true },
        { label: 'Away', data: A, spanGaps:true },
      ]
    },
    options: {
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        y: { reverse: false, title: { display: true, text: 'Коэффициент' } },
        x: { ticks: { autoSkip: true, maxTicksLimit: 10 } }
      },
      plugins: { legend: { position: 'top' } }
    }
  });
}

function drawOU(labels, L, O, U){
  const ctx = document.getElementById('chartOU').getContext('2d');
  if(ch2){ ch2.destroy(); }
  ch2 = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Over', data: O, spanGaps:true },
        { label: 'Under', data: U, spanGaps:true },
      ]
    },
    options: {
      interaction: { mode: 'nearest', intersect: false },
      scales: {
        y: { title: { display: true, text: 'Коэффициент' } },
        x: { ticks: { autoSkip: true, maxTicksLimit: 10 } }
      },
      plugins: {
        legend: { position: 'top' },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const i = items?.[0]?.dataIndex;
              const line = (i!=null && L[i]!=null) ? Number(L[i]).toFixed(2) : '—';
              return `Линия: ${line}`;
            }
          }
        }
      }
    }
  });
}

// boot
ensureUI();
