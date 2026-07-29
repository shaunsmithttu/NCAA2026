import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

// Rule #46/#53 HARD BLOCK: any surfaced sub-2% / xSLG≥.45 bat must be
// adjudicated in writing (keep/drop + reason) before the build can export.
export default function DiscardedSignals({ slateId, onChange }) {
  const [signals, setSignals] = useState([])
  const [nUnadj, setNUnadj] = useState(0)
  const [drafts, setDrafts] = useState({})

  async function load() {
    const r = await api.signals(slateId, false)
    setSignals(r.signals); setNUnadj(r.n_unadjudicated)
    onChange?.(r.n_unadjudicated)
  }
  useEffect(() => { load() }, [slateId])

  async function submit(id) {
    const d = drafts[id] || {}
    if (!d.decision || !d.reason?.trim()) return
    await api.adjudicate(id, d.decision, d.reason)
    await load()
  }

  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Discarded-Signal Log (Rule #53)</h2>
        <span className={nUnadj > 0 ? 'pill-fail' : 'pill-pass'}>
          {nUnadj > 0 ? `${nUnadj} UNADJUDICATED — export blocked` : 'all adjudicated'}
        </span>
      </div>
      <p className="text-sm text-slate-400">
        Every confirmed sub-2%-owned bat with xSLG ≥ .45 that a rule blocked must be adjudicated in
        writing before export. Four consecutive slates were lost to this being skipped.
      </p>
      {signals.length === 0 && <p className="text-sm text-slate-500">No signals surfaced for this slate.</p>}
      {signals.map((s) => (
        <div key={s.id} className="bg-slate-950 border border-slate-800 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">{s.player_name} <span className="text-slate-500">({s.team})</span></span>
            <span className="text-xs text-slate-400">own {s.proj_own}% · xSLG {s.xslg}
              {s.blocked_by_rule ? ` · blocked by #${s.blocked_by_rule}` : ''}</span>
          </div>
          {s.adjudication ? (
            <div className="text-sm">
              <span className={s.adjudication === 'keep' ? 'pill-pass' : 'pill-info'}>{s.adjudication}</span>
              <span className="text-slate-400 ml-2">{s.reason}</span>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <select className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
                value={drafts[s.id]?.decision || ''}
                onChange={(e) => setDrafts({ ...drafts, [s.id]: { ...drafts[s.id], decision: e.target.value } })}>
                <option value="">decide…</option>
                <option value="keep">keep</option>
                <option value="drop">drop</option>
              </select>
              <input placeholder="written reason (required)" className="flex-1 min-w-40 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm"
                value={drafts[s.id]?.reason || ''}
                onChange={(e) => setDrafts({ ...drafts, [s.id]: { ...drafts[s.id], reason: e.target.value } })} />
              <button className="btn-primary" onClick={() => submit(s.id)}>Adjudicate</button>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
