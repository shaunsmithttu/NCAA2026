"""DraftKings CSV export (spec S2 A -> export DK CSV).

The DK bulk-upload format is one row per entry with the ten roster columns in
slot order: P, P, C, 1B, 2B, 3B, SS, OF, OF, OF. Each cell is "Name (ID)".
Export is only permitted when validate() returns export_allowed=True (the hard
gate lives in the router, not here).
"""
from __future__ import annotations

import csv
import io

DK_HEADER = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]


def _cell(p: dict) -> str:
    name = p.get("name", "")
    dk_id = p.get("dk_id", "")
    return f"{name} ({dk_id})" if dk_id else name


def portfolio_to_csv(portfolio: list[list[dict]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(DK_HEADER)
    for lu in portfolio:
        # lineup is already slot-ordered by optimizer._order_lineup
        row = [_cell(p) for p in lu[:10]]
        row += [""] * (10 - len(row))
        w.writerow(row)
    return buf.getvalue()
