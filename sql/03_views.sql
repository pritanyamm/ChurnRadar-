-- ChurnRadar - analytics views
-- These are what the API and Power BI read. Keeping the logic here (not in
-- Python) means the number on the dashboard and the number an analyst gets
-- from a SQL console are the same number, by construction.

-- 1. The headline KPI strip -------------------------------------------------

CREATE OR REPLACE VIEW v_portfolio_kpis AS
SELECT
    count(*)                                                    AS active_customers,
    count(*) FILTER (WHERE churn_probability_90d >= 0.15)       AS at_risk_customers,
    round(avg(churn_probability_90d) * 100, 2)                  AS predicted_churn_pct,
    round(sum(arr))                                             AS active_arr,
    round(sum(revenue_at_risk))                                 AS revenue_at_risk,
    round(sum(arr) FILTER (WHERE churn_probability_90d >= 0.15)) AS arr_in_at_risk_accounts,
    round(avg(mrr))                                             AS avg_mrr,
    max(scored_at)                                              AS scored_at
FROM scored_customers;

-- 2. Risk band distribution, weighted by money not headcount ---------------
-- The point of the whole product: 40 Critical accounts worth 3 Cr matter more
-- than 4,000 Watch accounts worth 60 L.

CREATE OR REPLACE VIEW v_risk_bands AS
SELECT
    risk_band,
    count(*)                       AS accounts,
    round(sum(arr))                AS arr,
    round(sum(revenue_at_risk))    AS revenue_at_risk,
    round(avg(churn_probability_90d) * 100, 1) AS avg_risk_pct,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_accounts,
    round(100.0 * sum(arr) / sum(sum(arr)) OVER (), 1) AS pct_of_arr
FROM scored_customers
GROUP BY risk_band;

-- 3. Why are they leaving? -------------------------------------------------

CREATE OR REPLACE VIEW v_churn_reasons AS
SELECT
    primary_reason,
    count(*)                    AS accounts,
    round(sum(revenue_at_risk)) AS revenue_at_risk,
    round(avg(churn_probability_90d) * 100, 1) AS avg_risk_pct,
    round(avg(mrr))             AS avg_mrr
FROM scored_customers
WHERE churn_probability_90d >= 0.15
GROUP BY primary_reason
ORDER BY revenue_at_risk DESC;

-- 4. Segment view ----------------------------------------------------------

CREATE OR REPLACE VIEW v_segment_risk AS
SELECT
    segment,
    tier,
    count(*)                                            AS accounts,
    round(avg(churn_probability_90d) * 100, 1)          AS predicted_churn_pct,
    round(sum(arr))                                     AS arr,
    round(sum(revenue_at_risk))                         AS revenue_at_risk,
    round(avg(seat_utilisation) * 100, 1)               AS avg_seat_util_pct,
    round(avg(t90_tickets), 2)                          AS avg_tickets_90d
FROM scored_customers
GROUP BY segment, tier
ORDER BY revenue_at_risk DESC;

-- 5. Historical monthly churn - the "are we getting better?" chart ---------
-- Uses a generated month spine so months with zero churn still appear.

CREATE OR REPLACE VIEW v_monthly_churn AS
WITH months AS (
    SELECT generate_series(
        date_trunc('month', (SELECT min(start_date) FROM subscriptions)),
        date_trunc('month', (SELECT max(COALESCE(end_date, CURRENT_DATE)) FROM subscriptions)),
        interval '1 month'
    )::date AS month_start
),
active AS (
    SELECT m.month_start,
           count(*)     AS active_accounts,
           sum(s.mrr)   AS active_mrr
    FROM months m
    JOIN subscriptions s
      ON s.start_date <= (m.month_start + interval '1 month - 1 day')
     AND (s.end_date IS NULL OR s.end_date >= m.month_start)
    GROUP BY m.month_start
),
lost AS (
    SELECT date_trunc('month', s.end_date)::date AS month_start,
           count(*)   AS churned_accounts,
           sum(s.mrr) AS churned_mrr
    FROM subscriptions s
    WHERE s.end_date IS NOT NULL
    GROUP BY 1
)
SELECT a.month_start,
       a.active_accounts,
       round(a.active_mrr)                       AS active_mrr,
       COALESCE(l.churned_accounts, 0)           AS churned_accounts,
       round(COALESCE(l.churned_mrr, 0))         AS churned_mrr,
       round(100.0 * COALESCE(l.churned_accounts, 0) / NULLIF(a.active_accounts, 0), 2)
                                                 AS logo_churn_pct,
       round(100.0 * COALESCE(l.churned_mrr, 0) / NULLIF(a.active_mrr, 0), 2)
                                                 AS revenue_churn_pct
FROM active a
LEFT JOIN lost l USING (month_start)
ORDER BY a.month_start;

-- 6. Cohort retention triangle --------------------------------------------
-- Rows = signup month, columns = months since signup. The classic analyst
-- artefact, and the fastest way to see whether onboarding changes worked.

CREATE OR REPLACE VIEW v_cohort_retention AS
WITH base AS (
    SELECT date_trunc('month', s.start_date)::date AS cohort_month,
           s.customer_id,
           s.end_date,
           s.mrr
    FROM subscriptions s
),
sized AS (
    SELECT cohort_month, count(*) AS cohort_size FROM base GROUP BY cohort_month
),
spans AS (
    SELECT b.cohort_month,
           gs.m AS months_since_signup,
           count(*) FILTER (
               WHERE b.end_date IS NULL
                  OR b.end_date >= b.cohort_month + (gs.m || ' month')::interval
           ) AS retained
    FROM base b
    CROSS JOIN generate_series(0, 23) AS gs(m)
    WHERE b.cohort_month + (gs.m || ' month')::interval <= CURRENT_DATE
    GROUP BY b.cohort_month, gs.m
)
SELECT s.cohort_month,
       z.cohort_size,
       s.months_since_signup,
       s.retained,
       round(100.0 * s.retained / NULLIF(z.cohort_size, 0), 1) AS retention_pct
FROM spans s
JOIN sized z USING (cohort_month)
ORDER BY s.cohort_month, s.months_since_signup;

-- 7. The action list -------------------------------------------------------
-- What a Customer Success rep actually opens on Monday morning: highest
-- expected loss first, with the reason already attached.

CREATE OR REPLACE VIEW v_action_list AS
SELECT
    sc.customer_id,
    c.company_name,
    sc.segment,
    sc.tier,
    sc.state,
    sc.mrr,
    sc.arr,
    sc.churn_probability_90d,
    sc.risk_band,
    sc.revenue_at_risk,
    sc.primary_reason,
    sc.reasons,
    sc.discount_pct,
    round(sc.seat_utilisation * 100, 1) AS seat_util_pct,
    sc.t90_tickets,
    sc.tenure_months,
    row_number() OVER (ORDER BY sc.revenue_at_risk DESC) AS priority_rank
FROM scored_customers sc
JOIN customers c USING (customer_id)
WHERE sc.churn_probability_90d >= 0.15
ORDER BY sc.revenue_at_risk DESC;
