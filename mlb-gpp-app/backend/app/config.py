"""Environment-based configuration.

No hardcoded absolute paths (spec Section 1): every path derives from either an
env var or the package location, so the app can later be deployed without code
changes. v1 runs on localhost only.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent          # .../backend
APP_DIR = Path(__file__).resolve().parent                     # .../backend/app
SEED_DIR = APP_DIR / "seed"

# The SQLite file lives outside the source tree by default so it survives edits.
DATA_DIR = Path(os.environ.get("MLB_GPP_DATA_DIR", BACKEND_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("MLB_GPP_DB_PATH", DATA_DIR / "mlb_gpp.sqlite3"))
UPLOAD_DIR = Path(os.environ.get("MLB_GPP_UPLOAD_DIR", DATA_DIR / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

RULES_SEED_PATH = SEED_DIR / "rules_seed.json"

# ---------------------------------------------------------------------------
# CORS (localhost dev only for v1)
# ---------------------------------------------------------------------------
CORS_ORIGINS = os.environ.get(
    "MLB_GPP_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# ---------------------------------------------------------------------------
# Roster / cap constants (DK MLB Classic). Values that a rule can override live
# in the rules table instead — see services/rules_ledger.get_param().
# ---------------------------------------------------------------------------
ROSTER_SLOTS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
SALARY_CAP = 50_000
MAX_HITTERS_PER_TEAM = 5
MIN_GAMES_SPANNED = 2
