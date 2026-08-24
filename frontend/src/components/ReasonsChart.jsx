import {
  Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { inr, num } from '../api'

function Tip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="panel" style={{ padding: '10px 12px', fontSize: 12.5 }}>
      <div style={{ marginBottom: 4 }}>{d.primary_reason}</div>
      <div style={{ color: 'var(--muted)' }}>
        {num(d.accounts)} accounts &middot; {inr(d.revenue_at_risk)} at risk<br />
        average risk {d.avg_risk_pct}% &middot; average MRR {inr(d.avg_mrr)}
      </div>
    </div>
  )
}

export default function ReasonsChart({ data }) {
  const rows = data.slice(0, 8)
  return (
    <ResponsiveContainer width="100%" height={Math.max(220, rows.length * 42)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 4, right: 16 }}>
        <XAxis
          type="number"
          tickFormatter={inr}
          tick={{ fill: 'var(--dim)', fontSize: 10, fontFamily: 'var(--mono)' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="primary_reason"
          width={168}
          tick={{ fill: 'var(--muted)', fontSize: 11.5 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<Tip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Bar dataKey="revenue_at_risk" fill="var(--high)" radius={[0, 3, 3, 0]} barSize={18} />
      </BarChart>
    </ResponsiveContainer>
  )
}
