# MLB GPP Build App — Spec for Claude Code

## Who this is for
Shaun (DK handle: shaunsmithttu) runs a rules-based MLB DFS GPP operation on DraftKings.
This folder is a full handoff package to build a **local web app** (localhost only,
no hosting) that replaces the current manual/chat-based build process with:
upload files → validate → build → export DK CSV, plus a persistent, queryable
rules ledger and a post-mortem/calibration loop.

**Read `source_docs/MLB_GPP_Master_Playbook_v4.md` in full before writing any
rule logic.** It is the authoritative current ruleset (48 active rules,
5 folded/superseded, ledger through Rule #53). Do not build against v3 — v3 is
included only for historical diff context (a Rule #45/#47 contradiction that v4
fixed). Everything else in `source_docs/` is supporting evidence the rules cite.

---

## 1. Architecture (decided)

- **Backend:** FastAPI (Python) — reuses/extends the existing PuLP + CBC optimizer
  logic and `chalk_live_detector.py` (included in this folder, working code).
- **Frontend:** React (Vite is fine), Tailwind for styling.
- **Storage:** SQLite (file-based, local) for the rules ledger, hit/miss log,
  post-mortem records, and ownership calibration history. No cloud DB.
- **Run mode:** `localhost` only for v1. Structure the code so it *could* be
  deployed later (env-based config, no hardcoded absolute paths), but do not
  spend v1 effort on auth, HTTPS, or hosting.
- **File I/O:** all uploads (DK entries CSV, SaberSim/projections CSV, ROO
  stacks file, pitcher splits, weather) are local file uploads through the UI;
  no external API calls except optionally re-fetching DK's live scoring rules
  (`Rules__DraftKings.pdf` is the last-known snapshot, included for reference).

## 2. v1 scope (full build, as agreed with Shaun)

Build all of the following in v1, in roughly this dependency order:

### A. Ingest & validate
1. Upload screen for: DKEntries CSV, SaberSim/projections CSV, ROO stacks file,
   pitcher split sheet (Baseball Savant xSLG by handedness), weather CSV
   (RotoWire-sourced), Vegas odds/totals, and — when available — the sim's
   full lineup pool + final portfolio (per the Sim-Overlay Operating Model).
2. `validate()` pipeline (this is the core trust layer — see Section 4 below
   for the full checklist pulled directly from Playbook v4 Section 7).
3. Player-pool reconciliation: DKEntries CSV is authoritative for player IDs,
   position eligibility, salary, team, game string. Never infer these from the
   projections file. Confirmed-starter status must be cross-checked against
   actual lineup cards, not just a projections status column (recurring leak
   in post-mortems).

### B. Gate analysis / decision support
4. Chalk-live detector — port `chalk_live_detector.py` as-is into the backend
   (it's already correct, tested against the June 30 slate). Expose its output
   (4-signal score, verdict, recommended chalk-block %) in the UI before the
   optimizer runs.
5. Rule #50 single-factor-screen ranking (NOT gating) for xSLG/park/weather —
   these must rank/weight stacks and arms, never hard-exclude, except for the
   specific hard constraints listed in Section 4.
6. Ownership transform: apply Rule #42 (≥~500 entries) or Rule #51 (<~500
   entries) based on field size + entry fee, before any leverage math.
7. Discarded-signal log (Rule #46/#53): any sub-2%-owned bat with xSLG ≥ .45
   that a rule would otherwise drop must appear in a UI panel requiring a
   typed adjudication ("keep" / "drop" + reason) before the build can proceed
   to CSV export. This is a **hard block**, not a warning — four consecutive
   slates were lost to this being skipped.

### C. Optimizer / build
8. Contest-shape selector (large-field GPP vs. small-field WTA) — this must be
   set explicitly by the user before any player-level optimization begins
   (Rule "contest shape first" / the meta-rule). It determines the objective
   function: p99-weighted for large-field, p75/p95 blend for small-field WTA
   (Rule #44).
9. PuLP/CBC integer optimizer, objective and constraints parameterized by the
   rules ledger (see Section 3 — rules as data).
10. Sim-overlay mode (per `DFS_Sim-Overlay_Operating_Model_PORTABLE.md`):
    if a sim portfolio + lineup pool is uploaded, treat it as the **allocation
    baseline** and do NOT let the in-house optimizer re-shape it. Only two
    things may touch it: (a) a fixed-budget coverage overlay (~7–13% of
    entries, swapped in over the sim's lowest-projection lineups), and
    (b) surgical single-slot information fixes (late scratches). Log which
    mode was used (sim-overlay vs. full in-house build) on every build — this
    matters for the sim-baseline scoring in section D below.

### D. Post-lock / scoring / post-mortem loop
11. Post-lock rescan: re-verify all rostered players are still confirmed
    starters with no batting-order changes; flag ownership drift.
12. **Sim-baseline scoring**: whenever a sim portfolio was used as the
    allocation baseline, store and score the *untouched* sim portfolio
    alongside the final (overlaid) build every slate. This is the only way to
    know whether the overlay is earning its keep (explicit requirement in the
    Operating Model doc — currently not tracked anywhere).
13. Post-mortem ingest: upload the DK contest standings/results CSV →
    auto-score all submitted lineups, decompose the winning lineup(s),
    compute field scoring distribution, and diff projected vs. actual
    ownership for every rostered player.
14. **Ownership calibration curve**: append every slate's projected-vs-actual
    ownership pairs to a persistent log (SQLite). This directly answers the
    Playbook's open item that Rule #51's multipliers rest on only two slates.
15. Structured post-mortem doc generation (matches the existing Word doc
    section structure: scoreboard vs. peers, what went right, what went
    wrong ranked by cost, new rules adopted, process notes for next slate).
    Use the `docx` skill conventions if/when this is wired to produce an
    actual .docx — for v1 an in-app structured view + markdown export is
    sufficient; only build the .docx export if Shaun asks for it explicitly.

### E. Rules ledger (the governance layer)
16. `rules` table in SQLite, seeded from Playbook v4 Section 10 (see
    `rules_seed.json` in this folder — pre-extracted for you, 53 numbered
    entries, `active` flag reflects the v4 consolidation: #1, #15, #31, #32,
    #47, and the gate-clause of #45 are folded/superseded; everything else
    active). Schema:
    ```
    id INTEGER PRIMARY KEY,        -- the rule number, e.g. 50
    text TEXT,                     -- full rule text
    rationale TEXT,                -- the evidence/example column
    rule_type TEXT,                -- 'coverage' | 'allocation' | 'gate'
    active BOOLEAN,
    folded_into INTEGER NULL,      -- e.g. rule 1 -> folded_into 50
    fired_count INTEGER DEFAULT 0,
    hit_count INTEGER DEFAULT 0,
    last_fired_slate TEXT NULL
    ```
17. Classify every rule as **coverage** (force the winning shape to exist —
    apply freely) vs. **allocation** (how much of something — presumed
    harmful per the Operating Model doc, requires justification to enable
    against a sim baseline) vs. **gate** (hard build-time constraint, e.g.
    dead-bat cap, ceiling-bat requirement, salary floor). This classification
    is in the Operating Model doc and is not yet applied to the MLB ledger —
    you'll need to tag each of the 48 active rules on ingest; a first-pass
    tagging is included in `rules_seed.json`, treat it as a draft for Shaun
    to review, not ground truth.
18. Every build run logs which rules fired and, once post-mortem results are
    in, whether firing helped — this is the hit/miss tracking the Playbook's
    Section 11 governance flag says is currently missing entirely.
19. Governance dashboard: surface the rules-to-slates ratio (currently 48
    active / ~16 studied slates — flagged as a live risk in v4), flag rules
    with 2+ misfires as RETIRE candidates, and flag any two enabled rules
    whose text contradicts (the exact failure mode that cost the 7/28
    session — Rule #45 vs #47 before the v4 consolidation).

## 3. Rules as data, not code
Do not hardcode the 48 rules as if/else logic scattered through the optimizer.
Load them from the `rules` table at build time, so Shaun can toggle/edit
thresholds (e.g. the $48,500 salary floor, the 0.45 xSLG figure, the ~500-entry
field-size cutoff) without a code change, and so hit/miss tracking has
something stable to attach to.

## 4. `validate()` — hard constraints (pulled verbatim from Playbook v4 §7)
Implement every one of these as an explicit, named check that produces a
pass/fail + human-readable reason, run on every lineup/portfolio before export:

- Player IDs resolved on the **three-part key** (name, team, is-pitcher-flag) —
  NOT name-only. (The July 28 duplicate-Jose-Fermin bug: a name-only key wrote
  a pitcher's ID into a hitter slot. It only surfaced because DK's own upload
  validation rejected a hitter-slot/pitcher-ID mismatch — a hitter-on-hitter
  collision would upload clean and silently roster the wrong player.)
- Salary floor $48,500, cap $50,000.
- Roster legality: 10 slots (2P/C/1B/2B/3B/SS/3OF), max 5 hitters from one
  team, lineup spans ≥2 games.
- Negative-correlation check: no hitter facing a rostered pitcher.
- Dead-bat cap (Rule #49): below ~1,000-entry contests, REJECT (hard fail) any
  lineup with more than one hitter projected below the dk25 floor.
- Ceiling-bat requirement (Rule #52): in small-field WTA, REJECT any lineup
  whose highest-dk95 hitter is under 25 points.
- Top-5 coverage (Rule #50): REJECT any portfolio with zero exposure to any
  team ranked top-5 by projected stack median or implied total.
- Blocked-signal adjudication (Rule #53): refuse export while any
  rescan-surfaced sub-2%-owned / xSLG≥.45 bat is unadjudicated in the
  discarded-signal log.
- Stack-side team-identity assertion (Rule #45, retained half): for each
  stack, resolve the opposing SP from the game string and assert his team ≠
  the stack's team.
- Weather-state check (Rule #48): any game in an ANNOUNCED delay at lock caps
  at 3 bats per lineup and ≤1/3 of portfolio stacks. A **delay is not a
  postponement** (Rule #11) — do not auto-pull lineups on a delay.
- Exposure caps: single-player hitter cap 50% (Rule #13), single-SP cap ~20%
  (Rule #33) — both flagged as unenforceable below ~6 lineups (n=3 granularity
  floor is 33%); surface this as an info note, not a false failure, on
  small portfolios.
- Hash-based dedup before submission (Rule #5).
- Confirmed batting order validated against the actual lineup card, never just
  the projections file's status column.

## 5. Input file schemas (from current manual process)

**DKEntries CSV** (authoritative for IDs/positions/salary — always supersedes
inference from projections): player pool table starts at row 8 (0-indexed).
Column indices: Name @ 17, Name+ID @ 16, position eligibility @ 19, salary @
20, team @ 22, game string @ 21.

**SaberSim/projections CSV** key columns: `Name`, `Pos`, `Team`, `Opp`,
`Salary`, `SS Proj`, `dk_95_percentile`, `dk_99_percentile`, `Adj Own`,
`Order`, `Status`. Filter `Status=='Confirmed'` and `Order.notna()` before any
stack analysis.

**ROO stacks file**: stack medians, ceilings, ownership — used for edge ratio
(ceiling ÷ ownership).

**Scoring percentage CSV**: matchup-driven, not mean-correlated — never
interpret as mean-correlated without independent verification.

**Pitcher split sheets** (Baseball Savant): xSLG by LHH/RHH handedness. Also
needs the three-part player-ID key described in Section 4.

**Weather** (RotoWire): most reliable single source for game-level
precipitation/wind.

**DK scoring rules**: full point table is reproduced in Playbook v4 Section 0
(also see `source_docs/Rules__DraftKings.pdf` for the DK-published original).
Roster: 2P/C/1B/2B/3B/SS/3OF, $50,000 cap, $48,500 standing floor, max 5
hitters/team, ≥2 games spanned.

## 6. What's in this folder

```
BUILD_SPEC.md                          <- this file
rules_seed.json                        <- 53-row rules ledger, pre-extracted, draft-tagged
chalk_live_detector.py                 <- working prototype, port into backend as-is
source_docs/
  MLB_GPP_Master_Playbook_v4.md        <- CURRENT ruleset — read this first
  MLB_GPP_Master_Playbook_v3.md        <- prior version, historical diff only
  DFS_Sim-Overlay_Operating_Model_PORTABLE.md  <- the 3-job model (allocation/coverage/info),
                                           coverage-vs-allocation rule classification,
                                           sim-baseline scoring rationale
  MLB_GPP_PostMortem_July26_2026.md
  MLB_GPP_PostMortem_July27_2026.md
  MLB_GPP_PostMortem_July28_2026.md    <- most recent session; dup-player-ID bug + v4 triggers
  MLB_GPP_PostMortem_June15_2026.md
  MLB_GPP_PostMortem_June16_2026_Night.md
  MLB_GPP_PostMortem_June22_2026.md
  MLB_GPP_PostMortem_June23_2026.md
  MLB_GPP_PostMortem_May27_2026.md
  MLB_GPP_WinnerPatternStudy_June21-28_2026.md
  MLB_GPP_WinnerPatternStudy_June30-July5_2026.md
  pdf_reference/
    Rules__DraftKings.pdf              <- DK's published scoring/roster rules (also reproduced in v4 §0)
    DFS_Portable_Process_Framework_md.pdf  <- the sport-agnostic framework the MLB playbook was built from
```

## 7. Explicit non-goals for v1
- No auth, no multi-user, no hosting/deployment.
- No browser storage (SQLite file on disk only).
- Don't rebuild the PuLP optimizer's core solving logic from scratch — extend
  whatever Shaun already has; ask him for the existing optimizer script if
  it's not in this folder (it wasn't in the project files at time of writing).
- Don't let any allocation rule silently override a sim's portfolio — that's
  the exact failure mode the Operating Model doc measured at −$1,370 on one
  slate. If Shaun wants an allocation rule to override the sim baseline, the
  UI should require an explicit counterfactual-backtest note before enabling it.
