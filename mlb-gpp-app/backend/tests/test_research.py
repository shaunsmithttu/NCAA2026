"""Pre-slate research board against the REAL research CSVs (tests/fixtures/).
Proves the header auto-detection and each scan parse against live column layouts.

Run: cd backend && python -m tests.test_research
"""
import os
import pathlib
import tempfile

os.environ["MLB_GPP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "res.sqlite3")

from app.db import init_db                         # noqa: E402
from app.services import research, rules_ledger    # noqa: E402

init_db(seed=True)
rules_ledger.ensure_default_params()

FX = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    return research.parse_any((FX / name).read_bytes())


def test_header_detection():
    assert _load("roo_stacks.csv")["type"] == "roo_stacks"
    assert _load("pitcher_research.csv")["type"] == "pitcher_research"
    assert _load("hitter_research.csv")["type"] == "hitter_research"
    assert _load("team_research.csv")["type"] == "team_research"
    assert _load("scoring_pct.csv")["type"] == "scoring_pct"


def test_board_from_real_files():
    board = research.build_board(
        roo=_load("roo_stacks.csv")["data"],
        pitchers=_load("pitcher_research.csv")["data"],
        hitters=_load("hitter_research.csv")["data"],
        teams=_load("team_research.csv")["data"],
        scoring=_load("scoring_pct.csv")["data"],
    )
    # counts match the real files (data rows, header excluded)
    assert board["counts"]["roo"] == 48
    assert board["counts"]["hitters"] == 160
    # top-5 coverage produced from ROO median/ceiling
    assert 1 <= len(board["top5_teams"]) <= 5
    # edge ratio computed and sorted descending
    edges = [s["edge_ratio"] for s in board["stack_board"] if s["edge_ratio"]]
    assert edges == sorted(edges, reverse=True)
    # per-hitter xSLG-by-handedness parsed; the best matchup is a real ≥.45 arm spot
    assert board["bat_board"][0]["xslg"] >= 0.45
    assert board["bat_board"][0]["good_matchup"] is True
    # chalk feed carries real Opp_TT + xSLG for every arm
    assert board["chalk_inputs"]["pitchers"]
    assert all("opp_team_total" in p for p in board["chalk_inputs"]["pitchers"])


def test_ownership_enrichment_lights_up_scans():
    hitters = _load("hitter_research.csv")["data"]
    # fabricate ownership: make one great-matchup bat sub-2% owned
    target = max(hitters, key=lambda h: h.get("xslg") or 0)
    ownership = {target["name"]: 1.2}
    board = research.build_board(hitters=hitters, ownership=ownership)
    names = [c["name"] for c in board["discarded_candidates"]]
    assert target["name"] in names, "sub-2% + xSLG≥.45 bat must surface as a #53 candidate"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}"); p += 1
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{p}/{len(fns)} passed")
