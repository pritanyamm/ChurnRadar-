import { useEffect, useState } from 'react'
import { api, inr, num, pct } from '../api'

export default function ActionList({ onSelect }) {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [opts, setOpts] = useState({ segments: [], bands: [], reasons: [] })
  const [q, setQ] = useState({ segment: '', band: '', reason: '', limit: 40, offset: 0 })
  const [loading, setLoading] = useState(true)

  useEffect(() => { api.filters().then(setOpts).catch(() => {}) }, [])

  useEffect(() => {
    setLoading(true)
    api.customers(q)
      .then((r) => { setRows(r.items); setTotal(r.total) })
      .finally(() => setLoading(false))
  }, [q])

  const set = (k, v) => setQ((p) => ({ ...p, [k]: v, offset: 0 }))

  return (
    <>
      <div className="filters">
        <select value={q.segment} onChange={(e) => set('segment', e.target.value)} aria-label="Segment">
          <option value="">All segments</option>
          {opts.segments.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={q.band} onChange={(e) => set('band', e.target.value)} aria-label="Risk band">
          <option value="">All risk bands</option>
          {opts.bands.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <select value={q.reason} onChange={(e) => set('reason', e.target.value)} aria-label="Primary reason">
          <option value="">All reasons</option>
          {opts.reasons.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <span className="badge" style={{ marginLeft: 'auto' }}>
          {loading ? 'loading…' : `${num(total)} accounts`}
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th className="right">Risk</th>
              <th className="right">MRR</th>
              <th className="right">At risk</th>
              <th>Band</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.customer_id}
                tabIndex={0}
                onClick={() => onSelect(r.customer_id)}
                onKeyDown={(e) => e.key === 'Enter' && onSelect(r.customer_id)}
              >
                <td>
                  <div className="name">{r.company_name}</div>
                  <div className="reason">{r.segment} &middot; {r.primary_reason}</div>
                </td>
                <td className="right mono">{pct(r.churn_probability_90d * 100, 0)}</td>
                <td className="right mono">{inr(r.mrr)}</td>
                <td className="right mono">{inr(r.revenue_at_risk)}</td>
                <td><span className={`pill ${r.risk_band}`}>{r.risk_band}</span></td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={5} style={{ color: 'var(--muted)', padding: 24 }}>
                No accounts match these filters.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {total > q.limit && (
        <div className="filters" style={{ marginTop: 12 }}>
          <button
            className="close" style={{ position: 'static' }}
            disabled={q.offset === 0}
            onClick={() => setQ((p) => ({ ...p, offset: Math.max(0, p.offset - p.limit) }))}
          >Previous</button>
          <span className="badge">
            {q.offset + 1}–{Math.min(q.offset + q.limit, total)} of {num(total)}
          </span>
          <button
            className="close" style={{ position: 'static' }}
            disabled={q.offset + q.limit >= total}
            onClick={() => setQ((p) => ({ ...p, offset: p.offset + p.limit }))}
          >Next</button>
        </div>
      )}
    </>
  )
}
