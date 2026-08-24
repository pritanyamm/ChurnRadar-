# Power BI

The dashboard in `frontend/` and a Power BI report read the **same tables**.
Neither is a re-implementation of the other — the metric logic lives in
`sql/03_views.sql`, so the number on the web dashboard and the number in Power
BI are the same number by construction.

**New to Power BI?** Start with [BUILD-GUIDE.md](BUILD-GUIDE.md) — it walks
through the whole report from installing Desktop to exporting the PDF. This
file is the reference: schema, measures and design decisions.

## Connecting

**Option A — PostgreSQL (live, preferred)**

1. Get Data → PostgreSQL database
2. Server `localhost:5433`, Database `churnradar`
3. Import these views: `v_portfolio_kpis`, `v_risk_bands`, `v_churn_reasons`,
   `v_segment_risk`, `v_monthly_churn`, `v_cohort_retention`, `v_action_list`
4. Choose **Import**, not DirectQuery. The data refreshes nightly, so there is
   nothing to gain from querying live, and Import makes every visual instant.

**Option B — CSV star schema (no database needed)**

```bash
python powerbi/export_for_powerbi.py --data data/ --out data/powerbi/
```

Produces six CSVs already shaped as a star schema, with a proper date table,
the cohort triangle pre-computed, and the JSON reason codes flattened into
`reason_1`/`reason_2`/`reason_3` columns — Power BI cannot group on a nested
column, so flattening has to happen upstream.

Then: Get Data → Folder → `data/powerbi`.

## Model

One star schema. `scored_customers` is the fact table; `customers`, `plans` and
a date table are dimensions.

```
Date ──┐
       ├── scored_customers ──┬── customers
Plans ─┘                      └── (segment, tier as attributes)
```

Mark the date table as a date table, or time intelligence silently returns
wrong answers.

## Measures

The full library is in [`measures.dax`](measures.dax) — 20 measures covering
counts, revenue, risk concentration, cohort retention and the what-if
simulator. The six that matter most:

```dax
Active Customers    = DISTINCTCOUNT(scored_customers[customer_id])

At Risk Customers   = CALCULATE([Active Customers],
                        scored_customers[churn_probability_90d] >= 0.15)

Revenue at Risk     = SUM(scored_customers[revenue_at_risk])

Predicted Churn %   = AVERAGE(scored_customers[churn_probability_90d])

ARR                 = SUM(scored_customers[arr])

Risk Concentration  =
    DIVIDE(
        CALCULATE([Revenue at Risk],
            scored_customers[risk_band] IN {"High","Critical"}),
        [Revenue at Risk]
    )
```

`Risk Concentration` is the one worth having on the page: it answers "is our
risk spread thin or sitting on a few big accounts?", which changes whether the
right response is a campaign or a set of phone calls.

## Format the rupee figures properly

Power BI will render ₹1,136,858,088 by default, which nobody reads. Use a
custom format string so the numbers appear in crores:

```
#,##0,,,.0 "Cr"
```

## Pages

1. **Executive** — KPI cards, risk band donut weighted by ARR, monthly churn trend
2. **Diagnosis** — reasons bar chart, segment matrix, cohort retention heatmap
3. **Action** — the `v_action_list` table with drill-through to a single account

The retention simulator stays in the web app. Power BI what-if parameters can
approximate it, but the saturating uplift curve and the break-even bisection are
awkward in DAX and clear in Python — put logic where it belongs and link to it.
