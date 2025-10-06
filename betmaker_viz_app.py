# betmaker_viz_app.py
# Запуск: python betmaker_viz_app.py  → http://127.0.0.1:8000/
#
# Ключевые улучшения:
# - Сезоны: отдаются только те, где у выбранной команды реально есть матчи (по matches),
#   плюс корректные лейблы из seasons (если нет — показываем season_id).
# - Chart.js + chartjs-plugin-zoom: колесо мыши/пинч — ЗУМ, SHIFT+drag — прямоугольный зум, Pan — зажатая середина.
# - Кнопка Reset zoom, регулятор высоты графика, «Выбрать все сезоны».
# - Автодекимация (LTTB), плавные линии, кликабельная легенда (показывай/скрывай серии).
# - SQL безопасен для колонки "AS".
# - Команды по выбранной лиге подтягиваются из matches, а названия — из teams (если name есть).

import os
import sqlite3
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# === ПУТЬ К ТВОЕЙ БД ===
DB_PATH = r"C:\Users\HomeComp\PycharmProjects\pythonProject\UKparserToBD\betmaker.sqlite3"

# ---------------- Base ----------------
app = FastAPI(title="BetMaker Viz")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

def get_conn() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"SQLite не найден по пути: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def q(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    return list(conn.execute(sql, params))

def table_cols(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r["name"] for r in q(conn, f"PRAGMA table_info({table})")]

def table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in set(table_cols(conn, table))

# ---------------- API: справочники ----------------
@app.get("/api/leagues")
def api_leagues() -> List[Dict[str, Any]]:
    conn = get_conn()
    cols = set(table_cols(conn, "leagues"))
    base = ["id"]
    if "code" in cols: base.append("code")
    if "country" in cols: base.append("country")
    if "name" in cols: base.append("name")
    rows = q(conn, f"SELECT {', '.join(base)} FROM leagues ORDER BY COALESCE(country,''), COALESCE(name,code,'')")
    return [dict(r) for r in rows]

@app.get("/api/teams")
def api_teams(league_id: int = Query(...)) -> List[Dict[str, Any]]:
    """
    Универсально:
    - Если у teams есть league_id → берём по нему.
    - Иначе собираем team_id из matches по выбранной лиге и подтягиваем имена из teams.
    """
    conn = get_conn()
    if table_has_column(conn, "teams", "league_id"):
        rows = q(conn, """
            SELECT id, league_id, name
            FROM teams
            WHERE league_id = ?
            ORDER BY name
        """, (league_id,))
        return [dict(r) for r in rows]

    ids_rows = q(conn, """
        SELECT DISTINCT home_team_id AS tid FROM matches WHERE league_id = ?
        UNION
        SELECT DISTINCT away_team_id FROM matches WHERE league_id = ?
    """, (league_id, league_id))
    team_ids = [r[0] for r in ids_rows if r[0] is not None]
    if not team_ids:
        return []
    placeholders = ",".join(["?"] * len(team_ids))
    have_name = table_has_column(conn, "teams", "name")
    rows = q(conn, f"SELECT id{', name' if have_name else ''} FROM teams WHERE id IN ({placeholders})", tuple(team_ids))
    items = [{"id": r["id"], "league_id": league_id, "name": (r["name"] if have_name else str(r["id"]))} for r in rows]
    items.sort(key=lambda x: x["name"].lower())
    return items

@app.get("/api/seasons")
def api_seasons(
    league_id: int = Query(...),
    team_id: Optional[int] = Query(None, description="если указан — вернём только сезоны с матчами этой команды"),
) -> List[Dict[str, Any]]:
    """
    Даёт сезоны для лиги. Если указан team_id — вернёт только сезоны, где есть матчи этой команды.
    Лейблы берём из seasons; если в seasons нет — вернём {id: ..., label: str(id)}.
    """
    conn = get_conn()

    if team_id is not None:
        # сезоны из matches, где есть матчи этой команды в этой лиге
        season_rows = q(conn, """
            SELECT DISTINCT season_id
            FROM matches
            WHERE league_id = ?
              AND (home_team_id = ? OR away_team_id = ?)
            ORDER BY season_id DESC
        """, (league_id, team_id, team_id))
    else:
        season_rows = q(conn, """
            SELECT DISTINCT season_id
            FROM matches
            WHERE league_id = ?
            ORDER BY season_id DESC
        """, (league_id,))

    season_ids = [r["season_id"] for r in season_rows if r["season_id"] is not None]
    if not season_ids:
        return []

    placeholders = ",".join(["?"] * len(season_ids))
    # подтянем то, что есть в seasons
    seasons_map = {r["id"]: r["label"] for r in q(conn, f"SELECT id, label FROM seasons WHERE id IN ({placeholders})", tuple(season_ids))}
    out = [{"id": sid, "league_id": league_id, "label": seasons_map.get(sid, str(sid)), "is_current": 0} for sid in season_ids]
    # если есть is_current — обновим
    if table_has_column(conn, "seasons", "is_current"):
        cur = {r["id"]: r["is_current"] for r in q(conn, f"SELECT id, COALESCE(is_current,0) AS is_current FROM seasons WHERE id IN ({placeholders})", tuple(season_ids))}
        for rec in out:
            rec["is_current"] = int(cur.get(rec["id"], 0))
    # сортировка: текущие вверх, потом по label/id убыв.
    out.sort(key=lambda r: (0 if r["is_current"] else 1, str(r["label"]).lower()))
    return out

@app.get("/api/metrics")
def api_metrics() -> List[Dict[str, str]]:
    return [
        {"key": "GF", "label": "Голы For"},
        {"key": "GA", "label": "Голы Against"},
        {"key": "CF", "label": "Угловые For"},
        {"key": "CA", "label": "Угловые Against"},
        {"key": "SH", "label": "Удары For"},
        {"key": "SHA", "label": "Удары Against"},
        {"key": "SOT", "label": "В створ For"},
        {"key": "SOTA", "label": "В створ Against"},
        {"key": "F", "label": "Фолы For"},
        {"key": "FA", "label": "Фолы Against"},
        {"key": "Y", "label": "Жёлтые For"},
        {"key": "YA", "label": "Жёлтые Against"},
        {"key": "R", "label": "Красные For"},
        {"key": "RA", "label": "Красные Against"},
        {"key": "GD", "label": "Разница голов (GF-GA)"},
        {"key": "X_COR", "label": "Баланс угловых (CF-CA)"},
        {"key": "X_SOT", "label": "Баланс SOT (SOT-SOTA)"},
    ]

# ---------------- API: тайм-серии ----------------
@app.get("/api/timeseries")
def api_timeseries(
    team_id: int = Query(...),
    season_ids: List[int] = Query(..., description="несколько ?season_ids=..."),
    metrics: List[str] = Query(..., description="несколько ?metrics=GF&metrics=GA"),
) -> Dict[str, Any]:
    if not season_ids:
        raise HTTPException(400, "season_ids is required")
    conn = get_conn()

    # Лейблы сезонов (если есть)
    placeholders = ",".join(["?"] * len(season_ids))
    rows = q(conn, f"SELECT id, label FROM seasons WHERE id IN ({placeholders})", tuple(season_ids))
    season_map = {r["id"]: r["label"] for r in rows}

    # Какие фактические столбцы есть в matches?
    mcols = set(table_cols(conn, "matches"))

    want = ["FTHG","FTAG","HTHG","HTAG","HS","AS","HST","AST","HF","AF","HC","AC","HY","AY","HR","AR"]
    select_core = ["m.id", "m.date", "m.home_team_id", "m.away_team_id"]
    alias_map: Dict[str, str] = {}
    for col in want:
        if col not in mcols:
            continue
        if col == "AS":
            select_core.append('m."AS" AS AS_col')
            alias_map["AS"] = "AS_col"
        else:
            select_core.append(f"m.{col} AS {col}")
            alias_map[col] = col
    select_sql = ",\n              ".join(select_core)

    result: Dict[str, Any] = {"seasons": {}}

    for sid in season_ids:
        data_rows = q(conn, f"""
            SELECT
              {select_sql}
            FROM matches AS m
            WHERE m.season_id = ?
              AND (m.home_team_id = ? OR m.away_team_id = ?)
            ORDER BY m.date
        """, (sid, team_id, team_id))

        match_idx: List[int] = []
        series: Dict[str, List[Optional[float]]] = {m: [] for m in metrics}
        idx = 0
        for r in data_rows:
            idx += 1
            match_idx.append(idx)
            home = (r["home_team_id"] == team_id)

            def get(col: str) -> Optional[float]:
                alias = alias_map.get(col)
                return (r[alias] if alias in r.keys() else None)

            FTHG = get("FTHG"); FTAG = get("FTAG")
            HS   = get("HS");   AS_  = get("AS")
            HST  = get("HST");  AST  = get("AST")
            HF   = get("HF");   AF   = get("AF")
            HC   = get("HC");   AC   = get("AC")
            HY   = get("HY");   AY   = get("AY")
            HR   = get("HR");   AR_  = get("AR")

            GF = (FTHG if home else FTAG) if (FTHG is not None or FTAG is not None) else None
            GA = (FTAG if home else FTHG) if (FTHG is not None or FTAG is not None) else None

            SH  = (HS if home else AS_) if (HS is not None or AS_ is not None) else None
            SHA = (AS_ if home else HS) if (HS is not None or AS_ is not None) else None

            SOT  = (HST if home else AST) if (HST is not None or AST is not None) else None
            SOTA = (AST if home else HST) if (HST is not None or AST is not None) else None

            F  = (HF if home else AF) if (HF is not None or AF is not None) else None
            FA = (AF if home else HF) if (HF is not None or AF is not None) else None

            CF = (HC if home else AC) if (HC is not None or AC is not None) else None
            CA = (AC if home else HC) if (HC is not None or AC is not None) else None

            Y  = (HY if home else AY) if (HY is not None or AY is not None) else None
            YA = (AY if home else HY) if (HY is not None or AY is not None) else None

            R  = (HR if home else AR_) if (HR is not None or AR_ is not None) else None
            RA = (AR_ if home else HR) if (HR is not None or AR_ is not None) else None

            def nz(x: Optional[float]) -> float: return 0.0 if x is None else float(x)
            GD    = nz(GF) - nz(GA) if (GF is not None or GA is not None) else None
            X_COR = nz(CF) - nz(CA) if (CF is not None or CA is not None) else None
            X_SOT = nz(SOT) - nz(SOTA) if (SOT is not None or SOTA is not None) else None

            all_vals = {
                "GF": GF, "GA": GA,
                "CF": CF, "CA": CA,
                "SH": SH, "SHA": SHA,
                "SOT": SOT, "SOTA": SOTA,
                "F": F, "FA": FA,
                "Y": Y, "YA": YA,
                "R": R, "RA": RA,
                "GD": GD, "X_COR": X_COR, "X_SOT": X_SOT
            }
            for m in metrics:
                series[m].append(all_vals.get(m, None))

        result["seasons"][str(sid)] = {
            "label": season_map.get(sid, str(sid)),
            "series": series,
            "match_idx": match_idx
        }

    return result

# ---------------- UI ----------------
INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <title>BetMaker — Аналитика сезонов</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <style>
    :root{
      --bg:#0e0f14; --panel:#12151f; --muted:#a9b1bd; --fg:#e9ecef; --line:#1f2330; --accent:#4e79a7;
      --border:#2a2f3c; --chip:#181c27;
    }
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,Roboto,Arial,sans-serif}
    header{position:sticky;top:0;z-index:10;background:rgba(14,15,20,0.9);backdrop-filter:blur(6px);border-bottom:1px solid var(--border)}
    .wrap{max-width:1280px;margin:0 auto;padding:12px 16px}
    h1{margin:0 0 8px 0;font-size:18px}
    .grid{display:grid;grid-template-columns:1.1fr 1.8fr 1fr 1.6fr;gap:10px}
    .col{display:flex;flex-direction:column;gap:6px}
    label{font-size:12px;color:var(--muted)}
    select,input,button{background:var(--panel);color:var(--fg);border:1px solid var(--border);border-radius:10px;padding:8px 10px}
    select[multiple]{min-height:130px}
    button{cursor:pointer}
    button.primary{background:var(--accent);border-color:transparent}
    .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .legend{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
    .chip{background:var(--chip);border:1px solid var(--border);border-radius:999px;padding:2px 8px;font-size:12px}
    #chartCard{max-width:1280px;margin:12px auto;background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:8px 12px}
    #chartWrap{height:70vh}
    canvas{height:100% !important; width:100% !important;}
    .muted{color:var(--muted)}
    .search{display:flex;gap:6px;align-items:center}
    .search input{flex:1}
    .toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px}
    @media (max-width:1100px){ .grid{grid-template-columns:1fr 1fr} #chartWrap{height:60vh} }
    @media (max-width:700px){ .grid{grid-template-columns:1fr} #chartWrap{height:55vh} }
  </style>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.umd.min.js"></script>
</head>
<body>
<header>
  <div class="wrap">
    <h1>BetMaker · Сезоны и тренды</h1>
    <div class="grid">
      <div class="col">
        <label>Лига</label>
        <select id="league"></select>
      </div>
      <div class="col">
        <label>Команда</label>
        <div class="search">
          <input id="teamSearch" placeholder="Поиск по командам…">
          <select id="team"></select>
        </div>
        <small class="muted">Команды подтягиваются по матчам выбранной лиги</small>
      </div>
      <div class="col">
        <label>Сезоны (несколько)</label>
        <select id="seasons" multiple></select>
        <div class="row">
          <button id="selectAllSeasons">Выбрать все</button>
          <small class="muted" id="seasonHint"></small>
        </div>
      </div>
      <div class="col">
        <label>Метрики (несколько)</label>
        <select id="metrics" multiple></select>
      </div>
    </div>

    <div class="toolbar">
      <label title="Окно SMA/BB">SMA N</label><input id="smaN" type="number" value="5" min="1" style="width:72px">
      <label title="Альфа экспон. сглаживания [0..1]">EMA α</label><input id="emaA" type="number" value="0.3" step="0.05" min="0.01" max="0.99" style="width:72px">
      <label title="Окно Bollinger">BB N</label><input id="bbN" type="number" value="10" min="2" style="width:72px">
      <label title="Коэф. сигм">BB k</label><input id="bbK" type="number" value="2" step="0.5" min="0.5" style="width:72px">
      <label>Trend</label><input id="trendOn" type="checkbox" checked>
      <label>Высота</label><input id="height" type="range" min="40" max="90" value="70">
      <button id="draw" class="primary">Построить</button>
      <button id="resetZoom">Reset zoom</button>
    </div>
    <div id="legend" class="legend"></div>
  </div>
</header>

<main class="wrap">
  <div id="chartCard">
    <div id="chartWrap"><canvas id="chart"></canvas></div>
  </div>
</main>

<script>
const $ = s => document.querySelector(s);
const leagueSel = $("#league");
const teamSel = $("#team");
const teamSearch = $("#teamSearch");
const seasonsSel = $("#seasons");
const seasonHint = $("#seasonHint");
const metricsSel = $("#metrics");
const smaN = $("#smaN");
const emaA = $("#emaA");
const bbN  = $("#bbN");
const bbK  = $("#bbK");
const trendOn = $("#trendOn");
const heightRange = $("#height");
const drawBtn = $("#draw");
const resetZoomBtn = $("#resetZoom");
const legend = $("#legend");
const selectAllSeasonsBtn = $("#selectAllSeasons");
const chartWrap = $("#chartWrap");
let chart;
let allTeams = [];

function opt(v,t){ const o=document.createElement('option'); o.value=v; o.textContent=t; return o; }

async function loadLeagues(){
  const res = await fetch('/api/leagues'); const data = await res.json();
  leagueSel.innerHTML = "";
  data.forEach(l=>leagueSel.appendChild(opt(l.id, `${(l.country||'').trim()} — ${(l.name||l.code||('League '+l.id)).trim()}`)));
  if(data.length){ await loadTeams(); await loadSeasons(); }
}

async function loadTeams(){
  const id = leagueSel.value;
  const res = await fetch(`/api/teams?league_id=${id}`); const data = await res.json();
  allTeams = data;
  renderTeams(allTeams);
  // после загрузки команд — обновим сезоны с учётом выбранной команды (если есть)
  await loadSeasons();
}

function renderTeams(list){
  const cur = teamSel.value;
  teamSel.innerHTML = "";
  list.forEach(t=>teamSel.appendChild(opt(t.id, t.name)));
  if(cur) { const o=[...teamSel.options].find(o=>o.value===cur); if(o) o.selected=true; }
}

teamSearch.addEventListener('input', ()=>{
  const q = teamSearch.value.trim().toLowerCase();
  if(!q) { renderTeams(allTeams); return; }
  const filtered = allTeams.filter(t => t.name.toLowerCase().includes(q));
  renderTeams(filtered);
});

async function loadSeasons(){
  const leagueId = leagueSel.value;
  const teamId = teamSel.value || "";
  const url = teamId ? `/api/seasons?league_id=${leagueId}&team_id=${teamId}` : `/api/seasons?league_id=${leagueId}`;
  const res = await fetch(url); const data = await res.json();
  seasonsSel.innerHTML = "";
  data.forEach(s=>{
    const text = s.is_current ? `${s.label}  • current` : s.label;
    seasonsSel.appendChild(opt(s.id, text));
  });
  seasonHint.textContent = data.length ? `доступно сезонов: ${data.length}` : 'нет сезонов для выбранных фильтров';
}

$("#team").addEventListener('change', loadSeasons);

selectAllSeasonsBtn.addEventListener('click', ()=>{
  [...seasonsSel.options].forEach(o=>o.selected=true);
});

heightRange.addEventListener('input', ()=>{
  chartWrap.style.height = heightRange.value + "vh";
  if(chart) chart.resize();
});

async function loadMetrics(){
  const res = await fetch('/api/metrics'); const data = await res.json();
  metricsSel.innerHTML = "";
  data.forEach(m=>metricsSel.appendChild(opt(m.key, m.label)));
  [...metricsSel.options].forEach(o=>{ if(["GF","GA"].includes(o.value)) o.selected = true; });
}

function selValues(sel){ return [...sel.selectedOptions].map(o=>o.value); }

// --- индикаторы на фронте ---
function sma(arr, n){
  const out = Array(arr.length).fill(null);
  let sum=0, q=[];
  for(let i=0;i<arr.length;i++){
    const v = arr[i];
    q.push(v); sum+=v;
    if(q.length>n){ sum-=q.shift(); }
    if(q.length===n) out[i] = sum/n;
  }
  return out;
}
function ema(arr, alpha){
  const out = Array(arr.length).fill(null);
  let prev = null;
  for(let i=0;i<arr.length;i++){
    const v = arr[i];
    prev = (prev===null) ? v : (alpha*v + (1-alpha)*prev);
    out[i] = prev;
  }
  return out;
}
function mean(a){ return a.reduce((s,x)=>s+x,0)/a.length; }
function std(a){ const m = mean(a); return Math.sqrt(mean(a.map(x=>(x-m)*(x-m)))); }
function bollinger(arr, n, k){
  const up = Array(arr.length).fill(null);
  const mid = sma(arr, n);
  const lo = Array(arr.length).fill(null);
  for(let i=0;i<arr.length;i++){
    if (i+1>=n){
      const window = arr.slice(i+1-n, i+1);
      const m = mean(window), s = std(window);
      up[i] = m + k*s;
      lo[i] = m - k*s;
    }
  }
  return {mid, up, lo};
}

const COLORS = ['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ab',
                '#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd','#8c564b','#e377c2','#7f7f7f','#bcbd22','#17becf',
                '#6b6ecf','#bd9e39','#8ca252','#e7ba52'];
function color(i){ return COLORS[i % COLORS.length]; }

async function draw(){
  const teamId = teamSel.value;
  const seasonIds = selValues(seasonsSel);
  const metrics = selValues(metricsSel);
  if(!teamId || seasonIds.length===0 || metrics.length===0){
    alert("Выбери лигу, команду, сезоны и метрики");
    return;
  }
  const url = `/api/timeseries?team_id=${teamId}` + seasonIds.map(s=>`&season_ids=${s}`).join('') + metrics.map(m=>`&metrics=${m}`).join('');
  const res = await fetch(url); const data = await res.json();

  const ctx = document.getElementById('chart').getContext('2d');
  if(chart){ chart.destroy(); }

  const datasets = [];
  legend.innerHTML = "";
  let dsIdx = 0;

  for(const [sid, payload] of Object.entries(data.seasons)){
    const labelSeason = payload.label || sid;
    const X = payload.match_idx;

    metrics.forEach((m)=>{
      const base = payload.series[m] || [];
      if(base.length===0) return;

      datasets.push({
        label: `${labelSeason} — ${m}`,
        data: X.map((x,i)=>({x, y: base[i]})),
        parsing: false,
        borderColor: color(dsIdx++),
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.18
      });

      const n = Math.max(1, parseInt(smaN.value||'5', 10));
      const sm = sma(base, n);
      datasets.push({
        label: `${labelSeason} — ${m} SMA(${n})`,
        data: X.map((x,i)=> sm[i]==null?null:{x, y: sm[i]}).filter(Boolean),
        parsing:false,
        borderColor: color(dsIdx++),
        borderDash: [6,4],
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.15
      });

      const a = Math.min(0.99, Math.max(0.01, parseFloat(emaA.value||'0.3')));
      const em = ema(base, a);
      datasets.push({
        label: `${labelSeason} — ${m} EMA(α=${a})`,
        data: X.map((x,i)=>({x, y: em[i]})),
        parsing:false,
        borderColor: color(dsIdx++),
        borderWidth: 1.2,
        pointRadius: 0,
        borderDash: [3,3],
        tension: 0.15
      });

      const bbn = Math.max(2, parseInt(bbN.value||'10', 10));
      const bbk = parseFloat(bbK.value||'2');
      const bb = bollinger(base, bbn, bbk);
      datasets.push({
        label: `${labelSeason} — ${m} BB mid(${bbn})`,
        data: X.map((x,i)=> bb.mid[i]==null?null:{x, y: bb.mid[i]}).filter(Boolean),
        parsing:false,
        borderColor: color(dsIdx++),
        borderWidth: 1.2,
        pointRadius: 0,
        borderDash: [8,3],
        tension: 0.15
      });
      datasets.push({
        label: `${labelSeason} — ${m} BB up`,
        data: X.map((x,i)=> bb.up[i]==null?null:{x, y: bb.up[i]}).filter(Boolean),
        parsing:false,
        borderColor: color(dsIdx++),
        borderWidth: 1,
        pointRadius: 0,
        borderDash: [2,2],
        tension: 0.15
      });
      datasets.push({
        label: `${labelSeason} — ${m} BB low`,
        data: X.map((x,i)=> bb.lo[i]==null?null:{x, y: bb.lo[i]}).filter(Boolean),
        parsing:false,
        borderColor: color(dsIdx++),
        borderWidth: 1,
        pointRadius: 0,
        borderDash: [2,2],
        tension: 0.15
      });

      const chip = document.createElement('div');
      chip.className = 'chip';
      chip.textContent = `${labelSeason} · ${m}`;
      legend.appendChild(chip);
    });
  }

  chart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      normalized: true,
      plugins: {
        legend: { display: true, labels: { color: '#e9ecef' } },
        tooltip: { callbacks: { title: (items)=> items.length? `Матч #${items[0].raw.x}` : '' } },
        decimation: { enabled: true, algorithm: 'lttb' },
        zoom: {
          zoom: {
            wheel: { enabled: true },
            pinch: { enabled: true },
            drag: { enabled: true, modifierKey: 'shift' },
            mode: 'xy'
          },
          pan: { enabled: true, mode: 'xy' }
        }
      },
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 0 } },
      scales: {
        x: {
          title: { display: true, text: 'Матч (индекс по сезону)' },
          ticks: { color: '#cbd5e1' },
          grid: { color: '#1f2330' },
          type: 'linear',
          min: 1
        },
        y: {
          ticks: { color: '#cbd5e1' },
          grid: { color: '#1f2330' }
        }
      }
    }
  });

  resetZoomBtn.onclick = ()=> chart.resetZoom();
}

leagueSel.addEventListener('change', async ()=>{ await loadTeams(); /* loadSeasons вызывается внутри */ });
document.getElementById('team').addEventListener('change', loadSeasons);
document.getElementById('draw').addEventListener('click', draw);

(async function init(){
  await loadLeagues();
  await loadMetrics();
  chartWrap.style.height = heightRange.value + "vh";
})();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/favicon.ico")
def favicon():
    return PlainTextResponse("", status_code=204)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
