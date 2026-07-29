import React, { useState } from 'react'
import { api } from '../lib/api.js'
import ValidationReport from './ValidationReport.jsx'
import DiscardedSignals from './DiscardedSignals.jsx'

// Spec S2 #10/#12 (Sim-Overlay Operating Model): the uploaded sim portfolio is
// the ALLOCATION BASELINE. The in-house optimizer must NOT re-shape it. Only a
// fixed-budget coverage overlay (7-13% of entries, swapped over the sim's
// lowest-projection lineups) + surgical info fixes may touch it. The untouched
// sim baseline is always stored for side-by-side scoring.
export default function SimOverlay({ pool, slate }) {
  const [simFile, setSimFile] = useState(null)
  const [covFile, setCovFile] = useState(null)
  const [sim, setSim] = useState(null)          // parsed baseline lineups
  const [coverage, setCoverage] = useState(null) // parsed/generated coverage lineups
  const [pct, setPct] = useState(10)
  const [covSource, setCovSource] = useState('generate')
  const [result, setResult] = useState(null)
  const [nUnadj, setNUnadj] = useState(0)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const needPool = !pool
  const k = sim ? Math.max(1, Math.round(sim.n_lineups * pct / 100)) : 0
  const pctOutOfBand = pct < 7 || pct > 13

  async function parseSim() {
    setErr(null)
    try {
      const text = await simFile.text()
      setSim(await api.parseLineups(text, pool.players))
    } catch (e) { setErr(e.message) }
  }

  async function prepareCoverage() {
    setErr(null); setBusy(true)
    try {
      if (covSource === 'upload') {
        const text = await covFile.text()
        const parsed = await api.parseLineups(text, pool.players)
        setCoverage(parsed.lineups)
      } else {
        // generate coverage via the in-house optimizer (k lineups) — these fill
        // coverage gaps (#50 etc.) and are swapped over the sim's weakest lineups.
        const b = await api.build({
          players: pool.players, contest_shape: slate.contest_shape || 'large_field_gpp',
          n_lineups: k, field_size: slate.field_size ? Number(slate.field_size) : null,
          entry_fee: slate.entry_fee ? Number(slate.entry_fee) : null,
        })
        setCoverage(b.lineups)
      }
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  async function runOverlay() {
    setErr(null); setBusy(true)
    try {
      const res = await api.buildSimOverlay({
        sim_portfolio: sim.lineups,
        coverage_lineups: coverage || [],
        coverage_pct: Number(pct),
        contest_shape: slate.contest_shape || 'large_field_gpp',
        field_size: slate.field_size ? Number(slate.field_size) : null,
        slate_id: slate.slate_id,
      })
      setResult(res)
      setNUnadj(res.unadjudicated_blocked_signals || 0)
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  async function doExport() {
    try {
      const csv = await api.exportCsv(result.final_portfolio, {
        contest_shape: slate.contest_shape, field_size: slate.field_size ? Number(slate.field_size) : null,
        slate_id: slate.slate_id,
      }, slate.slate_id)
      const blob = new Blob([csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'dk_upload_sim_overlay.csv'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setErr(e.message) }
  }

  const swapped = new Set((result?.swap_log || []).map(s => s.replaced_sim_lineup_index))

  return (
    <div className="space-y-4">
      <div className="card border-sky-900 bg-sky-950/20">
        <p className="text-sm text-sky-200">
          <b>Operating model:</b> the sim portfolio is the allocation baseline. The in-house optimizer
          <b> does not re-shape it</b> — only a fixed-budget coverage overlay (7–13%) swaps in over the
          sim's lowest-projection lineups, plus surgical late-scratch fixes. The untouched baseline is
          stored for side-by-side scoring (the only way to know if the overlay earns its keep).
        </p>
      </div>

      {needPool && (
        <div className="card border-amber-800 bg-amber-950/30">
          <p className="text-sm text-amber-300">Ingest the player pool first (tab 1) — sim lineups are
            mapped back onto the reconciled pool by DK id / name.</p>
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">1 · Upload sim portfolio (final)</h2>
        <p className="text-sm text-slate-400">DK-upload or sim export CSV — one lineup per row of
          "Name (ID)" cells. Cells are resolved by DK id, then by name.</p>
        <div className="flex items-center gap-3 flex-wrap">
          <input type="file" accept=".csv" disabled={needPool} onChange={(e) => setSimFile(e.target.files[0])}
            className="text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
          <button className="btn-primary" disabled={!simFile || needPool} onClick={parseSim}>Parse baseline</button>
        </div>
        {sim && (
          <div className="text-sm text-slate-300">
            Parsed <b>{sim.n_lineups}</b> baseline lineups.
            {sim.unresolved.length > 0 &&
              <span className="text-amber-400"> ⚠ {sim.unresolved.length} unresolved cell(s): {sim.unresolved.slice(0, 8).join(', ')}</span>}
          </div>
        )}
      </div>

      {sim && (
        <div className="card space-y-3">
          <h2 className="font-semibold">2 · Coverage overlay (fixed budget)</h2>
          <div className="flex items-end gap-4 flex-wrap">
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-slate-500">Coverage %</span>
              <input type="number" value={pct} onChange={(e) => setPct(e.target.value)}
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1 w-24" />
            </label>
            <div className="text-sm text-slate-400">
              = <b>{k}</b> of {sim.n_lineups} entries swapped
              {pctOutOfBand && <span className="text-amber-400"> · outside the 7–13% band</span>}
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-wide text-slate-500">Coverage source</span>
              <select value={covSource} onChange={(e) => setCovSource(e.target.value)}
                className="bg-slate-950 border border-slate-700 rounded px-2 py-1">
                <option value="generate">Generate (in-house optimizer)</option>
                <option value="upload">Upload CSV</option>
              </select>
            </label>
            {covSource === 'upload' && (
              <input type="file" accept=".csv" onChange={(e) => setCovFile(e.target.files[0])}
                className="text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
            )}
            <button className="btn-ghost" disabled={busy || (covSource === 'upload' && !covFile)} onClick={prepareCoverage}>
              {busy ? 'Preparing…' : 'Prepare coverage'}
            </button>
          </div>
          {coverage && <div className="text-sm text-emerald-400">{coverage.length} coverage lineups ready.</div>}
          <button className="btn-primary" disabled={busy} onClick={runOverlay}>Run overlay & validate</button>
          {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
        </div>
      )}

      {result && (
        <>
          <div className="card space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Final portfolio · {result.n_entries} entries</h2>
              <span className="text-xs text-slate-500">build #{result.build_id} · mode {result.mode} ·
                {result.n_coverage_swapped} swapped ({result.coverage_pct}%)</span>
            </div>
            {result.warning && <p className="pill-warn block">{result.warning}</p>}
            <p className="text-xs text-slate-500">
              Rows tinted sky are coverage swaps; the rest are the untouched sim baseline (stored separately for scoring).
            </p>
            <div className="max-h-96 overflow-auto">
              {result.final_portfolio.map((lu, i) => (
                <div key={i} className={`border-t border-slate-800 py-1.5 text-xs ${swapped.has(i) ? 'bg-sky-950/40' : ''}`}>
                  <span className="text-slate-500 w-8 inline-block">#{i + 1}</span>
                  {swapped.has(i) && <span className="pill-info mr-1">coverage</span>}
                  {lu.map((p, j) => (
                    <span key={j} className="font-mono mr-2">
                      <span className="text-slate-500">{p.slot}</span> {p.name}<span className="text-slate-600">·{p.team}</span>
                    </span>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <InfoFixPanel pool={pool} slate={slate} result={result} setResult={setResult} />

          <DiscardedSignals slateId={slate.slate_id} onChange={setNUnadj} />
          <ValidationReport report={result.validation} />

          <div className="card flex items-center justify-between">
            <div className="text-sm text-slate-400">
              Sim baseline stored with the build — score it beside the final in the Post-Mortem tab once actuals land.
            </div>
            <button className="btn-primary"
              disabled={!result.validation?.export_allowed || nUnadj > 0} onClick={doExport}>
              Export DK CSV
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// Surgical late-scratch fixes (spec S2 #10b): swap a single rostered player for
// a same-slot replacement from the pool. Nothing else in the lineup moves. The
// fixed portfolio is re-validated in place.
function InfoFixPanel({ pool, slate, result, setResult }) {
  const [lineupIdx, setLineupIdx] = useState(0)
  const [outKey, setOutKey] = useState('')
  const [inKey, setInKey] = useState('')
  const [err, setErr] = useState(null)

  const lu = result.final_portfolio[lineupIdx] || []
  const outPlayer = lu.find((p) => JSON.stringify(p.key) === outKey)
  const inLineup = new Set(lu.map((p) => JSON.stringify(p.key)))
  const candidates = !outPlayer ? [] : (pool?.players || []).filter((p) =>
    p.is_pitcher === outPlayer.is_pitcher
    && !inLineup.has(JSON.stringify(p.key))
    && (outPlayer.slot === 'P' ? p.is_pitcher
        : (p.positions || []).map((x) => x.toUpperCase()).includes(outPlayer.slot)))

  async function apply() {
    setErr(null)
    try {
      const repl = candidates.find((p) => JSON.stringify(p.key) === inKey)
      const fixed = await api.infoFix(result.final_portfolio,
        [{ out_key: outPlayer.key, replacement: { ...repl, slot: outPlayer.slot } }],
        { contest_shape: slate.contest_shape, field_size: slate.field_size ? Number(slate.field_size) : null, slate_id: slate.slate_id })
      setResult({ ...result, final_portfolio: fixed.portfolio, validation: fixed.validation })
      setOutKey(''); setInKey('')
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="card space-y-3">
      <h2 className="font-semibold">Late-scratch info fix (#10b)</h2>
      <p className="text-sm text-slate-400">
        A late scratch swaps a single slot — the rest of the sim allocation is untouched. Pick the scratched
        player and a same-position replacement; the portfolio re-validates immediately.
      </p>
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-slate-500">Lineup</span>
          <select value={lineupIdx} onChange={(e) => { setLineupIdx(Number(e.target.value)); setOutKey('') }}
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm">
            {result.final_portfolio.map((_, i) => <option key={i} value={i}>#{i + 1}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-slate-500">Scratch (out)</span>
          <select value={outKey} onChange={(e) => { setOutKey(e.target.value); setInKey('') }}
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm">
            <option value="">— player —</option>
            {lu.map((p, i) => <option key={i} value={JSON.stringify(p.key)}>{p.slot} {p.name} ({p.team})</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase tracking-wide text-slate-500">Replacement (in)</span>
          <select value={inKey} onChange={(e) => setInKey(e.target.value)} disabled={!outPlayer}
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm min-w-48">
            <option value="">{outPlayer ? `— ${candidates.length} eligible —` : 'pick scratch first'}</option>
            {candidates.map((p, i) => <option key={i} value={JSON.stringify(p.key)}>{p.name} ({p.team}) ${p.salary}</option>)}
          </select>
        </label>
        <button className="btn-primary" disabled={!outKey || !inKey} onClick={apply}>Apply fix</button>
      </div>
      {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
    </div>
  )
}
