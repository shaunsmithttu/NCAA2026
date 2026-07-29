import React, { useState } from 'react'
import { api } from '../lib/api.js'

// Spec S2 B: the pre-slate research board. Upload any subset of the research
// files (ROO stacks, pitcher/hitter/team research, scoring pct); each is
// auto-detected. Ownership from the ingested pool lights up the ownership-gated
// scans (#22/#40/#53). The board's chalk_inputs feed the Gate Analysis tab.
export default function Research({ pool, slate, setResearch, research }) {
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function run() {
    setBusy(true); setErr(null)
    try {
      let ownership = null
      if (pool) {
        ownership = {}
        pool.players.forEach((p) => { if (p.adj_own != null) ownership[p.name] = p.adj_own })
      }
      const res = await api.research([...files], ownership,
        slate.field_size ? Number(slate.field_size) : null)
      setResearch(res.board)
    } catch (e) { setErr(e.message) }
    finally { setBusy(false) }
  }

  const b = research

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <h2 className="font-semibold">Pre-slate research board</h2>
        <p className="text-sm text-slate-400">
          Upload ROO stacks, pitcher/hitter/team research, and scoring-pct CSVs (any subset — files are
          auto-detected by header). If you've ingested the pool (tab 1), its projected ownership is used to
          light up the sub-2% (#53), sub-4% dart (#22), IL-return (#40) and thin-arm (#39) scans.
        </p>
        <input type="file" accept=".csv" multiple onChange={(e) => setFiles([...e.target.files])}
          className="block w-full text-sm text-slate-400 file:mr-3 file:py-1.5 file:px-3
                     file:rounded-lg file:border-0 file:bg-slate-800 file:text-slate-200" />
        {files.length > 0 && <div className="text-xs text-emerald-400">{files.length} file(s) selected</div>}
        <button className="btn-primary" disabled={!files.length || busy} onClick={run}>
          {busy ? 'Analyzing…' : 'Build research board'}
        </button>
        {err && <p className="pill-fail block whitespace-pre-wrap">{err}</p>}
      </div>

      {b && (
        <>
          {b.notes.map((n, i) => <p key={i} className="pill-warn block">{n}</p>)}

          <div className="card">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold">Top-5 coverage set (#50)</h2>
              <button className="btn-ghost" onClick={() => setResearch({ ...b, _pushChalk: Date.now() })}>
                Chalk feed ready → Gate Analysis
              </button>
            </div>
            <div className="flex gap-2 flex-wrap">
              {b.top5_teams.map((t) => <span key={t} className="tag bg-sky-900 text-sky-300 text-sm">{t}</span>)}
            </div>
            <p className="text-xs text-slate-500 mt-1">
              These teams enter the build candidate set regardless of any single-factor screen. The chalk
              detector on the Gate tab can now be fed real xSLG + Opp_TT from this research
              ({b.chalk_inputs.pitchers.length} arms, {b.chalk_inputs.stacks.length} stacks).
            </p>
          </div>

          <Section title={`Stack board — edge ratio (ceiling ÷ own) · ${b.stack_board.length}`}>
            <Table cols={['Stack', 'Median', 'Ceiling', 'Own%', 'Edge', 'Top5%']}
              rows={b.stack_board.slice(0, 15).map((s) => [
                s.label, s.median, s.ceiling, s.own?.toFixed(1),
                <b className="text-emerald-400">{s.edge_ratio}</b>, s.top5 != null ? (s.top5 * 100).toFixed(0) + '%' : '—'])} />
          </Section>

          <Section title={`Arm board — quality composite (#8), gate as weight (#50) · ${b.arm_board.length}`}>
            <Table cols={['Pitcher', 'Team', 'K%', 'xSLG', 'OppTT', 'Own%', 'Screen']}
              rows={b.arm_board.slice(0, 12).map((p) => [
                p.name, p.team, p.k_pct, p.xslg, p.opp_tt,
                p.proj_own ?? '—',
                <span className={p.gate_flag.startsWith('capped') ? 'text-amber-400' : 'text-emerald-400'}>{p.gate_flag}</span>])} />
          </Section>

          <Section title={`Best bat matchups — opp xSLG by handedness (feeds #53) · showing 15`}>
            <Table cols={['Hitter', 'Team', 'Ord', 'Bats', 'vs SP', 'Hand', 'xSLG', 'Own%']}
              rows={b.bat_board.slice(0, 15).map((h) => [
                h.name, h.team, h.order ?? '—', h.bats, h.opp_sp, h.opp_hand,
                <b className={h.good_matchup ? 'text-emerald-400' : ''}>{h.xslg}</b>, h.proj_own ?? '—'])} />
          </Section>

          <div className="grid md:grid-cols-2 gap-4">
            <Section title={`Dart pool — top-6 order, good matchup (#22/#30) · ${b.dart_pool.length}`}>
              <Table cols={['Hitter', 'Team', 'Ord', 'xSLG', 'xHRs', 'Own%']}
                rows={b.dart_pool.slice(0, 12).map((d) => [
                  d.name, d.team, d.order, d.xslg, d.xhrs, d.proj_own ?? '—'])} />
            </Section>
            <Section title={`IL-return / superstar darts (#40) · ${b.star_darts.length}`}>
              {b.star_darts.length === 0
                ? <p className="text-sm text-slate-500">None (needs projected ownership to fire).</p>
                : <Table cols={['Hitter', 'Team', 'Own%', 'xHRs', 'xSLG']}
                    rows={b.star_darts.map((d) => [d.name, d.team, d.proj_own, d.xhrs, d.xslg])} />}
            </Section>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <Section title={`Rule #53 discarded-signal candidates · ${b.discarded_candidates.length}`}>
              {b.discarded_candidates.length === 0
                ? <p className="text-sm text-slate-500">None surfaced (needs ownership; fires on sub-2% + xSLG≥.45).</p>
                : <Table cols={['Hitter', 'Team', 'Own%', 'xSLG', 'Hand']}
                    rows={b.discarded_candidates.map((d) => [d.name, d.team, d.proj_own, d.xslg, d.opp_hand])} />}
            </Section>
            <Section title="Environment ranking (#10/#35/#36)">
              <Table cols={['Team', 'AvgScore', 'OppSP', 'OppxSLG']}
                rows={b.environments.slice(0, 10).map((e) => [
                  e.team, e.avg_score ?? '—', e.opp_sp ?? '—', e.opp_xslg ?? '—'])} />
              {b.coors_environments.length > 0 &&
                <p className="text-xs text-emerald-400 mt-1">Coors/high-total: {b.coors_environments.map(e => e.team).join(', ')}</p>}
            </Section>
          </div>

          {b.thin_arm && (
            <div className={`card ${b.thin_arm.triggered ? 'border-amber-800 bg-amber-950/20' : ''}`}>
              <h2 className="font-semibold mb-1">Thin-arm slate (#39): {b.thin_arm.triggered ? 'TRIGGERED' : 'no'}</h2>
              <p className="text-sm text-slate-400">
                {b.thin_arm.chalk_sps.length} SP(s) at ≥35% projected own
                {b.thin_arm.chalk_sps.length > 0 && `: ${b.thin_arm.chalk_sps.map(s => `${s.name} (${s.own}%)`).join(', ')}`}.
                {b.thin_arm.triggered && ' Roster both and generate all differentiation through sub-10% bats.'}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="card">
      <h2 className="font-semibold mb-2 text-sm">{title}</h2>
      <div className="overflow-x-auto">{children}</div>
    </div>
  )
}

function Table({ cols, rows }) {
  return (
    <table className="w-full text-xs">
      <thead className="text-slate-500 text-left">
        <tr>{cols.map((c) => <th key={c} className="pr-3 pb-1">{c}</th>)}</tr>
      </thead>
      <tbody className="font-mono">
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-slate-800">
            {r.map((cell, j) => <td key={j} className="pr-3 py-0.5">{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
