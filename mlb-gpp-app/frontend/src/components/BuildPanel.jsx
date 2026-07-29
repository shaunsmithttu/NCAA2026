import React, { useState } from 'react'
import { api } from '../lib/api.js'
import ValidationReport from './ValidationReport.jsx'
import DiscardedSignals from './DiscardedSignals.jsx'

// Spec S2 C: contest shape must be set first; the optimizer objective follows
// from it (p99 vs p75/p95). Export is hard-gated on validate() + Rule #53.
export default function BuildPanel({ pool, slate, chalk, build, setBuild }) {
  const [n, setN] = useState(20)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [nUnadj, setNUnadj] = useState(0)
  const [exportErr, setExportErr] = useState(null)

  const ready = pool && slate.contest_shape
  const shapeSet = !!slate.contest_shape

  async function run() {
    setBusy(true); setErr(null)
    try {
      const res = await api.build({
        players: pool.players,
        contest_shape: slate.contest_shape,
        n_lineups: Number(n),
        field_size: slate.field_size ? Number(slate.field_size) : null,
        entry_fee: slate.entry_fee ? Number(slate.entry_fee) : null,
        slate_id: slate.slate_id,
        chalk: chalk || null,
      })
      setBuild(res)
      setNUnadj(res.unadjudicated_blocked_signals || 0)
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  async function doExport() {
    setExportErr(null)
    try {
      const csv = await api.exportCsv(build.lineups, {
        contest_shape: slate.contest_shape,
        field_size: slate.field_size ? Number(slate.field_size) : null,
        slate_id: slate.slate_id,
      }, slate.slate_id)
      const blob = new Blob([csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'dk_upload.csv'; a.click()
      URL.revokeObjectURL(url)
    } catch (e) { setExportErr(e.message) }
  }

  return (
    <div className="space-y-4">
      {!shapeSet && (
        <div className="card border-amber-800 bg-amber-950/30">
          <p className="text-sm text-amber-300">
            Set the <b>contest shape</b> in the slate bar first — it's the meta-rule and it selects the
            optimizer objective (p99-weighted for large-field GPP, p75/p95 blend for small-field WTA).
          </p>
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">Build portfolio</h2>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-slate-500"># lineups</span>
            <input type="number" value={n} min={1} onChange={(e) => setN(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 w-24" />
          </label>
          <div className="text-sm text-slate-400">
            Objective: <b>{slate.contest_shape === 'small_field_wta' ? 'p75/p95 blend' :
              slate.contest_shape === 'large_field_gpp' ? 'p99-weighted' : '—'}</b>
            {slate.field_size && slate.entry_fee &&
              <span> · ownership transform auto-applied ({Number(slate.field_size) >= 500 ? '#42' : '#51'})</span>}
          </div>
          <button className="btn-primary" disabled={!ready || busy} onClick={run}>
            {busy ? 'Solving…' : 'Build'}
          </button>
        </div>
        {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
      </div>

      {build && (
        <>
          <div className="card space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Portfolio · {build.n_built}/{build.n_requested} lineups</h2>
              <span className="text-xs text-slate-500">build #{build.build_id} · {build.objective}</span>
            </div>
            <div className="text-xs text-slate-400">
              Fired rules: {Object.keys(build.fired_rules).map(r => `#${r}`).join(', ') || 'none'}
            </div>
            <div className="max-h-96 overflow-auto">
              {build.lineups.map((lu, i) => <LineupRow key={i} lu={lu} idx={i} />)}
            </div>
          </div>

          <DiscardedSignals slateId={slate.slate_id} onChange={setNUnadj} />

          <ValidationReport report={build.validation} />

          <div className="card flex items-center justify-between">
            <div className="text-sm text-slate-400">
              Export is hard-gated: all validate() failures clear AND zero unadjudicated Rule #53 signals.
            </div>
            <button className="btn-primary"
              disabled={!build.validation?.export_allowed || nUnadj > 0}
              onClick={doExport}>
              Export DK CSV
            </button>
          </div>
          {exportErr && <p className="pill-fail block whitespace-pre-wrap">{exportErr}</p>}
        </>
      )}
    </div>
  )
}

function LineupRow({ lu, idx }) {
  const sal = lu.reduce((a, p) => a + (p.salary || 0), 0)
  return (
    <div className="border-t border-slate-800 py-1.5 text-xs">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-slate-500 w-8">#{idx + 1}</span>
        {lu.map((p, i) => (
          <span key={i} className="font-mono">
            <span className="text-slate-500">{p.slot}</span> {p.name}
            <span className="text-slate-600">·{p.team}</span>
          </span>
        ))}
        <span className={`ml-auto ${sal > 50000 || sal < 48500 ? 'text-rose-400' : 'text-slate-500'}`}>${sal}</span>
      </div>
    </div>
  )
}
