# MLB GPP Build App

A local, rules-driven DraftKings MLB GPP portfolio builder for `shaunsmithttu`.
Replaces the manual/chat build process with: **upload → validate → build →
export DK CSV**, plus a persistent, queryable rules ledger and a
post-mortem/calibration loop.

Built to `BUILD_SPEC.md` and **Playbook v4** (48 active rules, ledger through
Rule #53). Rules are **data, not code** — every threshold lives in the SQLite
`rules` table and is editable in the UI without a code change.

> v1 is **localhost only** — no auth, no hosting, SQLite file on disk. The code
> is structured (env-based config, no hardcoded paths) so it *could* be deployed
> later, but v1 doesn't spend effort there.

## Architecture

| Layer | Tech | Location |
|-------|------|----------|
| Backend | FastAPI + PuLP/CBC | `backend/app` |
| Optimizer | PuLP integer program, objective per contest shape | `backend/app/services/optimizer.py` |
| Trust layer | `validate()` — every §7 hard constraint, named | `backend/app/services/validate.py` |
| Chalk detector | ported verbatim from the prototype + JSON adapter | `backend/app/services/chalk*.py` |
| Storage | SQLite (rules, builds, calibration, signals, post-mortems) | `backend/app/db.py` |
| Frontend | React + Vite + Tailwind | `frontend/` |

## Running it

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # optional
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The database (`backend/data/mlb_gpp.sqlite3`) is created and seeded from
`app/seed/rules_seed.json` on first startup. Override locations with
`MLB_GPP_DB_PATH` / `MLB_GPP_DATA_DIR`.

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173  (proxies /api -> :8000)
```

### Tests

```bash
cd backend
python -m tests.test_core            # trust layer, detector, optimizer, transforms
python -m tests.test_integration     # DK CSV parse -> build -> export, end to end
# or: pip install pytest && python -m pytest -q
```

## The workflow (tabs mirror the spec's five subsystems)

1. **Ingest & Validate** — upload DKEntries CSV (authoritative for IDs, positions,
   salary, team, game) + projections CSV. Reconciled via the **three-part key**
   `(name, team, is-pitcher)` — never name-only (the 7/28 duplicate-Jose-Fermin
   bug). Diagnostics surface unmatched players and key collisions.
2. **Gate Analysis** — the **chalk-live detector** (4 signals, verdict, Rule #34
   block %), the v4 **arm/stack split**, the xSLG **leverage-exception** list
   (#31/#50 — capped-but-sub-6% arms are *not* zeroed), and the individual-vs-
   aggregate **stack ownership audit** (#29). Ownership transform (#42/#51) is
   auto-selected by field size + entry fee.
3. **Build & Export** — set **contest shape first** (the meta-rule); it selects the
   objective (p99-weighted large-field vs p75/p95 blend WTA, Rule #44). The
   optimizer enforces roster legality, salary band, max-5-hitters/team, ≥2 games,
   no hitter-vs-rostered-pitcher, dead-bat cap (#49), and ceiling-bat (#52) as
   **hard constraints**. Export is **hard-gated** on `validate()` clearing AND
   zero unadjudicated Rule #53 signals.
4. **Post-Mortem** — upload DK standings → field distribution, winner, actual
   ownership. The **ownership calibration curve** persists projected-vs-actual
   pairs every slate (the open item behind Rule #51's provisional multipliers).
5. **Rules Ledger** — the governance layer. Toggle rules, retag
   coverage/allocation/gate, edit thresholds. Dashboard surfaces the
   rules-to-slates ratio, RETIRE candidates (2+ misfires), and **contradictions
   among enabled rules** (the exact #45-vs-#47 failure that cost 7/28).

## What's faithful to the docs, and what to review

- **DK scoring** (`app/scoring.py`) is transcribed from Playbook v4 §0 (incl. the
  Sac Fly/Hit +1.25 and the 10+K / 7+IP bonuses).
- **Rule `rule_type` tags** come from `rules_seed.json` and are a **draft** —
  review/correct them in the Rules tab before trusting the allocation-override
  and contradiction warnings (per the seed's own note).
- **Sim-overlay mode** (`app/services/sim_overlay.py`) treats an uploaded sim
  portfolio as the allocation baseline, applies only a fixed-budget coverage
  overlay (7–13%) + surgical info fixes, and **always stores the untouched sim
  baseline** for side-by-side scoring (spec §2 D12). Wiring a full sim-pool
  upload screen is the natural next step.

## Layout

```
backend/
  app/
    main.py            FastAPI routes (ingest/validate/build/export/rules/…)
    config.py          env-based config, roster/cap constants
    scoring.py         DK scoring table (Playbook §0)
    db.py              SQLite schema + rules seeding
    models.py          request models
    seed/rules_seed.json
    services/
      ingest.py             DK/projection parse, three-part key, reconcile
      chalk_live_detector.py  ported prototype (verbatim)
      chalk.py                JSON adapter + v4 arm/stack split
      ownership.py            Rule #42/#51 transform
      validate.py             the trust layer — every §7 check
      optimizer.py            PuLP/CBC build
      sim_overlay.py          allocation-baseline overlay + info fixes
      discarded_signals.py    Rule #46/#53 hard-block log
      postmortem.py           scoring, standings ingest, calibration
      rules_ledger.py         rules-as-data, hit/miss, governance
  tests/
frontend/
  src/{App.jsx, lib/api.js, components/*}
```
