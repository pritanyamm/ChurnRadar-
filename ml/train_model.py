"""
ChurnRadar - model training and scoring
=======================================

Trains a gradient-boosted tree to answer: "will this account churn in the
next 90 days?", validates it on a LATER snapshot (out-of-time), then scores
today's customer base and writes a table the dashboard can read.

Three things make this more than a toy:

1. Out-of-time validation.
   Random train/test splits lie to you in churn problems, because a customer's
   September behaviour and December behaviour are almost the same row. We train
   on the Sep-2025 snapshot and test on the Dec-2025 snapshot - different
   customers, different market conditions, honest number.

2. Calibrated probabilities.
   The dashboard multiplies probability by rupees. If the model says 0.30 and
   only 12% of those accounts actually leave, every rupee figure is wrong. We
   fit isotonic calibration and print a reliability table.

3. Per-customer reasons, not just a score.
   For each account we re-score it with one feature swapped to a healthy
   reference value. The drop in predicted risk is that feature's contribution.
   This is a simplified SHAP, but it needs no extra dependency and is trivial
   to explain to a business stakeholder: "if their seat usage were normal,
   their risk would fall from 41% to 22% - that is the seat usage problem."

Run:
    python ml/train_model.py --data data/ --artifacts ml/artifacts/
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

TARGET = "churned_90d"
ID_COLS = ["customer_id", "snapshot_date"]

CATEGORICAL = ["segment", "industry", "acquisition_channel", "state", "billing_cycle", "tier"]

# Features we are willing to show a human as a "reason", and the value we
# consider healthy. `q` means "use this quantile of the training population".
REASON_DRIVERS = {
    "seat_utilisation":        {"q": 0.75, "label": "Seats sitting unused"},
    "feature_adoption":        {"q": 0.75, "label": "Shallow product adoption"},
    "login_trend_pct":         {"q": 0.75, "label": "Usage trending down"},
    "months_since_activity":   {"q": 0.10, "label": "Gone quiet recently"},
    "active_day_rate_3m":      {"q": 0.75, "label": "Logs in rarely"},
    "t90_tickets":             {"q": 0.25, "label": "Heavy support load"},
    "t90_high_sev":            {"q": 0.10, "label": "Serious unresolved issues"},
    "t90_avg_csat":            {"q": 0.75, "label": "Unhappy with support"},
    "t90_avg_resolution_h":    {"q": 0.25, "label": "Slow ticket resolution"},
    "late_payment_rate_180d":  {"q": 0.10, "label": "Paying late"},
    "p180_failed":             {"q": 0.10, "label": "Failed payments"},
    "discount_pct":            {"q": 0.25, "label": "Price sensitive (deep discount)"},
    "tenure_months":           {"q": 0.75, "label": "Still early in lifecycle"},
}

# Which drivers a *discount* can realistically fix. Used by the simulator.
PRICE_DRIVERS = {"discount_pct", "late_payment_rate_180d", "p180_failed"}


def split_xy(df: pd.DataFrame):
    y = df[TARGET].to_numpy() if TARGET in df else None
    X = df.drop(columns=[c for c in ID_COLS + [TARGET] if c in df.columns])
    for c in CATEGORICAL:
        if c in X:
            X[c] = X[c].astype("category")
    return X, y


def reliability_table(y, p, bins=10):
    q = pd.qcut(p, bins, labels=False, duplicates="drop")
    return pd.DataFrame({"y": y, "p": p, "bin": q}).groupby("bin").agg(
        accounts=("y", "size"), predicted=("p", "mean"), actual=("y", "mean")
    ).reset_index(drop=True)


def lift_table(y, p, deciles=10):
    order = np.argsort(-p)
    y, p = y[order], p[order]
    n = len(y)
    base = y.mean()
    rows = []
    for d in range(deciles):
        lo, hi = int(n * d / deciles), int(n * (d + 1) / deciles)
        seg = y[lo:hi]
        rows.append({
            "decile": d + 1,
            "accounts": len(seg),
            "avg_score": p[lo:hi].mean().round(4),
            "actual_churn": seg.mean().round(4),
            "lift": round(seg.mean() / base, 2) if base else 0,
            "share_of_all_churn": round(seg.sum() / y.sum(), 3) if y.sum() else 0,
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--artifacts", default="ml/artifacts")
    ap.add_argument("--gross-margin", type=float, default=0.78)
    args = ap.parse_args()
    os.makedirs(args.artifacts, exist_ok=True)

    train = pd.read_csv(os.path.join(args.data, "features_train.csv"), parse_dates=["snapshot_date"])
    valid = pd.read_csv(os.path.join(args.data, "features_valid.csv"), parse_dates=["snapshot_date"])
    score = pd.read_csv(os.path.join(args.data, "features_score.csv"), parse_dates=["snapshot_date"])

    Xtr, ytr = split_xy(train)
    Xva, yva = split_xy(valid)
    Xsc, _ = split_xy(score)
    Xva = Xva[Xtr.columns]
    Xsc = Xsc[Xtr.columns]

    cat_mask = [c in CATEGORICAL for c in Xtr.columns]

    print(f"Train {Xtr.shape}  churn={ytr.mean():.2%}   |   Valid {Xva.shape}  churn={yva.mean():.2%}")

    base = HistGradientBoostingClassifier(
        max_iter=400,
        learning_rate=0.06,
        max_leaf_nodes=31,
        min_samples_leaf=40,
        l2_regularization=1.0,
        categorical_features=cat_mask,
        early_stopping=True,
        validation_fraction=0.15,
        random_state=42,
    )
    # Isotonic calibration on top, fitted with internal CV so probabilities
    # can be trusted as probabilities.
    model = CalibratedClassifierCV(base, method="isotonic", cv=4)
    model.fit(Xtr, ytr)

    p_va = model.predict_proba(Xva)[:, 1]
    metrics = {
        "roc_auc": round(float(roc_auc_score(yva, p_va)), 4),
        "pr_auc": round(float(average_precision_score(yva, p_va)), 4),
        "brier": round(float(brier_score_loss(yva, p_va)), 5),
        "base_rate": round(float(yva.mean()), 4),
        "train_snapshot": str(train["snapshot_date"].iloc[0].date()),
        "valid_snapshot": str(valid["snapshot_date"].iloc[0].date()),
        "n_train": int(len(Xtr)),
        "n_valid": int(len(Xva)),
    }
    print("\n--- Out-of-time validation -------------------------------")
    for k, v in metrics.items():
        print(f"  {k:<16} {v}")

    lift = lift_table(yva, p_va)
    print("\n--- Lift by risk decile (decile 1 = riskiest) ------------")
    print(lift.to_string(index=False))
    top2 = lift.head(2)["share_of_all_churn"].sum()
    print(f"\n  Top 20% of accounts by score contain {top2:.0%} of all churn.")

    rel = reliability_table(yva, p_va)
    print("\n--- Calibration ------------------------------------------")
    print(rel.round(4).to_string(index=False))

    # --- global drivers ---------------------------------------------------
    sub = np.random.default_rng(0).choice(len(Xva), size=min(4000, len(Xva)), replace=False)
    imp = permutation_importance(model, Xva.iloc[sub], yva[sub], n_repeats=4,
                                 random_state=42, scoring="roc_auc")
    importance = (pd.DataFrame({"feature": Xtr.columns, "importance": imp.importances_mean})
                  .sort_values("importance", ascending=False).reset_index(drop=True))
    print("\n--- Top global drivers -----------------------------------")
    print(importance.head(12).round(5).to_string(index=False))

    # --- score today's base ----------------------------------------------
    print("\nScoring current customer base...")
    p_now = model.predict_proba(Xsc)[:, 1]

    # Reference ("healthy") values taken from the training population.
    reference = {}
    for feat, cfg in REASON_DRIVERS.items():
        if feat in Xtr.columns:
            reference[feat] = float(np.nanquantile(Xtr[feat].astype(float), cfg["q"]))

    # Counterfactual attribution: swap one feature to healthy, re-score.
    contrib = {}
    for feat, ref in reference.items():
        Xcf = Xsc.copy()
        # Only counterfactual in the *healthier* direction, otherwise we would
        # "explain" a strength as a weakness.
        worse_is_higher = feat in {"months_since_activity", "t90_tickets", "t90_high_sev",
                                   "t90_avg_resolution_h", "late_payment_rate_180d",
                                   "p180_failed", "discount_pct"}
        cur = Xcf[feat].astype(float)
        Xcf[feat] = np.minimum(cur, ref) if worse_is_higher else np.maximum(cur, ref)
        contrib[feat] = p_now - model.predict_proba(Xcf)[:, 1]
    contrib = pd.DataFrame(contrib, index=score.index)

    price_share = (contrib[[c for c in contrib.columns if c in PRICE_DRIVERS]].clip(lower=0).sum(axis=1)
                   / contrib.clip(lower=0).sum(axis=1).replace(0, np.nan)).fillna(0.2).clip(0, 1)

    top3 = []
    for i in range(len(contrib)):
        row = contrib.iloc[i]
        picks = row[row > 0.004].sort_values(ascending=False).head(3)
        top3.append([{"feature": k,
                      "label": REASON_DRIVERS[k]["label"],
                      "impact_pp": round(float(v) * 100, 1)} for k, v in picks.items()])

    # --- economics --------------------------------------------------------
    out = score[["customer_id"]].copy()
    for c in ["segment", "industry", "state", "tier", "billing_cycle", "mrr", "arr",
              "discount_pct", "tenure_months", "seats_licensed", "seat_utilisation",
              "feature_adoption", "login_trend_pct", "t90_tickets", "t90_avg_csat",
              "late_payment_rate_180d", "months_since_activity"]:
        out[c] = score[c].values

    out["churn_probability_90d"] = p_now.round(4)
    # Convert a 90-day probability into an annual one: surviving 4 quarters.
    out["churn_probability_12m"] = (1 - (1 - p_now) ** 4).round(4)
    out["risk_band"] = pd.cut(p_now, [-0.01, 0.05, 0.15, 0.35, 1.01],
                              labels=["Low", "Watch", "High", "Critical"])
    out["gross_margin_arr"] = (out["arr"] * args.gross_margin).round(0)
    out["revenue_at_risk"] = (out["arr"] * out["churn_probability_12m"]).round(0)
    out["price_sensitivity"] = price_share.round(3).values
    out["reasons"] = [json.dumps(r) for r in top3]
    out["primary_reason"] = [r[0]["label"] if r else "No clear signal" for r in top3]
    out["scored_at"] = score["snapshot_date"].iloc[0].date()

    out = out.sort_values("revenue_at_risk", ascending=False)
    out.to_csv(os.path.join(args.data, "scored_customers.csv"), index=False)

    import joblib
    joblib.dump({"model": model, "columns": list(Xtr.columns), "reference": reference,
                 "categorical": CATEGORICAL},
                os.path.join(args.artifacts, "churn_model.joblib"))
    with open(os.path.join(args.artifacts, "metrics.json"), "w") as fh:
        json.dump({"metrics": metrics,
                   "lift": lift.to_dict("records"),
                   "calibration": rel.round(4).to_dict("records"),
                   "importance": importance.head(20).to_dict("records")}, fh, indent=2)
    importance.to_csv(os.path.join(args.artifacts, "feature_importance.csv"), index=False)

    at_risk = out[out["churn_probability_90d"] >= 0.15]
    print(f"\n--- Portfolio ---------------------------------------------")
    print(f"  Active accounts        {len(out):>12,}")
    print(f"  At risk (p >= 0.15)    {len(at_risk):>12,}")
    print(f"  Active ARR             Rs {out['arr'].sum():>12,.0f}")
    print(f"  Expected ARR at risk   Rs {out['revenue_at_risk'].sum():>12,.0f}")
    print(f"  Predicted 90d churn    {out['churn_probability_90d'].mean():>12.2%}")
    print(f"\nWrote data/scored_customers.csv and ml/artifacts/")


if __name__ == "__main__":
    main()
