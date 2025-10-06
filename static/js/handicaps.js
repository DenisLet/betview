// static/js/handicaps.js
// Простая обёртка поверх API /api/handicaps и отрисовка (Chart.js уже есть в проекте)

async function fetchHandicaps(params) {
  const q = new URLSearchParams(params);
  const resp = await fetch(`/api/handicaps?${q.toString()}`);
  if (!resp.ok) throw new Error(await resp.text());
  return await resp.json();
}

// Рисуем 3 графика:
// 1) столбцы Moneyline (Win/Draw/Lose)
// 2) линия вероятности COVER по азиатским форам
// 3) линия fair-odds (decimal) для COVER по тем же линиям
function renderHandicapCharts(container, data) {
  const root = (typeof container === 'string') ? document.querySelector(container) : container;
  root.innerHTML = `
    <div class="row">
      <div class="col"><canvas id="chart_moneyline"></canvas></div>
      <div class="col"><canvas id="chart_ah_cover"></canvas></div>
      <div class="col"><canvas id="chart_ah_odds"></canvas></div>
    </div>
  `;

  // 1) moneyline
  const ctx1 = root.querySelector('#chart_moneyline').getContext('2d');
  new Chart(ctx1, {
    type: 'bar',
    data: {
      labels: ['Win', 'Draw', 'Lose'],
      datasets: [{
        label: 'Probability',
        data: [
          data.moneyline.home,
          data.moneyline.draw,
          data.moneyline.away
        ]
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, max: 1 } }
    }
  });

  // 2) COVER by lines
  const labels = data.asian.map(x => x.line);
  const cover = data.asian.map(x => x.cover);
  const push  = data.asian.map(x => x.push);
  const lose  = data.asian.map(x => x.lose);

  const ctx2 = root.querySelector('#chart_ah_cover').getContext('2d');
  new Chart(ctx2, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Cover', data: cover },
        { label: 'Push',  data: push  },
        { label: 'Lose',  data: lose  },
      ]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      stacked: false,
      scales: { y: { beginAtZero: true, max: 1 } }
    }
  });

  // 3) Fair odds for Cover (decimal)
  const odds = data.asian.map(x => (x.fair_odds_cover === Infinity ? null : x.fair_odds_cover));
  const ctx3 = root.querySelector('#chart_ah_odds').getContext('2d');
  new Chart(ctx3, {
    type: 'line',
    data: {
      labels,
      datasets: [{ label: 'Fair odds (Cover)', data: odds }]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      scales: { y: { beginAtZero: true } }
    }
  });
}

// Хелпер для кнопки-переключателя
async function loadHandicapsInto(container, {
  league_id, team_id, seasons,
  ha_mode = 'all',
  opponent_id = '',
  half_life_days = 180,
  lines = '-1.5,-1,-0.75,-0.5,-0.25,0,+0.25,+0.5,+0.75,+1,+1.5'
}) {
  const data = await fetchHandicaps({
    league_id, team_id, seasons, ha_mode, opponent_id, half_life_days, lines
  });
  renderHandicapCharts(container, data);
}

window.Handicaps = { fetchHandicaps, renderHandicapCharts, loadHandicapsInto };
