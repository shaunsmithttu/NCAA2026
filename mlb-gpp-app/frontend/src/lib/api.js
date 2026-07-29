// Thin fetch wrapper over the FastAPI backend. All calls are same-origin via
// the Vite proxy (/api -> localhost:8000), so no CORS handling needed in dev.

async function j(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail
    try { detail = await res.json() } catch { detail = await res.text() }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail?.detail || detail))
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const api = {
  health: () => j('GET', '/api/health'),

  ingest: async (dkFile, projFile) => {
    const fd = new FormData()
    fd.append('dk_entries', dkFile)
    fd.append('projections', projFile)
    const res = await fetch('/api/ingest', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(JSON.stringify((await res.json()).detail))
    return res.json()
  },

  transform: (players, field_size, entry_fee) =>
    j('POST', '/api/ownership/transform', { players, field_size, entry_fee }),

  chalk: (payload) => j('POST', '/api/chalk/analyze', payload),

  build: (payload) => j('POST', '/api/build', payload),

  validate: (portfolio, ctx) => j('POST', '/api/validate', { portfolio, ctx }),

  exportCsv: async (portfolio, ctx, slate_id) => {
    const res = await fetch('/api/export/dk-csv', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ portfolio, ctx, slate_id }),
    })
    if (!res.ok) { const e = await res.json(); throw new Error(JSON.stringify(e.detail)) }
    return res.text()
  },

  rules: (includeFolded = true) => j('GET', `/api/rules?include_folded=${includeFolded}`),
  updateRule: (id, patch) => j('PATCH', `/api/rules/${id}`, patch),
  governance: () => j('GET', '/api/governance'),

  signals: (slateId, onlyUnadj = false) =>
    j('GET', `/api/signals?only_unadjudicated=${onlyUnadj}` + (slateId ? `&slate_id=${slateId}` : '')),
  adjudicate: (signal_id, decision, reason) =>
    j('POST', '/api/signals/adjudicate', { signal_id, decision, reason }),

  parseLineups: (csv_text, players) => j('POST', '/api/lineups/parse', { csv_text, players }),
  buildSimOverlay: (payload) => j('POST', '/api/build/sim-overlay', payload),
  infoFix: (portfolio, fixes, ctx) => j('POST', '/api/sim-overlay/info-fix', { portfolio, fixes, ctx }),

  research: async (files, ownershipMap, fieldSize) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    if (ownershipMap) fd.append('ownership_json', JSON.stringify(ownershipMap))
    if (fieldSize) fd.append('field_size', String(fieldSize))
    const res = await fetch('/api/research/board', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(JSON.stringify((await res.json()).detail))
    return res.json()
  },

  builds: () => j('GET', '/api/builds'),
  parseActuals: async (file) => {
    const fd = new FormData(); fd.append('actuals', file)
    const res = await fetch('/api/postmortem/actuals/parse', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
  simBaselineScore: (build_id, actuals) =>
    j('POST', '/api/postmortem/sim-baseline-score', { build_id, actuals }),

  calibration: () => j('GET', '/api/calibration'),
  slates: () => j('GET', '/api/slates'),
  createSlate: (payload) => j('POST', '/api/slates', payload),

  standings: async (file) => {
    const fd = new FormData(); fd.append('standings', file)
    const res = await fetch('/api/postmortem/standings', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
}
