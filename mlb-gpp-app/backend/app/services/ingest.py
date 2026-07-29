"""File ingest + player-pool reconciliation (spec Sections 2A, 5).

DKEntries CSV is AUTHORITATIVE for player IDs, position eligibility, salary,
team, and game string. Never infer these from the projections file (spec S2 #3).
Every player is keyed on the THREE-PART key (name, team, is_pitcher) — never
name-only — to prevent the July 28 duplicate-Jose-Fermin bug (spec S4).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Optional


# DKEntries column indices (spec S5). Player pool table starts at row 8 (0-indexed).
DK_POOL_START_ROW = 8
DK_COL = {
    "name_id": 16,          # "Name (ID)"
    "name": 17,
    "pos_elig": 19,         # combined eligibility e.g. "1B/OF"
    "salary": 20,
    "game_info": 21,        # game string e.g. "SEA@DET 07/29/2026 07:10PM ET"
    "team": 22,
}

PITCHER_POS = {"P", "SP", "RP"}


def norm_name(name: str) -> str:
    """Normalize a player name for keying: lowercase, strip accents-ish, collapse
    punctuation/whitespace, drop trailing Jr/Sr/II/III. Team + is_pitcher still
    disambiguate — normalization only absorbs formatting noise between files."""
    s = name.strip().lower()
    s = s.replace(".", "").replace("'", "").replace("`", "")
    s = re.sub(r"\s+(jr|sr|ii|iii|iv)\.?$", "", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def player_key(name: str, team: str, is_pitcher: bool) -> tuple:
    """The three-part key (spec S4). NEVER key on name alone."""
    return (norm_name(name), (team or "").strip().upper(), bool(is_pitcher))


@dataclass
class DKPlayer:
    dk_id: str
    name: str
    positions: list[str]          # parsed combined eligibility
    salary: int
    team: str
    opp: str
    game_info: str
    is_pitcher: bool

    @property
    def key(self) -> tuple:
        return player_key(self.name, self.team, self.is_pitcher)


def _parse_positions(raw: str) -> list[str]:
    """Parse combined eligibility '1B/OF' correctly (Rule #6)."""
    return [p.strip().upper() for p in re.split(r"[/,]", raw or "") if p.strip()]


def _parse_name_from_name_id(name_id: str) -> tuple[str, str]:
    """'Aaron Judge (12345)' -> ('Aaron Judge', '12345'). Returns (name, id)."""
    m = re.match(r"^(.*?)\s*\((\d+)\)\s*$", (name_id or "").strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return (name_id or "").strip(), ""


def _teams_from_game_info(game_info: str) -> tuple[str, str]:
    """'SEA@DET 07/29/2026 ...' -> ('SEA', 'DET'). Empty on unparseable."""
    m = re.search(r"\b([A-Z]{2,3})@([A-Z]{2,3})\b", game_info or "")
    if m:
        return m.group(1), m.group(2)
    return "", ""


def parse_dk_entries(content: bytes | str) -> list[DKPlayer]:
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    reader = list(csv.reader(io.StringIO(text)))
    players: list[DKPlayer] = []
    for row in reader[DK_POOL_START_ROW:]:
        if len(row) <= DK_COL["team"]:
            continue
        name_id = row[DK_COL["name_id"]]
        name = row[DK_COL["name"]].strip()
        if not name:
            continue
        parsed_name, dk_id = _parse_name_from_name_id(name_id)
        if not dk_id:
            # fall back: some exports carry the id in a trailing "(NNN)" on Name
            parsed_name2, dk_id = _parse_name_from_name_id(name)
            if dk_id:
                name = parsed_name2
        positions = _parse_positions(row[DK_COL["pos_elig"]])
        is_pitcher = any(p in PITCHER_POS for p in positions)
        team = (row[DK_COL["team"]] or "").strip().upper()
        game_info = row[DK_COL["game_info"]]
        t1, t2 = _teams_from_game_info(game_info)
        opp = t2 if team == t1 else (t1 if team == t2 else "")
        try:
            salary = int(re.sub(r"[^\d]", "", row[DK_COL["salary"]] or "0") or 0)
        except ValueError:
            salary = 0
        players.append(DKPlayer(
            dk_id=dk_id or "", name=name or parsed_name, positions=positions,
            salary=salary, team=team, opp=opp, game_info=game_info,
            is_pitcher=is_pitcher,
        ))
    return players


@dataclass
class Projection:
    name: str
    pos: str
    team: str
    opp: str
    salary: Optional[int]
    proj: float
    dk95: Optional[float]
    dk99: Optional[float]
    dk25: Optional[float]
    dk75: Optional[float]
    adj_own: Optional[float]
    order: Optional[int]
    status: str
    is_pitcher: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return player_key(self.name, self.team, self.is_pitcher)


def _f(row: dict, *keys) -> Optional[float]:
    for k in keys:
        if k in row and str(row[k]).strip() not in ("", "-", "NA", "nan"):
            try:
                return float(str(row[k]).replace("%", "").replace(",", "").strip())
            except ValueError:
                continue
    return None


def _s(row: dict, *keys) -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return str(row[k]).strip()
    return ""


def parse_projections(content: bytes | str) -> list[Projection]:
    """Parse SaberSim/projections CSV (spec S5 key columns). Column lookups are
    tolerant of header casing/spacing variants."""
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    reader = csv.DictReader(io.StringIO(text))
    # build a case/space-insensitive header map
    out: list[Projection] = []
    for raw in reader:
        row = { (k or "").strip(): v for k, v in raw.items() }
        low = { (k or "").strip().lower(): v for k, v in raw.items() }

        def g(*names):
            for n in names:
                if n in row:
                    return row[n]
                if n.lower() in low:
                    return low[n.lower()]
            return None

        name = _s({**row}, "Name") or _s(low, "name")
        if not name:
            continue
        pos = (g("Pos", "Position") or "").strip()
        is_pitcher = pos.upper() in PITCHER_POS or pos.upper().startswith("P")
        order_raw = g("Order", "Batting Order")
        try:
            order = int(float(order_raw)) if order_raw not in (None, "", "-") else None
        except (ValueError, TypeError):
            order = None
        rowl = {k.lower(): v for k, v in row.items()}
        out.append(Projection(
            name=name.strip(),
            pos=pos,
            team=(g("Team", "Tm") or "").strip().upper(),
            opp=(g("Opp", "Opponent") or "").strip().upper(),
            salary=int(float(g("Salary"))) if _f(rowl, "salary") is not None else None,
            proj=_f(rowl, "ss proj", "proj", "projection", "fpts") or 0.0,
            dk95=_f(rowl, "dk_95_percentile", "dk95", "dk_95"),
            dk99=_f(rowl, "dk_99_percentile", "dk99", "dk_99"),
            dk25=_f(rowl, "dk_25_percentile", "dk25", "dk_25"),
            dk75=_f(rowl, "dk_75_percentile", "dk75", "dk_75"),
            adj_own=_f(rowl, "adj own", "adj_own", "ownership", "own", "proj own"),
            order=order,
            status=(g("Status") or "").strip(),
            is_pitcher=is_pitcher,
            raw=row,
        ))
    return out


def confirmed_hitters(projections: list[Projection]) -> list[Projection]:
    """Filter Status=='Confirmed' and Order.notna() before stack analysis (spec S5)."""
    return [p for p in projections
            if not p.is_pitcher
            and p.status.lower() == "confirmed"
            and p.order is not None]


_SLOT_ORDER = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
_DK_HEADER = ["p", "p", "c", "1b", "2b", "3b", "ss", "of", "of", "of"]


def _assign_slots(players: list[dict]) -> list[dict]:
    """Greedy/backtracking assignment of a set of players onto the DK slot
    template honouring combined eligibility. Sets each player's 'slot' and
    returns them in slot order. Leaves 'slot' blank if no legal assignment."""
    def eligible(p, slot):
        if slot == "P":
            return p.get("is_pitcher")
        if p.get("is_pitcher"):
            return False
        return slot in [x.upper() for x in (p.get("positions") or [])]

    slots = list(_SLOT_ORDER)
    assign: dict[int, str] = {}

    def bt(si):
        if si == len(slots):
            return True
        for i, p in enumerate(players):
            if i in assign:
                continue
            if eligible(p, slots[si]):
                assign[i] = slots[si]
                if bt(si + 1):
                    return True
                del assign[i]
        return False

    ordered = []
    if bt(0):
        for slot in _SLOT_ORDER:
            for i, p in enumerate(players):
                if assign.get(i) == slot and not any(id(o) == id(p) for o in ordered):
                    ordered.append({**p, "slot": slot})
                    break
        return ordered
    return [{**p, "slot": ""} for p in players]


def parse_lineup_rows(csv_text: str, pool_players: list[dict]) -> dict:
    """Parse a sim/DK-format lineup CSV and map each cell back onto the
    reconciled pool (spec S2 A: the sim's final portfolio + lineup pool upload).

    Cells look like 'Aaron Judge (12345)' or just 'Aaron Judge'. Players are
    resolved by DK id first, then by normalized name. Returns lineups (each a
    list of player dicts with 'slot' set) plus any unresolved cells."""
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for p in pool_players:
        if p.get("dk_id"):
            by_id[str(p["dk_id"])] = p
        by_name.setdefault(norm_name(p["name"]), p)

    rows = list(csv.reader(io.StringIO(csv_text)))
    lineups, unresolved = [], []
    for r in rows:
        cells = [c.strip() for c in r if c and c.strip()]
        if not cells:
            continue
        # skip a DK header row
        low = [re.sub(r"[^a-z0-9]", "", c.lower()) for c in cells]
        if low[:10] == _DK_HEADER:
            continue
        found = []
        for c in cells:
            m = re.search(r"\((\d+)\)", c)
            player = None
            if m and m.group(1) in by_id:
                player = by_id[m.group(1)]
            else:
                nm = norm_name(re.sub(r"\(\d+\)", "", c))
                player = by_name.get(nm)
            if player is not None:
                found.append(player)
            elif re.search(r"[a-zA-Z]", c):
                unresolved.append(c)
        if len(found) >= 8:                       # tolerate a stray column or two
            lineups.append(_assign_slots(found[:10]))
    return {"lineups": lineups, "n_lineups": len(lineups),
            "unresolved": sorted(set(unresolved))}


def reconcile(dk_players: list[DKPlayer],
              projections: list[Projection]) -> dict:
    """Join projections onto the authoritative DK pool via the three-part key.

    Returns matched players (DK id/pos/salary from DK, proj metrics from
    projections) plus unmatched diagnostics for the validate() layer.
    """
    proj_by_key: dict[tuple, Projection] = {}
    collisions: list[dict] = []
    for p in projections:
        if p.key in proj_by_key:
            collisions.append({"key": list(p.key), "name": p.name, "team": p.team})
        proj_by_key[p.key] = p

    matched, unmatched_dk = [], []
    used_proj_keys = set()
    for dk in dk_players:
        pr = proj_by_key.get(dk.key)
        if pr is None:
            unmatched_dk.append({"name": dk.name, "team": dk.team, "is_pitcher": dk.is_pitcher})
            continue
        used_proj_keys.add(dk.key)
        matched.append({
            "dk_id": dk.dk_id, "name": dk.name, "positions": dk.positions,
            "salary": dk.salary, "team": dk.team, "opp": dk.opp,
            "game_info": dk.game_info, "is_pitcher": dk.is_pitcher,
            "proj": pr.proj, "dk95": pr.dk95, "dk99": pr.dk99,
            "dk25": pr.dk25, "dk75": pr.dk75, "adj_own": pr.adj_own,
            "order": pr.order, "status": pr.status,
            "key": list(dk.key),
        })
    unmatched_proj = [
        {"name": p.name, "team": p.team, "is_pitcher": p.is_pitcher}
        for p in projections if p.key not in used_proj_keys
    ]
    return {
        "players": matched,
        "unmatched_dk": unmatched_dk,
        "unmatched_projections": unmatched_proj,
        "projection_key_collisions": collisions,
        "n_matched": len(matched),
        "n_dk": len(dk_players),
        "n_projections": len(projections),
    }
