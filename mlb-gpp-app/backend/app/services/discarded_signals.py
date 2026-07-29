"""Discarded-signal log (spec S2 #7; Rules #46 / #53).

Any confirmed, sub-2%-owned bat with xSLG ≥ .45 that a standing rule would drop
must be adjudicated IN WRITING ("keep"/"drop" + reason) before the build can
ship. This is a HARD BLOCK, not a warning (spec: four consecutive slates lost to
this being skipped). validate.check_blocked_signal reads the count this module
maintains.

xSLG here is the OPPOSING pitcher's xSLG vs the bat's handedness (the higher the
opposing arm's xSLG, the better the bat's spot) — a bat facing a ≥.45 arm that a
rule nonetheless blocked is exactly the signal that keeps dying silently.
"""
from __future__ import annotations

from ..db import get_conn
from . import rules_ledger as rl


def surface_candidates(players: list[dict], blocked_keys: set[tuple],
                       opp_xslg: dict[str, float]) -> list[dict]:
    """players: reconciled pool. blocked_keys: three-part keys a rule dropped.
    opp_xslg: {team_or_player_key -> opposing arm xSLG}. Returns bats meeting the
    sub-2% / xSLG≥.45 threshold that were blocked."""
    own_thr = rl.get_param(53, "own_threshold_pct", 2.0)
    xslg_thr = rl.get_param(53, "xslg_threshold", 0.45)
    out = []
    for p in players:
        if p["is_pitcher"]:
            continue
        key = tuple(p["key"]) if isinstance(p.get("key"), list) else p.get("key")
        if key not in blocked_keys:
            continue
        own = p.get("adj_own")
        xslg = opp_xslg.get(p.get("team")) or opp_xslg.get(str(key))
        if own is not None and own < own_thr and xslg is not None and xslg >= xslg_thr:
            out.append({"name": p["name"], "team": p["team"], "proj_own": own,
                        "xslg": xslg, "key": list(key)})
    return out


def record_candidates(slate_id: int | None, build_id: int | None,
                      candidates: list[dict], blocked_by_rule: int | None) -> int:
    n = 0
    with get_conn() as conn:
        for c in candidates:
            # skip if already logged & adjudicated for this slate/player
            exists = conn.execute(
                "SELECT id, adjudication FROM discarded_signals "
                "WHERE slate_id IS ? AND player_name=? AND team IS ?",
                (slate_id, c["name"], c.get("team"))).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO discarded_signals
                   (slate_id, build_id, player_name, team, proj_own, xslg, blocked_by_rule)
                   VALUES (?,?,?,?,?,?,?)""",
                (slate_id, build_id, c["name"], c.get("team"),
                 c.get("proj_own"), c.get("xslg"), blocked_by_rule))
            n += 1
    return n


def list_signals(slate_id: int | None = None, only_unadjudicated: bool = False) -> list[dict]:
    q = "SELECT * FROM discarded_signals"
    conds, args = [], []
    if slate_id is not None:
        conds.append("slate_id IS ?"); args.append(slate_id)
    if only_unadjudicated:
        conds.append("adjudication IS NULL")
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY created_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, args).fetchall()]


def adjudicate(signal_id: int, decision: str, reason: str) -> dict:
    if decision not in ("keep", "drop"):
        raise ValueError("decision must be 'keep' or 'drop'")
    if not reason or not reason.strip():
        raise ValueError("a written reason is required (Rule #53)")
    with get_conn() as conn:
        conn.execute("UPDATE discarded_signals SET adjudication=?, reason=? WHERE id=?",
                     (decision, reason.strip(), signal_id))
        row = conn.execute("SELECT * FROM discarded_signals WHERE id=?", (signal_id,)).fetchone()
    return dict(row)


def count_unadjudicated(slate_id: int | None = None) -> int:
    q = "SELECT COUNT(*) n FROM discarded_signals WHERE adjudication IS NULL"
    args = []
    if slate_id is not None:
        q += " AND slate_id IS ?"; args.append(slate_id)
    with get_conn() as conn:
        return conn.execute(q, args).fetchone()["n"]
