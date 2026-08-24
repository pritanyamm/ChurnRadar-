import { useEffect, useState } from 'react'
import { api, inr, num, pct } from './api'
import KpiStrip from './components/KpiStrip'
import RiskLadder from './components/RiskLadder'
import ReasonsChart from './components/ReasonsChart'
import ActionList from './components/ActionList'
import SimulatorDrawer from './components/SimulatorDrawer'

export default function App() {
  const [kpis, setKpis] = useState(null)
  const [dist, setDist] = useState([])
  const [reasons, setReasons] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([api.kpis(), api.riskDistribution(), api.reasons()])
      .then(([k, d, r]) => { setKpis(k); setDist(d); setReasons(r) })
      .catch((e) => setError(e.message))
    api.metrics().then(setMetrics).catch(() => {})
  }, [])

  if (error) {
    return (
      <div className="shell">
        <div className="state">
          Could not reach the API.
          <code>{error}{'\n\n'}Start it with:{'\n'}uvicorn app.main:app --reload --app-dir backend</code>
        </div>
      </div>
    )
  }

  return (
    <div className="shell">
      <header className="topbar">
        <h1 className="wordmark">Churn<span>Radar</span></h1>
        <span className="tagline">Who is leaving, why, and what it costs us</span>
        <div className="topbar-right">
          {metrics && (
            <>
              <span className="badge">AUC {metrics.metrics.roc_auc}</span>
              <span className="badge">
                validated out-of-time on {metrics.metrics.valid_snapshot}
              </span>
            </>
          )}
          {kpis && <span className="badge">scored {kpis.scored_at}</span>}
        </div>
      </header>

      <KpiStrip k={kpis} />

      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Risk ladder</h2>
        <p className="sub">
          Every active account placed by its 90-day churn probability. Bar height is
          annual revenue, not headcount — which is the whole point: most accounts are
          safe, but the money clusters on the right.
        </p>
        <RiskLadder data={dist} />
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Why they are leaving</h2>
          <p className="sub">
            Each at-risk account's strongest driver, weighted by the revenue behind it.
            A discount fixes the top bar; it will not fix the others.
          </p>
          <ReasonsChart data={reasons} />
        </div>

        <div className="panel">
          <h2>Action list</h2>
          <p className="sub">
            Ranked by expected rupees lost, not by risk score. Select an account to run
            the retention simulator.
          </p>
          <ActionList onSelect={setSelected} />
        </div>
      </div>

      {kpis && (
        <p style={{ color: 'var(--dim)', fontSize: 12, marginTop: 20 }}>
          {num(kpis.active_customers)} active accounts &middot; {inr(kpis.active_arr)} annual
          recurring revenue &middot; at-risk threshold {pct(kpis.risk_threshold * 100, 0)} probability
          over 90 days. Figures are probability-weighted expectations, not worst cases.
        </p>
      )}

      {selected && (
        <SimulatorDrawer customerId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
