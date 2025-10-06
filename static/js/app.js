// /js/app.js
import { getLeagues, getSeasons, getTeams, getTimeSeries, getSuperProg } from './api.js';
import { buildSeasonShell, fillChartsForSeason } from './charts.js';

const els = {
  league:    document.getElementById('league'),
  season:    document.getElementById('season'),
  team1:     document.getElementById('team1'),
  team2:     document.getElementById('team2'),
  showBtn:   document.getElementById('showBtn'),
  status:    document.getElementById('status'),

  typePills:      document.getElementById('typePills'),
  haPills:        document.getElementById('haPills'),
  patternPills:   document.getElementById('patternPills'),
  tolerancePills: document.getElementById('tolerancePills'),
  modePills:      document.getElementById('modePills'),

  showTeam1:   document.getElementById('showTeam1'),
  showTeam2:   document.getElementById('showTeam2'),
  showMedian:  document.getElementById('showMedian'),
  showMean:    document.getElementById('showMean'),
  showForecast:document.getElementById('showForecast'),
  showKernel:  document.getElementById('showKernel'),
  showBayes:   document.getElementById('showBayes'),
  showSuper:   document.getElementById('showSuper'),

  seasonView: document.getElementById('seasonView'),
};

// ===== GLOBAL STATE =====
let leagueId = null;
let seasonsAll = [];
let teamNames = {};
let cache = {};      // сезонные точки (по выбору)
let histCache = {};  // история по команде (мультисезон)
let sprogCache = {}; // суперпрогнозы

// публичные настройки для charts.js
window.__GE_STATE__ = {
  STAT_TYPE: 'goals',   // 'goals' | 'corners' | 'cards' | 'shots' | 'sot'
  HA_MODE: 'all',       // 'all' | 'home' | 'away'
  PATTERN_K: 2,         // 2 | 3
  TOL: 0,               // 0 | 1
  HANDICAP_MODE: false, // режим «фора» (только для goals)

  getTeamNames: () => teamNames,
  getSeasonsAll: () => seasonsAll,
  getLeagueId:   () => leagueId,
  getCache:      () => cache,
  getHistCache:  () => histCache,
  setHist(teamId, payload) { histCache[teamId] = payload; },
};

// helpers
function setStatus(msg, isErr=false){
  if(!els.status) return;
  els.status.textContent = msg || '';
  els.status.style.color = isErr ? '#ff9a9a' : '';
}
function validateShowButton(){
  const hasSeason = els.season && els.season.value !== '';
  const hasTeam   = (els.team1 && els.team1.value) || (els.team2 && els.team2.value);
  if (els.showBtn) els.showBtn.disabled = !(hasSeason && hasTeam);
}
function selectedTeamIdsRaw(){
  const t1 = els.team1 && els.team1.value ? Number(els.team1.value) : null;
  const t2 = els.team2 && els.team2.value ? Number(els.team2.value) : null;
  const out = [];
  if(t1) out.push(t1);
  if(t2 && t2 !== t1) out.push(t2);
  return out;
}
function clearSeasonView(){ if(els.seasonView) els.seasonView.innerHTML = ''; }

// ===== history helper for charts.js =====
async function ensureHistoryLoaded(teamId){
  const seasonsKey = seasonsAll.join(',');
  const TYPE = window.__GE_STATE__.STAT_TYPE;
  const cacheKey = `${TYPE}|${teamId}|${seasonsKey}`;
  const h = histCache[cacheKey];
  if (h) return h;
  const resp = await getTimeSeries({
    leagueId,
    teamIds: String(teamId),
    seasons: seasonsKey,
    statType: TYPE
  });
  const payload = { pointsAllSeasons: Array.isArray(resp.points) ? resp.points : [], __seasonsKey: seasonsKey };
  histCache[cacheKey] = payload;
  return payload;
}

// окно сезонов для бекенда суперпрога: текущий + 5 прошлых
async function getSuperProgForecast({ teamId, seasonLabel, metricKey }){
  const TYPE = window.__GE_STATE__.STAT_TYPE;
  const HA = window.__GE_STATE__.HA_MODE;
  const key = `${TYPE}|${leagueId}|${teamId}|${seasonLabel}|${HA}|${metricKey}`;
  if (sprogCache[key]) return sprogCache[key];

  const idx = seasonsAll.indexOf(seasonLabel);
  const trainSeasons = (idx >= 0) ? seasonsAll.slice(idx, idx+6) : [seasonLabel];
  const seasonsParam = trainSeasons.join(',');

  const resp = await getSuperProg({
    leagueId, teamId, seasons: seasonsParam, haMode: HA, statType: TYPE, halfLifeDays: 180
  }).catch((e)=>{
    console.warn('[sprog] backend error', e?.message || e);
    return null;
  });
  if (!resp) return null;

  let value = null;
  if (metricKey === 'goal_diff') {
    value = Number(resp.lambda_gf) - Number(resp.lambda_ga);
  } else if (metricKey.endsWith('_for')) {
    value = Number(resp.lambda_gf);
  } else if (metricKey.endsWith('_against') || metricKey === 'goals_against_neg') {
    const v = Number(resp.lambda_ga);
    value = (metricKey === 'goals_against_neg') ? -v : v;
  } else {
    value = Number(resp.lambda_total);
  }

  const out = { value, ci_low: resp.ci_total_low, ci_high: resp.ci_total_high };
  sprogCache[key] = out;
  return out;
}
window.__GE_API__ = { ensureHistoryLoaded, getSuperProgForecast };

// ===== загрузка списков =====
async function populateLeagues() {
  const leagues = await getLeagues();
  if (!Array.isArray(leagues) || leagues.length === 0) {
    throw new Error('Нет лиг');
  }
  els.league.innerHTML = leagues.map(l => `<option value="${l.id}">${l.country} — ${l.name}</option>`).join('');
  leagueId = Number(els.league.value);
  if (!Number.isInteger(leagueId)) throw new Error('Некорректный leagueId');
}

async function populateTeamsAndSeasons() {
  if (!Number.isInteger(leagueId) || leagueId <= 0) return;

  const [teams, seasons] = await Promise.all([
    getTeams(leagueId).catch(e => { console.error('getTeams fail', e); return []; }),
    getSeasons(leagueId).catch(e => { console.error('getSeasons fail', e); return []; }),
  ]);

  // команды
  teamNames = {};
  (Array.isArray(teams) ? teams : []).forEach(t => (teamNames[t.id] = t.name));
  const teamOpts = (Array.isArray(teams) ? teams : []).slice().sort((a,b)=>a.name.localeCompare(b.name))
    .map(t => `<option value="${t.id}">${t.name}</option>`).join('');
  if (els.team1) els.team1.innerHTML = teamOpts;
  if (els.team2) els.team2.innerHTML = `<option value="">— не выбрано —</option>` + teamOpts;

  // сезоны
  seasonsAll = (Array.isArray(seasons) ? seasons : []).map(s => s.label);
  if (els.season) els.season.innerHTML = seasonsAll.map((s,i)=>`<option value="${i}">${s}</option>`).join('');

  cache = {};
  histCache = {};
  sprogCache = {};
  validateShowButton();
  setStatus('');
}

// ===== основной рендер сезона =====
async function showSeason() {
  try {
    const hasTeam = !!(els.team1 && els.team1.value) || !!(els.team2 && els.team2.value);
    if (!hasTeam) { setStatus('Выбери хотя бы одну команду', true); return; }
    if (!Array.isArray(seasonsAll) || seasonsAll.length === 0) { setStatus('Для лиги нет сезонов', true); return; }

    const idx = Number(els.season.value);
    if (!Number.isInteger(idx) || idx < 0 || idx >= seasonsAll.length) {
      setStatus('Сезон не выбран', true); return;
    }
    const seasonLabel = seasonsAll[idx];
    const TYPE = window.__GE_STATE__.STAT_TYPE;
    const MODE = window.__GE_STATE__.HANDICAP_MODE;

    const niceType = TYPE==='corners' ? 'угловые' : TYPE==='cards' ? 'карточки'
                     : TYPE==='shots' ? 'удары' : TYPE==='sot' ? 'удары в створ'
                     : 'голы';
    const modeSuffix = (TYPE==='goals' && MODE) ? ' · фора' : '';
    setStatus(`Загрузка ${seasonLabel} (${niceType}${modeSuffix})…`);

    const ids = selectedTeamIdsRaw();
    const teamKey = ids.join(',');
    const cacheKey = `${TYPE}|${seasonLabel}|${teamKey}`;
    if (!cache[cacheKey]) {
      const resp = await getTimeSeries({
        leagueId,
        teamIds: teamKey,
        seasons: seasonLabel,
        statType: TYPE
      });
      cache[cacheKey] = resp;
    }
    const data = cache[cacheKey];
    if (!data || !Array.isArray(data.points)) throw new Error('Нет данных для визуализации');

    clearSeasonView();
    const charts = buildSeasonShell(seasonLabel, idx);
    await fillChartsForSeason(seasonLabel, charts, data.points);
    setStatus(`Показан сезон: ${seasonLabel}${modeSuffix}`);
  } catch (e) {
    console.error('[showSeason]', e);
    setStatus(e.message || String(e), true);
  }
}

// ===== утилиты =====
function toggleGroupActive(container, targetBtn) {
  container.querySelectorAll('.pill').forEach(b => b.classList.remove('active'));
  targetBtn.classList.add('active');
}
function goSeasonDelta(delta){
  const curIdx = Number(els.season.value);
  const nextIdx = curIdx + delta;
  if(nextIdx < 0 || nextIdx >= seasonsAll.length) return;
  els.season.value = String(nextIdx);
  showSeason();
}

// ===== события =====
els.league.addEventListener('change', async (e) => {
  const val = Number(e.target.value);
  if (!Number.isInteger(val) || val <= 0) return;
  leagueId = val;
  setStatus('');
  if (els.season) els.season.innerHTML = '';
  if (els.team1) els.team1.innerHTML = '';
  if (els.team2) els.team2.innerHTML = '<option value="">— не выбрано —</option>';
  cache = {};
  histCache = {};
  sprogCache = {};
  await populateTeamsAndSeasons();
});
[els.season, els.team1, els.team2].forEach(el=>{
  el.addEventListener('change', ()=>{
    cache = {};
    histCache = {};
    sprogCache = {};
    validateShowButton();
  });
});
els.showBtn.addEventListener('click', showSeason);

// тип метрик
els.typePills?.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill'); if (!btn) return;
  toggleGroupActive(els.typePills, btn);
  const t = btn.dataset.type;
  const allowed = ['goals','corners','cards','shots','sot'];
  window.__GE_STATE__.STAT_TYPE = allowed.includes(t) ? t : 'goals';

  // ВАЖНО: не трогаем HANDICAP_MODE здесь.
  // Пользователь сам управляет режимом через «Тоталы/Фора».
  // Очищаем кэши и перерисовываем.
  cache = {};
  histCache = {};
  sprogCache = {};
  showSeason();
});

// H/A
els.haPills?.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill'); if (!btn) return;
  toggleGroupActive(els.haPills, btn);
  window.__GE_STATE__.HA_MODE = btn.dataset.ha || 'all';
  showSeason();
});

// Pattern K
els.patternPills?.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill'); if (!btn) return;
  toggleGroupActive(els.patternPills, btn);
  window.__GE_STATE__.PATTERN_K = Number(btn.dataset.k) || 2;
  showSeason();
});

// Tolerance
els.tolerancePills?.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill'); if (!btn) return;
  toggleGroupActive(els.tolerancePills, btn);
  window.__GE_STATE__.TOL = Number(btn.dataset.tol) || 0;
  showSeason();
});

// режим тоталы/фора
els.modePills?.addEventListener('click', (e) => {
  const btn = e.target.closest('.pill'); if (!btn) return;
  toggleGroupActive(els.modePills, btn);
  const mode = btn.dataset.mode || 'totals';
  window.__GE_STATE__.HANDICAP_MODE = (mode === 'handicap');
  showSeason();
});

// чекбоксы
['showTeam1','showTeam2','showMedian','showMean','showForecast','showKernel','showBayes','showSuper']
  .forEach(id => els[id]?.addEventListener('change', showSeason));

// стрелки сезонов
window.addEventListener('GE_SEASON_DELTA', (e) => {
  const d = Number(e.detail) || 0;
  goSeasonDelta(d);
});

// стрелки на клавиатуре
window.addEventListener('keydown', (e)=>{
  if(e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  const tag = (document.activeElement && document.activeElement.tagName) || '';
  if(['INPUT','TEXTAREA','SELECT','BUTTON'].includes(tag)){ document.activeElement.blur(); }
  e.preventDefault(); e.stopPropagation();
  if(e.key === 'ArrowLeft')  goSeasonDelta(+1);
  if(e.key === 'ArrowRight') goSeasonDelta(-1);
});

// boot
(async function init(){
  try{
    setStatus('Загрузка лиг…');
    await populateLeagues();
    setStatus('Загрузка команд и сезонов…');
    await populateTeamsAndSeasons();
    setStatus('Готово: выбери команды и нажми «Показать».');
  }catch(e){
    console.error('[init]', e);
    setStatus(e.message || String(e), true);
  }
})();
