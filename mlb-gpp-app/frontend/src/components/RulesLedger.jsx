import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

// Spec S2 E: the governance layer. Rules are data — toggle enabled, retag
// coverage/allocation/gate, and edit thresholds without a code change. The
// dashboard surfaces the rules-to-slates ratio, RETIRE candidates (2+ misfires),
// and enabled-rule contradictions (the 7/28 #45-vs-#47 failure mode).
const TYPE_COLORS = {
  coverage: 'bg-emerald-900 text-emerald-300',
  allocation: 'bg-amber-900 text-amber-300',
  gate: 'bg-sky-900 text-sky-300',
  process: 'bg-slate-800 text-slate-400',
}

export default function RulesLedger() {
  const [rules, setRules] = useState([])
  const [gov, setGov] = useState(null)
  const [editing, setEditing] = useState(null)

  async function load() {
    setRules((await api.rules(true)).rules)
    setGov(await api.governance())
  }
  useEffect(() => { load() }, [])

  async function toggle(r) { await api.updateRule(r.id, { enabled: !r.enabled }); load() }
  async function setType(r, t) { await api.updateRule(r.id, { rule_type: t }); load() }
  async function saveParams(id, params) {
    await api.updateRule(id, { params }); setEditing(null); load()
  }

  return (
    <div className="space-y-4">
      {gov && (
        <div className="card">
          <h2 className="font-semibold mb-3">Governance dashboard</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Metric label="Active rules" value={gov.n_active} />
            <Metric label="Enabled" value={gov.n_enabled} />
            <Metric label="Studied slates" value={gov.studied_slates} />
            <Metric label="Rules ÷ slates" value={gov.rules_to_slates_ratio}
              alert={gov.ratio_flagged} sub={gov.ratio_flagged ? 'overfit risk' : 'ok'} />
          </div>
          {gov.contradictions.length > 0 && (
            <div className="mt-3">
              <div className="text-xs uppercase tracking-wide text-rose-400 mb-1">
                Contradictions among enabled rules</div>
              {gov.contradictions.map((c, i) => (
                <div key={i} className="text-sm text-rose-300">⚠ {c.note}</div>
              ))}
            </div>
          )}
          {gov.retire_candidates.length > 0 && (
            <div className="mt-3">
              <div className="text-xs uppercase tracking-wide text-amber-400 mb-1">
                RETIRE candidates (2+ misfires)</div>
              {gov.retire_candidates.map((c) => (
                <div key={c.id} className="text-sm text-amber-300">#{c.id} — {c.miss_count} misfires</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="card">
        <h2 className="font-semibold mb-3">Rules ledger ({rules.length})</h2>
        <div className="space-y-1 max-h-[70vh] overflow-auto">
          {rules.map((r) => (
            <div key={r.id} className={`border border-slate-800 rounded-lg p-2 ${!r.active ? 'opacity-50' : ''}`}>
              <div className="flex items-start gap-2">
                <span className="font-mono text-sm text-slate-400 w-8">#{r.id}</span>
                <div className="flex-1">
                  <div className="text-sm">{r.text}</div>
                  {r.rationale && <div className="text-xs text-slate-500 mt-0.5">{r.rationale}</div>}
                  {Object.keys(r.params || {}).length > 0 && (
                    <div className="text-xs mt-1">
                      {editing === r.id
                        ? <ParamEditor params={r.params} onSave={(p) => saveParams(r.id, p)} onCancel={() => setEditing(null)} />
                        : <button className="text-sky-400 hover:underline"
                            onClick={() => setEditing(r.id)}>
                            {Object.entries(r.params).map(([k, v]) => `${k}=${v}`).join(' · ')} ✎
                          </button>}
                    </div>
                  )}
                  {r.folded_into && <div className="text-xs text-slate-600">folded → #{r.folded_into}</div>}
                </div>
                <div className="flex flex-col items-end gap-1">
                  <select value={r.rule_type || ''} onChange={(e) => setType(r, e.target.value)}
                    className={`text-xs rounded px-1.5 py-0.5 ${TYPE_COLORS[r.rule_type] || 'bg-slate-800'}`}>
                    {['coverage', 'allocation', 'gate', 'process'].map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                  {r.active && (
                    <button onClick={() => toggle(r)}
                      className={r.enabled ? 'pill-pass' : 'pill-info'}>
                      {r.enabled ? 'enabled' : 'disabled'}
                    </button>
                  )}
                  {(r.fired_count > 0 || r.miss_count > 0) && (
                    <span className="text-xs text-slate-500">{r.hit_count}✓ / {r.miss_count}✗ · {r.fired_count} fired</span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, sub, alert }) {
  return (
    <div className={`rounded-lg p-3 border ${alert ? 'border-rose-800 bg-rose-950/30' : 'border-slate-800 bg-slate-950'}`}>
      <div className={`text-2xl font-bold ${alert ? 'text-rose-400' : ''}`}>{value ?? '—'}</div>
      <div className="text-xs text-slate-500">{label}{sub ? ` · ${sub}` : ''}</div>
    </div>
  )
}

function ParamEditor({ params, onSave, onCancel }) {
  const [txt, setTxt] = useState(JSON.stringify(params, null, 0))
  const [err, setErr] = useState(null)
  return (
    <div className="flex items-center gap-2">
      <input value={txt} onChange={(e) => setTxt(e.target.value)}
        className="flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1 font-mono text-xs" />
      <button className="btn-primary" onClick={() => {
        try { onSave(JSON.parse(txt)) } catch (e) { setErr(e.message) }
      }}>save</button>
      <button className="btn-ghost" onClick={onCancel}>cancel</button>
      {err && <span className="text-rose-400 text-xs">{err}</span>}
    </div>
  )
}
