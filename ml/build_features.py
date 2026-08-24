"""
ChurnRadar - feature builder
============================

The single most important idea in this whole project:

    A churn model must only ever see data that existed BEFORE the moment it
    is asked to predict.

So we work with *snapshots*. A snapshot has two parts:

    observation window            prediction window
    <---- 12 months ------|------ 90 days ------->
                    snapshot_date

  - Features are built ONLY from rows dated on or before `snapshot_date`.
  - The label is 1 if the customer churned inside the 90 days AFTER it.

If you skip this and just compute "tickets in the last 90 days" over the whole
table, you leak the future into the past, get 0.99 AUC in training, and the
model falls over in production. This is the #1 mistake in churn projects and
being able to explain it is worth more in an interview than the model itself.

We build two snapshots:
  TRAIN  2025-09-30  -> label known (we have data through 2026-06-30)
  VALID  2025-12-31  -> label known, used as an out-of-time test set
  SCORE  2026-06-30  -> label unknown, this is what the dashboard shows

Run:
    python ml/build_features.py --data data/ --out data/
"""

from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd

HORIZON_DAYS = 90

SNAPSHOTS = {
    "train": pd.Timestamp("2025-09-30"),
    "valid": pd.Timestamp("2025-12-31"),
    "score": pd.Timestamp("2026-06-30"),
}


def load(data_dir: str) -> dict[str, pd.DataFrame]:
    t = {}
    for name, dates in {
        "customers": ["signup_date"],
        "subscriptions": ["start_date", "end_date"],
        "usage_monthly": ["month_start"],
        "support_tickets": ["created_at"],
        "invoices": ["invoice_date"],
        "churn_events": ["churn_date"],
        "plans": [],
    }.items():
        t[name] = pd.read_csv(os.path.join(data_dir, f"{name}.csv"), parse_dates=dates)
    return t


def window_agg(df, date_col, snap, days, by="customer_id", aggs=None, prefix=""):
    """Aggregate rows falling in (snap - days, snap]."""
    lo = snap - pd.Timedelta(days=days)
    w = df[(df[date_col] > lo) & (df[date_col] <= snap)]
    if w.empty:
        return pd.DataFrame(columns=[by])
    out = w.groupby(by).agg(**aggs).reset_index()
    out.columns = [by] + [f"{prefix}{c}" for c in out.columns[1:]]
    return out


def build_snapshot(t: dict, snap: pd.Timestamp, with_label: bool) -> pd.DataFrame:
    subs = t["subscriptions"]
    churn = t["churn_events"]

    # --- who is even a customer at this point in time? --------------------
    # Alive = signed up on/before the snapshot AND not churned on/before it.
    churn_map = churn.set_index("customer_id")["churn_date"]
    base = subs.merge(t["customers"], on="customer_id", how="left")
    base["churn_date"] = base["customer_id"].map(churn_map)
    alive = base[(base["start_date"] <= snap) &
                 (base["churn_date"].isna() | (base["churn_date"] > snap))].copy()

    f = alive[[
        "customer_id", "segment", "industry", "acquisition_channel", "state",
        "plan_id", "mrr", "discount_pct", "billing_cycle", "seats_licensed", "signup_date",
    ]].copy()
    f = f.merge(t["plans"][["plan_id", "tier", "features_available"]], on="plan_id", how="left")

    f["tenure_months"] = ((snap - f["signup_date"]).dt.days / 30.44).round(1)
    f["arr"] = f["mrr"] * 12

    # --- usage ------------------------------------------------------------
    u = t["usage_monthly"]
    u = u[u["month_start"] <= snap]

    last3 = window_agg(u, "month_start", snap, 92, aggs=dict(
        logins=("logins", "sum"), active_days=("active_days", "sum"),
        seats_active=("seats_active", "mean"), features_used=("features_used", "mean"),
        api_calls=("api_calls", "sum")), prefix="u3m_")
    prev3 = window_agg(u, "month_start", snap - pd.Timedelta(days=92), 92, aggs=dict(
        logins=("logins", "sum"), seats_active=("seats_active", "mean"),
        api_calls=("api_calls", "sum")), prefix="u_prev3m_")
    last1 = window_agg(u, "month_start", snap, 31, aggs=dict(
        logins=("logins", "sum"), active_days=("active_days", "sum"),
        seats_active=("seats_active", "mean")), prefix="u1m_")

    f = f.merge(last3, on="customer_id", how="left").merge(prev3, on="customer_id", how="left") \
         .merge(last1, on="customer_id", how="left")

    for c in [c for c in f.columns if c.startswith("u")]:
        f[c] = f[c].fillna(0)

    f["seat_utilisation"] = (f["u3m_seats_active"] / f["seats_licensed"].clip(lower=1)).clip(0, 1)
    f["feature_adoption"] = (f["u3m_features_used"] / f["features_available"].clip(lower=1)).clip(0, 1)
    f["logins_per_seat_3m"] = f["u3m_logins"] / f["seats_licensed"].clip(lower=1)
    f["active_day_rate_3m"] = (f["u3m_active_days"] / 66).clip(0, 1)   # 66 = ~3 months of working days

    # Trend: last 3 months vs the 3 months before that. Negative = shrinking.
    f["login_trend_pct"] = np.where(
        f["u_prev3m_logins"] > 0,
        (f["u3m_logins"] - f["u_prev3m_logins"]) / f["u_prev3m_logins"],
        0.0,
    ).clip(-1, 3)
    f["seat_trend_pct"] = np.where(
        f["u_prev3m_seats_active"] > 0,
        (f["u3m_seats_active"] - f["u_prev3m_seats_active"]) / f["u_prev3m_seats_active"],
        0.0,
    ).clip(-1, 3)

    # Recency: how long since we last saw any activity at all.
    last_active = u[u["logins"] > 0].groupby("customer_id")["month_start"].max()
    f["months_since_activity"] = ((snap - f["customer_id"].map(last_active)).dt.days / 30.44)
    f["months_since_activity"] = f["months_since_activity"].fillna(99).clip(0, 99).round(1)

    # --- support ----------------------------------------------------------
    tk = t["support_tickets"]
    tk = tk[tk["created_at"] <= snap].copy()
    tk["is_high_sev"] = tk["severity"].isin(["High", "Critical"]).astype(int)

    t90 = window_agg(tk, "created_at", snap, 90, aggs=dict(
        tickets=("ticket_id", "count"), high_sev=("is_high_sev", "sum"),
        escalations=("is_escalated", "sum"), avg_csat=("csat_score", "mean"),
        avg_resolution_h=("resolution_hours", "mean")), prefix="t90_")
    t365 = window_agg(tk, "created_at", snap, 365, aggs=dict(
        tickets=("ticket_id", "count"), avg_csat=("csat_score", "mean")), prefix="t365_")

    f = f.merge(t90, on="customer_id", how="left").merge(t365, on="customer_id", how="left")
    for c in ["t90_tickets", "t90_high_sev", "t90_escalations", "t365_tickets"]:
        f[c] = f[c].fillna(0)
    for c in ["t90_avg_csat", "t365_avg_csat"]:
        f[c] = f[c].fillna(4.0)          # no news is neutral news
    f["t90_avg_resolution_h"] = f["t90_avg_resolution_h"].fillna(0)
    f["tickets_per_seat_90d"] = f["t90_tickets"] / f["seats_licensed"].clip(lower=1)

    # --- billing ----------------------------------------------------------
    inv = t["invoices"]
    inv = inv[inv["invoice_date"] <= snap].copy()
    inv["is_late"] = (inv["days_late"] > 0).astype(int)
    inv["is_failed"] = (inv["status"] == "Failed").astype(int)

    i180 = window_agg(inv, "invoice_date", snap, 180, aggs=dict(
        invoices=("invoice_id", "count"), late=("is_late", "sum"),
        failed=("is_failed", "sum"), avg_days_late=("days_late", "mean"),
        max_days_late=("days_late", "max")), prefix="p180_")
    f = f.merge(i180, on="customer_id", how="left")
    for c in ["p180_invoices", "p180_late", "p180_failed", "p180_avg_days_late", "p180_max_days_late"]:
        f[c] = f[c].fillna(0)
    f["late_payment_rate_180d"] = f["p180_late"] / f["p180_invoices"].clip(lower=1)

    # --- label ------------------------------------------------------------
    f["snapshot_date"] = snap
    if with_label:
        end = snap + pd.Timedelta(days=HORIZON_DAYS)
        cd = f["customer_id"].map(churn_map)
        f["churned_90d"] = ((cd > snap) & (cd <= end)).astype(int)

    drop = ["signup_date", "plan_id", "u_prev3m_logins", "u_prev3m_seats_active",
            "u_prev3m_api_calls", "u3m_features_used"]
    return f.drop(columns=[c for c in drop if c in f.columns])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    t = load(args.data)
    for name, snap in SNAPSHOTS.items():
        with_label = name != "score"
        df = build_snapshot(t, snap, with_label)
        path = os.path.join(args.out, f"features_{name}.csv")
        df.to_csv(path, index=False)
        rate = f"{df['churned_90d'].mean():.2%}" if with_label else "n/a (future)"
        print(f"{name:<6} snapshot={snap.date()}  rows={len(df):>8,}  90-day churn={rate}  -> {path}")


if __name__ == "__main__":
    main()
