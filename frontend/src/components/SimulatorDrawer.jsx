import { useEffect, useState } from 'react'
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api, inr, inrFull, pct } from '../api'

export default function SimulatorDrawer({ customerId, onClose }) {
  const [discount, setDiscount] = useState(15)
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(true)

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    setBusy(true)
    const t = setTimeout(() => {
      api.simulate(customerId, discount / 100)
        .then(setData)
        .finally(() => setBusy(false))
    }, 120)                       // debounce while the slider is dragged
    return () => clearTimeout(t)
  }, [customerId, discount])

  const r = data?.result
  const good = r && r.expected_benefit > 0

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Retention simulator">
        <button className="close" onClick={onClose}>Close</button>

        <h3>{data?.company_name || `Account ${customerId}`}</h3>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginTop: 0 }}>
          Retention simulator &mdash; is a discount worth it for this account?
        </p>

        {data?.reasons?.length > 0 && (
          <div className="reason-chips">
            {data.reasons.map((x) => (
              <span className="chip" key={x.feature}>
                {x.label} <b>+{x.impact_pp}pp</b>
              </span>
            ))}
          </div>
        )}

        <div style={{ marginTop: 22 }}>
          <div className="kpi-label">Discount offered, held for 12 months</div>
          <div className="slider-row">
            <input
              type="range" min={0} max={40} step={1} value={discount}
              onChange={(e) => setDiscount(Number(e.target.value))}
              aria-label="Discount percentage"
            />
            <span className="slider-value">{discount}%</span>
          </div>
        </div>

        {r && (
          <>
            <div className="ledger">
              <div className="ledger-row">
                <span className="k">Annual revenue at list price</span>
                <span className="v">{inrFull(r.annual_revenue)}</span>
              </div>
              <div className="ledger-row">
                <span className="k">Churn risk over 12 months</span>
                <span className="v">
                  {pct(r.churn_probability_12m * 100, 0)}
                  <span style={{ color: 'var(--dim)' }}> → </span>
                  <span className="pos">{pct(r.churn_probability_12m_with_offer * 100, 0)}</span>
                </span>
              </div>
              <div className="ledger-row">
                <span className="k">Retention cost (discount + CSM time)</span>
                <span className="v neg">−{inrFull(r.retention_cost)}</span>
              </div>
              <div className="ledger-row">
                <span className="k">Expected revenue saved</span>
                <span className="v pos">+{inrFull(r.expected_revenue_saved)}</span>
              </div>
              <div className="ledger-row total">
                <span className="k">Expected benefit</span>
                <span className={`v ${good ? 'pos' : 'neg'}`}>
                  {good ? '+' : '−'}{inrFull(Math.abs(r.expected_benefit))}
                </span>
              </div>
            </div>

            <div className={`verdict ${good ? 'good' : 'bad'}`}>
              <div className="head">{r.recommendation}</div>
              <p>{r.rationale}</p>
            </div>

            <div style={{ marginTop: 22 }}>
              <div className="kpi-label">Net benefit across every discount level</div>
              <p style={{ color: 'var(--dim)', fontSize: 12, margin: '2px 0 10px' }}>
                The curve turns over because a bigger discount buys less and less extra
                retention while costing linearly more. The peak is the offer to make.
              </p>
              <ResponsiveContainer width="100%" height={190}>
                <LineChart data={data.curve} margin={{ top: 6, right: 10, left: 4 }}>
                  <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                  <XAxis
                    dataKey="discount_pct" unit="%"
                    tick={{ fill: 'var(--dim)', fontSize: 10, fontFamily: 'var(--mono)' }}
                    axisLine={{ stroke: 'var(--line)' }} tickLine={false}
                  />
                  <YAxis
                    tickFormatter={inr}
                    tick={{ fill: 'var(--dim)', fontSize: 10, fontFamily: 'var(--mono)' }}
                    axisLine={false} tickLine={false} width={58}
                  />
                  <Tooltip
                    formatter={(v) => inrFull(v)}
                    labelFormatter={(l) => `${l}% discount`}
                    contentStyle={{
                      background: 'var(--panel-2)', border: '1px solid var(--line)',
                      borderRadius: 8, fontSize: 12,
                    }}
                  />
                  <ReferenceLine y={0} stroke="var(--dim)" strokeDasharray="3 3" />
                  <ReferenceLine
                    x={data.optimal.discount_pct * 100}
                    stroke="var(--safe)"
                    label={{ value: 'best', fill: 'var(--safe)', fontSize: 10, position: 'top' }}
                  />
                  <Line
                    type="monotone" dataKey="expected_benefit"
                    stroke="var(--watch)" strokeWidth={2} dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>

              <div className="ledger" style={{ marginTop: 6 }}>
                <div className="ledger-row">
                  <span className="k">Best offer for this account</span>
                  <span className="v pos">
                    {pct(data.optimal.discount_pct * 100, 0)} → {inrFull(data.optimal.expected_benefit)}
                  </span>
                </div>
                {r.breakeven_discount_pct != null && (
                  <div className="ledger-row">
                    <span className="k">Break-even discount ceiling</span>
                    <span className="v">{pct(r.breakeven_discount_pct, 1)}</span>
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {busy && !r && <p style={{ color: 'var(--muted)' }}>Running simulation…</p>}
      </aside>
    </>
  )
}
