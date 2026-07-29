import React, { useState } from 'react'
import { api } from '../lib/api.js'

// Spec S2 A: upload DKEntries (authoritative for IDs/pos/salary) + projections,
// reconcile via the three-part key, and surface reconciliation diagnostics.
export default function Ingest({ pool, setPool }) {
  const [dk, setDk] = useState(null)
  const [proj, setProj] = useState(null)
  const [ssOnly, setSsOnly] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function run() {
    setBusy(true); setErr(null)
    try { setPool(await api.ingest(dk, proj)) }
    catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  async function runSsOnly() {
    setBusy(true); setErr(null)
    try {
      const p = await api.poolFromProjections(ssOnly)
      // normalize to the reconciliation shape the rest of the UI expects
      setPool({ ...p, n_dk: p.n_players, n_projections: p.n_players, n_matched: p.n_players,
                unmatched_dk: [], projection_key_collisions: [] })
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <h2 className="font-semibold">Upload & reconcile</h2>
        <p className="text-sm text-slate-400">
          DKEntries CSV is authoritative for player IDs, positions, salary, team, and game string —
          projections never override these (spec §2.3). Players are keyed on the three-part key
          (name, team, is-pitcher) to prevent name-only collisions (the 7/28 Jose-Fermin bug).
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <FileInput label="DKEntries CSV" onChange={setDk} file={dk} />
          <FileInput label="Projections CSV (SaberSim)" onChange={setProj} file={proj} />
        </div>
        <button className="btn-primary" disabled={!dk || !proj || busy} onClick={run}>
          {busy ? 'Reconciling…' : 'Ingest & reconcile'}
        </button>
        {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold">…or build from SaberSim only</h2>
        <p className="text-sm text-slate-400">
          No DKEntries on hand? The SaberSim export carries a <b>DFS ID</b> (the DraftKings player ID) plus
          combined eligibility, salary, and all percentiles — enough to build and export a real DK CSV.
          DKEntries remains the authoritative ID source (spec §2.3); verify before high-stakes submission.
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <FileInput label="SaberSim projections CSV" onChange={setSsOnly} file={ssOnly} />
          <button className="btn-primary self-end" disabled={!ssOnly || busy} onClick={runSsOnly}>
            {busy ? 'Building…' : 'Build pool from SaberSim'}
          </button>
        </div>
      </div>

      {pool && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Reconciliation</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <Stat label="DK players" value={pool.n_dk} />
            <Stat label="Projections" value={pool.n_projections} />
            <Stat label="Matched" value={pool.n_matched} good />
            <Stat label="Confirmed hitters" value={pool.confirmed_hitters?.length} />
          </div>
          <Diag title="Unmatched DK players (no projection)" items={pool.unmatched_dk}
            render={(x) => `${x.name} (${x.team}${x.is_pitcher ? ', P' : ''})`} />
          <Diag title="Projection key collisions (three-part key needed)"
            items={pool.projection_key_collisions} sev="warn"
            render={(x) => `${x.name} (${x.team})`} />
          <details>
            <summary className="text-sm text-slate-400 cursor-pointer">
              Player pool ({pool.players.length})
            </summary>
            <div className="mt-2 max-h-80 overflow-auto text-xs">
              <table className="w-full">
                <thead className="text-slate-500 text-left sticky top-0 bg-slate-900">
                  <tr><th>Name</th><th>Pos</th><th>Team</th><th>Sal</th><th>Proj</th>
                    <th>dk95</th><th>Own%</th><th>Ord</th></tr>
                </thead>
                <tbody className="font-mono">
                  {pool.players.map((p, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td>{p.name}</td><td>{(p.positions || []).join('/')}</td><td>{p.team}</td>
                      <td>{p.salary}</td><td>{p.proj}</td><td>{p.dk95 ?? '—'}</td>
                      <td>{p.adj_own ?? '—'}</td><td>{p.order ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

function FileInput({ label, onChange, file }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <input type="file" accept=".csv" onChange={(e) => onChange(e.target.files[0])}
        className="mt-1 block w-full text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3
                   file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
      {file && <span className="text-xs text-emerald-400">{file.name}</span>}
    </label>
  )
}

function Stat({ label, value, good }) {
  return (
    <div className="bg-slate-950 rounded-lg p-3 border border-slate-800">
      <div className={`text-2xl font-bold ${good ? 'text-emerald-400' : ''}`}>{value ?? '—'}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  )
}

function Diag({ title, items, render, sev = 'info' }) {
  if (!items?.length) return null
  return (
    <div>
      <div className={`text-xs uppercase tracking-wide ${sev === 'warn' ? 'text-amber-400' : 'text-slate-500'}`}>
        {title} ({items.length})
      </div>
      <div className="text-xs text-slate-400 max-h-24 overflow-auto mt-1">
        {items.slice(0, 50).map((x, i) => <span key={i} className="mr-2">{render(x)}</span>)}
      </div>
    </div>
  )
}
