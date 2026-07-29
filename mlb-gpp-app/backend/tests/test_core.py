"""Smoke + correctness tests for the trust layer, detector port, and optimizer.

Run:  cd backend && python -m pytest -q   (or: python -m tests.test_core)
Uses a temp DB via MLB_GPP_DB_PATH so it never touches real data.
"""
import os
import tempfile

os.environ["MLB_GPP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.sqlite3")

from app.db import init_db                                    # noqa: E402
from app.services import rules_ledger as rl                   # noqa: E402
from app.services import (chalk, ingest, optimizer, ownership,  # noqa: E402
                          validate)

init_db(seed=True)
rl.ensure_default_params()


def _pool():
    """A tiny legal pool: 3 games, enough players to fill a lineup twice over."""
    teams = {"SEA": "DET", "DET": "SEA", "NYM": "ATL", "ATL": "NYM",
             "SD": "COL", "COL": "SD"}
    gi = {"SEA": "SEA@DET", "DET": "SEA@DET", "NYM": "NYM@ATL", "ATL": "NYM@ATL",
          "SD": "SD@COL", "COL": "SD@COL"}
    players = []
    pid = 1000
    # pitchers, one per team
    for t in teams:
        players.append(dict(dk_id=str(pid), name=f"SP_{t}", positions=["P"], salary=8000,
                            team=t, opp=teams[t], game_info=gi[t], is_pitcher=True,
                            proj=16, dk95=25, dk99=30, dk25=8, dk75=18, adj_own=12,
                            order=None, status="Confirmed", key=[f"sp_{t.lower()}", t, True]))
        pid += 1
    # hitters: 6 per team across the standard positions
    positions = ["C", "1B", "2B", "3B", "SS", "OF"]
    for t in teams:
        for i, pos in enumerate(positions):
            players.append(dict(
                dk_id=str(pid), name=f"{t}_{pos}", positions=[pos, "OF"] if pos != "OF" else ["OF"],
                salary=4200, team=t, opp=teams[t], game_info=gi[t], is_pitcher=False,
                proj=9 + i, dk95=26 + i, dk99=32 + i, dk25=5 + i, dk75=12 + i,
                adj_own=8 + i, order=i + 1, status="Confirmed",
                key=[f"{t.lower()}_{pos.lower()}", t, False]))
            pid += 1
    return players


def test_three_part_key_disambiguates():
    a = ingest.player_key("Jose Fermin", "CLE", is_pitcher=False)
    b = ingest.player_key("Jose Fermin", "MIN", is_pitcher=True)
    assert a != b, "three-part key must separate two Jose Fermins"


def test_chalk_detector_june30():
    # the June 30 back-test from the prototype: 3 signals fire, chalk-live strong
    import app.services.chalk_live_detector as cld
    june30 = cld.Slate(
        pitchers=[cld.Pitcher("Bryan Woo", "SEA", 9000, 47.9, 0.36, 0.30, 3.29),
                  cld.Pitcher("Tarik Skubal", "DET", 10000, 34.7, 0.20, 0.31, 3.28),
                  cld.Pitcher("Cade Cavalli", "WSH", 6600, 2.6, 0.50, 0.28, 3.27)],
        stacks=[cld.Stack("MIA", [15.1, 26.9, 4.1, 17.3, 4.5, 7.0, 3.9], 171.0),
                cld.Stack("CHC", [8.6, 25.3, 26.7, 33.0, 10.4, 13.5], 175.0)],
        game_totals=[11.5, 11.5, 11.0], fav_moneylines=[-156, -136, -180])
    d = cld.detect(june30)
    assert d["score"] >= 1
    # Cavalli must surface as a leverage exception, not a hard cap (Rule #31/#50)
    _, lev = cld.xslg_gate(june30.pitchers)
    assert any(p.name == "Cade Cavalli" for p in lev)


def test_ownership_transform_inverts_by_field_size():
    players = _pool()
    # a chalky hitter
    players[7]["adj_own"] = 30.0
    big = ownership.apply_transform(players, field_size=5000, entry_fee=150)
    small = ownership.apply_transform(players, field_size=300, entry_fee=150)
    assert big["transform"] == "rule_42"
    assert small["transform"] == "rule_51"
    # same 30%-owned hitter: #42 deflates mid chalk (<=1), #51 deflates hitter chalk too
    h_big = next(p for p in big["players"] if p["name"] == players[7]["name"])
    h_small = next(p for p in small["players"] if p["name"] == players[7]["name"])
    assert h_big["own_mult"] <= 1.0
    assert h_small["own_category"] == "hitter_chalk"


def test_optimizer_builds_legal_unique_lineups():
    pool = _pool()
    res = optimizer.build_portfolio(pool, contest_shape="large_field_gpp",
                                    n_lineups=3, field_size=5000)
    assert res["n_built"] >= 1
    rep = validate.validate_portfolio(res["lineups"],
                                      {"contest_shape": "large_field_gpp", "field_size": 5000})
    # no hard failures on a clean pool
    assert rep["passed"], rep["failures"]
    # each lineup is 10 players, salary within band
    for lu in res["lineups"]:
        assert len(lu) == 10
        sal = sum(p["salary"] for p in lu)
        assert sal <= 50000


def test_blocked_signal_hard_blocks_export():
    pool = _pool()
    res = optimizer.build_portfolio(pool, contest_shape="large_field_gpp",
                                    n_lineups=2, field_size=5000)
    rep = validate.validate_portfolio(res["lineups"], {
        "contest_shape": "large_field_gpp", "field_size": 5000,
        "unadjudicated_blocked_signals": 1})
    assert not rep["export_allowed"], "Rule #53 must hard-block export"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
