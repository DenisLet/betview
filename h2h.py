# h2h.py — стабильная версия /api/h2h_odds с optional open/close
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import os
from collections import defaultdict

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, MetaData, Table, select, and_, or_

DB_URL = os.environ.get(
    "BETMAKER_DB_URL",
    "sqlite:///C:/Users/HomeComp/PycharmProjects/pythonProject/UKparserToBD/betmaker.sqlite3"
)
engine = create_engine(DB_URL, future=True)
meta = MetaData()
meta.reflect(bind=engine)

Leagues: Table   = meta.tables["leagues"]
Seasons: Table   = meta.tables["seasons"]
Teams:   Table   = meta.tables["teams"]
Matches: Table   = meta.tables["matches"]
Odds1x2: Table   = meta.tables.get("odds_1x2")
OddsOU:  Table   = meta.tables.get("odds_ou")

router = APIRouter()

def _col(tbl: Table | None, *candidates: str):
    if tbl is None:
        return None
    keys = set(tbl.c.keys())
    for name in candidates:
        if name in keys:
            return tbl.c[name]
    return None

def _name_map(conn) -> Dict[int, str]:
    rows = conn.execute(select(Teams.c.id, Teams.c.name)).all()
    return {int(r.id): r.name for r in rows}

def _season_map(conn) -> Dict[int, str]:
    rows = conn.execute(select(Seasons.c.id, Seasons.c.label)).all()
    return {int(r.id): r.label for r in rows}

def _fetch_h2h_matches(conn, league_id:int, home_team_id:int, away_team_id:int, orientation:str):
    base = select(
        Matches.c.id.label("match_id"),
        Matches.c.date,
        Matches.c.season_id,
        Matches.c.home_team_id,
        Matches.c.away_team_id,
        Matches.c.FTHG,
        Matches.c.FTAG,
    ).where(Matches.c.league_id == league_id)

    if orientation == "both":
        q = base.where(or_(
            and_(Matches.c.home_team_id == home_team_id, Matches.c.away_team_id == away_team_id),
            and_(Matches.c.home_team_id == away_team_id, Matches.c.away_team_id == home_team_id),
        ))
    else:
        q = base.where(
            Matches.c.home_team_id == home_team_id,
            Matches.c.away_team_id == away_team_id,
        )
    return conn.execute(q.order_by(Matches.c.date.asc())).all()

class H2HSeriesOut(BaseModel):
    points: List[Dict[str, Any]]
    meta: Dict[str, Any]

@router.get("/api/h2h_odds", response_model=H2HSeriesOut)
def api_h2h_odds(
    league_id: int = Query(..., ge=1),
    home_team_id: int = Query(..., ge=1),
    away_team_id: int = Query(..., ge=1),
    bookmaker: str | None = Query(None, description="Если колонки нет — игнорируется"),
    line: float = Query(2.5),
    line_tol: float = Query(0.05, ge=0.0, le=1.0),
    use_closing: bool = Query(True, description="true -> is_closing=1 для close (если колонка есть)"),
    include_open: bool = Query(False, description="вернуть *_open из is_closing=0 (если колонка есть)"),
    orientation: str = Query("strict", regex="^(strict|both)$"),
):
    if Odds1x2 is None or OddsOU is None:
        raise HTTPException(500, "odds_* таблицы не найдены в БД")

    # columns (динамично)
    bk1_col     = _col(Odds1x2, "bookmaker", "bk", "bookie")
    close1_col  = _col(Odds1x2, "is_closing", "closing", "isclose")
    home_col    = _col(Odds1x2, "home", "one", "H")
    draw_col    = _col(Odds1x2, "draw", "X", "D")
    away_col    = _col(Odds1x2, "away", "two", "A")

    bkou_col    = _col(OddsOU, "bookmaker", "bk", "bookie")
    closeou_col = _col(OddsOU, "is_closing", "closing", "isclose")
    line_col    = _col(OddsOU, "line", "total_line", "ou_line")
    over_col    = _col(OddsOU, "over", "o", "over_odds")
    under_col   = _col(OddsOU, "under", "u", "under_odds")

    if home_col is None or draw_col is None or away_col is None:
        raise HTTPException(500, "В odds_1x2 нет обязательных колонок (home/draw/away).")
    if line_col is None or over_col is None or under_col is None:
        raise HTTPException(500, "В odds_ou нет обязательных колонок (line/over/under).")

    with engine.begin() as conn:
        name_by_id   = _name_map(conn)
        season_by_id = _season_map(conn)
        match_rows   = _fetch_h2h_matches(conn, league_id, home_team_id, away_team_id, orientation)
        if not match_rows:
            return H2HSeriesOut(points=[], meta={
                "league_id": league_id, "home_team_id": home_team_id, "away_team_id": away_team_id,
                "n_matches": 0, "bookmaker": bookmaker, "line": line, "line_tol": line_tol,
                "orientation": orientation, "has_open": False
            })
        match_ids = [int(r.match_id) for r in match_rows]

        # ---- helpers ----
        def fetch_1x2(state: str):
            where_ = [Odds1x2.c.match_id.in_(match_ids)]
            if state == "close" and use_closing and close1_col is not None:
                where_.append(close1_col == 1)
            if state == "open" and close1_col is not None:
                where_.append(close1_col == 0)
            if bookmaker and bk1_col is not None:
                where_.append(bk1_col == bookmaker)

            sel = [Odds1x2.c.match_id, home_col.label("one"), draw_col.label("draw"), away_col.label("two")]
            if bk1_col is not None:
                sel.append(bk1_col.label("bookmaker"))
            rows = conn.execute(select(*sel).where(and_(*where_))).all()

            r_one: Dict[int, float | None]  = {}
            r_draw: Dict[int, float | None] = {}
            r_two: Dict[int, float | None]  = {}
            if bookmaker and bk1_col is not None:
                for r in rows:
                    mid = int(r.match_id)
                    r_one[mid]  = float(r.one)  if r.one  is not None else None
                    r_draw[mid] = float(r.draw) if r.draw is not None else None
                    r_two[mid]  = float(r.two)  if r.two  is not None else None
            else:
                acc: Dict[int, Dict[str, list]] = defaultdict(lambda: {"one": [], "draw": [], "two": []})
                for r in rows:
                    mid = int(r.match_id)
                    if r.one  is not None:  acc[mid]["one"].append(float(r.one))
                    if r.draw is not None:  acc[mid]["draw"].append(float(r.draw))
                    if r.two  is not None:  acc[mid]["two"].append(float(r.two))
                for mid, d in acc.items():
                    r_one[mid]  = sum(d["one"])/len(d["one"])   if d["one"]  else None
                    r_draw[mid] = sum(d["draw"])/len(d["draw"]) if d["draw"] else None
                    r_two[mid]  = sum(d["two"])/len(d["two"])   if d["two"]  else None
            return r_one, r_draw, r_two

        def fetch_ou(state: str):
            where_ = [OddsOU.c.match_id.in_(match_ids)]
            if state == "close" and closeou_col is not None:
                where_.append(closeou_col == 1)
            if state == "open" and closeou_col is not None:
                where_.append(closeou_col == 0)

            sel = [OddsOU.c.match_id, line_col.label("line"), over_col.label("over"), under_col.label("under")]
            if bkou_col is not None:
                sel.append(bkou_col.label("bookmaker"))
            rows = conn.execute(select(*sel).where(and_(*where_))).all()

            best_per_mid_book: Dict[Tuple[int, str], Tuple[float, float | None, float | None]] = {}
            for r in rows:
                if r.line is None:
                    continue
                diff = abs(float(r.line) - float(line))
                if diff > float(line_tol):
                    continue
                mid = int(r.match_id)
                bk = str(getattr(r, "bookmaker", "") or "")
                prev = best_per_mid_book.get((mid, bk))
                if (prev is None) or (abs(prev[0] - line) > diff):
                    best_per_mid_book[(mid, bk)] = (
                        float(r.line),
                        float(r.over) if r.over is not None else None,
                        float(r.under) if r.under is not None else None
                    )

            grouped: Dict[int, list] = defaultdict(list)
            for (mid, bk), tup in best_per_mid_book.items():
                if bookmaker and bkou_col is not None and bk != bookmaker:
                    continue
                grouped[mid].append(tup)

            r_line: Dict[int, float | None]  = {}
            r_over: Dict[int, float | None]  = {}
            r_under: Dict[int, float | None] = {}
            for mid, arr in grouped.items():
                if not arr: continue
                Ls = [t[0] for t in arr if t[0] is not None]
                Os = [t[1] for t in arr if t[1] is not None]
                Us = [t[2] for t in arr if t[2] is not None]
                r_line[mid]  = sum(Ls)/len(Ls) if Ls else None
                r_over[mid]  = sum(Os)/len(Os) if Os else None
                r_under[mid] = sum(Us)/len(Us) if Us else None
            return r_line, r_over, r_under

        # ---- close
        one_c, draw_c, two_c = fetch_1x2("close")
        line_c, over_c, under_c = fetch_ou("close")

        # ---- open (опционально)
        one_o = draw_o = two_o = {}
        line_o = over_o = under_o = {}
        has_open = False
        if include_open and (close1_col is not None or closeou_col is not None):
            if close1_col is not None:
                one_o, draw_o, two_o = fetch_1x2("open")
                has_open = True
            if closeou_col is not None:
                line_o, over_o, under_o = fetch_ou("open")
                has_open = True

        points: List[Dict[str, Any]] = []
        for m in match_rows:
            mid = int(m.match_id)
            pt = {
                "date": str(m.date),
                "season": season_by_id.get(int(m.season_id), ""),
                "match_id": mid,
                "score": (f"{int(m.FTHG)}–{int(m.FTAG)}"
                          if (m.FTHG is not None and m.FTAG is not None) else "—"),
                # close
                "one":  one_c.get(mid),
                "draw": draw_c.get(mid),
                "two":  two_c.get(mid),
                "over":  over_c.get(mid),
                "under": under_c.get(mid),
                "line":  line_c.get(mid),
                # open (если просили и есть)
                "one_open":  one_o.get(mid)   if one_o else None,
                "draw_open": draw_o.get(mid)  if draw_o else None,
                "two_open":  two_o.get(mid)   if two_o else None,
                "over_open":  over_o.get(mid) if over_o else None,
                "under_open": under_o.get(mid) if under_o else None,
                "line_open":  line_o.get(mid)  if line_o else None,
            }
            points.append(pt)
        points.sort(key=lambda x: x["date"])

        return H2HSeriesOut(
            points=points,
            meta={
                "league_id": league_id,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "n_matches": len(match_rows),
                "bookmaker": bookmaker if bk1_col or bkou_col else None,
                "line": line,
                "line_tol": line_tol,
                "orientation": orientation,
                "has_open": has_open,
            }
        )
