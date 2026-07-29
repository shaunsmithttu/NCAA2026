import React from 'react'

// Renders a validate() report: the hard gate for CSV export. Failures are red,
// warnings amber, info grey. Grouped so per-lineup noise doesn't drown the
// portfolio-level hard constraints.
export default function ValidationReport({ report }) {
  if (!report) return null
  const sev = (c) => c.severity === 'fail' ? (c.passed ? 'pass' : 'fail')
    : c.severity === 'warn' ? (c.passed ? 'pass' : 'warn')
    : c.passed ? 'pass' : 'info'
  return (
    <div className="card space-y-3">
      <div className="flex items-center gap-3">
        <span className={report.export_allowed ? 'pill-pass' : 'pill-fail'}>
          {report.export_allowed ? 'EXPORT ALLOWED' : 'EXPORT BLOCKED'}
        </span>
        <span className="text-sm text-slate-400">
          {report.n_fail} hard failure(s) · {report.n_warn} warning(s)
        </span>
      </div>
      {report.failures?.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs uppercase tracking-wide text-rose-400">Hard failures</div>
          {report.failures.map((c, i) => <CheckRow key={i} c={c} sev="fail" />)}
        </div>
      )}
      {report.warnings?.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs uppercase tracking-wide text-amber-400">Warnings</div>
          {report.warnings.map((c, i) => <CheckRow key={i} c={c} sev="warn" />)}
        </div>
      )}
      <details>
        <summary className="text-xs text-slate-500 cursor-pointer">All {report.checks.length} checks</summary>
        <div className="mt-2 space-y-1">
          {report.checks.map((c, i) => <CheckRow key={i} c={c} sev={sev(c)} />)}
        </div>
      </details>
    </div>
  )
}

function CheckRow({ c, sev }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className={`pill-${sev} mt-0.5 shrink-0`}>{c.rule_id ? `#${c.rule_id}` : sev}</span>
      <div>
        <span className="font-mono text-xs text-slate-400">{c.check}</span>
        <span className="text-slate-300"> — {c.reason}</span>
      </div>
    </div>
  )
}
