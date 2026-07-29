"""Post-lock rescan, scoring, and the post-mortem / calibration loop
(spec S2 D #11-#15).

  - post_lock_rescan: re-verify rostered players still confirmed, flag drift.
  - score_portfolio:  score submitted lineups from an actuals map.
  - ingest_standings: parse a DK standings/results CSV, decompose winner(s),
                      compute field distribution.
  - calibration:      append projected-vs-actual ownership pairs to SQLite
                      (spec S2 #14 — answers the Playbook's open item on #51).
  - sim_baseline_score: score the untouched sim portfolio beside the final
                        build (spec S2 #12).
  - build_doc:        structured post-mortem (markdown) matching the Word-doc
                      section structure (spec S2 #15).
"""
from __future__ import annotations

import csv
import io
import statistics
from collections import Counter

from ..db import get_conn
from .ingest import norm_name, player_key


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def _actual_for(player: dict, actuals: dict) -> float | None:
    """actuals keyed by norm_name or three-part key -> points."""
    k = tuple(player["key"]) if isinstance(player.get("key"), list) else player.get("key")
    if k in actuals:
        return actuals[k]
    return actuals.get(norm_name(player["name"]))


def score_lineup(lu: list[dict], actuals: dict) -> dict:
    total, missing = 0.0, []
    per = []
    for p in lu:
        pts = _actual_for(p, actuals)
        if pts is None:
            missing.append(p["name"])
            pts = 0.0
        total += pts
        per.append({"name": p["name"], "team": p.get("team"), "points": round(pts, 2)})
    return {"total": round(total, 2), "players": per, "missing": missing}


def score_portfolio(portfolio: list[list[dict]], actuals: dict) -> dict:
    scored = [score_lineup(lu, actuals) for lu in portfolio]
    totals = [s["total"] for s in scored]
    return {
        "lineups": scored,
        "best": max(totals) if totals else 0,
        "worst": min(totals) if totals else 0,
        "mean": round(statistics.mean(totals), 2) if totals else 0,
    }


def sim_baseline_score(final_portfolio, sim_baseline, actuals) -> dict:
    """Spec S2 #12 — score the untouched sim portfolio beside the final build."""
    fin = score_portfolio(final_portfolio, actuals)
    base = score_portfolio(sim_baseline, actuals) if sim_baseline else None
    overlay_delta = None
    if base:
        overlay_delta = round(fin["mean"] - base["mean"], 2)
    return {"final": fin, "sim_baseline": base,
            "overlay_mean_delta": overlay_delta,
            "overlay_earned_keep": (overlay_delta or 0) > 0}


# ---------------------------------------------------------------------------
# post-lock rescan (spec S2 #11)
# ---------------------------------------------------------------------------
def post_lock_rescan(portfolio, confirmed_now: dict, projected_own: dict,
                     actual_own: dict) -> dict:
    """confirmed_now: {team: [names]} current lineup cards.
    Flags rostered players no longer confirmed and ownership drift."""
    norm_cards = {t.upper(): {norm_name(x) for x in names}
                  for t, names in (confirmed_now or {}).items()}
    unconfirmed, drift = [], []
    seen = set()
    for lu in portfolio:
        for p in lu:
            if p["is_pitcher"]:
                continue
            nk = (norm_name(p["name"]), p["team"])
            if nk in seen:
                continue
            seen.add(nk)
            card = norm_cards.get(p["team"].upper())
            if card is not None and norm_name(p["name"]) not in card:
                unconfirmed.append({"name": p["name"], "team": p["team"]})
            pj = projected_own.get(norm_name(p["name"]))
            ac = actual_own.get(norm_name(p["name"]))
            if pj is not None and ac is not None and abs(ac - pj) >= 5:
                drift.append({"name": p["name"], "proj_own": pj, "actual_own": ac,
                              "drift": round(ac - pj, 1)})
    return {"unconfirmed": unconfirmed, "ownership_drift": drift,
            "n_unconfirmed": len(unconfirmed), "n_drift": len(drift)}


# ---------------------------------------------------------------------------
# standings ingest + winner decomposition (spec S2 #13)
# ---------------------------------------------------------------------------
def ingest_standings(content: bytes | str) -> dict:
    """Parse a DK contest standings/results CSV. DK standings carry columns like
    Rank, EntryName, Points, Lineup, plus a trailing player %Drafted block.
    Returns field scoring distribution + the winning lineup string(s)."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    rows = list(csv.DictReader(io.StringIO(text)))
    points, winners, ownership = [], [], {}
    for r in rows:
        low = {(k or "").strip().lower(): v for k, v in r.items()}
        pts = low.get("points") or low.get("fpts")
        try:
            if pts not in (None, ""):
                points.append(float(pts))
        except ValueError:
            pass
        rank = low.get("rank")
        if rank in ("1", "1.0"):
            winners.append(low.get("lineup", ""))
        # DK appends a "Player","%Drafted" pair in the same CSV
        pl = low.get("player")
        drafted = low.get("%drafted") or low.get("percent drafted")
        if pl and drafted:
            try:
                ownership[norm_name(pl)] = float(str(drafted).replace("%", "").strip())
            except ValueError:
                pass
    dist = {}
    if points:
        pts_sorted = sorted(points, reverse=True)
        dist = {
            "n_entries": len(points),
            "max": max(points), "min": min(points),
            "mean": round(statistics.mean(points), 2),
            "median": round(statistics.median(points), 2),
            "p90": round(pts_sorted[int(len(pts_sorted) * 0.10)], 2),
            "p99": round(pts_sorted[int(len(pts_sorted) * 0.01)], 2),
        }
    return {"distribution": dist, "winning_lineups": winners,
            "actual_ownership": ownership, "n_rows": len(rows)}


# ---------------------------------------------------------------------------
# ownership calibration (spec S2 #14)
# ---------------------------------------------------------------------------
def append_calibration(slate_id: int | None, slate_date: str,
                       pairs: list[dict], field_size: int | None = None,
                       entry_fee: float | None = None) -> int:
    """pairs: [{name, team, is_pitcher, proj_own, actual_own}]. Persisted so the
    #51 multipliers can finally be calibrated on more than two slates."""
    n = 0
    with get_conn() as conn:
        for p in pairs:
            conn.execute(
                """INSERT INTO ownership_calibration
                   (slate_id, slate_date, player_name, team, is_pitcher,
                    proj_own, actual_own, field_size, entry_fee)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (slate_id, slate_date, p.get("name"), p.get("team"),
                 1 if p.get("is_pitcher") else 0, p.get("proj_own"),
                 p.get("actual_own"), field_size, entry_fee))
            n += 1
    return n


def calibration_summary() -> dict:
    """Aggregate realised/projected ownership ratios across all logged slates,
    bucketed by projected-ownership band — the calibration curve (spec S2 #14)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT proj_own, actual_own, is_pitcher FROM ownership_calibration "
            "WHERE proj_own IS NOT NULL AND actual_own IS NOT NULL").fetchall()
    bands = {"<2": [], "2-10": [], "10-20": [], "20-35": [], "35+": []}
    for r in rows:
        pj = r["proj_own"] or 0
        ratio = (r["actual_own"] / pj) if pj else None
        if ratio is None:
            continue
        b = ("<2" if pj < 2 else "2-10" if pj < 10 else "10-20" if pj < 20
             else "20-35" if pj < 35 else "35+")
        bands[b].append(ratio)
    curve = {b: {"n": len(v), "mean_ratio": round(statistics.mean(v), 3) if v else None}
             for b, v in bands.items()}
    return {"n_pairs": len(rows), "curve": curve}


# ---------------------------------------------------------------------------
# structured post-mortem doc (spec S2 #15)
# ---------------------------------------------------------------------------
def build_doc(slate_date: str, scoreboard: dict, right: list[str],
              wrong: list[dict], new_rules: list[str], process_notes: list[str]) -> str:
    """Markdown matching the existing Word-doc section structure. .docx export is
    only built on explicit request (spec S2 #15) — this is the v1 markdown view."""
    lines = [f"# MLB GPP Post-Mortem — {slate_date}", ""]
    lines += ["## Scoreboard vs. peers"]
    for k, v in (scoreboard or {}).items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "## What went right"]
    lines += [f"- {x}" for x in (right or [])] or ["- (none logged)"]
    lines += ["", "## What went wrong (ranked by cost)"]
    for i, w in enumerate(sorted(wrong or [], key=lambda d: -(d.get("cost", 0))), 1):
        lines.append(f"{i}. **{w.get('title','')}** — cost {w.get('cost','?')}. {w.get('detail','')}")
    lines += ["", "## New rules adopted"]
    lines += [f"- {x}" for x in (new_rules or [])] or ["- (none)"]
    lines += ["", "## Process notes for next slate"]
    lines += [f"- {x}" for x in (process_notes or [])] or ["- (none)"]
    return "\n".join(lines)
