"""Pydantic request/response models. Kept permissive (dicts for player pools)
so the frontend can round-trip the reconciled pool without a rigid schema."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class TransformRequest(BaseModel):
    players: list[dict[str, Any]]
    field_size: Optional[int] = None
    entry_fee: Optional[float] = None


class ChalkRequest(BaseModel):
    pitchers: list[dict[str, Any]] = []
    stacks: list[dict[str, Any]] = []
    game_totals: list[float] = []
    fav_moneylines: list[int] = []


class BuildRequest(BaseModel):
    players: list[dict[str, Any]]
    contest_shape: str                      # large_field_gpp | small_field_wta
    n_lineups: int = 20
    field_size: Optional[int] = None
    entry_fee: Optional[float] = None
    slate_id: Optional[int] = None
    leverage_lambda: Optional[float] = None
    locks: list[list[Any]] = []
    bans: list[list[Any]] = []
    opp_xslg: dict[str, float] = {}         # team/key -> opposing arm xSLG (for #53)
    ctx: dict[str, Any] = {}                # extra validate() context
    chalk: Optional[dict[str, Any]] = None  # chalk output to persist with the build


class ValidateRequest(BaseModel):
    portfolio: list[list[dict[str, Any]]]
    ctx: dict[str, Any] = {}


class ExportRequest(BaseModel):
    portfolio: list[list[dict[str, Any]]]
    ctx: dict[str, Any] = {}
    slate_id: Optional[int] = None


class RuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    rule_type: Optional[str] = None
    params: Optional[dict[str, Any]] = None


class AdjudicateRequest(BaseModel):
    signal_id: int
    decision: str                           # keep | drop
    reason: str


class SlateCreate(BaseModel):
    slate_date: str
    contest_shape: Optional[str] = None
    field_size: Optional[int] = None
    entry_fee: Optional[float] = None
    notes: Optional[str] = None


class SimOverlayRequest(BaseModel):
    sim_portfolio: list[list[dict[str, Any]]]
    coverage_lineups: list[list[dict[str, Any]]]
    coverage_pct: float = 10.0


class ParseLineupsRequest(BaseModel):
    csv_text: str
    players: list[dict[str, Any]]           # the reconciled pool to map onto


class SimOverlayBuildRequest(BaseModel):
    sim_portfolio: list[list[dict[str, Any]]]
    coverage_lineups: list[list[dict[str, Any]]] = []
    coverage_pct: float = 10.0
    contest_shape: str = "large_field_gpp"
    field_size: Optional[int] = None
    slate_id: Optional[int] = None
    ctx: dict[str, Any] = {}
    chalk: Optional[dict[str, Any]] = None


class InfoFixRequest(BaseModel):
    portfolio: list[list[dict[str, Any]]]
    fixes: list[dict[str, Any]]              # [{out_key:[name,team,is_p], replacement:{...}}]
    ctx: dict[str, Any] = {}


class SimBaselineScoreRequest(BaseModel):
    build_id: int
    actuals: dict[str, float]                # {norm_name -> points}


class CalibrationRequest(BaseModel):
    slate_id: Optional[int] = None
    slate_date: str
    pairs: list[dict[str, Any]]
    field_size: Optional[int] = None
    entry_fee: Optional[float] = None
