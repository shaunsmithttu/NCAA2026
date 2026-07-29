"""Real DKEntries + SaberSim reconciliation and the canonical (DK-authoritative)
build/export path, against the real fixtures.

Run: cd backend && python -m tests.test_reconcile
"""
import os
import pathlib
import tempfile

os.environ["MLB_GPP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "rec.sqlite3")

from app.db import init_db                                        # noqa: E402
from app.services import (dk_export, ingest, optimizer,           # noqa: E402
                          rules_ledger, validate)

init_db(seed=True)
rules_ledger.ensure_default_params()

FX = pathlib.Path(__file__).parent / "fixtures"
DK = ingest.parse_dk_entries((FX / "dk_entries.csv").read_bytes())
PROJS = ingest.parse_projections((FX / "sabersim_projections.csv").read_bytes())


def test_dk_entries_parse():
    assert len(DK) > 700
    # combined eligibility parsed from the Roster Position column (Rule #6)
    ohtani = next(p for p in DK if p.name.startswith("Shohei Ohtani"))
    assert set(ohtani.positions) == {"1B", "OF"}
    # DK ids resolved off the Name+ID column
    assert ohtani.dk_id and ohtani.dk_id.isdigit()


def test_reconcile_matches_on_three_part_key():
    rec = ingest.reconcile(DK, PROJS)
    # both files describe the same slate -> full match, no name-only collisions
    assert rec["n_matched"] == rec["n_dk"]
    assert len(rec["unmatched_dk"]) == 0
    assert len(rec["projection_key_collisions"]) == 0
    # DK stays authoritative for ids/positions/salary; projection metrics join on
    s = next(p for p in rec["players"] if p["name"].startswith("Shohei Ohtani"))
    assert s["positions"] == ["1B", "OF"] and s["dk95"] is not None


def test_canonical_build_and_export():
    pool = ingest.reconcile(DK, PROJS)["players"]
    res = optimizer.build_portfolio(pool, contest_shape="large_field_gpp",
                                    n_lineups=10, field_size=20000)
    assert res["n_built"] == 10
    rep = validate.validate_portfolio(res["lineups"], {
        "contest_shape": "large_field_gpp", "field_size": 20000})
    assert rep["export_allowed"], rep["failures"]
    csv = dk_export.portfolio_to_csv(res["lineups"])
    assert csv.splitlines()[0] == "P,P,C,1B,2B,3B,SS,OF,OF,OF"
    # every rostered cell carries the DK id from the entries file
    for line in csv.splitlines()[1:]:
        assert line.count("(") == 10


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
