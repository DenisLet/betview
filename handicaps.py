# handicaps.py
from __future__ import annotations
from typing import List, Dict, Tuple
from math import exp
from datetime import datetime

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, MetaData, Table, select

import os
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

router = APIRouter()

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

def _col(tbl, *candidates):
    cols = set(tbl.c.keys())
    for name in candidates:
        if name in cols:
            return tbl.c[name]
    return None

def _resolve_stat_columns(stat_type: str):
    """
    Возвращает пары колонок (home, away) для выбранного типа статистики.
    """
    st = (stat_type or "goals").lower()
    if st == "goals":
        return Matches.c.FTHG, Matches.c.FTAG
    if st == "shots":
        h = _col(Matches, "HS", "HomeShots", "shots_home", "SH", "S_H")
        a = _col(Matches, "AS_", "AS", "AwayShots", "shots_away", "SA", "S_A")
        return h, a
    if st == "sot":
        h = _col(Matches, "HST", "HomeShotsOnTarget", "sot_home", "HSoT")
        a = _col(Matches, "AST", "AwayShotsOnTarget", "sot_away", "ASoT")
        return h, a
    if st == "corners":
        h = _col(Matches, "HC", "HomeCorners", "corners_home")
        a = _col(Matches, "AC", "AwayCorners", "corners_away")
        return h, a
    if st == "cards":
        # берём жёлтые (HY/AY). При желании можно сделать параметр "cards=yellow|red|total".
        h = _col(Matches, "HY", "HomeYellows", "cards_y_home")
        a = _col(Matches, "AY", "AwayYellows", "cards_y_away")
        return h, a
    return None, None

def _timestamp(dt)->float:
    if isinstance(dt, str):
        try:
            return datetime.fromisoformat(dt).timestamp()
        except:
            return 0.0
    if isinstance(dt, datetime):
        return dt.timestamp()
    return 0.0

def _exp_decay(age_days: float, half_life_days: float) -> float:
    if half_life_days <= 0: return 1.0
    return 2 ** ( - age_days / half_life_days )

def _fit_dc_strengths(matches, team_ids_set, half_life_days: float, max_iter:int=60, tol:float=1e-6):
    """
    Лог-пуассоновская регрессия «атака/оборона + home_adv».
    Универсальна для любых счётных метрик (голы, угловые, удары, карточки и т.д.).
    """
    teams = sorted(list(team_ids_set))
    idx = {tid:i for i,tid in enumerate(teams)}
    nT = len(teams)
    atk = [0.0]*nT
    dfn = [0.0]*nT
    home_adv = 0.20

    def _normalize():
        if nT == 0: return
        a_mean = sum(atk)/nT
        d_mean = sum(dfn)/nT
        for i in range(nT):
            atk[i] -= a_mean
            dfn[i] -= d_mean

    tmax = max((_timestamp(m['date']) for m in matches), default=0.0)

    for _ in range(max_iter):
        _normalize()
        g_atk = [0.0]*nT
        g_dfn = [0.0]*nT
        g_h   = 0.0

        h_atk = [1e-6]*nT
        h_dfn = [1e-6]*nT
        h_h   = 1e-6

        for m in matches:
            ht = m['home_team_id']; at = m['away_team_id']
            hv = m['HVAL'];         av = m['AVAL']
            if hv is None or av is None: 
                continue
            i = idx.get(ht); j = idx.get(at)
            if i is None or j is None: 
                continue

            age_days = max(0.0, (tmax - _timestamp(m['date']))/86400.0)
            w = _exp_decay(age_days, half_life_days)

            lam_h = exp(atk[i] - dfn[j] + home_adv)
            lam_a = exp(atk[j] - dfn[i])

            g_atk[i] += w*(hv - lam_h)
            g_dfn[j] += w*(-hv + lam_h)
            g_atk[j] += w*(av - lam_a)
            g_dfn[i] += w*(-av + lam_a)
            g_h      += w*(hv - lam_h)

            h_atk[i] += w*lam_h
            h_dfn[j] += w*lam_h
            h_atk[j] += w*lam_a
            h_dfn[i] += w*lam_a
            h_h      += w*lam_h

        step = 0.25
        for i in range(nT):
            atk[i] += step * g_atk[i]/h_atk[i]
            dfn[i] += step * g_dfn[i]/h_dfn[i]
        home_adv += step * g_h / h_h

        if max(
            max(abs(step*g_atk[i]/h_atk[i]) for i in range(nT)) if nT else 0.0,
            max(abs(step*g_dfn[i]/h_dfn[i]) for i in range(nT)) if nT else 0.0,
            abs(step*g_h/h_h),
        ) < tol:
            break

    _normalize()
    return teams, atk, dfn, home_adv

def _load_matches_for_league(league_id:int, season_labels:list[str], stat_type:str, conn):
    hcol, acol = _resolve_stat_columns(stat_type)
    if hcol is None or acol is None:
        raise HTTPException(400, f"Unsupported stat_type: {stat_type}")

    sids = [r[0] for r in conn.execute(
        select(Seasons.c.id).where(Seasons.c.league_id==league_id, Seasons.c.label.in_(season_labels))
    ).all()]
    if not sids:
        return [], set()

    rows = conn.execute(
        select(Matches.c.date, Matches.c.home_team_id, Matches.c.away_team_id,
               hcol.label("HVAL"), acol.label("AVAL"))
        .where(Matches.c.league_id==league_id, Matches.c.season_id.in_(sids))
        .order_by(Matches.c.date.asc())
    ).all()

    matches = []
    teams = set()
    for r in rows:
        d, h, a, hv, av = r.date, int(r.home_team_id), int(r.away_team_id), r.HVAL, r.AVAL
        if hv is None or av is None:
            continue
        teams.add(h); teams.add(a)
        try:
            hv = int(hv)
            av = int(av)
        except:
            # на случай float-колонок — округляем
            hv = int(round(float(hv)))
            av = int(round(float(av)))
        matches.append({
            'date': str(d), 'home_team_id': h, 'away_team_id': a,
            'HVAL': hv, 'AVAL': av,
        })
    return matches, teams

def _extend_seasons_until_enough(league_id:int, chosen_labels:list[str], stat_type:str, conn, min_matches:int=50):
    all_rows = conn.execute(
        select(Seasons.c.label).where(Seasons.c.league_id == league_id)
    ).all()
    all_labels = _sort_labels_desc([r.label for r in all_rows])

    window = list(chosen_labels)
    seen = set(window)

    while True:
        matches, _ = _load_matches_for_league(league_id, window, stat_type, conn)
        if len(matches) >= min_matches:
            return window
        last_idx = max((all_labels.index(l) for l in window if l in all_labels), default=-1)
        next_idx = last_idx + 1
        if next_idx >= len(all_labels):
            return window
        nxt = all_labels[next_idx]
        if nxt not in seen:
            window.append(nxt)
            seen.add(nxt)

def _pair_lambdas(teams, atk, dfn, home_adv, team_id:int, opponent_id:int|None, mode:str)->Tuple[float,float]:
    idx = {tid:i for i,tid in enumerate(teams)}
    if team_id not in idx:
        raise HTTPException(404, "team_id not present in this league/seasons window")

    i = idx[team_id]
    if opponent_id is not None and opponent_id in idx:
        j = idx[opponent_id]
        if mode == 'home':
            lam_for = exp(atk[i] - dfn[j] + home_adv)
            lam_agn = exp(atk[j] - dfn[i])
        elif mode == 'away':
            lam_for = exp(atk[i] - dfn[j])
            lam_agn = exp(atk[j] - dfn[i] + home_adv)
        else:  # all
            lam_home_for = exp(atk[i] - dfn[j] + home_adv)
            lam_home_agn = exp(atk[j] - dfn[i])
            lam_away_for = exp(atk[i] - dfn[j])
            lam_away_agn = exp(atk[j] - dfn[i] + home_adv)
            lam_for = 0.5*(lam_home_for + lam_away_for)
            lam_agn = 0.5*(lam_home_agn + lam_away_agn)
        return float(lam_for), float(lam_agn)

    # против «среднего» соперника
    a_avg = 0.0; d_avg = 0.0
    if mode == 'home':
        lam_for = exp(atk[i] - d_avg + home_adv)
        lam_agn = exp(a_avg - dfn[i])
    elif mode == 'away':
        lam_for = exp(atk[i] - d_avg)
        lam_agn = exp(a_avg - dfn[i] + home_adv)
    else:
        lam_for = 0.5*(exp(atk[i] - d_avg + home_adv) + exp(atk[i] - d_avg))
        lam_agn = 0.5*(exp(a_avg - dfn[i]) + exp(a_avg - dfn[i] + home_adv))
    return float(lam_for), float(lam_agn)

def _poisson_pmf(lam: float, k: int) -> float:
    if k < 0: 
        return 0.0
    p = exp(-lam)
    for i in range(1, k+1):
        p *= lam / i
    return p

def _joint_prob_table(l1: float, l2: float, max_g: int = 12) -> List[List[float]]:
    ph = [_poisson_pmf(l1, k) for k in range(max_g+1)]
    pa = [_poisson_pmf(l2, k) for k in range(max_g+1)]
    return [[ph[h]*pa[a] for a in range(max_g+1)] for h in range(max_g+1)]

def _moneyline_probs(l1: float, l2: float, max_g:int=12) -> Dict[str,float]:
    tbl = _joint_prob_table(l1, l2, max_g=max_g)
    pH = sum(tbl[h][a] for h in range(max_g+1) for a in range(max_g+1) if h > a)
    pD = sum(tbl[h][a] for h in range(max_g+1) for a in range(max_g+1) if h == a)
    pA = 1.0 - pH - pD
    return {"home": pH, "draw": pD, "away": pA}

def _ah_probs(l1: float, l2: float, line: float, team_is_home: bool, max_g:int=12) -> Dict[str,float]:
    q = abs(line*2 - round(line*2))
    if q > 1e-9:  # четвертные
        if line > 0:
            l1a = line - 0.25
            l1b = line + 0.25
        else:
            l1a = line + 0.25
            l1b = line - 0.25
        p1 = _ah_probs(l1, l2, l1a, team_is_home, max_g=max_g)
        p2 = _ah_probs(l1, l2, l1b, team_is_home, max_g=max_g)
        return {
            "cover": 0.5*(p1["cover"] + p2["cover"]),
            "push":  0.5*(p1["push"]  + p2["push"]),
            "lose":  0.5*(p1["lose"]  + p2["lose"]),
        }

    tbl = _joint_prob_table(l1, l2, max_g=max_g)
    cover = push = lose = 0.0
    for h in range(max_g+1):
        for a in range(max_g+1):
            p = tbl[h][a]
            margin = (h - a) if team_is_home else (a - h)
            if margin > line + 1e-12:
                cover += p
            elif abs(margin - line) <= 1e-12:
                push += p
            else:
                lose += p
    return {"cover": cover, "push": push, "lose": lose}

def _fair_decimal(p: float) -> float:
    return float('inf') if p <= 0 else 1.0/p

class AHQuote(BaseModel):
    line: float
    cover: float
    push: float
    lose: float
    fair_odds_cover: float

class AHPreviewOut(BaseModel):
    team_id: int
    season_labels: list[str]
    stat_type: str            # NEW: goals|corners|cards|shots|sot
    ha_mode: str              # 'all'|'home'|'away'
    opponent_id: int | None
    lambda_gf: float
    lambda_ga: float
    moneyline: Dict[str, float]
    asian: List[AHQuote]
    lines: List[float]

@router.get("/api/handicaps", response_model=AHPreviewOut)
def api_handicaps(
    league_id: int = Query(..., ge=1),
    team_id: int   = Query(..., ge=1),
    seasons: str   = Query(..., description="comma-separated season labels"),
    stat_type: str = Query("goals", regex="^(goals|corners|cards|shots|sot)$"),
    ha_mode: str   = Query("all", regex="^(all|home|away)$"),
    opponent_id: int | None = Query(None),
    half_life_days: float = Query(180.0, ge=1.0, le=2000.0),
    lines: str = Query("-1.5,-1,-0.75,-0.5,-0.25,0,+0.25,+0.5,+0.75,+1,+1.5"),
):
    season_labels = [s.strip() for s in seasons.split(",") if s.strip()]
    if not season_labels:
        raise HTTPException(400, "seasons required")

    try:
        line_vals = [float(x.strip()) for x in lines.split(",") if x.strip()]
    except:
        raise HTTPException(400, "Bad line in 'lines'")

    with engine.begin() as conn:
        season_labels = _extend_seasons_until_enough(league_id, season_labels, stat_type, conn, min_matches=50)
        matches, team_ids_set = _load_matches_for_league(league_id, season_labels, stat_type, conn)
        if len(matches) < 20:
            raise HTTPException(404, "Недостаточно данных для оценки")

        teams, atk, dfn, home_adv = _fit_dc_strengths(
            matches, team_ids_set, half_life_days=half_life_days
        )

    lam_gf, lam_ga = _pair_lambdas(teams, atk, dfn, home_adv, team_id, opponent_id, ha_mode)
    mprobs = _moneyline_probs(lam_gf, lam_ga, max_g=20 if stat_type in ("shots","sot") else 12)

    def _quotes_for_mode(is_home: bool):
        q = []
        for ln in line_vals:
            stats = _ah_probs(lam_gf, lam_ga, ln, team_is_home=is_home, max_g=20 if stat_type in ("shots","sot") else 12)
            q.append(AHQuote(
                line=float(ln),
                cover=float(stats["cover"]),
                push=float(stats["push"]),
                lose=float(stats["lose"]),
                fair_odds_cover=_fair_decimal(stats["cover"])
            ))
        return q

    if ha_mode == "home":
        asian_quotes = _quotes_for_mode(True)
    elif ha_mode == "away":
        asian_quotes = _quotes_for_mode(False)
    else:
        hq = _quotes_for_mode(True)
        aq = _quotes_for_mode(False)
        asian_quotes = []
        for h, a in zip(hq, aq):
            cover = 0.5*(h.cover + a.cover)
            push  = 0.5*(h.push  + a.push)
            lose  = 0.5*(h.lose  + a.lose)
            asian_quotes.append(AHQuote(
                line=h.line,
                cover=cover, push=push, lose=lose,
                fair_odds_cover=_fair_decimal(cover)
            ))

    return AHPreviewOut(
        team_id=team_id,
        season_labels=season_labels,
        stat_type=stat_type,
        ha_mode=ha_mode,
        opponent_id=opponent_id,
        lambda_gf=float(lam_gf),
        lambda_ga=float(lam_ga),
        moneyline=mprobs,
        asian=asian_quotes,
        lines=[float(x) for x in line_vals],
    )
