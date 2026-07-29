import React, { useState } from 'react'
import { api } from '../lib/api.js'

// Spec S2 B #4: run the chalk-live detector BEFORE the optimizer. Pitcher/stack
// rows can be auto-derived from the reconciled pool, then hand-corrected with
// xSLG (pitcher splits) and Vegas totals/moneylines before analysis.
export default function ChalkPanel({ pool, chalk, setChalk }) {
  const [pitchers, setPitchers] = useState('[]')
  const [stacks, setStacks] = useState('[]')
  const [totals, setTotals] = useState('')
  const [moneylines, setMoneylines] = useState('')
  const [err, setErr] = useState(null)

  function derive() {
    if (!pool) return
    const p = pool.players.filter(x => x.is_pitcher).map(x => ({
      name: x.name, team: x.team, salary: x.salary, proj_own: x.adj_own || 0,
      xslg: 0.0, k_pct: 0.0, opp_team_total: 0.0,
    }))
    const byTeam = {}
    pool.players.filter(x => !x.is_pitcher && x.order).forEach(x => {
      (byTeam[x.team] ||= []).push(x)
    })
    const s = Object.entries(byTeam).map(([team, hs]) => ({
      team, bat_owns: hs.sort((a, b) => a.order - b.order).map(h => h.adj_own || 0),
      ceiling: hs.reduce((acc, h) => acc + (h.dk95 || 0), 0),
    }))
    setPitchers(JSON.stringify(p, null, 1))
    setStacks(JSON.stringify(s, null, 1))
  }

  async function analyze() {
    setErr(null)
    try {
      const payload = {
        pitchers: JSON.parse(pitchers || '[]'),
        stacks: JSON.parse(stacks || '[]'),
        game_totals: totals.split(',').map(x => parseFloat(x.trim())).filter(x => !isNaN(x)),
        fav_moneylines: moneylines.split(',').map(x => parseInt(x.trim())).filter(x => !isNaN(x)),
      }
      setChalk(await api.chalk(payload))
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Chalk-Live Detector</h2>
          <button className="btn-ghost" onClick={derive} disabled={!pool}>Derive rows from pool</button>
        </div>
        <p className="text-sm text-slate-400">
          Fill xSLG (opponent expected SLG from Savant splits) and Vegas numbers, then analyze.
          v4 scores the chalk <em>arm</em> and chalk <em>stack</em> separately — signal (c) not firing is
          the tell that the stack half is a trap.
        </p>
        <div className="grid sm:grid-cols-2 gap-3">
          <JsonArea label="Pitcher rows" value={pitchers} onChange={setPitchers} />
          <JsonArea label="Stack rows" value={stacks} onChange={setStacks} />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <TextField label="Game totals (comma-sep)" value={totals} onChange={setTotals} ph="11.5, 10, 9, 8.5" />
          <TextField label="Favorite moneylines (comma-sep)" value={moneylines} onChange={setMoneylines} ph="-156, -180, -122" />
        </div>
        <button className="btn-primary" onClick={analyze}>Analyze slate shape</button>
        {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
      </div>

      {chalk && (
        <div className="card space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-3xl font-bold">{chalk.score}/4</span>
            <span className={`tag text-base ${chalk.score >= 2 ? 'bg-amber-900 text-amber-300' : 'bg-emerald-900 text-emerald-300'}`}>
              {chalk.verdict}
            </span>
            <span className="text-sm text-slate-400">Rule #34 chalk-anchored block: <b>{chalk.chalk_block_pct}</b></span>
          </div>

          <div className="grid sm:grid-cols-2 gap-2">
            {Object.entries(chalk.signals).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2 text-sm">
                <span className={v.fired ? 'pill-warn' : 'pill-info'}>{v.fired ? 'FIRED' : '—'}</span>
                <span className="text-slate-300">{k}</span>
              </div>
            ))}
          </div>

          <div className="bg-slate-950 rounded-lg p-3 border border-slate-800 text-sm">
            <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Detector split (v4)</div>
            <div className="flex gap-4 flex-wrap">
              <span className={chalk.detector_split.arm_half_live ? 'pill-warn' : 'pill-info'}>
                arm {chalk.detector_split.arm_half_live ? 'live' : 'quiet'}</span>
              <span className={chalk.detector_split.stack_half_trap ? 'pill-fail' :
                chalk.detector_split.stack_half_live ? 'pill-warn' : 'pill-info'}>
                stack {chalk.detector_split.stack_half_trap ? 'TRAP' :
                  chalk.detector_split.stack_half_live ? 'live' : 'quiet'}</span>
            </div>
            <p className="text-slate-400 mt-1">{chalk.detector_split.note}</p>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">
                xSLG gate — leverage exceptions (#31/#50, DO NOT ZERO)</div>
              {chalk.xslg_gate.leverage_exception.length === 0 && <p className="text-sm text-slate-500">none</p>}
              {chalk.xslg_gate.leverage_exception.map((p, i) => (
                <div key={i} className="text-sm text-emerald-300">{p.name} — {p.proj_own}% own, xSLG {p.xslg}</div>
              ))}
              <div className="text-xs uppercase tracking-wide text-slate-500 mt-2 mb-1">Hard-capped</div>
              {chalk.xslg_gate.hard_capped.map((p, i) => (
                <div key={i} className="text-sm text-slate-400">{p.name} — {p.proj_own}%, xSLG {p.xslg}</div>
              )) || null}
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Stack ownership audit (#29/#32)</div>
              <table className="w-full text-xs">
                <thead className="text-slate-500 text-left"><tr><th>Team</th><th>Agg%</th><th>#sub10</th><th>Ceil</th><th>Verdict</th></tr></thead>
                <tbody>
                  {chalk.stack_audit.map((r, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="font-mono">{r.team}</td><td>{r.agg_own}</td><td>{r.n_sub10}</td>
                      <td>{r.ceiling}</td>
                      <td className={r.verdict.startsWith('LIVE') ? 'text-emerald-400' : 'text-slate-400'}>{r.verdict}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function JsonArea({ label, value, onChange }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={6}
        className="mt-1 w-full bg-slate-950 border border-slate-700 rounded p-2 font-mono text-xs" />
    </label>
  )
}
function TextField({ label, value, onChange, ph }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={ph}
        className="mt-1 w-full bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm" />
    </label>
  )
}
