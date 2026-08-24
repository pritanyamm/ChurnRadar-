# 2. Data dictionary

Eight tables. Seven are raw facts and dimensions; `scored_customers` is model
output. All money is INR.

## `plans` — reference

| Column | Type | Notes |
|---|---|---|
| `plan_id` | smallint PK | 1–4 |
| `plan_name`, `tier` | text | Starter, Growth, Business, Enterprise |
| `base_price_per_seat` | numeric | Before volume and negotiated discounts |
| `features_available` | smallint | Denominator for the adoption ratio |

## `customers` — dimension

| Column | Type | Notes |
|---|---|---|
| `customer_id` | bigint PK | |
| `company_name` | text | Synthetic |
| `signup_date` | date | Drives tenure and the cohort analysis |
| `segment` | text | SMB / Mid-Market / Enterprise |
| `industry`, `acquisition_channel`, `city`, `state` | text | |

## `subscriptions` — one per customer

| Column | Type | Notes |
|---|---|---|
| `subscription_id` | bigint PK | |
| `customer_id` | bigint FK | |
| `plan_id` | smallint FK | |
| `start_date` | date | |
| `end_date` | date | **NULL while active.** The churn date otherwise. |
| `status` | text | Active / Churned |
| `mrr` | numeric | Net of discount |
| `discount_pct` | numeric | 0–55 |
| `billing_cycle` | text | Monthly / Annual |
| `seats_licensed` | integer | Denominator for seat utilisation |

## `usage_monthly` — one row per customer per month

| Column | Type | Notes |
|---|---|---|
| `customer_id`, `month_start` | composite PK | |
| `logins` | integer | Total sessions |
| `active_days` | smallint | Days with any activity, 0–22 working days |
| `seats_active` | integer | Seats that logged in at all |
| `features_used` | smallint | Distinct features touched |
| `features_available` | smallint | From the plan |
| `api_calls` | bigint | Depth-of-integration proxy — high API usage means switching cost |

## `support_tickets` — one row per ticket

| Column | Type | Notes |
|---|---|---|
| `ticket_id` | bigint PK | |
| `customer_id` | bigint FK | |
| `created_at` | date | |
| `category` | text | Billing, Bug, How-to, Integration, Performance, Feature Request, Outage |
| `severity` | text | Low / Medium / High / Critical |
| `resolution_hours` | numeric | Time to close |
| `csat_score` | smallint | 1–5, NULL if not surveyed |
| `is_escalated` | smallint | 0/1 |

## `invoices` — one row per billing event

Monthly plans bill every month; annual plans bill in their anniversary month.

| Column | Type | Notes |
|---|---|---|
| `invoice_id` | bigint PK | |
| `customer_id` | bigint FK | |
| `invoice_date` | date | |
| `amount` | numeric | Annual invoices carry a 10% prepay discount |
| `days_late` | integer | 0 if paid on time |
| `status` | text | Paid / Paid Late / Failed |

## `churn_events`

| Column | Type | Notes |
|---|---|---|
| `customer_id` | bigint PK | |
| `churn_date` | date | |
| `churn_reason` | text | Ground truth from the generator. **Never used as a feature** — it is the answer key, and in a real company it would only be recorded after the fact. |

## `scored_customers` — model output

Written by `ml/train_model.py`, read by the API and Power BI.

| Column | Notes |
|---|---|
| `churn_probability_90d` | Calibrated probability |
| `churn_probability_12m` | `1 − (1 − p90)⁴`, used for all money maths |
| `risk_band` | Low / Watch / High / Critical |
| `revenue_at_risk` | `arr × churn_probability_12m` — an expectation, not a worst case |
| `gross_margin_arr` | ARR × 0.78 |
| `price_sensitivity` | Share of this account's risk attributable to price and payment features. Drives the simulator. |
| `reasons` | JSONB array of up to 3 `{feature, label, impact_pp}` |
| `primary_reason` | The strongest one, denormalised for fast grouping |
| `scored_at` | Snapshot date |

## How the data is generated

Each customer gets a hidden health trajectory plus three independent failure
channels — a support crisis (16% of accounts), a billing squeeze (13%), and
price pressure from their own finance team (18%). Observable columns are
produced *from* those hidden states, then churn is sampled from a hazard
function combining health, tenure, recent tickets, payment lateness, discount
depth, seat utilisation and contract type.

The independence of the failure channels is what makes the reason codes useful.
Without it, every unhealthy account looks identical and the model degenerates
into a single "engagement" axis.
