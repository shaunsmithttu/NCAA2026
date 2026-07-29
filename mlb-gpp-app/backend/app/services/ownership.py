"""Ownership transform (spec S2 #6; Rules #42 / #51).

Applied the moment entry fee AND field size are known, BEFORE any leverage math
(Playbook §8). Field size selects the transform:

  above ~500 entries -> Rule #42 : chalk AMPLIFIES
                        structural chalk SP x1.5-1.7, mid-priced stacks x0.5-0.6,
                        obvious cheap value x2-4.
  below ~500 entries -> Rule #51 : chalk DEFLATES, tails inflate (the #42 hitter
                        multiplier INVERTS): hitter chalk x~0.5, sub-2% x~3-5,
                        ace SP x~1.0.

The ~1.0x ace-SP multiplier holds at both field sizes (Rule #42 note).
Every category boundary is a rule param (rules-as-data, spec S3) so Shaun can
retune without a code change. Returns per-player before/after + which multiplier
fired, so the transform is auditable and can be verified against realised
ownership every slate (Playbook §8 open item / spec S2 #14).
"""
from __future__ import annotations

from . import rules_ledger as rl

# category thresholds (editable via rule params; sensible defaults here)
_DEFAULTS = {
    "sp_chalk_own_threshold": 20.0,   # SP at/above this projected own = structural chalk
    "cheap_salary_max": 3600,         # hitter at/below this salary = "obvious cheap value"
    "mid_own_threshold": 15.0,        # hitter at/above this own = model-consensus chalk
    "hitter_chalk_own_threshold": 15.0,
    "sub2_own_threshold": 2.0,
}


def _p(rule_id: int, key: str) -> float:
    return rl.get_param(rule_id, key, _DEFAULTS.get(key))


def select_transform(field_size: int | None, entry_fee: float | None) -> str:
    """Return 'rule_42', 'rule_51', or 'none'."""
    cutoff_42 = rl.get_param(42, "field_size_cutoff", 500)
    fee_min = rl.get_param(42, "entry_fee_min", 100)
    if field_size is None or entry_fee is None:
        return "none"
    if entry_fee < fee_min:
        return "none"        # transform is a sharp-field tool (fee >= ~$100)
    return "rule_42" if field_size >= cutoff_42 else "rule_51"


def _mult_rule_42(pl: dict) -> tuple[float, str]:
    own = pl.get("adj_own") or 0.0
    if pl["is_pitcher"]:
        if own >= _p(42, "sp_chalk_own_threshold"):
            return rl.get_param(42, "structural_sp_mult", 1.6), "structural_chalk_sp"
        return 1.0, "sp_neutral"
    # hitters
    if (pl.get("salary") or 99999) <= _p(42, "cheap_salary_max"):
        return rl.get_param(42, "cheap_value_mult", 3.0), "cheap_value"
    if own >= _p(42, "mid_own_threshold"):
        return rl.get_param(42, "mid_stack_mult", 0.55), "mid_priced_chalk"
    return 1.0, "neutral"


def _mult_rule_51(pl: dict) -> tuple[float, str]:
    own = pl.get("adj_own") or 0.0
    if pl["is_pitcher"]:
        return rl.get_param(51, "ace_sp_mult", 1.0), "ace_sp"
    if own < _p(51, "sub2_own_threshold"):
        return rl.get_param(51, "sub2_mult", 4.0), "sub2_tail"
    if own >= _p(51, "hitter_chalk_own_threshold"):
        return rl.get_param(51, "hitter_chalk_mult", 0.5), "hitter_chalk"
    return 1.0, "neutral"


def apply_transform(players: list[dict], field_size: int | None,
                    entry_fee: float | None) -> dict:
    which = select_transform(field_size, entry_fee)
    fn = {"rule_42": _mult_rule_42, "rule_51": _mult_rule_51}.get(which)
    out = []
    for pl in players:
        base = pl.get("adj_own") or 0.0
        if fn is None:
            mult, cat = 1.0, "untransformed"
        else:
            mult, cat = fn(pl)
        transformed = round(base * mult, 2)
        out.append({
            **pl,
            "own_base": base,
            "own_mult": mult,
            "own_category": cat,
            "own_transformed": transformed,
        })
    return {
        "transform": which,
        "rule_id": {"rule_42": 42, "rule_51": 51}.get(which),
        "field_size": field_size,
        "entry_fee": entry_fee,
        "players": out,
    }
