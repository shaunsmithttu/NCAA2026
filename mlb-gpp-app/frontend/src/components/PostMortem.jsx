import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

// Spec S2 D: upload DK standings -> field distribution + winner + actual
// ownership. The ownership calibration curve (S2 #14) is the persistent answer
// to the Playbook's open item that Rule #51 rests on only two slates.
export default function PostMortem({ slate }) {
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [cal, setCal] = useState(null)
  const [err, setErr] = useState(null)
  const [builds, setBuilds] = useState([])
  const [buildId, setBuildId] = useState('')
  const [actualsFile, setActualsFile] = useState(null)
  const [sbScore, setSbScore] = useState(null)
  const [sbErr, setSbErr] = useState(null)

  async function load() {
    setCal(await api.calibration())
    try { setBuilds((await api.builds()).builds) } catch { /* ignore */ }
  }
  useEffect(() => { load() }, [])

  async function scoreSimBaseline() {
    setSbErr(null)
    try {
      const { actuals } = await api.parseActuals(actualsFile)
      setSbScore(await api.simBaselineScore(Number(buildId), actuals))
    } catch (e) { setSbErr(e.message) }
  }

  async function run() {
    setErr(null)
    try { setResult(await api.standings(file)) }
    catch (e) { setErr(e.message) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <h2 className="font-semibold">Post-mortem ingest</h2>
        <p className="text-sm text-slate-400">
          Upload the DK contest standings/results CSV to auto-score the field, decompose the winning
          lineup, and read the scoring distribution.
        </p>
        <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files[0])}
          className="block w-full text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3
                     file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
        <button className="btn-primary" disabled={!file} onClick={run}>Ingest standings</button>
        {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
      </div>

      {result && (
        <div className="card space-y-3">
          <h2 className="font-semibold">Field distribution</h2>
          {result.distribution?.n_entries ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {Object.entries(result.distribution).map(([k, v]) => (
                <div key={k} className="bg-slate-950 rounded-lg p-3 border border-slate-800">
                  <div className="text-xl font-bold">{v}</div>
                  <div className="text-xs text-slate-500">{k}</div>
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-slate-500">No Points column parsed — check the standings CSV.</p>}
          {result.winning_lineups?.filter(Boolean).length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wide text-emerald-400 mb-1">Winning lineup</div>
              <div className="text-sm font-mono text-slate-300">{result.winning_lineups[0]}</div>
            </div>
          )}
          <div className="text-xs text-slate-500">
            {Object.keys(result.actual_ownership || {}).length} players with actual %Drafted parsed.
          </div>
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">Sim-baseline scoring (#12)</h2>
        <p className="text-sm text-slate-400">
          Score the final build beside the <b>untouched sim baseline</b> stored with it — the only way to
          know whether the coverage overlay earned its keep. Pick a sim-overlay build and upload a player
          actuals CSV (Name + Points).
        </p>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-slate-500">Build</span>
            <select value={buildId} onChange={(e) => setBuildId(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm">
              <option value="">— choose —</option>
              {builds.map((b) => (
                <option key={b.id} value={b.id}>
                  #{b.id} · {b.mode} · {b.contest_shape} · {b.n_lineups}LU · {b.created_at}
                </option>
              ))}
            </select>
          </label>
          <input type="file" accept=".csv" onChange={(e) => setActualsFile(e.target.files[0])}
            className="text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
          <button className="btn-primary" disabled={!buildId || !actualsFile} onClick={scoreSimBaseline}>Score</button>
        </div>
        {sbErr && <p className="pill-fail block whitespace-pre-wrap">{sbErr}</p>}
        {sbScore && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Metric label="Final mean" value={sbScore.final?.mean} />
            <Metric label="Baseline mean" value={sbScore.sim_baseline?.mean ?? '—'} />
            <Metric label="Overlay Δ" value={sbScore.overlay_mean_delta ?? '—'}
              good={sbScore.overlay_mean_delta > 0} bad={sbScore.overlay_mean_delta < 0} />
            <div className="bg-slate-950 rounded-lg p-3 border border-slate-800">
              <div className={`text-sm font-bold ${sbScore.overlay_earned_keep ? 'text-emerald-400' : 'text-amber-400'}`}>
                {sbScore.has_baseline ? (sbScore.overlay_earned_keep ? 'Overlay earned keep' : 'Overlay did NOT earn keep') : 'No baseline (in-house build)'}
              </div>
              <div className="text-xs text-slate-500">final best {sbScore.final?.best}</div>
            </div>
          </div>
        )}
      </div>

      <div className="card space-y-3">
        <h2 className="font-semibold">Ownership calibration curve</h2>
        <p className="text-sm text-slate-400">
          Projected-vs-actual ownership ratios, bucketed by projected band, across every logged slate.
          This is what turns Rule #51's provisional multipliers into a calibrated curve.
        </p>
        {cal && (
          <table className="w-full text-sm">
            <thead className="text-slate-500 text-left">
              <tr><th>Projected band</th><th>n pairs</th><th>mean actual÷proj</th></tr>
            </thead>
            <tbody>
              {Object.entries(cal.curve).map(([band, v]) => (
                <tr key={band} className="border-t border-slate-800">
                  <td className="font-mono">{band}%</td>
                  <td>{v.n}</td>
                  <td className={v.mean_ratio > 1 ? 'text-emerald-400' : v.mean_ratio < 1 ? 'text-amber-400' : ''}>
                    {v.mean_ratio ?? '—'}{v.mean_ratio ? '×' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-slate-600">
          {cal?.n_pairs || 0} total calibration pairs logged. Append pairs via the post-mortem flow to grow the curve.
        </p>
      </div>
    </div>
  )
}

function Metric({ label, value, good, bad }) {
  return (
    <div className="bg-slate-950 rounded-lg p-3 border border-slate-800">
      <div className={`text-2xl font-bold ${good ? 'text-emerald-400' : bad ? 'text-rose-400' : ''}`}>{value ?? '—'}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  )
}
