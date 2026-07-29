"""End-to-end: synthetic DKEntries CSV (row-8 offset, documented column indices)
+ projections CSV -> /api/ingest -> /api/build -> validate -> export gate.
Proves the parser matches spec §5 and the full request flow works.

Run: cd backend && python -m tests.test_integration
"""
import csv
import io
import os
import tempfile

os.environ["MLB_GPP_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "itest.sqlite3")

from fastapi.testclient import TestClient        # noqa: E402
from app.main import app                          # noqa: E402

TEAMS = {"SEA": "DET", "DET": "SEA", "NYM": "ATL", "ATL": "NYM", "SD": "COL", "COL": "SD"}
GAME = {"SEA": "SEA@DET", "DET": "SEA@DET", "NYM": "NYM@ATL", "ATL": "NYM@ATL",
        "SD": "SD@COL", "COL": "SD@COL"}
HIT_POS = ["C", "1B", "2B", "3B", "SS", "OF"]


def make_dk_entries() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for _ in range(8):                 # rows 0-7 are pre-pool header junk (spec S5)
        w.writerow(["Entry", "Contest", "", "", "", "", "", "", ""])
    pid = 1
    def row(name, pos, salary, team):
        r = [""] * 23
        r[16] = f"{name} ({pid})"      # Name (ID)
        r[17] = name                    # Name
        r[19] = pos                     # combined eligibility
        r[20] = str(salary)             # salary
        r[21] = f"{GAME[team]} 07/29/2026 07:10PM ET"   # game string
        r[22] = team                    # team
        return r
    for t in TEAMS:
        w.writerow(row(f"SP_{t}", "P", 8000, t)); pid += 1
    for t in TEAMS:
        for pos in HIT_POS:
            elig = pos if pos == "OF" else f"{pos}/OF"
            w.writerow(row(f"{t}_{pos}", elig, 4200, t)); pid += 1
    return buf.getvalue()


def make_projections() -> str:
    buf = io.StringIO()
    cols = ["Name", "Pos", "Team", "Opp", "Salary", "SS Proj", "dk_95_percentile",
            "dk_99_percentile", "dk_25_percentile", "dk_75_percentile", "Adj Own", "Order", "Status"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    def rec(name, pos, team, proj, own, order, dk25):
        return {"Name": name, "Pos": pos, "Team": team, "Opp": TEAMS[team],
                "Salary": 8000 if pos == "P" else 4200, "SS Proj": proj,
                "dk_95_percentile": proj + 12, "dk_99_percentile": proj + 18,
                "dk_25_percentile": dk25, "dk_75_percentile": proj + 4,
                "Adj Own": own, "Order": order, "Status": "Confirmed"}
    for t in TEAMS:
        w.writerow(rec(f"SP_{t}", "P", t, 16, 12, "", 8))
    for t in TEAMS:
        for i, pos in enumerate(HIT_POS):
            w.writerow(rec(f"{t}_{pos}", pos, t, 9 + i, 8 + i, i + 1, 6 + i))
    return buf.getvalue()


def main():
    with TestClient(app) as c:
        dk, proj = make_dk_entries(), make_projections()
        r = c.post("/api/ingest", files={
            "dk_entries": ("dk.csv", dk, "text/csv"),
            "projections": ("proj.csv", proj, "text/csv"),
        })
        assert r.status_code == 200, r.text
        pool = r.json()
        print(f"ingest: {pool['n_matched']} matched / {pool['n_dk']} DK / {pool['n_projections']} proj")
        assert pool["n_matched"] == pool["n_dk"] == 42, pool["n_matched"]
        # verify DK is authoritative: positions parsed as combined eligibility
        of_eligible = [p for p in pool["players"] if "OF" in p["positions"] and not p["is_pitcher"]]
        assert len(of_eligible) >= 30, "combined eligibility (Rule #6) not parsed"

        b = c.post("/api/build", json={
            "players": pool["players"], "contest_shape": "large_field_gpp",
            "n_lineups": 5, "field_size": 5000, "entry_fee": 100,
        })
        assert b.status_code == 200, b.text
        build = b.json()
        print(f"build: {build['n_built']} lineups, objective={build['objective']}, "
              f"export_allowed={build['validation']['export_allowed']}")
        assert build["n_built"] >= 1
        assert build["objective"] == "p99_weighted"

        e = c.post("/api/export/dk-csv", json={
            "portfolio": build["lineups"],
            "ctx": {"contest_shape": "large_field_gpp", "field_size": 5000}})
        assert e.status_code == 200, e.text
        header = e.text.splitlines()[0]
        print(f"export header: {header}")
        assert header.split(",")[:3] == ["P", "P", "C"]
        print(f"exported {len(e.text.splitlines()) - 1} lineup rows")
        print("\nINTEGRATION OK")


if __name__ == "__main__":
    main()
