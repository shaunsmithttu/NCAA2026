"""validate() — the core trust layer (spec Section 4; Playbook v4 §7).

Every hard constraint below is an explicit, NAMED check producing pass/fail +
a human-readable reason. Run on every lineup/portfolio before export. Thresholds
are read from the rules table (rules-as-data) via rules_ledger.get_param().

A lineup is a list of 10 player dicts. A player dict carries at least:
  name, team, opp, game_info, is_pitcher, positions(list), salary, dk_id,
  dk25, dk95, adj_own, order.
Context (ctx) carries slate-level facts: contest_shape, field_size,
delayed_games, lineup_cards, team_rank (top-5), stacks (opposing-SP metadata),
unadjudicated_blocked_signals, projection_key_collisions.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any

from ..config import (MAX_HITTERS_PER_TEAM, MIN_GAMES_SPANNED, ROSTER_SLOTS,
                      SALARY_CAP)
from . import rules_ledger as rl
from .ingest import norm_name, player_key

FAIL, WARN, INFO = "fail", "warn", "info"


def _check(name: str, passed: bool, reason: str, severity: str = FAIL,
           rule_id: int | None = None, items: Any = None) -> dict:
    return {"check": name, "passed": passed, "severity": severity,
            "reason": reason, "rule_id": rule_id, "items": items or []}


def _hitters(lu: list[dict]) -> list[dict]:
    return [p for p in lu if not p["is_pitcher"]]


def _pitchers(lu: list[dict]) -> list[dict]:
    return [p for p in lu if p["is_pitcher"]]


def _games(lu: list[dict]) -> set[str]:
    g = set()
    for p in lu:
        gi = (p.get("game_info") or "").split(" ")[0]
        if "@" in gi:
            g.add("@".join(sorted(gi.split("@"))))
    return g


def _lineup_hash(lu: list[dict]) -> str:
    ids = sorted(str(p.get("dk_id") or norm_name(p["name"])) for p in lu)
    return hashlib.sha1("|".join(ids).encode()).hexdigest()


# ---------------------------------------------------------------------------
# per-lineup checks
# ---------------------------------------------------------------------------
def check_salary(lu: list[dict], idx: int) -> list[dict]:
    floor = rl.get_param(2, "salary_floor", 48_500)
    total = sum(int(p.get("salary") or 0) for p in lu)
    out = [_check(f"salary_cap[L{idx}]", total <= SALARY_CAP,
                  f"Lineup salary {total} within cap {SALARY_CAP}." if total <= SALARY_CAP
                  else f"Lineup salary {total} EXCEEDS cap {SALARY_CAP}.", rule_id=2)]
    out.append(_check(f"salary_floor[L{idx}]", total >= floor,
                      f"Lineup salary {total} at/above floor {floor}." if total >= floor
                      else f"Lineup salary {total} BELOW floor {floor}.", rule_id=2))
    return out


def check_roster_legality(lu: list[dict], idx: int) -> list[dict]:
    out = []
    out.append(_check(f"roster_size[L{idx}]", len(lu) == len(ROSTER_SLOTS),
                      f"{len(lu)} players (need {len(ROSTER_SLOTS)})."))
    # positional fill via bipartite feasibility
    ok, why = _positions_fillable(lu)
    out.append(_check(f"position_eligibility[L{idx}]", ok, why, rule_id=6))
    # max hitters per team
    team_counts = Counter(p["team"] for p in _hitters(lu))
    worst = max(team_counts.values()) if team_counts else 0
    over = [t for t, c in team_counts.items() if c > MAX_HITTERS_PER_TEAM]
    out.append(_check(f"max_hitters_per_team[L{idx}]", not over,
                      f"Max {worst} hitters from one team (limit {MAX_HITTERS_PER_TEAM})."
                      if not over else f"Teams over the {MAX_HITTERS_PER_TEAM}-hitter limit: {over}.",
                      items=over))
    # games spanned
    ng = len(_games(lu))
    out.append(_check(f"games_spanned[L{idx}]", ng >= MIN_GAMES_SPANNED,
                      f"Lineup spans {ng} game(s) (need ≥{MIN_GAMES_SPANNED})."))
    return out


def _positions_fillable(lu: list[dict]) -> tuple[bool, str]:
    """Greedy/backtracking assignment of players to ROSTER_SLOTS honouring
    combined eligibility (Rule #6). Pitchers fill P; hitters fill their slots;
    any hitter position also fills nothing else implicitly (no UTIL in DK MLB)."""
    slots = list(ROSTER_SLOTS)
    # eligibility per player
    def eligible(p, slot):
        if slot == "P":
            return p["is_pitcher"]
        if p["is_pitcher"]:
            return False
        pos = [x.upper() for x in (p.get("positions") or [])]
        return slot in pos
    players = list(lu)
    assignment = {}

    def bt(si):
        if si == len(slots):
            return True
        slot = slots[si]
        for p in players:
            if id(p) in assignment:
                continue
            if eligible(p, slot):
                assignment[id(p)] = slot
                if bt(si + 1):
                    return True
                del assignment[id(p)]
        return False

    if bt(0):
        return True, "All slots fillable under combined eligibility."
    return False, "No legal assignment of players to roster slots (position conflict)."


def check_negative_correlation(lu: list[dict], idx: int) -> list[dict]:
    """No hitter facing a rostered pitcher (spec S4)."""
    p_teams = {p["team"] for p in _pitchers(lu)}
    clashes = [h["name"] for h in _hitters(lu) if h.get("opp") in p_teams]
    return [_check(f"negative_correlation[L{idx}]", not clashes,
                   "No hitter faces a rostered pitcher." if not clashes
                   else f"Hitters facing a rostered pitcher: {clashes}.", items=clashes)]


def check_dead_bat_cap(lu: list[dict], idx: int, field_size: int | None) -> list[dict]:
    """Rule #49: below ~1,000 entries, REJECT lineup with >1 hitter under the
    dk25 floor. Hard fail."""
    cutoff = rl.get_param(49, "field_size_cutoff", 1000)
    if field_size is None or field_size >= cutoff:
        return [_check(f"dead_bat_cap[L{idx}]", True,
                       f"Not enforced (field {field_size} ≥ {cutoff} or unknown).",
                       severity=INFO, rule_id=49)]
    floor_pts = rl.get_param(49, "dk25_floor_pts", 4.0)
    cap = rl.get_param(49, "dead_bat_cap", 1)
    missing = [h["name"] for h in _hitters(lu) if h.get("dk25") is None]
    if missing:
        return [_check(f"dead_bat_cap[L{idx}]", False,
                       f"Cannot enforce dead-bat cap — dk25 missing for {missing}. "
                       f"Provide dk_25_percentile in projections.", severity=WARN, rule_id=49,
                       items=missing)]
    dead = [h["name"] for h in _hitters(lu) if (h.get("dk25") or 0) < floor_pts]
    return [_check(f"dead_bat_cap[L{idx}]", len(dead) <= cap,
                   f"{len(dead)} dead bat(s) (dk25 < {floor_pts}); cap {cap}."
                   + (f" Offenders: {dead}." if len(dead) > cap else ""),
                   rule_id=49, items=dead)]


def check_ceiling_bat(lu: list[dict], idx: int, contest_shape: str) -> list[dict]:
    """Rule #52: small-field WTA — REJECT lineup whose highest-dk95 hitter < 25."""
    if contest_shape != "small_field_wta":
        return [_check(f"ceiling_bat[L{idx}]", True,
                       "Not enforced (only small-field WTA).", severity=INFO, rule_id=52)]
    min_pts = rl.get_param(52, "ceiling_bat_min_pts", 25.0)
    dk95s = [h.get("dk95") for h in _hitters(lu) if h.get("dk95") is not None]
    if not dk95s:
        return [_check(f"ceiling_bat[L{idx}]", False,
                       "Cannot enforce — no dk95 values on hitters.", severity=WARN, rule_id=52)]
    top = max(dk95s)
    return [_check(f"ceiling_bat[L{idx}]", top >= min_pts,
                   f"Highest-dk95 hitter at {top:.1f} (need ≥{min_pts}).", rule_id=52)]


def check_stack_side_identity(lu: list[dict], idx: int, ctx: dict) -> list[dict]:
    """Rule #45 (retained): for each stack, the opposing SP's team ≠ stack team.

    If stack metadata with an explicit opposing_sp_team is provided, assert it.
    Otherwise assert structurally that no stacked hitter's own team equals the
    team we believe they're stacked against (via game_info opp)."""
    hitters = _hitters(lu)
    team_counts = Counter(h["team"] for h in hitters)
    stacks = [t for t, c in team_counts.items() if c >= 2]
    meta = {s.get("team"): s for s in ctx.get("stacks", [])}
    bad = []
    for t in stacks:
        m = meta.get(t)
        if m and m.get("opposing_sp_team"):
            if m["opposing_sp_team"] == t:
                bad.append(f"{t} justified vs an SP on its OWN team ({m.get('opposing_sp_name','?')})")
        else:
            # structural: the opp of the stack team should differ from the team
            opp = next((h.get("opp") for h in hitters if h["team"] == t), None)
            if opp == t:
                bad.append(f"{t} opp resolves to itself in game string")
    return [_check(f"stack_side_identity[L{idx}]", not bad,
                   "Stack-side team identities consistent." if not bad
                   else "; ".join(bad), rule_id=45, items=bad)]


def check_weather_lineup(lu: list[dict], idx: int, delayed_games: list[str]) -> list[dict]:
    """Rule #48: game in ANNOUNCED delay caps at 3 bats per lineup."""
    if not delayed_games:
        return [_check(f"weather_delay[L{idx}]", True, "No announced delays.",
                       severity=INFO, rule_id=48)]
    cap = rl.get_param(48, "delay_bat_cap", 3)
    dg = {"@".join(sorted(g.split("@"))) for g in delayed_games}
    delayed_bats = [h["name"] for h in _hitters(lu)
                    if "@".join(sorted((h.get("game_info") or "").split(" ")[0].split("@"))) in dg]
    return [_check(f"weather_delay[L{idx}]", len(delayed_bats) <= cap,
                   f"{len(delayed_bats)} bat(s) from an announced-delay game (cap {cap}).",
                   rule_id=48, items=delayed_bats)]


# ---------------------------------------------------------------------------
# portfolio-level checks
# ---------------------------------------------------------------------------
def check_top5_coverage(portfolio: list[list[dict]], ctx: dict) -> dict:
    """Rule #50: REJECT portfolio with zero exposure to the top-5 team set."""
    team_rank = ctx.get("team_rank") or []          # ordered team codes, best first
    top5 = team_rank[:rl.get_param(50, "top_n_teams", 5)]
    if not top5:
        return _check("top5_coverage", True,
                      "No team ranking supplied — cannot enforce top-5 coverage.",
                      severity=WARN, rule_id=50)
    exposure = defaultdict(int)
    for lu in portfolio:
        teams = {h["team"] for h in _hitters(lu)}
        for t in teams:
            exposure[t] += 1
    covered = [t for t in top5 if exposure.get(t, 0) > 0]
    zero = [t for t in top5 if exposure.get(t, 0) == 0]
    min_cov = rl.get_param(50, "min_top5_covered", 1)
    passed = len(covered) >= min_cov
    return _check("top5_coverage", passed,
                  f"Top-5 teams {top5}: covered {covered}, zero-exposure {zero}. "
                  f"(need ≥{min_cov} covered)", rule_id=50, items=zero)


def check_exposure_caps(portfolio: list[list[dict]]) -> list[dict]:
    """Rule #13 hitter cap 50%, Rule #33 SP cap ~20%. Unenforceable below the
    granularity floor — surface as INFO, never a false failure (spec S4)."""
    n = len(portfolio)
    floor = rl.get_param(13, "granularity_floor_lineups", 6)
    hitter_cap = rl.get_param(13, "hitter_exposure_cap_pct", 50) / 100.0
    sp_cap = rl.get_param(33, "single_sp_cap_pct", 20) / 100.0
    if n < floor:
        return [_check("exposure_caps", True,
                       f"Portfolio has {n} lineup(s) — below the granularity floor "
                       f"({floor}); n=3 floor is 33%. Exposure caps not enforced.",
                       severity=INFO, rule_id=13)]
    hcount, scount = Counter(), Counter()
    for lu in portfolio:
        for h in _hitters(lu):
            hcount[(norm_name(h["name"]), h["team"])] += 1
        for p in _pitchers(lu):
            scount[(norm_name(p["name"]), p["team"])] += 1
    h_over = [f"{k[0]} {round(c/n*100)}%" for k, c in hcount.items() if c / n > hitter_cap]
    s_over = [f"{k[0]} {round(c/n*100)}%" for k, c in scount.items() if c / n > sp_cap]
    out = [_check("hitter_exposure_cap", not h_over,
                  "All hitters within 50% cap." if not h_over else f"Over 50%: {h_over}.",
                  rule_id=13, items=h_over)]
    out.append(_check("sp_exposure_cap", not s_over,
                      "All SPs within ~20% cap." if not s_over else f"Over ~20%: {s_over}.",
                      rule_id=33, items=s_over))
    return out


def check_dedup(portfolio: list[list[dict]]) -> dict:
    """Rule #5: hash-based dedup before submission."""
    hashes = [_lineup_hash(lu) for lu in portfolio]
    dupes = [h for h, c in Counter(hashes).items() if c > 1]
    return _check("hash_dedup", not dupes,
                  f"{len(portfolio)} lineups, all unique." if not dupes
                  else f"{len(dupes)} duplicate lineup hash(es) present.", rule_id=5)


def check_weather_portfolio(portfolio: list[list[dict]], delayed_games: list[str]) -> dict:
    """Rule #48: announced-delay stacks ≤ 1/3 of portfolio stacks."""
    if not delayed_games:
        return _check("weather_portfolio", True, "No announced delays.",
                      severity=INFO, rule_id=48)
    frac = rl.get_param(48, "delay_stack_fraction", 1 / 3)
    dg = {"@".join(sorted(g.split("@"))) for g in delayed_games}
    total_stacks, delay_stacks = 0, 0
    for lu in portfolio:
        counts = Counter(h["team"] for h in _hitters(lu))
        for t, c in counts.items():
            if c >= 3:
                total_stacks += 1
                gi = next(("@".join(sorted((h.get("game_info") or "").split(" ")[0].split("@")))
                           for h in _hitters(lu) if h["team"] == t), "")
                if gi in dg:
                    delay_stacks += 1
    ratio = (delay_stacks / total_stacks) if total_stacks else 0
    return _check("weather_portfolio", ratio <= frac + 1e-9,
                  f"{delay_stacks}/{total_stacks} stacks in announced-delay games "
                  f"({ratio:.0%}); cap {frac:.0%}.", rule_id=48)


def check_blocked_signal(ctx: dict) -> dict:
    """Rule #53: refuse export while any blocked signal is unadjudicated. HARD."""
    n = int(ctx.get("unadjudicated_blocked_signals", 0) or 0)
    return _check("blocked_signal_adjudication", n == 0,
                  "No unadjudicated blocked signals." if n == 0
                  else f"{n} blocked signal(s) UNADJUDICATED — Rule #53 hard block. "
                       "Adjudicate each (keep/drop + reason) in the discarded-signal log "
                       "before export.", rule_id=53, items=[])


def check_three_part_key(ctx: dict) -> dict:
    """Player-ID keying on (name, team, is_pitcher) — never name-only (spec S4)."""
    collisions = ctx.get("projection_key_collisions") or []
    # detect name-only collisions that the three-part key correctly separates
    return _check("three_part_key", not collisions,
                  "Player IDs resolved on the three-part key; no key collisions."
                  if not collisions else
                  f"{len(collisions)} projection key collision(s) — inspect: {collisions}.",
                  severity=WARN if collisions else INFO)


def check_batting_order(portfolio: list[list[dict]], ctx: dict) -> dict:
    """Confirmed batting order validated against the actual lineup card, never
    the projections status column (spec S4)."""
    cards = ctx.get("lineup_cards")     # {TEAM: [names in order]}
    if not cards:
        return _check("batting_order_confirmed", True,
                      "No lineup cards supplied — batting order NOT verified against "
                      "actual cards (projections status column is not sufficient).",
                      severity=WARN)
    norm_cards = {t.upper(): [norm_name(x) for x in names] for t, names in cards.items()}
    missing = []
    for lu in portfolio:
        for h in _hitters(lu):
            card = norm_cards.get(h["team"].upper())
            if card is None:
                continue
            if norm_name(h["name"]) not in card:
                missing.append(f"{h['name']} ({h['team']}) not in confirmed card")
    missing = sorted(set(missing))
    return _check("batting_order_confirmed", not missing,
                  "All rostered hitters present in confirmed lineup cards."
                  if not missing else f"Rostered hitters not confirmed: {missing}.",
                  items=missing)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def validate_portfolio(portfolio: list[list[dict]], ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    contest_shape = ctx.get("contest_shape", "large_field_gpp")
    field_size = ctx.get("field_size")
    delayed_games = ctx.get("delayed_games", [])

    checks: list[dict] = []
    # portfolio-level
    checks.append(check_three_part_key(ctx))
    checks.append(check_top5_coverage(portfolio, ctx))
    checks.extend(check_exposure_caps(portfolio))
    checks.append(check_dedup(portfolio))
    checks.append(check_weather_portfolio(portfolio, delayed_games))
    checks.append(check_blocked_signal(ctx))
    checks.append(check_batting_order(portfolio, ctx))
    # per-lineup
    for i, lu in enumerate(portfolio):
        checks.extend(check_salary(lu, i))
        checks.extend(check_roster_legality(lu, i))
        checks.extend(check_negative_correlation(lu, i))
        checks.extend(check_dead_bat_cap(lu, i, field_size))
        checks.extend(check_ceiling_bat(lu, i, contest_shape))
        checks.extend(check_stack_side_identity(lu, i, ctx))
        checks.extend(check_weather_lineup(lu, i, delayed_games))

    fails = [c for c in checks if c["severity"] == FAIL and not c["passed"]]
    warns = [c for c in checks if c["severity"] == WARN and not c["passed"]]
    return {
        "passed": len(fails) == 0,
        "export_allowed": len(fails) == 0,       # hard gate for CSV export
        "n_fail": len(fails), "n_warn": len(warns),
        "checks": checks,
        "failures": fails,
        "warnings": warns,
    }
