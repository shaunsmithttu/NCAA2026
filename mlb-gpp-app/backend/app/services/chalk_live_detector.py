#!/usr/bin/env python3
"""
chalk_live_detector.py  —  MLB GPP pre-slate slate-shape classifier
Adopted from the June 30, 2026 Bat Flip post-mortem (Master Playbook Rules #31-#34).

Purpose: before finalizing portfolio SHAPE, score the slate for "chalk-live"
conditions so we do not run a maximum-leverage portfolio into a slate the chalk
wins outright (the June 30 failure: top-1% avg own 10.2%, Skubal 63% / Woo 48%
of the top-1%, MIA+CHC 85% of top-1% stacks, us cashed 3.3% / zero top-1%).

Inputs (per slate):
  - pitcher rows: name, team, salary, proj_own (0-100), xslg (opp expected SLG),
                  k_pct, opp_team_total (implied runs allowed to opponent)
  - stack rows:   team, bat_owns = list of each projected-order bat's individual
                  ownership %, team_agg_own (sum), ceiling
  - vegas:        list of game totals; list of favorite moneylines

Outputs:
  - chalk_live score (0-4 signals) + verdict
  - recommended chalk-anchored block size (% of portfolio)  [Rule #34]
  - the xSLG-gate LEVERAGE EXCEPTION list                    [Rule #31]
  - individual-vs-aggregate ownership flags on each stack    [Rule #32]

This is a decision-support prototype: it recommends block sizes and flags,
it does not build lineups.
"""

from dataclasses import dataclass, field
from typing import List

# ----------------------------- data models -----------------------------
@dataclass
class Pitcher:
    name: str; team: str; salary: int
    proj_own: float          # projected ownership %, 0-100
    xslg: float              # opponent expected SLG (the Rule #1 gate metric)
    k_pct: float             # 0-1
    opp_team_total: float    # implied runs the opponent scores

@dataclass
class Stack:
    team: str
    bat_owns: List[float]    # individual projected ownership % per top-of-order bat
    ceiling: float
    @property
    def team_agg_own(self): return round(sum(self.bat_owns), 1)
    @property
    def n_sub10(self): return sum(1 for o in self.bat_owns if o < 10.0)

@dataclass
class Slate:
    pitchers: List[Pitcher]
    stacks: List[Stack]
    game_totals: List[float]
    fav_moneylines: List[int]   # e.g. [-115, -180, -156, ...]

# ----------------------------- thresholds -----------------------------
ACE_OWN = 35.0          # "elite high-owned ace" ownership floor
ACE_OPP_TT = 3.6        # ace matchup is "plus" if opp implied total <= this
BIG_TOTAL = 9.5         # a "double-digit-ish" total
COMPRESSED_MAX_BIG = 2  # <= this many big totals => compressed/small-favorite slate
STRONG_FAV = -170       # moneyline at/below this = strong favorite
XSLG_CAP = 0.45         # Rule #1 gate
LEVERAGE_OWN = 6.0      # Rule #31: capped arm under this own% = leverage exception

# ----------------------------- detector -----------------------------
def detect(slate: Slate):
    signals = {}

    # Signal A: one or two elite aces at 35%+ own in plus matchups
    chalk_aces = [p for p in slate.pitchers
                  if p.proj_own >= ACE_OWN and p.opp_team_total <= ACE_OPP_TT]
    signals['A_elite_chalk_aces_in_plus_spots'] = (len(chalk_aces) >= 1, chalk_aces)

    # Signal B: compressed slate of small favorites (few big totals)
    big = [t for t in slate.game_totals if t >= BIG_TOTAL]
    strong_favs = [m for m in slate.fav_moneylines if m <= STRONG_FAV]
    compressed = (len(big) <= COMPRESSED_MAX_BIG) and (len(strong_favs) <= 2)
    signals['B_compressed_small_favorite_slate'] = (compressed,
        {'big_totals': len(big), 'strong_favs': len(strong_favs)})

    # Signal C: the chalk STACK is a distributed-ownership favorite
    #           (high aggregate team own, but its bats are individually low-owned)
    distributed = [s for s in slate.stacks
                   if s.team_agg_own >= 60 and s.n_sub10 >= 3]
    signals['C_distributed_chalk_stack'] = (len(distributed) >= 1, distributed)

    # Signal D: chalk ceiling parity — the highest-ceiling stacks ARE the chalk
    #           (leverage has no ceiling edge to justify a full fade)
    if slate.stacks:
        top_ceiling = sorted(slate.stacks, key=lambda s: -s.ceiling)[:3]
        chalky_top = [s for s in top_ceiling if s.team_agg_own >= 50]
        parity = len(chalky_top) >= 2
    else:
        parity, chalky_top = False, []
    signals['D_chalk_owns_the_ceiling'] = (parity, chalky_top)

    score = sum(1 for v in signals.values() if v[0])

    # verdict + recommended chalk-anchored block (Rule #34)
    if score >= 3:
        verdict = "CHALK-LIVE (strong)"; block = "30%"
    elif score == 2:
        verdict = "CHALK-LIVE (moderate)"; block = "25%"
    elif score == 1:
        verdict = "MIXED — lean leverage, carry a small chalk anchor"; block = "15%"
    else:
        verdict = "LEVERAGE SLATE — winner-study defaults apply"; block = "0-10%"

    return {'signals': signals, 'score': score, 'verdict': verdict,
            'chalk_block_pct': block}

# ----------------------------- Rule #31 gate reform -----------------------------
def xslg_gate(pitchers: List[Pitcher]):
    """Return (capped_hard, leverage_exception) lists.
    capped_hard      -> classic Rule #1 cap at 15% (facing strong offense, NOT low-owned)
    leverage_exception -> Rule #31: capped BUT sub-6% owned => Chase-block leverage arm (10-20%)
    """
    capped_hard, leverage_exception = [], []
    for p in pitchers:
        if p.xslg > XSLG_CAP:
            if p.proj_own < LEVERAGE_OWN:
                leverage_exception.append(p)   # DO NOT zero — Chase block
            else:
                capped_hard.append(p)          # classic cap at 15%
    return capped_hard, leverage_exception

# ----------------------------- Rule #32 stack audit -----------------------------
def stack_ownership_audit(stacks: List[Stack]):
    """Flag stacks that a naive aggregate read would wrongly fade."""
    rows = []
    for s in stacks:
        naive_fade = s.team_agg_own >= 60
        actually_live = s.n_sub10 >= 3
        verdict = ("LIVE (do not fade — Rule #32)" if (naive_fade and actually_live)
                   else "concentrated chalk (fade OK)" if naive_fade
                   else "normal")
        rows.append((s.team, s.team_agg_own, s.n_sub10, round(s.ceiling,1), verdict))
    return sorted(rows, key=lambda r: -r[3])

# ----------------------------- report -----------------------------
def report(slate: Slate):
    d = detect(slate)
    print("="*68)
    print("CHALK-LIVE DETECTOR  —  slate shape classification")
    print("="*68)
    for name,(fired,detail) in d['signals'].items():
        mark = "FIRED " if fired else "  -   "
        extra = ""
        if name.startswith('A') and fired: extra = " -> " + ", ".join(p.name for p in detail)
        if name.startswith('C') and fired: extra = " -> " + ", ".join(s.team for s in detail)
        if name.startswith('D') and fired: extra = " -> " + ", ".join(s.team for s in detail)
        print(f"  [{mark}] {name}{extra}")
    print(f"\n  SCORE: {d['score']}/4   VERDICT: {d['verdict']}")
    print(f"  >>> Rule #34 recommended CHALK-ANCHORED BLOCK: {d['chalk_block_pct']} of portfolio")

    hard, lev = xslg_gate(slate.pitchers)
    print("\n--- xSLG gate (Rule #1 + #31 reform) ---")
    print("  Hard-capped (15%, facing strong offense, not low-owned):",
          ", ".join(p.name for p in hard) or "none")
    print("  LEVERAGE EXCEPTION (capped BUT sub-6% own -> Chase 10-20%, DO NOT ZERO):",
          ", ".join(f"{p.name} ({p.proj_own}%)" for p in lev) or "none")

    print("\n--- Stack ownership audit (Rule #32: individual vs aggregate) ---")
    print(f"  {'Team':5} {'AggOwn':>7} {'#sub10':>7} {'Ceil':>6}  Verdict")
    for t,agg,n,ceil,v in stack_ownership_audit(slate.stacks):
        print(f"  {t:5} {agg:7.1f} {n:7d} {ceil:6.1f}  {v}")
    print("="*68)
    return d

# ----------------------------- June 30, 2026 back-test -----------------------------
if __name__ == "__main__":
    # Reconstructed from the June 30 Bat Flip post-mortem (the slate we LOST).
    june30 = Slate(
        pitchers=[
            Pitcher("Bryan Woo","SEA",9000,47.9,0.36,0.30,3.29),      # chalk ace, plus spot
            Pitcher("Tarik Skubal","DET",10000,34.7,0.20,0.31,3.28),  # chalk ace, plus spot
            Pitcher("Cam Schlittler","NYY",10500,26.6,0.33,0.26,2.55),
            Pitcher("Joe Ryan","MIN",9700,19.8,0.33,0.34,2.17),
            Pitcher("Cade Cavalli","WSH",6600,2.6,0.50,0.28,3.27),    # CAPPED but 2.6% -> leverage
            Pitcher("Justin Wrobleski","LAD",5900,3.8,0.48,0.22,4.26),# CAPPED but 3.8% -> leverage
            Pitcher("Matthew Liberatore","STL",6300,1.2,0.46,0.20,3.15),# CAPPED but 1.2% -> leverage
            Pitcher("Brandon Sproat","MIL",6500,17.9,0.55,0.29,3.95), # capped, 17.9% -> hard cap
        ],
        stacks=[
            Stack("MIA",[15.1,26.9,4.1,17.3,4.5,7.0,3.9], 171.0),  # ~90% agg, bats mostly low -> LIVE
            Stack("CHC",[8.6,25.3,26.7,33.0,10.4,13.5], 175.0),   # concentrated chalk in middle
            Stack("LAD",[17.6,8.1,9.0,13.0,8.9], 175.0),
            Stack("MIN",[1.1,4.1,8.4,5.1,0.7], 153.0),            # true leverage
            Stack("WSH",[0.9,4.2,2.1,1.0,3.8], 160.0),            # true leverage
            Stack("STL",[2.1,5.6,1.1,1.8,7.0], 155.0),            # true leverage
        ],
        game_totals=[11.5,11.5,11.0,10.0,9.0,9.0,9.0,9.0,8.5,8.0,7.0,7.0],
        fav_moneylines=[-156,-136,-180,-122,-149,-175,-136,-115,-115,-122,-115,-193],
    )
    report(june30)
    print("\nEXPECTED (post-mortem): chalk-live fires on the distributed MIA stack (C),")
    print("chalk owning the ceiling (D), and the elite aces Woo/Skubal in plus spots (A).")
    print("Cavalli/Wrobleski/Liberatore surface as Rule #31 leverage arms we wrongly zeroed.")
