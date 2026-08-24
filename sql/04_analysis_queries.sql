-- ChurnRadar - analyst query pack
-- These are not used by the app. They exist because "show me your SQL" is a
-- real interview question, and each one demonstrates a different technique.
-- Run them one at a time in psql or any SQL client.

-- =========================================================================
-- Q1. Does support pain actually predict churn, or does it just feel like it?
-- Technique: conditional aggregation + a control group.
-- =========================================================================
WITH tickets_last_quarter AS (
    SELECT s.customer_id,
           count(t.ticket_id) FILTER (
               WHERE t.created_at BETWEEN COALESCE(s.end_date, DATE '2026-06-30') - 90
                                      AND COALESCE(s.end_date, DATE '2026-06-30')
           ) AS tickets_90d,
           count(t.ticket_id) FILTER (WHERE t.severity IN ('High','Critical')) AS high_sev_all_time,
           avg(t.csat_score) AS avg_csat
    FROM subscriptions s
    LEFT JOIN support_tickets t ON t.customer_id = s.customer_id
    GROUP BY s.customer_id, s.end_date
)
SELECT
    CASE WHEN tickets_90d = 0 THEN '0 tickets'
         WHEN tickets_90d <= 2 THEN '1-2'
         WHEN tickets_90d <= 5 THEN '3-5'
         ELSE '6+' END                                     AS ticket_bucket,
    count(*)                                               AS accounts,
    round(avg(avg_csat), 2)                                AS avg_csat,
    round(100.0 * avg((s.status = 'Churned')::int), 1)     AS churn_rate_pct
FROM tickets_last_quarter t
JOIN subscriptions s USING (customer_id)
GROUP BY 1
ORDER BY min(tickets_90d);


-- =========================================================================
-- Q2. Are we discounting our way into churn?
-- Technique: NTILE bucketing + revenue-weighted rate.
-- Business question: deep discounts are supposed to save deals. Do they?
-- =========================================================================
WITH banded AS (
    SELECT customer_id, discount_pct, mrr, status,
           ntile(5) OVER (ORDER BY discount_pct) AS discount_quintile
    FROM subscriptions
)
SELECT discount_quintile,
       round(min(discount_pct), 1)                       AS min_discount,
       round(max(discount_pct), 1)                       AS max_discount,
       count(*)                                          AS accounts,
       round(100.0 * avg((status = 'Churned')::int), 1)  AS logo_churn_pct,
       round(100.0 * sum(mrr) FILTER (WHERE status = 'Churned') / NULLIF(sum(mrr), 0), 1)
                                                         AS revenue_churn_pct,
       round(sum(mrr) FILTER (WHERE status = 'Churned'))  AS mrr_lost
FROM banded
GROUP BY discount_quintile
ORDER BY discount_quintile;


-- =========================================================================
-- Q3. Silent decliners: accounts whose usage is collapsing but who have
--     never complained. These are invisible to a support-ticket-only view
--     and are exactly what a model earns its keep on.
-- Technique: LAG over a monthly series + anti-join.
-- =========================================================================
WITH trend AS (
    SELECT customer_id,
           month_start,
           logins,
           lag(logins, 3) OVER (PARTITION BY customer_id ORDER BY month_start) AS logins_3m_ago
    FROM usage_monthly
),
latest AS (
    SELECT DISTINCT ON (customer_id) customer_id, logins, logins_3m_ago
    FROM trend
    WHERE logins_3m_ago IS NOT NULL
    ORDER BY customer_id, month_start DESC
)
SELECT l.customer_id,
       c.company_name,
       s.mrr,
       l.logins_3m_ago,
       l.logins                                                    AS logins_now,
       round(100.0 * (l.logins - l.logins_3m_ago) / NULLIF(l.logins_3m_ago, 0), 0)
                                                                   AS pct_change
FROM latest l
JOIN subscriptions s USING (customer_id)
JOIN customers c USING (customer_id)
WHERE s.status = 'Active'
  AND l.logins < l.logins_3m_ago * 0.5
  AND NOT EXISTS (
      SELECT 1 FROM support_tickets t
      WHERE t.customer_id = l.customer_id
        AND t.created_at >= DATE '2026-03-31'
  )
ORDER BY s.mrr DESC
LIMIT 50;


-- =========================================================================
-- Q4. Net revenue retention by cohort - the metric investors ask for.
-- Technique: self-join on a month offset.
-- =========================================================================
WITH monthly AS (
    SELECT date_trunc('month', s.start_date)::date AS cohort_month,
           u.month_start,
           sum(s.mrr) AS mrr
    FROM usage_monthly u
    JOIN subscriptions s USING (customer_id)
    WHERE s.end_date IS NULL OR s.end_date >= u.month_start
    GROUP BY 1, 2
)
SELECT m0.cohort_month,
       round(m0.mrr)                                        AS starting_mrr,
       round(m12.mrr)                                       AS mrr_12m_later,
       round(100.0 * m12.mrr / NULLIF(m0.mrr, 0), 1)        AS nrr_pct
FROM monthly m0
JOIN monthly m12
  ON m12.cohort_month = m0.cohort_month
 AND m12.month_start = m0.month_start + interval '12 months'
WHERE m0.month_start = m0.cohort_month
ORDER BY m0.cohort_month;


-- =========================================================================
-- Q5. Where should the CS team spend Monday? Pareto of revenue at risk.
-- Technique: running total window function to find the 80/20 cut-off.
-- =========================================================================
WITH ranked AS (
    SELECT sc.customer_id,
           c.company_name,
           sc.revenue_at_risk,
           sum(sc.revenue_at_risk) OVER (ORDER BY sc.revenue_at_risk DESC
                                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
               AS cumulative_at_risk,
           sum(sc.revenue_at_risk) OVER () AS total_at_risk,
           row_number() OVER (ORDER BY sc.revenue_at_risk DESC) AS rn
    FROM scored_customers sc
    JOIN customers c USING (customer_id)
)
SELECT rn, company_name, round(revenue_at_risk) AS revenue_at_risk,
       round(100.0 * cumulative_at_risk / total_at_risk, 1) AS cumulative_pct_of_risk
FROM ranked
WHERE cumulative_at_risk <= total_at_risk * 0.80
ORDER BY rn;


-- =========================================================================
-- Q6. Model sanity check: do the accounts we flagged as high risk actually
--     look different on the raw facts? Never trust a score you cannot
--     corroborate with a groupby.
-- =========================================================================
SELECT risk_band,
       count(*)                                  AS accounts,
       round(avg(seat_utilisation) * 100, 1)     AS seat_util_pct,
       round(avg(feature_adoption) * 100, 1)     AS feature_adoption_pct,
       round(avg(t90_tickets), 2)                AS tickets_90d,
       round(avg(t90_avg_csat), 2)               AS csat,
       round(avg(late_payment_rate_180d) * 100, 1) AS late_payment_pct,
       round(avg(discount_pct), 1)               AS discount_pct,
       round(avg(tenure_months), 1)              AS tenure_months
FROM scored_customers
GROUP BY risk_band
ORDER BY avg(churn_probability_90d) DESC;
