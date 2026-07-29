"""JSON adapter over the ported chalk_live_detector.

The prototype (chalk_live_detector.py) is kept verbatim per spec S2 #4 ("port as
is ... already correct, tested against the June 30 slate"). This module only
builds its dataclasses from parsed slate inputs and serializes its output for
the API / UI — it adds no new decision logic.
"""
from __future__ import annotations

from . import chalk_live_detector as cld


def build_slate(pitchers: list[dict], stacks: list[dict],
                game_totals: list[float], fav_moneylines: list[int]) -> cld.Slate:
    ps = [cld.Pitcher(
        name=p["name"], team=p.get("team", ""), salary=int(p.get("salary", 0) or 0),
        proj_own=float(p.get("proj_own", 0) or 0), xslg=float(p.get("xslg", 0) or 0),
        k_pct=float(p.get("k_pct", 0) or 0),
        opp_team_total=float(p.get("opp_team_total", 0) or 0),
    ) for p in pitchers]
    ss = [cld.Stack(
        team=s["team"], bat_owns=[float(x) for x in s.get("bat_owns", [])],
        ceiling=float(s.get("ceiling", 0) or 0),
    ) for s in stacks]
    return cld.Slate(pitchers=ps, stacks=ss,
                     game_totals=[float(t) for t in game_totals],
                     fav_moneylines=[int(m) for m in fav_moneylines])


def _serialize_signals(signals: dict) -> dict:
    out = {}
    for name, (fired, detail) in signals.items():
        d: object
        if isinstance(detail, list) and detail and hasattr(detail[0], "name"):
            d = [x.name for x in detail]
        elif isinstance(detail, list) and detail and hasattr(detail[0], "team"):
            d = [x.team for x in detail]
        elif isinstance(detail, dict):
            d = detail
        else:
            d = []
        out[name] = {"fired": bool(fired), "detail": d}
    return out


def _detector_split(signals: dict) -> dict:
    """v4 §8 DETECTOR SPLIT: score the chalk ARM and chalk STACK separately.

    Arm half  = signal A (elite aces in plus spots).
    Stack half = signals C (distributed chalk stack) + D (chalk owns the ceiling).
    Signal (c) NOT firing while (d) does is the tell that the stack half is a trap
    while the arm half may be real (7/28: 3-of-4 fired, chalk ace led all SPs,
    chalk stack finished last). Purely a re-read of existing signals — no new logic.
    """
    a = signals["A_elite_chalk_aces_in_plus_spots"]["fired"]
    c = signals["C_distributed_chalk_stack"]["fired"]
    d = signals["D_chalk_owns_the_ceiling"]["fired"]
    arm_live = a
    stack_live = c                       # distributed (individually low-owned) => real
    stack_trap = d and not c             # chalk owns ceiling but bats not low-owned
    return {
        "arm_half_live": arm_live,
        "stack_half_live": stack_live,
        "stack_half_trap": stack_trap,
        "note": ("Stack half looks like a TRAP (signal D fired, C did not): the "
                 "high-ceiling chalk stack's bats are not individually low-owned. "
                 "Arm half may still be real." if stack_trap else
                 "Stack half live — chalk stack's bats are individually low-owned."
                 if stack_live else "No distributed-chalk stack signal."),
    }


def analyze(pitchers: list[dict], stacks: list[dict],
            game_totals: list[float], fav_moneylines: list[int]) -> dict:
    slate = build_slate(pitchers, stacks, game_totals, fav_moneylines)
    d = cld.detect(slate)
    hard, lev = cld.xslg_gate(slate.pitchers)
    audit = cld.stack_ownership_audit(slate.stacks)
    signals = _serialize_signals(d["signals"])

    return {
        "signals": signals,
        "score": d["score"],
        "verdict": d["verdict"],
        "chalk_block_pct": d["chalk_block_pct"],
        "detector_split": _detector_split(signals),
        "xslg_gate": {
            "hard_capped": [{"name": p.name, "proj_own": p.proj_own, "xslg": p.xslg} for p in hard],
            "leverage_exception": [   # Rule #31/#50: capped BUT sub-6% own -> DO NOT ZERO
                {"name": p.name, "proj_own": p.proj_own, "xslg": p.xslg} for p in lev
            ],
        },
        "stack_audit": [
            {"team": t, "agg_own": agg, "n_sub10": n, "ceiling": ceil, "verdict": v}
            for (t, agg, n, ceil, v) in audit
        ],
    }
