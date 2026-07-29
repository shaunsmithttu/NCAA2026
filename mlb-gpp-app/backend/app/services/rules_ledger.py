"""Rules ledger service (spec Sections 2E, 3 — "rules as data, not code").

The optimizer and validator NEVER hardcode a threshold; they read it from the
rules table via get_param(). This module also owns:
  - the governance dashboard analytics (spec S2 #19)
  - hit/miss tracking (spec S2 #18)
"""
from __future__ import annotations

import json
from typing import Any

from ..db import get_conn

# ---------------------------------------------------------------------------
# Default editable thresholds (rules-as-data). These seed a rule's `params`
# JSON the first time and are then user-editable in the UI without a code
# change (spec S3). Keyed by rule id.
# ---------------------------------------------------------------------------
DEFAULT_PARAMS: dict[int, dict[str, Any]] = {
    2:  {"salary_floor": 48_500},
    8:  {"arm_own_max_pct": 12.0},          # underowned premium arm scan
    39: {"thin_arm_sp_own_pct": 35.0},      # thin-arm slate detection
    40: {"star_own_max_pct": 3.0},          # IL-return / superstar-dart scan
    13: {"hitter_exposure_cap_pct": 50, "granularity_floor_lineups": 6},
    21: {"target_sub10_bats": 3, "sub10_threshold_pct": 10.0},
    22: {"ceiling_bat_own_max_pct": 4.0, "ceiling_bat_rank_max": 6},
    33: {"single_sp_cap_pct": 20},
    42: {"field_size_cutoff": 500, "entry_fee_min": 100,
         "structural_sp_mult": 1.6, "mid_stack_mult": 0.55, "cheap_value_mult": 3.0},
    44: {"field_size_cutoff": 1000},
    48: {"delay_bat_cap": 3, "delay_stack_fraction": 0.3333},
    49: {"field_size_cutoff": 1000, "dead_bat_cap": 1, "floor_metric": "dk25"},
    50: {"xslg_cap": 0.45, "top_n_teams": 5},
    51: {"field_size_cutoff": 500, "entry_fee_min": 100,
         "hitter_chalk_mult": 0.5, "sub2_mult": 4.0, "ace_sp_mult": 1.0},
    52: {"ceiling_bat_min_pts": 25.0, "dk95_col": "dk_95_percentile"},
    53: {"own_threshold_pct": 2.0, "xslg_threshold": 0.45},
}


def ensure_default_params() -> None:
    """Populate empty params with defaults. Call after seed_rules()."""
    with get_conn() as conn:
        for rid, defaults in DEFAULT_PARAMS.items():
            row = conn.execute("SELECT params FROM rules WHERE id=?", (rid,)).fetchone()
            if row is None:
                continue
            cur = json.loads(row["params"] or "{}")
            merged = {**defaults, **cur}     # user values win over defaults
            conn.execute("UPDATE rules SET params=? WHERE id=?",
                         (json.dumps(merged), rid))


def get_param(rule_id: int, key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT params FROM rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        return default
    params = json.loads(row["params"] or "{}")
    return params.get(key, DEFAULT_PARAMS.get(rule_id, {}).get(key, default))


def list_rules(include_folded: bool = True) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rules ORDER BY id").fetchall()
    out = [dict(r) for r in rows]
    for r in out:
        r["params"] = json.loads(r["params"] or "{}")
        r["active"] = bool(r["active"])
        r["enabled"] = bool(r["enabled"])
    if not include_folded:
        out = [r for r in out if r["active"]]
    return out


def get_rule(rule_id: int) -> dict | None:
    rules = [r for r in list_rules() if r["id"] == rule_id]
    return rules[0] if rules else None


def update_rule(rule_id: int, *, enabled: bool | None = None,
                rule_type: str | None = None, params: dict | None = None) -> dict:
    with get_conn() as conn:
        if enabled is not None:
            conn.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
        if rule_type is not None:
            conn.execute("UPDATE rules SET rule_type=? WHERE id=?", (rule_type, rule_id))
        if params is not None:
            cur = conn.execute("SELECT params FROM rules WHERE id=?", (rule_id,)).fetchone()
            merged = {**json.loads(cur["params"] or "{}"), **params}
            conn.execute("UPDATE rules SET params=? WHERE id=?", (json.dumps(merged), rule_id))
    return get_rule(rule_id)


def enabled_active_rules() -> list[dict]:
    """Rules that are active (not folded) AND user-enabled — the set that fires."""
    return [r for r in list_rules() if r["active"] and r["enabled"]]


# ---------------------------------------------------------------------------
# hit/miss tracking (spec S2 #18)
# ---------------------------------------------------------------------------
def record_fired(build_id: int, rule_id: int, slate: str | None, detail: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO build_rules_fired (build_id, rule_id, detail) VALUES (?,?,?)",
            (build_id, rule_id, detail))
        conn.execute(
            "UPDATE rules SET fired_count = fired_count + 1, last_fired_slate = COALESCE(?, last_fired_slate) WHERE id=?",
            (slate, rule_id))


def score_fired(build_id: int, rule_id: int, helped: bool) -> None:
    """Called from the post-mortem loop once results are in."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE build_rules_fired SET helped=? WHERE build_id=? AND rule_id=?",
            (1 if helped else 0, build_id, rule_id))
        col = "hit_count" if helped else "miss_count"
        conn.execute(f"UPDATE rules SET {col} = {col} + 1 WHERE id=?", (rule_id,))


# ---------------------------------------------------------------------------
# Governance dashboard (spec S2 #19)
# ---------------------------------------------------------------------------
# Keyword pairs that indicate two rules push opposite directions on the same
# lever. A hit means both rules are enabled AND their text contains opposing
# terms — the exact failure mode that cost the 7/28 session (#45 vs #47).
_CONTRADICTION_HINTS = [
    ("exclude", "never exclude"),
    ("hard exclusion", "weights, never gates"),
    ("gate", "single-factor screens are weights"),
]


def governance_summary(studied_slates: int | None = None) -> dict:
    rules = list_rules()
    active = [r for r in rules if r["active"]]
    enabled = [r for r in active if r["enabled"]]

    # rules-to-slates ratio (spec: 48 active / ~16 studied slates flagged as risk)
    if studied_slates is None:
        with get_conn() as conn:
            row = conn.execute("SELECT COUNT(DISTINCT slate_date) n FROM ownership_calibration").fetchone()
        studied_slates = row["n"] or 16          # fall back to playbook's stated figure

    retire_candidates = [
        {"id": r["id"], "text": r["text"], "miss_count": r["miss_count"]}
        for r in active if r["miss_count"] >= 2
    ]

    contradictions = _detect_contradictions(enabled)

    return {
        "n_active": len(active),
        "n_enabled": len(enabled),
        "studied_slates": studied_slates,
        "rules_to_slates_ratio": round(len(active) / studied_slates, 2) if studied_slates else None,
        "ratio_flagged": (len(active) / studied_slates) > 2.5 if studied_slates else False,
        "retire_candidates": retire_candidates,
        "contradictions": contradictions,
    }


def _detect_contradictions(enabled: list[dict]) -> list[dict]:
    """Flag any two ENABLED rules whose text pushes opposite directions on the
    same lever. Conservative keyword heuristic — surfaces candidates for Shaun
    to confirm, does not auto-disable."""
    out = []
    gate_words = ("exclude", "hard exclusion", "hard-exclude", "zero any", "reject")
    weight_words = ("weighting tool", "weights, never gates", "never exclude",
                    "ranks stacks", "not exclusion", "weighting input")
    for i in range(len(enabled)):
        for j in range(i + 1, len(enabled)):
            a, b = enabled[i], enabled[j]
            ta, tb = a["text"].lower(), b["text"].lower()
            a_gate = any(w in ta for w in gate_words)
            b_weight = any(w in tb for w in weight_words)
            a_weight = any(w in ta for w in weight_words)
            b_gate = any(w in tb for w in gate_words)
            # only flag when they touch a shared domain keyword
            shared = _shared_domain(ta, tb)
            if shared and ((a_gate and b_weight) or (a_weight and b_gate)):
                out.append({
                    "rule_a": a["id"], "rule_b": b["id"], "domain": shared,
                    "note": f"#{a['id']} and #{b['id']} may contradict on '{shared}' "
                            f"(one gates/excludes, one weights). Confirm before both enabled.",
                })
    return out


def _shared_domain(a: str, b: str) -> str | None:
    for kw in ("xslg", "park", "weather", "ownership", "stack", "single-factor", "team"):
        if kw in a and kw in b:
            return kw
    return None
