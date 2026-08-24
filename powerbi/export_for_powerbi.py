"""
Export a Power BI ready star schema.
====================================

Power BI can connect straight to PostgreSQL (see powerbi/README.md), and that
is the better path if the database is running. This script exists for the case
where it is not: it flattens the warehouse into six CSVs shaped as a proper
star schema, so "Get Data -> Folder" gives you a working model in one click.

Why not just point Power BI at the raw tables?

  - `usage_monthly` is 700k+ rows of detail the report never shows. Importing
    it makes the .pbix huge and every visual slow.
  - Power BI needs a real date table to do time intelligence. There isn't one
    in the warehouse, so we build it here.
  - The cohort triangle and the monthly churn series are window-function work.
    Doing that in SQL/pandas once, on export, is far cheaper than doing it in
    DAX on every visual refresh.

Star schema produced in data/powerbi/:

    dim_date          one row per month, with a proper date key
    dim_customer      account attributes (no measures)
    dim_plan          plan and tier
    fact_scored       one row per active account - the main fact table
    fact_monthly      monthly active/churned counts and MRR
    fact_cohort       cohort retention triangle

Run:
    python powerbi/export_for_powerbi.py --data data/ --out data/powerbi/
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd


def build_dim_date(start, end):
    """Month grain. Power BI needs contiguous dates with no gaps."""
    months = pd.date_range(pd.Timestamp(start).replace(day=1),
                           pd.Timestamp(end).replace(day=1), freq="MS")
    d = pd.DataFrame({"date_key": months})
    d["year"] = d.date_key.dt.year
    d["quarter"] = "Q" + d.date_key.dt.quarter.astype(str)
    d["month_no"] = d.date_key.dt.month
    d["month_name"] = d.date_key.dt.strftime("%b")
    d["year_month"] = d.date_key.dt.strftime("%Y-%m")
    # Indian financial year runs April to March.
    d["fin_year"] = np.where(d.month_no >= 4,
                             "FY" + (d.year + 1).astype(str).str[-2:],
                             "FY" + d.year.astype(str).str[-2:])
    d["month_sort"] = d.year * 100 + d.month_no
    return d


def build_fact_monthly(subs):
    """Active and churned accounts per month, with MRR. Mirrors v_monthly_churn."""
    start = subs.start_date.min().replace(day=1)
    end = pd.Timestamp("2026-06-30").replace(day=1)
    rows = []
    for m in pd.date_range(start, end, freq="MS"):
        m_end = m + pd.offsets.MonthEnd(0)
        active = subs[(subs.start_date <= m_end) &
                      (subs.end_date.isna() | (subs.end_date >= m))]
        lost = subs[subs.end_date.notna() &
                    (subs.end_date >= m) & (subs.end_date <= m_end)]
        rows.append({
            "date_key": m,
            "active_accounts": len(active),
            "active_mrr": round(active.mrr.sum()),
            "churned_accounts": len(lost),
            "churned_mrr": round(lost.mrr.sum()),
        })
    f = pd.DataFrame(rows)
    f["logo_churn_pct"] = (100 * f.churned_accounts / f.active_accounts.clip(lower=1)).round(2)
    f["revenue_churn_pct"] = (100 * f.churned_mrr / f.active_mrr.clip(lower=1)).round(2)
    return f


def build_fact_cohort(subs, max_months=24):
    """Signup cohort by months-since-signup. Feeds the retention heatmap."""
    s = subs.copy()
    s["cohort_month"] = s.start_date.values.astype("datetime64[M]")
    sizes = s.groupby("cohort_month").size().rename("cohort_size")
    rows = []
    today = pd.Timestamp("2026-06-30")
    for cohort, grp in s.groupby("cohort_month"):
        for m in range(max_months + 1):
            asof = cohort + pd.DateOffset(months=m)
            if asof > today:
                break
            retained = int((grp.end_date.isna() | (grp.end_date >= asof)).sum())
            rows.append({"cohort_month": cohort, "months_since_signup": m,
                         "retained": retained})
    f = pd.DataFrame(rows).merge(sizes, on="cohort_month")
    f["retention_pct"] = (100 * f.retained / f.cohort_size).round(1)
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="data/powerbi")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    scored = pd.read_csv(f"{args.data}/scored_customers.csv")
    customers = pd.read_csv(f"{args.data}/customers.csv", parse_dates=["signup_date"])
    subs = pd.read_csv(f"{args.data}/subscriptions.csv",
                       parse_dates=["start_date", "end_date"])
    plans = pd.read_csv(f"{args.data}/plans.csv")

    # --- dimensions -------------------------------------------------------
    dim_customer = customers.merge(
        subs[["customer_id", "billing_cycle", "seats_licensed", "status"]],
        on="customer_id", how="left")
    dim_customer["signup_month"] = dim_customer.signup_date.values.astype("datetime64[M]")
    dim_customer = dim_customer[[
        "customer_id", "company_name", "signup_date", "signup_month", "segment",
        "industry", "acquisition_channel", "city", "state", "billing_cycle",
        "seats_licensed", "status"]]

    # --- main fact --------------------------------------------------------
    # One row per active account. Reason codes are flattened out of JSON,
    # because Power BI cannot filter or group on a nested column.
    fact = scored.copy()
    reasons = fact.reasons.apply(lambda v: json.loads(v) if isinstance(v, str) else [])
    for i in range(3):
        fact[f"reason_{i+1}"] = reasons.apply(lambda r: r[i]["label"] if len(r) > i else None)
        fact[f"reason_{i+1}_impact_pp"] = reasons.apply(
            lambda r: r[i]["impact_pp"] if len(r) > i else None)
    fact = fact.drop(columns=["reasons"])
    fact["scored_at"] = pd.to_datetime(fact.scored_at)
    fact["date_key"] = fact.scored_at.values.astype("datetime64[M]")

    # Pre-bucket the risk ladder so the histogram is a plain bar chart in
    # Power BI rather than a calculated-column exercise.
    fact["risk_bucket"] = pd.cut(
        fact.churn_probability_90d,
        bins=[i / 20 for i in range(21)],
        labels=[f"{i*5}-{(i+1)*5}%" for i in range(20)],
        include_lowest=True)
    fact["risk_bucket_sort"] = (fact.churn_probability_90d * 20).astype(int).clip(0, 19)

    fact_monthly = build_fact_monthly(subs)
    fact_cohort = build_fact_cohort(subs)
    dim_date = build_dim_date(subs.start_date.min(), "2026-06-30")

    out = {
        "dim_date": dim_date,
        "dim_customer": dim_customer,
        "dim_plan": plans,
        "fact_scored": fact,
        "fact_monthly": fact_monthly,
        "fact_cohort": fact_cohort,
    }
    for name, df in out.items():
        p = os.path.join(args.out, f"{name}.csv")
        df.to_csv(p, index=False)
        print(f"  {name:<14} {len(df):>8,} rows x {df.shape[1]:>2} cols  ->  {p}")

    print(f"\nIn Power BI Desktop: Get Data -> Folder -> {os.path.abspath(args.out)}")
    print("Then Combine & Transform, or import each CSV separately.")


if __name__ == "__main__":
    main()
