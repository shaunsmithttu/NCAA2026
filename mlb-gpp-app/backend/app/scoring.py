"""DraftKings MLB Classic scoring table.

Values transcribed from Playbook v4 Section 0 (the DK scoring table reproduced
there; original in source_docs/pdf_reference/Rules__DraftKings.pdf). Isolated
here (not scattered through the optimizer) so a single edit corrects every
downstream calculation if DK changes the table. The optimizer and post-mortem
scorer both import from here.

Note: the playbook §0 snapshot lists "Complete Game / CG SO +2.5" as one line and
does not enumerate a separate no-hitter bonus; both are represented below and
default to 0 occurrences, so they never affect a projection-based build.
"""
from __future__ import annotations

# Hitters (Playbook v4 §0)
HITTER_POINTS = {
    "single": 3.0,
    "double": 5.0,
    "triple": 8.0,
    "home_run": 10.0,
    "rbi": 2.0,
    "run": 2.0,
    "walk": 2.0,          # base on balls
    "hbp": 2.0,           # hit by pitch
    "stolen_base": 5.0,
    "sac_fly": 1.25,      # Sac Fly / Sac Hit  (§0)
    "sac_hit": 1.25,
    "caught_stealing": 0.0,
}

# Pitchers (Playbook v4 §0)
PITCHER_POINTS = {
    "inning_pitched": 2.25,        # +0.75 per out
    "strikeout": 2.0,
    "win": 4.0,
    "earned_run": -2.0,
    "hit_against": -0.6,
    "walk_against": -0.6,
    "hbp_against": -0.6,
    "complete_game": 2.5,
    "complete_game_shutout": 2.5,
    "ten_k_bonus": 2.0,            # 10+ K bonus (§0)
    "seven_ip_bonus": 1.25,       # 7+ IP bonus (§0)
    "no_hitter": 5.0,             # not in §0 snapshot; kept for completeness, defaults to 0
}


def score_hitter(stat_line: dict) -> float:
    """stat_line keys match HITTER_POINTS keys; missing keys count as 0."""
    return round(sum(HITTER_POINTS[k] * stat_line.get(k, 0) for k in HITTER_POINTS), 2)


def score_pitcher(stat_line: dict) -> float:
    return round(sum(PITCHER_POINTS[k] * stat_line.get(k, 0) for k in PITCHER_POINTS), 2)
