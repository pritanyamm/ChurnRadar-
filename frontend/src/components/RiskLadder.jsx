import {
  Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { inr, num } from '../api'

// Colour is the encoding, so it is derived from the bucket, never chosen.
function bandColour(bucket) {
  const lo = parseInt(bucket, 10)
  if (lo < 5) return 'var(--safe)'
  if (lo < 15) return 'var(--watch)'
  if (lo < 35) return 'var(--high)'
  return 'var(--critical)'
}

function LadderTip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="panel" style={{ padding: '10px 12px', fontSize: 12.5 }}>
      <div style={{ fontFamily: 'var(--mono)', marginBottom: 4 }}>
        {d.bucket} churn probability
      </div>
      <div style={{ color: 'var(--muted)' }}>
        {num(d.accounts)} accounts &middot; {inr(d.arr)} ARR
      </div>
    </div>
  )
}

export default function RiskLadder({ data }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
          <XAxis
            dataKey="bucket"
            tick={{ fill: 'var(--dim)', fontSize: 10, fontFamily: 'var(--mono)' }}
            axisLine={{ stroke: 'var(--line)' }}
            tickLine={false}
            interval={1}
          />
          <YAxis
            tickFormatter={inr}
            tick={{ fill: 'var(--dim)', fontSize: 10, fontFamily: 'var(--mono)' }}
            axisLine={false}
            tickLine={false}
            width={62}
          />
          <Tooltip content={<LadderTip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
          <Bar dataKey="arr" radius={[2, 2, 0, 0]}>
            {data.map((d) => <Cell key={d.bucket} fill={bandColour(d.bucket)} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="ladder-legend">
        <span><i className="swatch" style={{ background: 'var(--safe)' }} />Low &mdash; under 5%</span>
        <span><i className="swatch" style={{ background: 'var(--watch)' }} />Watch &mdash; 5 to 15%</span>
        <span><i className="swatch" style={{ background: 'var(--high)' }} />High &mdash; 15 to 35%</span>
        <span><i className="swatch" style={{ background: 'var(--critical)' }} />Critical &mdash; above 35%</span>
      </div>
    </>
  )
}
