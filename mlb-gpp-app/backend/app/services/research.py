"""Pre-slate research board (spec S2 B; the playbook's pre-slate scans).

Ingests the research files the playbook cites and produces a prioritized,
adjudicable board that runs BEFORE the build:

  - ROO stacks         -> edge ratio (ceiling ÷ own), top-5 coverage (#50)
  - pitcher research   -> underowned/quality arm scan (#8), chalk-detector feed
  - hitter research    -> per-hitter opp xSLG BY HANDEDNESS -> Rule #53 candidates
  - team research      -> team-level opp xSLG, environment ranking
  - scoring pct        -> matchup scoring context (NOT mean-correlated — spec S5)

Per-player projected ownership lives in the SaberSim/projections file, not these
research files. The board works without it and is enriched when an `ownership`
map ({name -> own%}) is supplied — the ownership-gated flags (sub-2% #53, sub-4%
dart #22, IL-return star #40, thin-arm #39) light up then.
"""
from __future__ import annotations

import csv
import io
import re
import statistics
from typing import Optional

from . import rules_ledger as rl
from .ingest import norm_name


def _rows(content: bytes | str) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    return [{(k or "").strip(): v for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(text))]


def _f(row: dict, *keys) -> Optional[float]:
    low = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = row.get(k, low.get(k.lower()))
        if v not in (None, "", "-"):
            try:
                return float(str(v).replace("%", "").replace(",", "").strip())
            except ValueError:
                continue
    return None


def _s(row: dict, *keys) -> str:
    low = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = row.get(k, low.get(k.lower()))
        if v not in (None, ""):
            return str(v).strip()
    return ""


# ---------------------------------------------------------------------------
# file-type detection + parsers
# ---------------------------------------------------------------------------
def detect_type(header: list[str]) -> str:
    h = {c.strip().lower() for c in header}
    if {"b1", "b2", "ceiling", "own"} <= h:
        return "roo_stacks"
    if {"names", "oppsp", "avgscore", "teamownpct"} <= h:
        return "scoring_pct"
    if {"team", "opp_sp", "xslg", "opp_hand"} <= h and "order" not in h and "player" not in h:
        return "team_research"
    if {"player", "order", "bats", "xslg"} <= h:
        return "hitter_research"
    if {"opp_tt", "xslg", "k%"} <= h and ("dk_salary" in h or "names" in h):
        return "pitcher_research"
    return "unknown"


def parse_any(content: bytes | str) -> dict:
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    header = next(csv.reader(io.StringIO(text)), [])
    t = detect_type(header)
    parser = {
        "roo_stacks": parse_roo_stacks, "scoring_pct": parse_scoring_pct,
        "team_research": parse_team_research, "hitter_research": parse_hitter_research,
        "pitcher_research": parse_pitcher_research,
    }.get(t)
    if not parser:
        return {"type": "unknown", "header": header, "data": []}
    return {"type": t, "data": parser(text)}


def parse_roo_stacks(content) -> list[dict]:
    out = []
    for r in _rows(content):
        label = _s(r, "Player")
        team = label.split()[0] if label else ""
        own = _f(r, "Own")
        ceiling = _f(r, "Ceiling")
        out.append({
            "label": label, "team": team, "prio": _s(r, "prio"),
            "bats": [_s(r, b) for b in ("B1", "B2", "B3", "B4", "B5") if _s(r, b)],
            "salary": _f(r, "Salary"), "floor": _f(r, "Floor"),
            "median": _f(r, "Median"), "ceiling": ceiling,
            "top_finish": _f(r, "Top_finish"), "top5": _f(r, "Top_5_finish"),
            "top10": _f(r, "Top_10_finish"), "own": own,
            "edge_ratio": round(ceiling / own, 3) if ceiling and own else None,
        })
    return out


def parse_scoring_pct(content) -> list[dict]:
    return [{
        "team": _s(r, "names"), "prio": _s(r, "prio"), "opp_sp": _s(r, "oppSP"),
        "avg_score": _f(r, "avgScore"), "eight_plus": _f(r, "eightPlusRuns"),
        "top_score": _f(r, "topScore"), "team_own": _f(r, "teamOwnPct"),
        "win_pct": _f(r, "winPercentage"),
    } for r in _rows(content)]


def parse_team_research(content) -> list[dict]:
    return [{
        "team": _s(r, "Team"), "opp": _s(r, "Opp"), "opp_sp": _s(r, "Opp_SP"),
        "opp_hand": _s(r, "Opp_Hand"), "opp_xslg": _f(r, "xSLG"),
        "opp_xba": _f(r, "xBA"), "k_pct": _f(r, "K%"), "sb": _f(r, "SB"),
        "xhr_pa": _f(r, "xHR/PA"), "avg_salary": _f(r, "Avg Salary"),
    } for r in _rows(content)]


def parse_hitter_research(content) -> list[dict]:
    out = []
    for r in _rows(content):
        out.append({
            "name": _s(r, "Player"), "salary": _f(r, "Salary"), "team": _s(r, "Team"),
            "opp": _s(r, "Opp"), "opp_sp": _s(r, "Opp_SP"), "opp_hand": _s(r, "Opp_Hand"),
            "order": int(_f(r, "Order")) if _f(r, "Order") is not None else None,
            "bats": _s(r, "bats"), "xslg": _f(r, "xSLG"), "xba": _f(r, "xBA"),
            "xhrs": _f(r, "xHRs"), "k_pct": _f(r, "K%"), "xhr_pa": _f(r, "xHR/PA"),
        })
    return out


def parse_pitcher_research(content) -> list[dict]:
    return [{
        "name": _s(r, "Names"), "dk_salary": _f(r, "DK_Salary"), "team": _s(r, "Team"),
        "opp": _s(r, "Opp"), "opp_tt": _f(r, "Opp_TT"), "hand": _s(r, "Hand"),
        "k_pct": _f(r, "K%"), "bb_pct": _f(r, "BB%"), "xslg": _f(r, "xSLG"),
        "xba": _f(r, "xBA"), "xhrs": _f(r, "xHRs"),
    } for r in _rows(content)]


# ---------------------------------------------------------------------------
# board builder
# ---------------------------------------------------------------------------
def build_board(*, roo=None, pitchers=None, hitters=None, teams=None,
                scoring=None, ownership: dict | None = None,
                field_size: int | None = None) -> dict:
    roo = roo or []; pitchers = pitchers or []; hitters = hitters or []
    teams = teams or []; scoring = scoring or []
    own = {norm_name(k): v for k, v in (ownership or {}).items()}
    notes = []
    if not own:
        notes.append("No projected-ownership map supplied — ownership-gated scans "
                     "(sub-2% #53, sub-4% dart #22, IL-return #40, thin-arm #39) are "
                     "listed by matchup quality only. Upload projections (Adj Own) to light them up.")

    xslg_cap = rl.get_param(50, "xslg_cap", 0.45)
    arm_own_max = rl.get_param(8, "arm_own_max_pct", 12.0)
    dart_own_max = rl.get_param(22, "ceiling_bat_own_max_pct", 4.0)
    dart_rank_max = rl.get_param(22, "ceiling_bat_rank_max", 6)
    star_own_max = rl.get_param(40, "star_own_max_pct", 3.0)
    sub2 = rl.get_param(53, "own_threshold_pct", 2.0)
    thin_own = rl.get_param(39, "thin_arm_sp_own_pct", 35.0)
    top_n = rl.get_param(50, "top_n_teams", 5)

    def o(name):        # ownership lookup, may be None
        return own.get(norm_name(name))

    # --- stack board: edge ratio, ranked ---
    stack_board = sorted(
        [s for s in roo if s.get("ceiling")],
        key=lambda s: -(s.get("edge_ratio") or 0))
    # top-5 coverage set (#50): union of top-N by median and by ceiling
    by_median = [s["team"] for s in sorted(roo, key=lambda s: -(s.get("median") or 0))][:top_n]
    by_ceiling = [s["team"] for s in sorted(roo, key=lambda s: -(s.get("ceiling") or 0))][:top_n]
    top5_union, seen = [], set()
    for t in by_median + by_ceiling:
        if t and t not in seen:
            seen.add(t); top5_union.append(t)

    # --- arm board (#8): quality composite + gate weight (never exclude) ---
    def arm_score(p):
        k = p.get("k_pct") or 0
        xslg = p.get("xslg")
        tt = p.get("opp_tt") or 0
        # higher K, lower opp xSLG, lower opp total = better
        return (k * 100) - ((xslg or 0.4) * 40) - (tt * 5)
    arm_board = []
    for p in sorted(pitchers, key=arm_score, reverse=True):
        arm_board.append({
            **p, "proj_own": o(p["name"]),
            "gate_flag": "capped (weight only, #50)" if (p.get("xslg") or 0) > xslg_cap else "clears screen",
            "underowned_arm": (o(p["name"]) is not None and o(p["name"]) <= arm_own_max),
        })

    # --- bat matchup board / Rule #53 candidates ---
    bat_board, discarded_candidates = [], []
    for h in sorted(hitters, key=lambda x: -(x.get("xslg") or 0)):
        own_h = o(h["name"])
        good_matchup = (h.get("xslg") or 0) >= xslg_cap
        entry = {**h, "proj_own": own_h, "good_matchup": good_matchup}
        bat_board.append(entry)
        # Rule #53: confirmed sub-2%-owned bat with xSLG >= .45
        if good_matchup and own_h is not None and own_h < sub2:
            discarded_candidates.append({
                "name": h["name"], "team": h["team"], "proj_own": own_h,
                "xslg": h["xslg"], "opp_hand": h.get("opp_hand"), "order": h.get("order")})

    # --- dart pool (#22/#30): top-6 order, sub-4% owned, ceiling matchup ---
    dart_pool = []
    for h in hitters:
        own_h = o(h["name"])
        if (h.get("order") or 99) <= dart_rank_max and (h.get("xslg") or 0) >= xslg_cap:
            if own_h is None or own_h < dart_own_max:
                dart_pool.append({"name": h["name"], "team": h["team"], "order": h.get("order"),
                                  "xslg": h["xslg"], "xhrs": h.get("xhrs"), "proj_own": own_h})
    dart_pool.sort(key=lambda x: -(x.get("xhrs") or 0))

    # --- IL-return / superstar dart (#40): high xHRs at very low own ---
    star_darts = []
    if own:
        for h in hitters:
            own_h = o(h["name"])
            if own_h is not None and own_h < star_own_max and (h.get("xhrs") or 0) >= 8:
                star_darts.append({"name": h["name"], "team": h["team"], "proj_own": own_h,
                                   "xhrs": h.get("xhrs"), "xslg": h.get("xslg")})

    # --- environment ranking (#10/#35/#36): avg_score + opp xSLG ---
    env = {}
    for s in scoring:
        env.setdefault(s["team"], {})["avg_score"] = s.get("avg_score")
        env[s["team"]]["eight_plus"] = s.get("eight_plus")
    for t in teams:
        env.setdefault(t["team"], {})["opp_xslg"] = t.get("opp_xslg")
        env[t["team"]]["opp_sp"] = t.get("opp_sp")
    environments = sorted(
        [{"team": k, **v} for k, v in env.items()],
        key=lambda e: -((e.get("avg_score") or 0) + (e.get("opp_xslg") or 0) * 5))
    coors = [e for e in environments if e["team"] in ("COL",)
             or (e.get("avg_score") or 0) >= 6.5]

    # --- thin-arm slate detection (#39) ---
    thin_arm = None
    if own:
        chalk_sps = [p for p in pitchers if (o(p["name"]) or 0) >= thin_own]
        thin_arm = {"triggered": len(chalk_sps) >= 2 and len(chalk_sps) <= 3,
                    "chalk_sps": [{"name": p["name"], "own": o(p["name"])} for p in chalk_sps]}

    # --- chalk-detector feed: real xSLG + Opp_TT from research ---
    chalk_pitchers = [{"name": p["name"], "team": p["team"], "salary": p.get("dk_salary") or 0,
                       "proj_own": o(p["name"]) or 0.0, "xslg": p.get("xslg") or 0.0,
                       "k_pct": p.get("k_pct") or 0.0, "opp_team_total": p.get("opp_tt") or 0.0}
                      for p in pitchers]
    chalk_stacks = []
    for s in roo:
        # individual bat owns from the ownership map when present, else aggregate/5
        bat_owns = [o(b) for b in s.get("bats", []) if o(b) is not None]
        if not bat_owns and s.get("own"):
            bat_owns = [round(s["own"] / max(1, len(s.get("bats") or [1])), 1)] * len(s.get("bats") or [])
        chalk_stacks.append({"team": s["team"], "bat_owns": bat_owns, "ceiling": s.get("ceiling") or 0})

    return {
        "notes": notes,
        "stack_board": stack_board,
        "top5_teams": top5_union[:top_n if top_n else 5],
        "arm_board": arm_board,
        "bat_board": bat_board[:60],
        "dart_pool": dart_pool,
        "star_darts": star_darts,
        "discarded_candidates": discarded_candidates,
        "environments": environments,
        "coors_environments": coors,
        "thin_arm": thin_arm,
        "chalk_inputs": {"pitchers": chalk_pitchers, "stacks": chalk_stacks},
        "counts": {"roo": len(roo), "pitchers": len(pitchers), "hitters": len(hitters),
                   "teams": len(teams), "scoring": len(scoring)},
    }
