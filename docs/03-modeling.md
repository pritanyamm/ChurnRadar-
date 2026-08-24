# 3. Modeling

## Snapshots, and the mistake almost everyone makes

A churn model must only ever see data that existed *before* the moment it is
asked to predict. The way to guarantee that is to work with snapshots:

```
        observation window                prediction window
   <-------- 12 months --------|--------- 90 days --------->
                        snapshot_date
                    (features end here)          (label lives here)
```

Three snapshots are built:

| Name | Date | Label | Purpose |
|---|---|---|---|
| `train` | 2025-09-30 | known | Fit the model |
| `valid` | 2025-12-31 | known | **Out-of-time** evaluation |
| `score` | 2026-06-30 | unknown | What the dashboard shows |

### The leakage trap

The tempting shortcut is to compute features over the entire table — "tickets
in the last 90 days" using every row you have. On a churned customer, "the last
90 days" silently becomes the 90 days *before they left*, which is exactly the
period when everything went wrong. The model learns "accounts with a spike of
tickets right before their end date churn", scores 0.99 AUC, and predicts
nothing useful in production because at prediction time there is no end date.

Every aggregate in `build_features.py` goes through `window_agg()`, which
filters `date > snap - days AND date <= snap`. Nothing else touches the fact
tables.

### Why not a random train/test split?

Because a customer's September row and their December row are nearly the same
row. A random split puts one in train and one in test, the model effectively
memorises the customer, and the test score is inflated. Splitting by *time*
instead answers the question you actually care about: does a model fit on last
quarter work on this one?

The out-of-time gap is visible in the results and worth pointing at: the
December base rate (8.4%) is higher than September's (6.1%). The model
consequently under-predicts slightly in the top decile. That is a real
distribution shift, honestly reported, and it is the argument for retraining on
a schedule rather than shipping once.

## Features

40 features in five families. Every one is something a CS team could see on a
Monday morning.

| Family | Examples |
|---|---|
| **Contract** | `tenure_months`, `mrr`, `discount_pct`, `billing_cycle`, `tier`, `seats_licensed` |
| **Engagement** | `seat_utilisation`, `feature_adoption`, `active_day_rate_3m`, `logins_per_seat_3m`, `u3m_api_calls` |
| **Momentum** | `login_trend_pct`, `seat_trend_pct`, `months_since_activity` — last 3 months against the 3 before |
| **Support** | `t90_tickets`, `t90_high_sev`, `t90_escalations`, `t90_avg_csat`, `t90_avg_resolution_h`, `tickets_per_seat_90d` |
| **Billing** | `late_payment_rate_180d`, `p180_avg_days_late`, `p180_max_days_late`, `p180_failed` |

Two design notes:

**Ratios beat raw counts.** A 200-seat account raising 6 tickets is healthy; a
4-seat account raising 6 tickets is on fire. `tickets_per_seat_90d` carries that;
`t90_tickets` alone does not.

**Momentum beats level.** An account at 40% seat utilisation that was at 80%
three months ago is in more trouble than one that has sat at 40% for two years.
The trend features exist because the level features cannot express that.

## Model

`HistGradientBoostingClassifier` wrapped in `CalibratedClassifierCV(isotonic)`.

**Why gradient boosting?** Tabular data with mixed types, non-linear
interactions and native categorical support. Logistic regression is a
reasonable baseline and would be a good addition; a neural network would be
worse and slower here.

**Why isotonic calibration?** Because the dashboard multiplies probability by
rupees. Raw boosted-tree scores are ranked well but poorly calibrated — they
pile up at the extremes. Isotonic regression maps them back onto observed
frequencies. The training script prints a reliability table so this is checked,
not assumed.

**Why not SMOTE or class weights?** Resampling changes the base rate, which
destroys calibration — the exact property this project needs most. An 8% base
rate is not severe imbalance; gradient boosting handles it. This is a common
reflex worth resisting deliberately.

## Reason codes

A global feature-importance chart tells you what matters on average. It does
not tell a CSM why *this* account is at risk, which is what they need before
picking up the phone.

For each account and each candidate driver, the account is re-scored with that
one feature swapped to a healthy reference value (a quantile of the training
population). The drop in predicted risk is that feature's contribution:

```
contribution(f) = p(customer) − p(customer with f set to healthy)
```

The top three positive contributions become the reason codes. Two guards:

- The swap only ever moves a feature in the *healthier* direction, so a
  strength never gets reported as a weakness.
- Contributions below 0.4 percentage points are dropped, which is why some
  accounts show "No clear signal" — an honest answer that beats a fabricated one.

This is a simplified SHAP. Real SHAP is better (it handles interactions and
sums exactly to the prediction) and is the natural upgrade. This version needs
no extra dependency and is trivial to explain to a non-technical stakeholder:
*"if their seat usage were normal, their risk would drop from 41% to 22% — so
seat usage is the problem."*

The same contributions produce `price_sensitivity`: the share of an account's
total positive contribution coming from price and payment features. That single
number is what tells the retention simulator whether money can fix this.

## What would make it better

Ranked by expected payoff:

1. **A holdout experiment.** Offline metrics measure prediction, not
   intervention. Withhold outreach from a random 20% of the at-risk list and
   measure the difference in survival.
2. **Survival analysis** (Cox or an accelerated failure time model) to predict
   *when*, not just whether — better for scheduling outreach.
3. **Uplift modeling** for the simulator. Right now the response to a discount
   is an assumed curve. With real offer/outcome data it should be a learned
   two-model or transformed-outcome estimate.
4. **Contraction and downgrade** as separate targets. Revenue leaves through
   seat reductions long before the logo does.
5. **Drift monitoring.** Population Stability Index on each feature, alerting
   when the input distribution moves away from the training snapshot.
