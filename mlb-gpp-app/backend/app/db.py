"""SQLite storage layer (spec Section 1: file-based, local, no cloud DB).

Tables:
  rules                  - the governance ledger, seeded from rules_seed.json
  builds                 - one row per optimizer/build run
  build_rules_fired      - which rules fired on a build (hit/miss tracking)
  discarded_signals      - Rule #53 blocked-signal adjudication log (hard block)
  ownership_calibration  - projected-vs-actual ownership pairs, per slate
  postmortems            - structured post-mortem records
  slates                 - lightweight slate registry (date + contest metadata)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import DB_PATH, RULES_SEED_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS rules (
    id                INTEGER PRIMARY KEY,     -- the rule number, e.g. 50
    text              TEXT NOT NULL,
    rationale         TEXT,
    rule_type         TEXT,                    -- coverage | allocation | gate | process
    active            INTEGER NOT NULL DEFAULT 1,
    folded_into       INTEGER,                 -- e.g. rule 1 -> 50
    enabled           INTEGER NOT NULL DEFAULT 1,  -- user toggle (distinct from active/folded)
    fired_count       INTEGER NOT NULL DEFAULT 0,
    hit_count         INTEGER NOT NULL DEFAULT 0,
    miss_count        INTEGER NOT NULL DEFAULT 0,
    last_fired_slate  TEXT,
    params            TEXT                     -- JSON: editable thresholds (rules-as-data, spec S3)
);

CREATE TABLE IF NOT EXISTS slates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slate_date    TEXT NOT NULL,
    contest_shape TEXT,                        -- large_field_gpp | small_field_wta
    field_size    INTEGER,
    entry_fee     REAL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS builds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    slate_id       INTEGER REFERENCES slates(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    mode           TEXT NOT NULL,              -- sim_overlay | in_house   (spec S2 C10)
    contest_shape  TEXT NOT NULL,
    n_lineups      INTEGER NOT NULL,
    objective      TEXT,                       -- p99 | p75_p95_blend
    lineups_json   TEXT,                       -- the final (overlaid) portfolio
    sim_baseline_json TEXT,                    -- untouched sim portfolio (spec S2 D12)
    validation_json TEXT,                      -- full validate() report
    chalk_json     TEXT                        -- chalk-live detector output at build time
);

CREATE TABLE IF NOT EXISTS build_rules_fired (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id   INTEGER NOT NULL REFERENCES builds(id),
    rule_id    INTEGER NOT NULL REFERENCES rules(id),
    detail     TEXT,
    helped     INTEGER                          -- NULL until post-mortem scores it
);

CREATE TABLE IF NOT EXISTS discarded_signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slate_id      INTEGER REFERENCES slates(id),
    build_id      INTEGER REFERENCES builds(id),
    player_name   TEXT NOT NULL,
    team          TEXT,
    proj_own      REAL,
    xslg          REAL,
    blocked_by_rule INTEGER,
    adjudication  TEXT,                          -- 'keep' | 'drop' | NULL(unadjudicated)
    reason        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ownership_calibration (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slate_id      INTEGER REFERENCES slates(id),
    slate_date    TEXT,
    player_name   TEXT NOT NULL,
    team          TEXT,
    is_pitcher    INTEGER NOT NULL DEFAULT 0,
    proj_own      REAL,
    actual_own    REAL,
    field_size    INTEGER,
    entry_fee     REAL
);

CREATE TABLE IF NOT EXISTS postmortems (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slate_id     INTEGER REFERENCES slates(id),
    build_id     INTEGER REFERENCES builds(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    doc_json     TEXT,                           -- structured post-mortem record
    markdown     TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(seed: bool = True) -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    if seed:
        seed_rules()


def seed_rules(force: bool = False) -> int:
    """Load rules_seed.json into the rules table.

    Idempotent: existing rules are left untouched (so user edits to params /
    enabled / hit-miss counts survive re-seeding) unless force=True, which
    resets the static columns (text/rationale/type/active/folded) from seed.
    """
    seed = json.loads(RULES_SEED_PATH.read_text())
    rows = seed["rules"]
    n = 0
    with get_conn() as conn:
        existing = {r["id"] for r in conn.execute("SELECT id FROM rules")}
        for r in rows:
            if r["id"] in existing and not force:
                continue
            if r["id"] in existing and force:
                conn.execute(
                    """UPDATE rules SET text=?, rationale=?, rule_type=?, active=?,
                       folded_into=? WHERE id=?""",
                    (r["text"], r.get("rationale"), r.get("rule_type"),
                     1 if r.get("active") else 0, r.get("folded_into"), r["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO rules
                       (id, text, rationale, rule_type, active, folded_into, enabled, params)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (r["id"], r["text"], r.get("rationale"), r.get("rule_type"),
                     1 if r.get("active") else 0, r.get("folded_into"),
                     1 if r.get("active") else 0, "{}"),
                )
            n += 1
    return n
