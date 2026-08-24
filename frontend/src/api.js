// Thin fetch wrapper. Vite proxies /api to the FastAPI server in dev; in
// production set VITE_API_BASE to the deployed API origin.
const BASE = import.meta.env.VITE_API_BASE || ''

async function get(path) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} returned ${r.status}`)
  return r.json()
}

async function post(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} returned ${r.status}`)
  return r.json()
}

export const api = {
  kpis: () => get('/api/kpis'),
  riskBands: () => get('/api/risk-bands'),
  riskDistribution: () => get('/api/risk-distribution?bins=20'),
  reasons: () => get('/api/reasons'),
  segments: () => get('/api/segments'),
  filters: () => get('/api/filters'),
  metrics: () => get('/api/model/metrics'),
  customers: (q = {}) => {
    const p = new URLSearchParams(Object.entries(q).filter(([, v]) => v))
    return get(`/api/customers?${p}`)
  },
  simulate: (customer_id, discount_pct) =>
    post('/api/simulate', { customer_id, discount_pct }),
}

// --- Indian number formatting --------------------------------------------
// Lakhs and crores, because "₹1,13,68,58,088" is unreadable and "₹113.7 Cr"
// is the number a CFO in Bengaluru actually says out loud.
export function inr(n) {
  if (n == null || isNaN(n)) return '—'
  const a = Math.abs(n)
  if (a >= 1e7) return `₹${(n / 1e7).toFixed(1)} Cr`
  if (a >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  if (a >= 1e3) return `₹${(n / 1e3).toFixed(1)} K`
  return `₹${Math.round(n)}`
}

export function inrFull(n) {
  if (n == null || isNaN(n)) return '—'
  return `₹${Math.round(n).toLocaleString('en-IN')}`
}

export const num = (n) => (n == null ? '—' : Math.round(n).toLocaleString('en-IN'))
export const pct = (n, d = 1) => (n == null ? '—' : `${Number(n).toFixed(d)}%`)
