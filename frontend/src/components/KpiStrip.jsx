import { inr, num, pct } from '../api'

function Kpi({ label, value, note, tone = '' }) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  )
}

export default function KpiStrip({ k }) {
  if (!k) {
    return (
      <div className="kpis">
        {[...Array(5)].map((_, i) => (
          <div className="kpi" key={i}>
            <div className="kpi-label">Loading</div>
            <div className="kpi-value" style={{ color: 'var(--dim)' }}>—</div>
          </div>
        ))}
      </div>
    )
  }

  const share = (100 * k.at_risk_customers) / k.active_customers

  return (
    <div className="kpis">
      <Kpi
        label="Active customers"
        value={num(k.active_customers)}
        note={`${inr(k.avg_mrr)} average MRR`}
        tone="is-safe"
      />
      <Kpi
        label="At-risk customers"
        value={num(k.at_risk_customers)}
        note={`${pct(share)} of the base`}
        tone="is-risk"
      />
      <Kpi
        label="Revenue at risk"
        value={inr(k.revenue_at_risk)}
        note={`expected loss from ${inr(k.arr_in_at_risk_accounts)} of exposed ARR`}
        tone="is-critical"
      />
      <Kpi
        label="Predicted churn"
        value={pct(k.predicted_churn_pct, 1)}
        note="probability-weighted, next 90 days"
        tone="is-risk"
      />
      <Kpi
        label="Potentially recoverable"
        value={inr(k.recoverable_value)}
        note="net gain if every offer worth making is made"
        tone="is-safe"
      />
    </div>
  )
}
