-- ChurnRadar - load CSVs into PostgreSQL
-- Run from the project root:  psql -d churnradar -f sql/02_load.sql
-- \copy runs client-side, so it works on managed Postgres (Neon, Supabase,
-- RDS) where the server cannot see your local disk.

\copy plans            FROM 'data/plans.csv'            CSV HEADER
\copy customers        FROM 'data/customers.csv'        CSV HEADER
\copy subscriptions    FROM 'data/subscriptions.csv'    CSV HEADER
\copy usage_monthly    FROM 'data/usage_monthly.csv'    CSV HEADER
\copy support_tickets  FROM 'data/support_tickets.csv'  CSV HEADER
\copy invoices         FROM 'data/invoices.csv'         CSV HEADER
\copy churn_events     FROM 'data/churn_events.csv'     CSV HEADER

-- Load model scores last (run after ml/train_model.py).
\copy scored_customers FROM 'data/scored_customers.csv' CSV HEADER

ANALYZE;

SELECT 'customers'  AS table, count(*) FROM customers
UNION ALL SELECT 'subscriptions',   count(*) FROM subscriptions
UNION ALL SELECT 'usage_monthly',   count(*) FROM usage_monthly
UNION ALL SELECT 'support_tickets', count(*) FROM support_tickets
UNION ALL SELECT 'invoices',        count(*) FROM invoices
UNION ALL SELECT 'churn_events',    count(*) FROM churn_events
UNION ALL SELECT 'scored',          count(*) FROM scored_customers;
