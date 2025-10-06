// --- tiny fetch helper with logs
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) {
    const txt = await r.text().catch(()=> '');
    console.error('[API ERROR]', r.status, url, txt);
    throw new Error(`${r.status} ${txt || 'Request failed'}`);
  }
  const data = await r.json().catch(() => null);
  return data;
}

function titleCaseCountry(raw) {
  const s = (raw ?? '').toString().trim();
  if (!s) return s;
  return s
    .toLowerCase()
    .split(/(\s+|-)/)
    .map(part => (part === '-' || /^\s+$/.test(part)) ? part
      : part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

function requireInt(name, val) {
  const n = Number(val);
  if (!Number.isInteger(n) || n <= 0) {
    console.warn(`[API] invalid ${name}:`, val);
    throw new Error(`Missing or invalid ${name}`);
  }
  return n;
}

export async function getLeagues() {
  const data = await fetchJSON('/api/leagues');
  const arr = Array.isArray(data) ? data : [];
  const mapped = arr.map(l => ({ ...l, country: titleCaseCountry(l.country) }));
  mapped.sort((a, b) => {
    const ac = (a.country || '').toLowerCase();
    const bc = (b.country || '').toLowerCase();
    if (ac !== bc) return ac.localeCompare(bc, 'ru', { sensitivity: 'base' });
    const an = (a.name || '').toLowerCase();
    const bn = (b.name || '').toLowerCase();
    return an.localeCompare(bn, 'ru', { sensitivity: 'base' });
  });
  return mapped;
}

export async function getSeasons(leagueId) {
  const lid = requireInt('leagueId', leagueId);
  const data = await fetchJSON(`/api/seasons?league_id=${lid}`);
  return Array.isArray(data) ? data : [];
}

export async function getTeams(leagueId) {
  const lid = requireInt('leagueId', leagueId);
  const data = await fetchJSON(`/api/teams?league_id=${lid}`);
  return Array.isArray(data) ? data : [];
}

/**
 * statType: 'goals' | 'corners' | 'cards' | 'shots' | 'sot' | 'fouls'
 */
export async function getTimeSeries({ leagueId, teamIds, seasons, statType='goals' }) {
  const lid = requireInt('leagueId', leagueId);
  const ids = (teamIds || '').toString().trim();
  const sez = (seasons || '').toString().trim();
  if (!ids || !sez) throw new Error('teamIds and seasons are required');

  let path = '/api/timeseries';
  if (statType === 'corners') path = '/api/timeseries_corners';
  else if (statType === 'cards') path = '/api/timeseries_cards';
  else if (statType === 'shots') path = '/api/timeseries_shots';
  else if (statType === 'sot')   path = '/api/timeseries_sot';
  else if (statType === 'fouls') path = '/api/timeseries_fouls';

  const url = `${path}?league_id=${lid}&team_ids=${ids}&seasons=${encodeURIComponent(sez)}`;
  const data = await fetchJSON(url);
  if (!data || !Array.isArray(data.points)) {
    console.warn('[API] timeseries returned no points for', { leagueId, teamIds, seasons, statType });
    return { seasons: Array.isArray(data?.seasons) ? data.seasons : [], points: [] };
  }
  return data;
}

export async function getSuperProg({ leagueId, teamId, seasons, haMode='all', statType='goals', halfLifeDays=180 }) {
  const lid = requireInt('leagueId', leagueId);
  const tid = requireInt('teamId', teamId);
  const sez = (seasons || '').toString().trim();
  const ha  = (haMode || 'all');
  const st  = (statType || 'goals');
  if (!sez) throw new Error('seasons required');

  const url = `/api/superprog?league_id=${lid}&team_id=${tid}&seasons=${encodeURIComponent(sez)}&ha_mode=${ha}&half_life_days=${halfLifeDays}&stat_type=${st}`;
  return await fetchJSON(url);
}

// числа
export function toNum(x){ const n = Number(x); return Number.isFinite(n) ? n : null; }
export function mean(arr){ const a = arr.map(toNum).filter(v=>v!==null); const n=a.length; if(!n) return null; return a.reduce((s,v)=>s+v,0)/n; }
