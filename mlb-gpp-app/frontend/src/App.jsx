import React, { useEffect, useState } from 'react'
import { api } from './lib/api.js'
import Ingest from './components/Ingest.jsx'
import ChalkPanel from './components/ChalkPanel.jsx'
import BuildPanel from './components/BuildPanel.jsx'
import SimOverlay from './components/SimOverlay.jsx'
import DiscardedSignals from './components/DiscardedSignals.jsx'
import RulesLedger from './components/RulesLedger.jsx'
import PostMortem from './components/PostMortem.jsx'

// Tabs mirror the spec's five subsystems (A ingest -> B gates -> C build ->
// D post-mortem -> E rules ledger). Slate context is lifted here and shared.
const TABS = [
  { id: 'ingest', label: '1 · Ingest & Validate' },
  { id: 'gates', label: '2 · Gate Analysis' },
  { id: 'build', label: '3 · Build & Export' },
  { id: 'simoverlay', label: '3b · Sim Overlay' },
  { id: 'postmortem', label: '4 · Post-Mortem' },
  { id: 'rules', label: '5 · Rules Ledger' },
]

export default function App() {
  const [tab, setTab] = useState('ingest')
  const [health, setHealth] = useState(null)
  const [slate, setSlate] = useState({
    slate_id: null, slate_date: new Date().toISOString().slice(0, 10),
    contest_shape: '', field_size: '', entry_fee: '',
  })
  const [pool, setPool] = useState(null)        // reconciled players + diagnostics
  const [chalk, setChalk] = useState(null)
  const [build, setBuild] = useState(null)

  useEffect(() => { api.health().then(setHealth).catch(() => setHealth({ status: 'down' })) }, [])

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/60 sticky top-0 z-10 backdrop-blur">
        <div className="max-w-6xl mx-auto px-5 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold tracking-tight">MLB GPP Build App</h1>
            <p className="text-xs text-slate-500">Rules-driven DraftKings GPP builder · localhost v1 · shaunsmithttu</p>
          </div>
          <span className={`pill-${health?.status === 'ok' ? 'pass' : 'fail'}`}>
            backend {health?.status || '…'}
          </span>
        </div>
        <nav className="max-w-6xl mx-auto px-5 flex gap-1 overflow-x-auto">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-sm border-b-2 whitespace-nowrap ${
                tab === t.id ? 'border-emerald-500 text-emerald-400'
                             : 'border-transparent text-slate-400 hover:text-slate-200'}`}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <SlateBar slate={slate} setSlate={setSlate} />

      <main className="max-w-6xl mx-auto px-5 py-6">
        {tab === 'ingest' && <Ingest slate={slate} pool={pool} setPool={setPool} />}
        {tab === 'gates' && <ChalkPanel pool={pool} slate={slate} chalk={chalk} setChalk={setChalk} />}
        {tab === 'build' && (
          <BuildPanel pool={pool} slate={slate} chalk={chalk} build={build} setBuild={setBuild} />
        )}
        {tab === 'simoverlay' && <SimOverlay pool={pool} slate={slate} />}
        {tab === 'postmortem' && <PostMortem slate={slate} build={build} />}
        {tab === 'rules' && <RulesLedger />}
      </main>
    </div>
  )
}

function SlateBar({ slate, setSlate }) {
  const set = (k) => (e) => setSlate({ ...slate, [k]: e.target.value })
  async function saveSlate() {
    const created = await api.createSlate({
      slate_date: slate.slate_date, contest_shape: slate.contest_shape || null,
      field_size: slate.field_size ? Number(slate.field_size) : null,
      entry_fee: slate.entry_fee ? Number(slate.entry_fee) : null,
    })
    setSlate({ ...slate, slate_id: created.id })
  }
  return (
    <div className="border-b border-slate-800 bg-slate-950">
      <div className="max-w-6xl mx-auto px-5 py-2 flex flex-wrap items-end gap-3 text-sm">
        <Field label="Slate date"><input type="date" value={slate.slate_date} onChange={set('slate_date')}
          className="bg-slate-900 border border-slate-700 rounded px-2 py-1" /></Field>
        <Field label="Contest shape (set FIRST — meta-rule)">
          <select value={slate.contest_shape} onChange={set('contest_shape')}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1">
            <option value="">— choose —</option>
            <option value="large_field_gpp">Large-field GPP (p99)</option>
            <option value="small_field_wta">Small-field WTA (p75/p95)</option>
          </select>
        </Field>
        <Field label="Field size"><input type="number" value={slate.field_size} onChange={set('field_size')}
          placeholder="e.g. 5000" className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-24" /></Field>
        <Field label="Entry fee $"><input type="number" value={slate.entry_fee} onChange={set('entry_fee')}
          placeholder="e.g. 100" className="bg-slate-900 border border-slate-700 rounded px-2 py-1 w-24" /></Field>
        <button className="btn-ghost" onClick={saveSlate}>
          {slate.slate_id ? `Slate #${slate.slate_id} saved` : 'Save slate'}
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  )
}
