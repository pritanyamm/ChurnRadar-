-- ChurnRadar - warehouse schema (PostgreSQL)
-- Run:  psql -d churnradar -f sql/01_schema.sql

DROP TABLE IF EXISTS scored_customers, churn_events, invoices, support_tickets,
                     usage_monthly, subscriptions, customers, plans CASCADE;

-- Reference ------------------------------------------------------------

CREATE TABLE plans (
    plan_id             SMALLINT PRIMARY KEY,
    plan_name           TEXT NOT NULL,
    tier                TEXT NOT NULL,
    base_price_per_seat NUMERIC(10,2) NOT NULL,
    features_available  SMALLINT NOT NULL
);

-- Dimension ------------------------------------------------------------

CREATE TABLE customers (
    customer_id         BIGINT PRIMARY KEY,
    company_name        TEXT NOT NULL,
    signup_date         DATE NOT NULL,
    segment             TEXT NOT NULL,
    industry            TEXT,
    acquisition_channel TEXT,
    city                TEXT,
    state               TEXT
);

CREATE TABLE subscriptions (
    subscription_id BIGINT PRIMARY KEY,
    customer_id     BIGINT NOT NULL REFERENCES customers(customer_id),
    plan_id         SMALLINT NOT NULL REFERENCES plans(plan_id),
    start_date      DATE NOT NULL,
    end_date        DATE,                       -- NULL while active
    status          TEXT NOT NULL CHECK (status IN ('Active','Churned')),
    mrr             NUMERIC(12,2) NOT NULL,
    discount_pct    NUMERIC(5,2) NOT NULL DEFAULT 0,
    billing_cycle   TEXT NOT NULL CHECK (billing_cycle IN ('Monthly','Annual')),
    seats_licensed  INTEGER NOT NULL
);

-- Facts ----------------------------------------------------------------

CREATE TABLE usage_monthly (
    customer_id        BIGINT NOT NULL REFERENCES customers(customer_id),
    month_start        DATE   NOT NULL,
    logins             INTEGER NOT NULL,
    active_days        SMALLINT NOT NULL,
    seats_active       INTEGER NOT NULL,
    features_used      SMALLINT NOT NULL,
    features_available SMALLINT NOT NULL,
    api_calls          BIGINT NOT NULL,
    PRIMARY KEY (customer_id, month_start)
);

CREATE TABLE support_tickets (
    ticket_id        BIGINT PRIMARY KEY,
    customer_id      BIGINT NOT NULL REFERENCES customers(customer_id),
    created_at       DATE NOT NULL,
    category         TEXT,
    severity         TEXT CHECK (severity IN ('Low','Medium','High','Critical')),
    resolution_hours NUMERIC(8,1),
    csat_score       SMALLINT CHECK (csat_score BETWEEN 1 AND 5),
    is_escalated     SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE invoices (
    invoice_id   BIGINT PRIMARY KEY,
    customer_id  BIGINT NOT NULL REFERENCES customers(customer_id),
    invoice_date DATE NOT NULL,
    amount       NUMERIC(12,2) NOT NULL,
    days_late    INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL CHECK (status IN ('Paid','Paid Late','Failed'))
);

CREATE TABLE churn_events (
    customer_id  BIGINT PRIMARY KEY REFERENCES customers(customer_id),
    churn_date   DATE NOT NULL,
    churn_reason TEXT
);

-- Model output ---------------------------------------------------------
-- Written by ml/train_model.py. The dashboard reads only this table plus
-- the dimensions, which keeps the API fast and the model swappable.

CREATE TABLE scored_customers (
    customer_id            BIGINT PRIMARY KEY REFERENCES customers(customer_id),
    segment                TEXT,
    industry               TEXT,
    state                  TEXT,
    tier                   TEXT,
    billing_cycle          TEXT,
    mrr                    NUMERIC(12,2),
    arr                    NUMERIC(14,2),
    discount_pct           NUMERIC(5,2),
    tenure_months          NUMERIC(6,1),
    seats_licensed         INTEGER,
    seat_utilisation       NUMERIC(5,4),
    feature_adoption       NUMERIC(5,4),
    login_trend_pct        NUMERIC(6,3),
    t90_tickets            NUMERIC(6,1),
    t90_avg_csat           NUMERIC(4,2),
    late_payment_rate_180d NUMERIC(5,4),
    months_since_activity  NUMERIC(6,1),
    churn_probability_90d  NUMERIC(6,4) NOT NULL,
    churn_probability_12m  NUMERIC(6,4) NOT NULL,
    risk_band              TEXT CHECK (risk_band IN ('Low','Watch','High','Critical')),
    gross_margin_arr       NUMERIC(14,2),
    revenue_at_risk        NUMERIC(14,2),
    price_sensitivity      NUMERIC(5,3),
    reasons                JSONB,
    primary_reason         TEXT,
    scored_at              DATE NOT NULL
);

-- Indexes ---------------------------------------------------------------
-- Every one of these exists because a specific dashboard query needs it.

CREATE INDEX idx_usage_month        ON usage_monthly (month_start);
CREATE INDEX idx_tickets_cust_date  ON support_tickets (customer_id, created_at DESC);
CREATE INDEX idx_invoices_cust_date ON invoices (customer_id, invoice_date DESC);
CREATE INDEX idx_subs_status        ON subscriptions (status);
CREATE INDEX idx_scored_risk        ON scored_customers (churn_probability_90d DESC);
CREATE INDEX idx_scored_rar         ON scored_customers (revenue_at_risk DESC);
CREATE INDEX idx_scored_band        ON scored_customers (risk_band, segment);
