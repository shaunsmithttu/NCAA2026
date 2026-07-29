"""Real-data pass against the SaberSim projections fixture (tests/fixtures/
sabersim_projections.csv): projections-only pool -> optimizer -> DK CSV export,
and research ownership enrichment surfacing Rule #53 candidates.

Run: cd backend && python -m tests.test_sabersim
"""
import os
import pathlib
import tempfile

os.environ["MLB_GPP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "ss.sqlite3")

from app.db import init_db                                       # noqa: E402
from app.services import (dk_export, ingest, optimizer,          # noqa: E402
                          research, rules_ledger, validate)

init_db(seed=True)
rules_ledger.ensure_default_params()

FX = pathlib.Path(__file__).parent / "fixtures"
PROJS = ingest.parse_projections((FX / "sabersim_projections.csv").read_bytes())


def test_projections_parse_and_pool():
    assert len(PROJS) > 700
    pool = ingest.pool_from_projections(PROJS)
    assert pool["n_missing_dk_id"] == 0, "SaberSim DFS ID column must resolve every player"
    # combined eligibility parsed (e.g. Shohei Ohtani 1B/OF)
    multi = [p for p in pool["players"] if not p["is_pitcher"] and len(p["positions"]) > 1]
    assert len(multi) >= 40


def test_real_gpp_build_and_export():
    pool = ingest.pool_from_projections(PROJS)["players"]
    res = optimizer.build_portfolio(pool, contest_shape="large_field_gpp",
                                    n_lineups=10, field_size=20000)
    assert res["n_built"] == 10
    rep = validate.validate_portfolio(res["lineups"], {
        "contest_shape": "large_field_gpp", "field_size": 20000})
    assert rep["export_allowed"], rep["failures"]
    csv = dk_export.portfolio_to_csv(res["lineups"])
    # every cell carries a DK id
    body = csv.splitlines()[1]
    assert "(" in body and ")" in body
    for lu in res["lineups"]:
        assert 48_500 <= sum(p["salary"] for p in lu) <= 50_000


def test_real_wta_enforces_hard_constraints():
    pool = ingest.pool_from_projections(PROJS)["players"]
    res = optimizer.build_portfolio(pool, contest_shape="small_field_wta",
                                    n_lineups=3, field_size=300)
    assert res["n_built"] >= 1
    # #49 (dead-bat) + #52 (ceiling-bat) fired as build constraints
    assert 49 in res["fired_rules"] and 52 in res["fired_rules"]
    rep = validate.validate_portfolio(res["lineups"],
                                      {"contest_shape": "small_field_wta", "field_size": 300})
    assert rep["export_allowed"], rep["failures"]


def test_research_real_ownership_surfaces_rule53():
    pool = ingest.pool_from_projections(PROJS)["players"]
    own = {p["name"]: p["adj_own"] for p in pool if p.get("adj_own") is not None}
    board = research.build_board(
        hitters=research.parse_hitter_research((FX / "hitter_research.csv").read_text()),
        ownership=own)
    # real sub-2% + xSLG>=.45 bats must surface (e.g. NYM/CHC low-owned high-xSLG)
    assert len(board["discarded_candidates"]) >= 1
    for c in board["discarded_candidates"]:
        assert c["proj_own"] < 2.0 and c["xslg"] >= 0.45


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
