"""Sim-overlay operating model (spec S2 #10; DFS_Sim-Overlay_Operating_Model).

When a sim portfolio + lineup pool is uploaded, the sim portfolio is the
ALLOCATION BASELINE. The in-house optimizer must NOT re-shape it. Only two
operations may touch it:
  (a) a fixed-budget COVERAGE overlay (~7-13% of entries), swapped in over the
      sim's LOWEST-projection lineups;
  (b) surgical single-slot INFORMATION fixes (late scratches).

The UNTOUCHED sim portfolio is always retained for sim-baseline scoring
(spec S2 #12) — the only way to know if the overlay earns its keep.
"""
from __future__ import annotations

import copy

COVERAGE_MIN_PCT, COVERAGE_MAX_PCT = 7, 13


def _lineup_proj(lu: list[dict]) -> float:
    return sum(p.get("proj", 0.0) or 0.0 for p in lu)


def coverage_overlay(sim_portfolio: list[list[dict]],
                     coverage_lineups: list[list[dict]],
                     coverage_pct: float) -> dict:
    """Swap coverage lineups in over the sim's lowest-projection lineups.

    coverage_pct must fall in [7, 13]. Returns final portfolio, the untouched
    sim baseline (deep copy), and a log of exactly what was swapped."""
    n = len(sim_portfolio)
    if not 0 < coverage_pct <= 100:
        raise ValueError("coverage_pct out of range")
    if not (COVERAGE_MIN_PCT <= coverage_pct <= COVERAGE_MAX_PCT):
        warning = (f"coverage_pct {coverage_pct}% is outside the operating model's "
                   f"{COVERAGE_MIN_PCT}-{COVERAGE_MAX_PCT}% fixed budget.")
    else:
        warning = None
    k = max(1, round(n * coverage_pct / 100.0))
    k = min(k, len(coverage_lineups), n)

    sim_baseline = copy.deepcopy(sim_portfolio)     # untouched, for scoring
    order = sorted(range(n), key=lambda i: _lineup_proj(sim_portfolio[i]))
    swap_idx = order[:k]
    final = copy.deepcopy(sim_portfolio)
    log = []
    for j, i in enumerate(swap_idx):
        log.append({"replaced_sim_lineup_index": i,
                    "sim_proj": round(_lineup_proj(sim_portfolio[i]), 2),
                    "with_coverage_index": j})
        final[i] = coverage_lineups[j]

    return {
        "mode": "sim_overlay",
        "final_portfolio": final,
        "sim_baseline": sim_baseline,          # spec S2 #12 — store & score separately
        "n_entries": n,
        "n_coverage_swapped": k,
        "coverage_pct": coverage_pct,
        "swap_log": log,
        "warning": warning,
    }


def apply_info_fixes(portfolio: list[list[dict]], fixes: list[dict]) -> dict:
    """JSON-friendly wrapper: fixes = [{"out_key":[name,team,is_p], "replacement":{...}}].
    Only the named slot changes — a surgical late-scratch fix (spec S2 #10b)."""
    scratches = [tuple(fx["out_key"]) for fx in fixes]
    replacements = {tuple(fx["out_key"]): fx["replacement"] for fx in fixes}
    return info_fix(portfolio, scratches, replacements)


def info_fix(portfolio: list[list[dict]], scratches: list[tuple],
             replacements: dict) -> dict:
    """Surgical single-slot fixes for late scratches. scratches = list of player
    keys; replacements maps a scratched key -> replacement player dict. Only the
    scratched slot changes; nothing else in the lineup moves."""
    fixed = copy.deepcopy(portfolio)
    changes = []
    scratch_set = {tuple(s) for s in scratches}
    for li, lu in enumerate(fixed):
        for pi, p in enumerate(lu):
            key = tuple(p["key"]) if isinstance(p.get("key"), list) else p.get("key")
            if key in scratch_set and key in replacements:
                changes.append({"lineup": li, "out": p["name"],
                                "in": replacements[key]["name"]})
                lu[pi] = {**replacements[key], "slot": p.get("slot")}
    return {"portfolio": fixed, "changes": changes, "n_changes": len(changes)}
