"""FastAPI application — MLB GPP Build App backend (localhost v1).

Endpoints follow the spec's dependency order: ingest/validate -> gate analysis ->
optimizer/build -> post-lock/scoring -> rules ledger/governance.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .config import CORS_ORIGINS
from .db import get_conn, init_db
from .models import (AdjudicateRequest, BuildRequest, CalibrationRequest,
                     ChalkRequest, ExportRequest, RuleUpdate, SimOverlayRequest,
                     SlateCreate, TransformRequest, ValidateRequest)
from .services import (chalk, dk_export, discarded_signals, ingest, optimizer,
                       ownership, postmortem, rules_ledger, sim_overlay, validate)

app = FastAPI(title="MLB GPP Build App", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db(seed=True)
    rules_ledger.ensure_default_params()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# A. Ingest & validate
# ---------------------------------------------------------------------------
@app.post("/api/ingest")
async def api_ingest(dk_entries: UploadFile = File(...),
                     projections: UploadFile = File(...)) -> dict:
    """DKEntries CSV is authoritative for IDs/positions/salary/team/game
    (spec S2 #3). Join projections via the three-part key."""
    dk_players = ingest.parse_dk_entries(await dk_entries.read())
    projs = ingest.parse_projections(await projections.read())
    if not dk_players:
        raise HTTPException(400, "No players parsed from DK entries file — check the "
                                 "row-8 pool offset / column layout (spec S5).")
    result = ingest.reconcile(dk_players, projs)
    result["confirmed_hitters"] = [
        {"name": p.name, "team": p.team, "order": p.order}
        for p in ingest.confirmed_hitters(projs)
    ]
    return result


@app.post("/api/validate")
def api_validate(req: ValidateRequest) -> dict:
    ctx = dict(req.ctx)
    slate_id = ctx.get("slate_id")
    ctx.setdefault("unadjudicated_blocked_signals",
                   discarded_signals.count_unadjudicated(slate_id))
    return validate.validate_portfolio(req.portfolio, ctx)


# ---------------------------------------------------------------------------
# B. Gate analysis / decision support
# ---------------------------------------------------------------------------
@app.post("/api/chalk/analyze")
def api_chalk(req: ChalkRequest) -> dict:
    return chalk.analyze(req.pitchers, req.stacks, req.game_totals, req.fav_moneylines)


@app.post("/api/ownership/transform")
def api_transform(req: TransformRequest) -> dict:
    return ownership.apply_transform(req.players, req.field_size, req.entry_fee)


# ---------------------------------------------------------------------------
# C. Optimizer / build
# ---------------------------------------------------------------------------
@app.post("/api/build")
def api_build(req: BuildRequest) -> dict:
    if req.contest_shape not in ("large_field_gpp", "small_field_wta"):
        raise HTTPException(400, "contest_shape must be set first (spec S2 #8): "
                                 "'large_field_gpp' or 'small_field_wta'.")
    # apply ownership transform onto the pool if field context is known
    pool = req.players
    if req.field_size is not None and req.entry_fee is not None:
        pool = ownership.apply_transform(req.players, req.field_size, req.entry_fee)["players"]

    result = optimizer.build_portfolio(
        pool, contest_shape=req.contest_shape, n_lineups=req.n_lineups,
        field_size=req.field_size, leverage_lambda=req.leverage_lambda,
        locks=[tuple(x) for x in req.locks] or None,
        bans=[tuple(x) for x in req.bans] or None,
    )
    portfolio = result["lineups"]

    # surface discarded signals (#53): qualifying bats that did not make the build
    rostered = set()
    for lu in portfolio:
        for p in lu:
            rostered.add(tuple(p["key"]) if isinstance(p.get("key"), list) else p["key"])
    if req.opp_xslg:
        blocked = {tuple(p["key"]) if isinstance(p.get("key"), list) else p["key"]
                   for p in pool} - rostered
        cands = discarded_signals.surface_candidates(pool, blocked, req.opp_xslg)
        discarded_signals.record_candidates(req.slate_id, None, cands, blocked_by_rule=None)

    # persist build + fired-rule log
    ctx = dict(req.ctx)
    ctx.update(contest_shape=req.contest_shape, field_size=req.field_size,
               slate_id=req.slate_id)
    ctx.setdefault("unadjudicated_blocked_signals",
                   discarded_signals.count_unadjudicated(req.slate_id))
    report = validate.validate_portfolio(portfolio, ctx)

    slate_date = _slate_date(req.slate_id)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO builds (slate_id, mode, contest_shape, n_lineups,
                                   objective, lineups_json, validation_json, chalk_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (req.slate_id, "in_house", req.contest_shape, len(portfolio),
             result["objective"], json.dumps(portfolio), json.dumps(report),
             json.dumps(req.chalk) if req.chalk else None))
        build_id = cur.lastrowid
    for rid, detail in result["fired_rules"].items():
        rules_ledger.record_fired(build_id, int(rid), slate_date, str(detail))

    return {"build_id": build_id, **result, "validation": report,
            "unadjudicated_blocked_signals":
                discarded_signals.count_unadjudicated(req.slate_id)}


@app.post("/api/export/dk-csv", response_class=PlainTextResponse)
def api_export(req: ExportRequest) -> PlainTextResponse:
    ctx = dict(req.ctx)
    ctx.setdefault("unadjudicated_blocked_signals",
                   discarded_signals.count_unadjudicated(req.slate_id))
    report = validate.validate_portfolio(req.portfolio, ctx)
    if not report["export_allowed"]:
        raise HTTPException(
            422, detail={"message": "Export blocked — validate() has hard failures "
                                    "(incl. any unadjudicated Rule #53 signal).",
                         "failures": report["failures"]})
    csv_text = dk_export.portfolio_to_csv(req.portfolio)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=dk_upload.csv"})


@app.post("/api/sim-overlay")
def api_sim_overlay(req: SimOverlayRequest) -> dict:
    return sim_overlay.coverage_overlay(req.sim_portfolio, req.coverage_lineups,
                                        req.coverage_pct)


# ---------------------------------------------------------------------------
# D. Post-lock / scoring / post-mortem
# ---------------------------------------------------------------------------
@app.post("/api/postmortem/standings")
async def api_standings(standings: UploadFile = File(...)) -> dict:
    return postmortem.ingest_standings(await standings.read())


@app.post("/api/calibration")
def api_calibration(req: CalibrationRequest) -> dict:
    n = postmortem.append_calibration(req.slate_id, req.slate_date, req.pairs,
                                      req.field_size, req.entry_fee)
    return {"appended": n, "summary": postmortem.calibration_summary()}


@app.get("/api/calibration")
def api_calibration_summary() -> dict:
    return postmortem.calibration_summary()


# ---------------------------------------------------------------------------
# E. Rules ledger / governance
# ---------------------------------------------------------------------------
@app.get("/api/rules")
def api_rules(include_folded: bool = True) -> dict:
    return {"rules": rules_ledger.list_rules(include_folded=include_folded)}


@app.get("/api/rules/{rule_id}")
def api_rule(rule_id: int) -> dict:
    r = rules_ledger.get_rule(rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    return r


@app.patch("/api/rules/{rule_id}")
def api_rule_update(rule_id: int, req: RuleUpdate) -> dict:
    return rules_ledger.update_rule(rule_id, enabled=req.enabled,
                                    rule_type=req.rule_type, params=req.params)


@app.get("/api/governance")
def api_governance() -> dict:
    return rules_ledger.governance_summary()


@app.get("/api/signals")
def api_signals(slate_id: int | None = None, only_unadjudicated: bool = False) -> dict:
    return {"signals": discarded_signals.list_signals(slate_id, only_unadjudicated),
            "n_unadjudicated": discarded_signals.count_unadjudicated(slate_id)}


@app.post("/api/signals/adjudicate")
def api_adjudicate(req: AdjudicateRequest) -> dict:
    try:
        return discarded_signals.adjudicate(req.signal_id, req.decision, req.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Slates
# ---------------------------------------------------------------------------
@app.post("/api/slates")
def api_create_slate(req: SlateCreate) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO slates (slate_date, contest_shape, field_size, entry_fee, notes)
               VALUES (?,?,?,?,?)""",
            (req.slate_date, req.contest_shape, req.field_size, req.entry_fee, req.notes))
        return {"id": cur.lastrowid, **req.model_dump()}


@app.get("/api/slates")
def api_list_slates() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM slates ORDER BY id DESC").fetchall()
    return {"slates": [dict(r) for r in rows]}


def _slate_date(slate_id: int | None) -> str | None:
    if slate_id is None:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT slate_date FROM slates WHERE id=?", (slate_id,)).fetchone()
    return row["slate_date"] if row else None
