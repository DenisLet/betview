from __future__ import annotations
from typing import List, Dict, Any, Tuple
import os

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, MetaData, Table, select, or_, func

# ================= DB INIT =================
DB_URL = os.environ.get(
    "BETMAKER_DB_URL",
    "sqlite:///C:/Users/HomeComp/PycharmProjects/pythonProject/UKparserToBD/betmaker.sqlite3"
)
engine = create_engine(DB_URL, future=True)
meta = MetaData()
meta.reflect(bind=engine)

Leagues: Table = meta.tables["leagues"]
Seasons: Table = meta.tables["seasons"]
Teams:   Table = meta.tables["teams"]
Matches: Table = meta.tables["matches"]

# =============== HELPERS ===================
def season_sort_key(label: str) -> Tuple[int, int, int]:
    try:
        if "_" in label:
            y1, y2 = map(int, label.split("_"))
            return (y2, y1, 0)
        y = int(label)
        return (y, y, 1)
    except Exception:
        return (0, 0, -1)

def _sort_labels_desc(labels: list[str]) -> list[str]:
    return sorted(labels, key=season_sort_key, reverse=True)

def _empty_series(season_labels: list[str]) -> "SeriesResponse":
    return SeriesResponse(seasons=season_labels, points=[])

# ---- динамическое разрешение имён колонок в matches ----
def _col(tbl, *candidates):
    cols = set(tbl.c.keys())
    for name in candidates:
        if name in cols:
            return tbl.c[name]
    return None

def _resolve_stat_columns(stat_type: str):
    """
    Возвращает (home_col, away_col) для нужного stat_type.
    """
    if stat_type == "shots":
        # В твоей схеме away-колонка называется AS_ (с подчёркиванием!)
        h = _col(Matches, "HS", "HomeShots", "shots_home", "SH", "S_H")
        a = _col(Matches, "AS_", "AS", "AwayShots", "shots_away", "SA", "S_A")
        return h, a
    if stat_type == "sot":
        h = _col(Matches, "HST", "HomeShotsOnTarget", "sot_home", "HSoT")
        a = _col(Matches, "AST", "AwayShotsOnTarget", "sot_away", "ASoT")
        return h, a
    if stat_type == "corners":
        h = _col(Matches, "HC", "HomeCorners", "corners_home")
        a = _col(Matches, "AC", "AwayCorners", "corners_away")
        return h, a
    if stat_type == "cards":
        h = _col(Matches, "HY", "HomeYellows", "cards_home", "YH")
        a = _col(Matches, "AY", "AwayYellows", "cards_away", "YA")
        return h, a
    return None, None

# =============== SCHEMAS ===================
class LeagueOut(BaseModel):
    id: int
    country: str
    name: str

class TeamOut(BaseModel):
    id: int
    name: str

class SeasonOut(BaseModel):
    id: int
    label: str
    is_current: int

class TimePoint(BaseModel):
    date: str
    season: str
    team_id: int
    team_name: str
    # goals
    goals_for: int | None = None
    goals_against: int | None = None
    total_goals: int | None = None
    # corners
    corners_for: int | None = None
    corners_against: int | None = None
    total_corners: int | None = None
    # cards (yellow)
    cards_for: int | None = None
    cards_against: int | None = None
    total_cards: int | None = None
    # shots
    shots_for: int | None = None
    shots_against: int | None = None
    total_shots: int | None = None
    # shots on target
    sot_for: int | None = None
    sot_against: int | None = None
    total_sot: int | None = None
    # tooltip
    opponent_name: str
    ha: str
    match_home: str
    match_away: str
    score: str
    match_label: str

class SeriesResponse(BaseModel):
    seasons: List[str]
    points: List[TimePoint]

# =============== APP =======================
app = FastAPI(title="Goals/Corners/Cards/Shots/SOT Explorer")

from handicaps import router as handicaps_router
app.include_router(handicaps_router)


from h2h import router as h2h_router

app.include_router(h2h_router)



@app.get("/__routes")
def __routes():
    return [r.path for r in app.router.routes]

@app.get("/__diag_matches_columns")
def __diag_matches_columns():
    return {"matches_columns": list(Matches.c.keys())}

# Диагностика наличия данных по SHOTS/SOT в окне сезонов
@app.get("/__diag_stat_counts")
def __diag_stat_counts(
    league_id: int,
    seasons: str,
):
    labels = [x.strip() for x in seasons.split(",") if x.strip()]
    with engine.begin() as conn:
        sids = [r[0] for r in conn.execute(
            select(Seasons.c.id).where(Seasons.c.league_id == league_id, Seasons.c.label.in_(labels))
        ).all()]
        hs = _col(Matches, "HS")
        aS = _col(Matches, "AS_") or _col(Matches, "AS")
        hst = _col(Matches, "HST")
        ast = _col(Matches, "AST")

        def _cnt(c1, c2):
            if c1 is None or c2 is None or not sids:
                return 0
            return conn.execute(
                select(func.count())
                .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
                .where(c1.isnot(None), c2.isnot(None))
            ).scalar_one()

        return {
            "shots_rows": _cnt(hs, aS),
            "sot_rows": _cnt(hst, ast),
            "seasons": labels,
        }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# =============== API: справочники ===============
@app.get("/api/leagues", response_model=List[LeagueOut])
def api_leagues():
    with engine.begin() as conn:
        rows = conn.execute(
            select(Leagues.c.id, Leagues.c.country, Leagues.c.name)
            .order_by(Leagues.c.country, Leagues.c.name)
        ).all()
    return [LeagueOut(id=r.id, country=r.country, name=r.name) for r in rows]

@app.get("/api/seasons", response_model=List[SeasonOut])
def api_seasons(league_id: int = Query(..., ge=1)):
    with engine.begin() as conn:
        rows = conn.execute(
            select(Seasons.c.id, Seasons.c.label, Seasons.c.is_current)
            .where(Seasons.c.league_id == league_id)
        ).all()
    rows_sorted = sorted(rows, key=lambda r: season_sort_key(r.label), reverse=True)
    return [SeasonOut(id=r.id, label=r.label, is_current=int(r.is_current or 0)) for r in rows_sorted]

@app.get("/api/teams", response_model=List[TeamOut])
def api_teams(league_id: int = Query(..., ge=1)):
    with engine.begin() as conn:
        home_ids = {row[0] for row in conn.execute(
            select(Matches.c.home_team_id).where(Matches.c.league_id == league_id)
        ).all()}
        away_ids = {row[0] for row in conn.execute(
            select(Matches.c.away_team_id).where(Matches.c.league_id == league_id)
        ).all()}
        ids = home_ids | away_ids
        if not ids:
            return []
        rows = conn.execute(
            select(Teams.c.id, Teams.c.name).where(Teams.c.id.in_(ids))
        ).all()
    rows_sorted = sorted(rows, key=lambda r: r.name or "")
    return [TeamOut(id=r.id, name=r.name) for r in rows_sorted]

# =============== API: ряды по ГОЛАМ ===============
@app.get("/api/timeseries", response_model=SeriesResponse)
def api_timeseries(
    league_id: int = Query(..., ge=1),
    team_ids: str = Query(...),
    seasons: str = Query(...),
):
    try:
        team_list = [int(x) for x in team_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(400, "Invalid team_ids")

    season_labels = [x.strip() for x in seasons.split(",") if x.strip()]
    if not team_list or not season_labels:
        raise HTTPException(400, "team_ids and seasons are required")

    with engine.begin() as conn:
        srows = conn.execute(
            select(Seasons.c.id, Seasons.c.label)
            .where(Seasons.c.league_id == league_id, Seasons.c.label.in_(season_labels))
        ).all()
        sid_by_label = {r.label: r.id for r in srows}
        if not sid_by_label:
            raise HTTPException(404, "No seasons found")

        trows = conn.execute(
            select(Teams.c.id, Teams.c.name)
            .where(Teams.c.id.in_(team_list))
        ).all()
        tname = {r.id: r.name for r in trows}

        all_team_rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
        name_by_id = {r.id: r.name for r in all_team_rows}

        sids = list(sid_by_label.values())
        mrows = conn.execute(
            select(
                Matches.c.date, Matches.c.season_id,
                Matches.c.home_team_id, Matches.c.away_team_id,
                Matches.c.FTHG, Matches.c.FTAG
            )
            .where(Matches.c.league_id == league_id, Matches.c.season_id.in_(sids))
            .where(or_(Matches.c.home_team_id.in_(team_list), Matches.c.away_team_id.in_(team_list)))
            .order_by(Matches.c.date.asc())
        ).all()

    points: List[Dict[str, Any]] = []
    label_by_sid = {v: k for k, v in sid_by_label.items()}

    for m in mrows:
        if m.FTHG is None or m.FTAG is None:
            continue
        FTHG, FTAG = int(m.FTHG), int(m.FTAG)
        lbl = label_by_sid.get(m.season_id)
        total = FTHG + FTAG

        home_id = m.home_team_id
        away_id = m.away_team_id
        home_name = name_by_id.get(home_id, str(home_id))
        away_name = name_by_id.get(away_id, str(away_id))
        score_str = f"{FTHG}–{FTAG}"
        match_label = f"{home_name} {score_str} {away_name}"

        for tid in team_list:
            if tid == home_id:
                gf = FTHG; ga = FTAG; opp = away_name; ha = "H"
            elif tid == away_id:
                gf = FTAG; ga = FTHG; opp = home_name; ha = "A"
            else:
                continue
            points.append(dict(
                date=str(m.date),
                season=lbl,
                team_id=tid,
                team_name=tname.get(tid, str(tid)),
                goals_for=gf,
                goals_against=ga,
                total_goals=total,
                opponent_name=opp,
                ha=ha,
                match_home=home_name,
                match_away=away_name,
                score=score_str,
                match_label=match_label,
            ))
    return SeriesResponse(seasons=season_labels, points=[TimePoint(**p) for p in points])

# =============== API: ряды по УГЛОВЫМ ===============
@app.get("/api/timeseries_corners", response_model=SeriesResponse)
def api_timeseries_corners(
    league_id: int = Query(..., ge=1),
    team_ids: str = Query(...),
    seasons: str = Query(...),
):
    try:
        team_list = [int(x) for x in team_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(400, "Invalid team_ids")

    season_labels = [x.strip() for x in seasons.split(",") if x.strip()]
    if not team_list or not season_labels:
        raise HTTPException(400, "team_ids and seasons are required")

    with engine.begin() as conn:
        srows = conn.execute(
            select(Seasons.c.id, Seasons.c.label)
            .where(Seasons.c.league_id == league_id, Seasons.c.label.in_(season_labels))
        ).all()
        sid_by_label = {r.label: r.id for r in srows}
        if not sid_by_label:
            raise HTTPException(404, "No seasons found")

        trows = conn.execute(
            select(Teams.c.id, Teams.c.name)
            .where(Teams.c.id.in_(team_list))
        ).all()
        tname = {r.id: r.name for r in trows}

        all_team_rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
        name_by_id = {r.id: r.name for r in all_team_rows}

        sids = list(sid_by_label.values())
        mrows = conn.execute(
            select(
                Matches.c.date, Matches.c.season_id,
                Matches.c.home_team_id, Matches.c.away_team_id,
                Matches.c.HC, Matches.c.AC
            )
            .where(Matches.c.league_id == league_id, Matches.c.season_id.in_(sids))
            .where(or_(Matches.c.home_team_id.in_(team_list), Matches.c.away_team_id.in_(team_list)))
            .order_by(Matches.c.date.asc())
        ).all()

    points: List[Dict[str, Any]] = []
    label_by_sid = {v: k for k, v in sid_by_label.items()}

    for m in mrows:
        if m.HC is None or m.AC is None:
            continue
        HCO, ACO = int(m.HC), int(m.AC)
        lbl = label_by_sid.get(m.season_id)
        total = HCO + ACO

        home_id = m.home_team_id
        away_id = m.away_team_id
        home_name = name_by_id.get(home_id, str(home_id))
        away_name = name_by_id.get(away_id, str(away_id))
        score_str = f"{HCO}–{ACO}"
        match_label = f"{home_name} {score_str} {away_name}"

        for tid in team_list:
            if tid == home_id:
                cf = HCO; ca = ACO; opp = away_name; ha = "H"
            elif tid == away_id:
                cf = ACO; ca = HCO; opp = home_name; ha = "A"
            else:
                continue
            points.append(dict(
                date=str(m.date),
                season=lbl,
                team_id=tid,
                team_name=tname.get(tid, str(tid)),
                corners_for=cf,
                corners_against=ca,
                total_corners=total,
                opponent_name=opp,
                ha=ha,
                match_home=home_name,
                match_away=away_name,
                score=score_str,
                match_label=match_label,
            ))
    return SeriesResponse(seasons=season_labels, points=[TimePoint(**p) for p in points])

# =============== API: ряды по ЖЁЛТЫМ КАРТОЧКАМ ===============
@app.get("/api/timeseries_cards", response_model=SeriesResponse)
def api_timeseries_cards(
    league_id: int = Query(..., ge=1),
    team_ids: str = Query(...),
    seasons: str = Query(...),
):
    try:
        team_list = [int(x) for x in team_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(400, "Invalid team_ids")

    season_labels = [x.strip() for x in seasons.split(",") if x.strip()]
    if not team_list or not season_labels:
        raise HTTPException(400, "team_ids and seasons are required")

    with engine.begin() as conn:
        srows = conn.execute(
            select(Seasons.c.id, Seasons.c.label)
            .where(Seasons.c.league_id == league_id, Seasons.c.label.in_(season_labels))
        ).all()
        sid_by_label = {r.label: r.id for r in srows}
        if not sid_by_label:
            raise HTTPException(404, "No seasons found")

        trows = conn.execute(
            select(Teams.c.id, Teams.c.name)
            .where(Teams.c.id.in_(team_list))
        ).all()
        tname = {r.id: r.name for r in trows}

        all_team_rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
        name_by_id = {r.id: r.name for r in all_team_rows}

        sids = list(sid_by_label.values())
        mrows = conn.execute(
            select(
                Matches.c.date, Matches.c.season_id,
                Matches.c.home_team_id, Matches.c.away_team_id,
                Matches.c.HY, Matches.c.AY
            )
            .where(Matches.c.league_id == league_id, Matches.c.season_id.in_(sids))
            .where(or_(Matches.c.home_team_id.in_(team_list), Matches.c.away_team_id.in_(team_list)))
            .order_by(Matches.c.date.asc())
        ).all()

    points: List[Dict[str, Any]] = []
    label_by_sid = {v: k for k, v in sid_by_label.items()}

    for m in mrows:
        if m.HY is None or m.AY is None:
            continue
        HY, AY = int(m.HY), int(m.AY)
        lbl = label_by_sid.get(m.season_id)
        total = HY + AY

        home_id = m.home_team_id
        away_id = m.away_team_id
        home_name = name_by_id.get(home_id, str(home_id))
        away_name = name_by_id.get(away_id, str(away_id))
        score_str = f"{HY}–{AY}"
        match_label = f"{home_name} {score_str} {away_name}"

        for tid in team_list:
            if tid == home_id:
                cf = HY; ca = AY; opp = away_name; ha = "H"
            elif tid == away_id:
                cf = AY; ca = HY; opp = home_name; ha = "A"
            else:
                continue
            points.append(dict(
                date=str(m.date),
                season=lbl,
                team_id=tid,
                team_name=tname.get(tid, str(tid)),
                cards_for=cf,
                cards_against=ca,
                total_cards=total,
                opponent_name=opp,
                ha=ha,
                match_home=home_name,
                match_away=away_name,
                score=score_str,
                match_label=match_label,
            ))
    return SeriesResponse(seasons=season_labels, points=[TimePoint(**p) for p in points])

# =============== API: ряды по SHOTS (общие удары) ===============
@app.get("/api/timeseries_shots", response_model=SeriesResponse)
def api_timeseries_shots(
    league_id: int = Query(..., ge=1),
    team_ids: str = Query(...),
    seasons: str = Query(...),
):
    try:
        team_list = [int(x) for x in team_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(400, "Invalid team_ids")

    season_labels = [x.strip() for x in seasons.split(",") if x.strip()]
    if not team_list or not season_labels:
        raise HTTPException(400, "team_ids and seasons are required")

    with engine.begin() as conn:
        srows = conn.execute(
            select(Seasons.c.id, Seasons.c.label)
            .where(Seasons.c.league_id == league_id, Seasons.c.label.in_(season_labels))
        ).all()
        sid_by_label = {r.label: r.id for r in srows}
        if not sid_by_label:
            raise HTTPException(404, "No seasons found")

        trows = conn.execute(select(Teams.c.id, Teams.c.name).where(Teams.c.id.in_(team_list))).all()
        tname = {r.id: r.name for r in trows}

        all_team_rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
        name_by_id = {r.id: r.name for r in all_team_rows}

        sids = list(sid_by_label.values())

        hs_col, as_col = _resolve_stat_columns("shots")
        if hs_col is None or as_col is None:
            return _empty_series(season_labels)

        mrows = conn.execute(
            select(
                Matches.c.date, Matches.c.season_id,
                Matches.c.home_team_id, Matches.c.away_team_id,
                hs_col.label("HVAL"), as_col.label("AVAL")
            )
            .where(Matches.c.league_id == league_id, Matches.c.season_id.in_(sids))
            .where(or_(Matches.c.home_team_id.in_(team_list), Matches.c.away_team_id.in_(team_list)))
            .order_by(Matches.c.date.asc())
        ).all()

    points: List[Dict[str, Any]] = []
    label_by_sid = {v: k for k, v in sid_by_label.items()}

    for m in mrows:
        HV, AV = m.HVAL, m.AVAL
        if HV is None or AV is None:
            continue
        HS, AS_ = int(HV), int(AV)
        lbl = label_by_sid.get(m.season_id)
        total = HS + AS_

        home_id = m.home_team_id
        away_id = m.away_team_id
        home_name = name_by_id.get(home_id, str(home_id))
        away_name = name_by_id.get(away_id, str(away_id))
        score_str = f"{HS}–{AS_}"
        match_label = f"{home_name} {score_str} {away_name}"

        for tid in team_list:
            if tid == home_id:
                sf, sa, opp, ha = HS, AS_, away_name, "H"
            elif tid == away_id:
                sf, sa, opp, ha = AS_, HS, home_name, "A"
            else:
                continue
            points.append(dict(
                date=str(m.date),
                season=lbl,
                team_id=tid,
                team_name=tname.get(tid, str(tid)),
                shots_for=sf,
                shots_against=sa,
                total_shots=total,
                opponent_name=opp,
                ha=ha,
                match_home=home_name,
                match_away=away_name,
                score=score_str,
                match_label=match_label,
            ))
    return SeriesResponse(seasons=season_labels, points=[TimePoint(**p) for p in points])

# =============== API: ряды по SOT (удары в створ) ===============
@app.get("/api/timeseries_sot", response_model=SeriesResponse)
def api_timeseries_sot(
    league_id: int = Query(..., ge=1),
    team_ids: str = Query(...),
    seasons: str = Query(...),
):
    try:
        team_list = [int(x) for x in team_ids.split(",") if x.strip()]
    except Exception:
        raise HTTPException(400, "Invalid team_ids")

    season_labels = [x.strip() for x in seasons.split(",") if x.strip()]
    if not team_list or not season_labels:
        raise HTTPException(400, "team_ids and seasons are required")

    with engine.begin() as conn:
        srows = conn.execute(
            select(Seasons.c.id, Seasons.c.label)
            .where(Seasons.c.league_id == league_id, Seasons.c.label.in_(season_labels))
        ).all()
        sid_by_label = {r.label: r.id for r in srows}
        if not sid_by_label:
            raise HTTPException(404, "No seasons found")

        trows = conn.execute(select(Teams.c.id, Teams.c.name).where(Teams.c.id.in_(team_list))).all()
        tname = {r.id: r.name for r in trows}

        all_team_rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
        name_by_id = {r.id: r.name for r in all_team_rows}

        sids = list(sid_by_label.values())

        hst_col, ast_col = _resolve_stat_columns("sot")
        if hst_col is None or ast_col is None:
            return _empty_series(season_labels)

        mrows = conn.execute(
            select(
                Matches.c.date, Matches.c.season_id,
                Matches.c.home_team_id, Matches.c.away_team_id,
                hst_col.label("HVAL"), ast_col.label("AVAL")
            )
            .where(Matches.c.league_id == league_id, Matches.c.season_id.in_(sids))
            .where(or_(Matches.c.home_team_id.in_(team_list), Matches.c.away_team_id.in_(team_list)))
            .order_by(Matches.c.date.asc())
        ).all()

    points: List[Dict[str, Any]] = []
    label_by_sid = {v: k for k, v in sid_by_label.items()}

    for m in mrows:
        HV, AV = m.HVAL, m.AVAL
        if HV is None or AV is None:
            continue
        HST, AST_ = int(HV), int(AV)
        lbl = label_by_sid.get(m.season_id)
        total = HST + AST_

        home_id = m.home_team_id
        away_id = m.away_team_id
        home_name = name_by_id.get(home_id, str(home_id))
        away_name = name_by_id.get(away_id, str(away_id))
        score_str = f"{HST}–{AST_}"
        match_label = f"{home_name} {score_str} {away_name}"

        for tid in team_list:
            if tid == home_id:
                sf, sa, opp, ha = HST, AST_, away_name, "H"
            elif tid == away_id:
                sf, sa, opp, ha = AST_, HST, home_name, "A"
            else:
                continue
            points.append(dict(
                date=str(m.date),
                season=lbl,
                team_id=tid,
                team_name=tname.get(tid, str(tid)),
                sot_for=sf,
                sot_against=sa,
                total_sot=total,
                opponent_name=opp,
                ha=ha,
                match_home=home_name,
                match_away=away_name,
                score=score_str,
                match_label=match_label,
            ))
    return SeriesResponse(seasons=season_labels, points=[TimePoint(**p) for p in points])

# ====== SUPERPROG (Dixon–Coles) ======
from math import exp, sqrt
from datetime import datetime

class SuperProgOut(BaseModel):
    team_id: int
    season_labels: list[str]
    ha_mode: str               # 'all'|'home'|'away'
    opponent_id: int | None
    lambda_gf: float
    lambda_ga: float
    lambda_total: float
    ci_total_low: float
    ci_total_high: float
    n_matches: int
    half_life_days: float
    rho: float
    stat_type: str

def _timestamp(dt)->float:
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt).timestamp()
        except:
            return 0.0
    if isinstance(dt, datetime):
        return dt.timestamp()
    return 0.0

def _exp_decay(w_age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0: return 1.0
    return 2 ** ( - w_age_days / half_life_days )

def _fit_dc_strengths(matches, team_ids_set, half_life_days: float, rho_init: float = 0.05,
                      max_iter:int=60, tol:float=1e-6):
    teams = sorted(list(team_ids_set))
    idx = {tid:i for i,tid in enumerate(teams)}
    nT = len(teams)
    atk = [0.0]*nT
    dfn = [0.0]*nT
    home_adv = 0.20
    rho = rho_init

    def _normalize():
        a_mean = sum(atk)/max(nT,1)
        d_mean = sum(dfn)/max(nT,1)
        for i in range(nT):
            atk[i] -= a_mean
            dfn[i] -= d_mean

    if matches:
        tmax = max(_timestamp(m['date']) for m in matches)
    else:
        tmax = 0.0

    for _ in range(max_iter):
        _normalize()
        g_atk = [0.0]*nT
        g_dfn = [0.0]*nT
        g_h = 0.0
        g_rho = 0.0

        h_atk = [1e-6]*nT
        h_dfn = [1e-6]*nT
        h_h = 1e-6
        h_rho = 1e-6

        for m in matches:
            ht = m['home_team_id']; at = m['away_team_id']
            hg = m['FTHX']; ag = m['FTAX']
            if hg is None or ag is None: continue
            i = idx.get(ht); j = idx.get(at)
            if i is None or j is None: continue

            age_days = max(0.0, (tmax - _timestamp(m['date']))/86400.0)
            w = _exp_decay(age_days, half_life_days)

            lam_h = exp(atk[i] - dfn[j] + home_adv)
            lam_a = exp(atk[j] - dfn[i])

            g_atk[i] += w*(hg - lam_h)
            g_dfn[j] += w*(-hg + lam_h)
            g_atk[j] += w*(ag - lam_a)
            g_dfn[i] += w*(-ag + lam_a)
            g_h += w*(hg - lam_h)

            h_atk[i] += w*lam_h
            h_dfn[j] += w*lam_h
            h_atk[j] += w*lam_a
            h_dfn[i] += w*lam_a
            h_h += w*lam_h

            if (hg,ag) in [(0,0),(0,1),(1,0),(1,1)]:
                # простая регуляризация корреляции для низких счётов
                g_rho += w*0.0
                h_rho += w

        step = 0.25
        for i in range(nT):
            atk[i] += step * g_atk[i]/h_atk[i]
            dfn[i] += step * g_dfn[i]/h_dfn[i]
        home_adv += step * g_h / h_h
        rho += step * g_rho / max(h_rho,1e-6)
        rho = max(-0.3, min(0.3, rho))

        if max(
            max(abs(step*g_atk[i]/h_atk[i]) for i in range(nT)) if nT else 0.0,
            max(abs(step*g_dfn[i]/h_dfn[i]) for i in range(nT)) if nT else 0.0,
            abs(step*g_h/h_h),
        ) < tol:
            break

    _normalize()
    return atk, dfn, home_adv, rho

def _load_matches_for_league(league_id:int, season_labels:list[str], conn, stat_type:str):
    sids = [r[0] for r in conn.execute(
        select(Seasons.c.id).where(Seasons.c.league_id==league_id, Seasons.c.label.in_(season_labels))
    ).all()]
    if not sids: return [], set()

    if stat_type == 'corners':
        rows = conn.execute(
            select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
                   Matches.c.HC.label("HVAL"), Matches.c.AC.label("AVAL"))
            .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
            .order_by(Matches.c.date.asc())
        ).all()
        getter = lambda r: (r.HVAL, r.AVAL)

    elif stat_type == 'cards':
        rows = conn.execute(
            select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
                   Matches.c.HY.label("HVAL"), Matches.c.AY.label("AVAL"))
            .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
            .order_by(Matches.c.date.asc())
        ).all()
        getter = lambda r: (r.HVAL, r.AVAL)

    elif stat_type == 'shots':
        hcol, acol = _resolve_stat_columns("shots")
        if hcol is None or acol is None:
            return [], set()
        rows = conn.execute(
            select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
                   hcol.label("HVAL"), acol.label("AVAL"))
            .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
            .order_by(Matches.c.date.asc())
        ).all()
        getter = lambda r: (r.HVAL, r.AVAL)

    elif stat_type == 'sot':
        hcol, acol = _resolve_stat_columns("sot")
        if hcol is None or acol is None:
            return [], set()
        rows = conn.execute(
            select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
                   hcol.label("HVAL"), acol.label("AVAL"))
            .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
            .order_by(Matches.c.date.asc())
        ).all()
        getter = lambda r: (r.HVAL, r.AVAL)

    else:  # goals
        rows = conn.execute(
            select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
                   Matches.c.FTHG.label("HVAL"), Matches.c.FTAG.label("AVAL"))
            .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
            .order_by(Matches.c.date.asc())
        ).all()
        getter = lambda r: (r.HVAL, r.AVAL)

    matches = []
    teams = set()
    for r in rows:
        d, h, a = r.date, int(r.home_team_id), int(r.away_team_id)
        hg, ag = getter(r)
        if hg is None or ag is None: 
            continue
        teams.add(h); teams.add(a)
        matches.append({
            'date': str(d), 'home_team_id': h, 'away_team_id': a,
            'FTHX': int(hg), 'FTAX': int(ag),
        })
    return matches, teams

def _extend_seasons_until_enough(league_id:int, chosen_labels:list[str], conn, stat_type:str, min_matches:int=50):
    """
    Расширяем окно сезонов назад, пока не наберём нужное число матчей с ненулевой статой.
    """
    all_rows = conn.execute(
        select(Seasons.c.label).where(Seasons.c.league_id == league_id)
    ).all()
    all_labels = _sort_labels_desc([r.label for r in all_rows])

    # стартуем с выбранного окна в их порядке
    window = list(chosen_labels)
    seen = set(window)

    while True:
        matches, _ = _load_matches_for_league(league_id, window, conn, stat_type)
        if len(matches) >= min_matches:
            return window
        # ищем следующий более старый сезон
        last_idx = max(all_labels.index(l) for l in window if l in all_labels) if window else -1
        next_idx = last_idx + 1
        if next_idx >= len(all_labels):
            return window  # больше нечего добавлять
        nxt = all_labels[next_idx]
        if nxt not in seen:
            window.append(nxt)
            seen.add(nxt)

@app.get("/api/superprog", response_model=SuperProgOut)
def api_superprog(
    league_id: int = Query(..., ge=1),
    team_id: int = Query(..., ge=1),
    seasons: str = Query(..., description="comma-separated season labels"),
    ha_mode: str = Query("all", regex="^(all|home|away)$"),
    opponent_id: int | None = Query(None),
    half_life_days: float = Query(180.0, ge=1.0, le=2000.0),
    stat_type: str = Query("goals", regex="^(goals|corners|cards|shots|sot)$"),
):
    """
    Dixon–Coles + экспоненциальное затухание.
    Поддерживает: goals / corners / cards / shots / sot.
    """
    season_labels = [s.strip() for s in seasons.split(",") if s.strip()]
    if not season_labels: 
        raise HTTPException(400, "seasons required")

    min_needed = 50 if stat_type == "goals" else 30

    with engine.begin() as conn:
        season_labels = _extend_seasons_until_enough(league_id, season_labels, conn, stat_type, min_matches=min_needed)
        matches, team_ids_set = _load_matches_for_league(league_id, season_labels, conn, stat_type)

        n_matches = len(matches)
        if n_matches < max(15, min_needed // 2):
            raise HTTPException(404, f"Недостаточно данных для оценки ({n_matches} записей)")

        atk, dfn, home_adv, rho = _fit_dc_strengths(matches, team_ids_set, half_life_days=half_life_days)

        teams = sorted(list(team_ids_set))
        idx = {tid:i for i,tid in enumerate(teams)}
        if team_id not in idx:
            raise HTTPException(404, "team_id not present in this league/seasons window")

        i = idx[team_id]

        def pair_lambda(i, j, mode):
            if mode == 'home':
                lam_gf = exp(atk[i] - dfn[j] + home_adv)
                lam_ga = exp(atk[j] - dfn[i])
            elif mode == 'away':
                lam_gf = exp(atk[i] - dfn[j])
                lam_ga = exp(atk[j] - dfn[i] + home_adv)
            else:
                lam_home_gf = exp(atk[i] - dfn[j] + home_adv)
                lam_home_ga = exp(atk[j] - dfn[i])
                lam_away_gf = exp(atk[i] - dfn[j])
                lam_away_ga = exp(atk[j] - dfn[i] + home_adv)
                lam_gf = 0.5*(lam_home_gf + lam_away_gf)
                lam_ga = 0.5*(lam_home_ga + lam_away_ga)
                return lam_gf, lam_ga
            return lam_gf, lam_ga

        if opponent_id is not None and opponent_id in idx:
            j = idx[opponent_id]
            lam_gf, lam_ga = pair_lambda(i, j, ha_mode)
        else:
            a_avg = 0.0; d_avg = 0.0
            if ha_mode == 'home':
                lam_gf = exp(atk[i] - d_avg + home_adv)
                lam_ga = exp(a_avg - dfn[i])
            elif ha_mode == 'away':
                lam_gf = exp(atk[i] - d_avg)
                lam_ga = exp(a_avg - dfn[i] + home_adv)
            else:
                lam_gf = 0.5*(exp(atk[i] - d_avg + home_adv) + exp(atk[i] - d_avg))
                lam_ga = 0.5*(exp(a_avg - dfn[i]) + exp(a_avg - dfn[i] + home_adv))

        lam_total = lam_gf + lam_ga
        sigma = sqrt(max(lam_total, 1e-9))

    return SuperProgOut(
        team_id=team_id,
        season_labels=season_labels,
        ha_mode=ha_mode,
        opponent_id=opponent_id,
        lambda_gf=float(lam_gf),
        lambda_ga=float(lam_ga),
        lambda_total=float(lam_total),
        ci_total_low=float(max(0.0, lam_total - sigma)),
        ci_total_high=float(lam_total + sigma),
        n_matches=n_matches,
        half_life_days=half_life_days,
        rho=float(rho),
        stat_type=stat_type,
    )


from sqlalchemy import func

@app.get("/api/diag/routes")
def api_diag_routes():
    return [r.path for r in app.router.routes]

@app.get("/api/diag/matches-columns")
def api_diag_matches_columns():
    return {"matches_columns": list(Matches.c.keys())}

@app.get("/api/diag/stat-counts")
def api_diag_stat_counts(league_id: int, seasons: str):
    labels = [x.strip() for x in seasons.split(",") if x.strip()]
    with engine.begin() as conn:
        sids = [r[0] for r in conn.execute(
            select(Seasons.c.id).where(Seasons.c.league_id == league_id, Seasons.c.label.in_(labels))
        ).all()]
        hs  = Matches.c.HS if "HS"  in Matches.c.keys() else None
        aS  = Matches.c.AS_ if "AS_" in Matches.c.keys() else (Matches.c.AS if "AS" in Matches.c.keys() else None)
        hst = Matches.c.HST if "HST" in Matches.c.keys() else None
        ast = Matches.c.AST if "AST" in Matches.c.keys() else None

        def _cnt(c1, c2):
            if c1 is None or c2 is None or not sids:
                return 0
            return conn.execute(
                select(func.count()).where(
                    Matches.c.league_id == league_id,
                    Matches.c.season_id.in_(sids),
                    c1.isnot(None),
                    c2.isnot(None),
                )
            ).scalar_one()

        return {
            "shots_rows": _cnt(hs, aS),
            "sot_rows": _cnt(hst, ast),
            "seasons": labels,
        }


# статика
app.mount("/", StaticFiles(directory="static", html=True), name="static")
