"""PuLP/CBC integer optimizer (spec S2 #8, #9).

Objective is set by CONTEST SHAPE (spec S2 #8; Rule #44):
  large_field_gpp -> p99-weighted (dk99 ceiling)
  small_field_wta -> p75/p95 blend (dk75/dk95)

Constraints are parameterized from the rules table (rules-as-data, spec S3):
roster legality, salary floor/cap, max-5-hitters/team, ≥2 games, no hitter
facing a rostered pitcher, dead-bat cap (#49), ceiling-bat requirement (#52).

Generates N UNIQUE lineups with per-player exposure caps (#13/#33) respected by
construction, and records which rules fired for the ledger's hit/miss tracking.
"""
from __future__ import annotations

import math
from collections import defaultdict

import pulp

from ..config import MAX_HITTERS_PER_TEAM, MIN_GAMES_SPANNED, SALARY_CAP
from . import rules_ledger as rl

SLOT_CAP = {"P": 2, "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3}
HITTER_SLOTS = ["C", "1B", "2B", "3B", "SS", "OF"]


def _game_key(gi: str) -> str:
    part = (gi or "").split(" ")[0]
    return "@".join(sorted(part.split("@"))) if "@" in part else part


def _value(pl: dict, contest_shape: str, leverage_lambda: float) -> float:
    if contest_shape == "small_field_wta":
        dk75 = pl.get("dk75")
        dk95 = pl.get("dk95")
        if dk75 is not None and dk95 is not None:
            base = 0.5 * dk75 + 0.5 * dk95
        else:
            base = dk95 if dk95 is not None else pl.get("proj", 0.0)
    else:  # large_field_gpp -> p99-weighted
        base = pl.get("dk99") if pl.get("dk99") is not None else pl.get("proj", 0.0)
    # optional leverage tilt on transformed ownership (0 by default = pure ceiling)
    own = pl.get("own_transformed", pl.get("adj_own") or 0.0)
    return base - leverage_lambda * (own or 0.0)


def _eligible_slots(pl: dict) -> list[str]:
    if pl["is_pitcher"]:
        return ["P"]
    pos = [p.upper() for p in (pl.get("positions") or [])]
    return [s for s in HITTER_SLOTS if s in pos]


def build_portfolio(players: list[dict], *, contest_shape: str, n_lineups: int,
                    field_size: int | None = None,
                    leverage_lambda: float | None = None,
                    locks: list[tuple] | None = None,
                    bans: list[tuple] | None = None) -> dict:
    """players: reconciled pool (each has key list, positions, salary, metrics,
    optionally own_transformed). Returns lineups + fired-rule log + objective info."""
    leverage_lambda = leverage_lambda if leverage_lambda is not None \
        else rl.get_param(0, "leverage_lambda", 0.0)  # default 0.0

    # index players; drop those with no eligible slot
    pool = [p for p in players if _eligible_slots(p)]
    idx = {i: p for i, p in enumerate(pool)}
    values = {i: _value(p, contest_shape, leverage_lambda) for i, p in idx.items()}

    floor = rl.get_param(2, "salary_floor", 48_500)
    dead_cutoff = rl.get_param(49, "field_size_cutoff", 1000)
    dead_floor_pts = rl.get_param(49, "dk25_floor_pts", 4.0)
    dead_cap = rl.get_param(49, "dead_bat_cap", 1)
    ceil_min = rl.get_param(52, "ceiling_bat_min_pts", 25.0)
    hitter_cap_pct = rl.get_param(13, "hitter_exposure_cap_pct", 50) / 100.0
    sp_cap_pct = rl.get_param(33, "single_sp_cap_pct", 20) / 100.0

    enforce_dead = field_size is not None and field_size < dead_cutoff
    enforce_ceiling = contest_shape == "small_field_wta"

    max_hitter_appear = math.ceil(hitter_cap_pct * n_lineups)
    max_sp_appear = math.ceil(sp_cap_pct * n_lineups)
    appear = defaultdict(int)

    lineups: list[list[dict]] = []
    fired: dict[int, str] = {}
    prev_solution_cuts: list[list[int]] = []

    for _ in range(n_lineups):
        prob = pulp.LpProblem("mlb_gpp", pulp.LpMaximize)
        x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in idx}
        # assignment vars y[i,slot]
        y = {}
        for i, p in idx.items():
            for s in _eligible_slots(p):
                y[(i, s)] = pulp.LpVariable(f"y_{i}_{s}", cat="Binary")

        prob += pulp.lpSum(values[i] * x[i] for i in idx)

        # link assignment to selection; each selected player fills exactly one slot
        for i, p in idx.items():
            prob += pulp.lpSum(y[(i, s)] for s in _eligible_slots(p)) == x[i]
        # slot capacities
        for s, cap in SLOT_CAP.items():
            prob += pulp.lpSum(y[(i, s)] for i in idx if (i, s) in y) == cap
        # roster size
        prob += pulp.lpSum(x[i] for i in idx) == sum(SLOT_CAP.values())
        # salary
        prob += pulp.lpSum((idx[i].get("salary") or 0) * x[i] for i in idx) <= SALARY_CAP
        prob += pulp.lpSum((idx[i].get("salary") or 0) * x[i] for i in idx) >= floor
        # max hitters/team
        teams = {p["team"] for p in pool if not p["is_pitcher"]}
        for t in teams:
            prob += pulp.lpSum(x[i] for i, p in idx.items()
                               if not p["is_pitcher"] and p["team"] == t) <= MAX_HITTERS_PER_TEAM
        # >=2 games
        games = defaultdict(list)
        for i, p in idx.items():
            games[_game_key(p.get("game_info", ""))].append(i)
        u = {g: pulp.LpVariable(f"u_{k}", cat="Binary") for k, g in
             zip(range(len(games)), games)}
        for g, members in games.items():
            prob += pulp.lpSum(x[i] for i in members) <= len(members) * u[g]
        prob += pulp.lpSum(u.values()) >= MIN_GAMES_SPANNED
        # no hitter facing a rostered pitcher
        for pi, pp in idx.items():
            if not pp["is_pitcher"]:
                continue
            for hi, hp in idx.items():
                if hp["is_pitcher"]:
                    continue
                if hp.get("opp") and hp["opp"] == pp["team"]:
                    prob += x[pi] + x[hi] <= 1
        # dead-bat cap (#49)
        if enforce_dead:
            dead = [i for i, p in idx.items()
                    if not p["is_pitcher"] and p.get("dk25") is not None
                    and (p.get("dk25") or 0) < dead_floor_pts]
            if dead:
                prob += pulp.lpSum(x[i] for i in dead) <= dead_cap
                fired[49] = f"dead-bat cap ≤{dead_cap} enforced ({len(dead)} dead candidates)"
        # ceiling-bat (#52)
        if enforce_ceiling:
            ceil_ok = [i for i, p in idx.items()
                       if not p["is_pitcher"] and (p.get("dk95") or 0) >= ceil_min]
            if ceil_ok:
                prob += pulp.lpSum(x[i] for i in ceil_ok) >= 1
                fired[52] = f"≥1 hitter with dk95≥{ceil_min} required"
        # exposure caps by construction (#13/#33)
        for i, p in idx.items():
            cap = max_sp_appear if p["is_pitcher"] else max_hitter_appear
            if appear[_pkey(p)] >= cap:
                prob += x[i] == 0
        if appear:
            fired.setdefault(13, "hitter exposure cap enforced by construction")
            fired.setdefault(33, "SP exposure cap enforced by construction")
        # locks / bans
        for i, p in idx.items():
            if locks and _pkey(p) in locks:
                prob += x[i] == 1
            if bans and _pkey(p) in bans:
                prob += x[i] == 0
        # uniqueness cuts vs previous lineups
        for sol in prev_solution_cuts:
            prob += pulp.lpSum(x[i] for i in sol) <= len(sol) - 1

        status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[status] != "Optimal":
            break
        chosen = [i for i in idx if x[i].value() and x[i].value() > 0.5]
        if not chosen:
            break
        prev_solution_cuts.append(chosen)
        slot_of = {i: s for (i, s), var in y.items()
                   if var.value() and var.value() > 0.5}
        lu = [{**idx[i], "slot": slot_of.get(i, "P" if idx[i]["is_pitcher"] else "")}
              for i in chosen]
        for i in chosen:
            appear[_pkey(idx[i])] += 1
        lineups.append(_order_lineup(lu))

    fired.setdefault(44, f"objective set by contest shape: {contest_shape}")
    return {
        "contest_shape": contest_shape,
        "objective": "p99_weighted" if contest_shape != "small_field_wta" else "p75_p95_blend",
        "n_requested": n_lineups,
        "n_built": len(lineups),
        "lineups": lineups,
        "fired_rules": fired,
    }


def _pkey(p: dict) -> tuple:
    return tuple(p["key"]) if isinstance(p.get("key"), list) else p.get("key")


_SLOT_ORDER = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]


def _order_lineup(lu: list[dict]) -> list[dict]:
    """Return players ordered to the DK slot template using their assigned slot."""
    remaining = list(lu)
    ordered = []
    for slot in _SLOT_ORDER:
        for p in remaining:
            if p.get("slot") == slot:
                ordered.append(p)
                remaining.remove(p)
                break
    ordered.extend(remaining)   # any leftover (shouldn't happen) appended
    return ordered
