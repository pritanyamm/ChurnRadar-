"""
Data access.

Two modes, chosen automatically:

  DATABASE_URL set  ->  read from PostgreSQL (production path)
  otherwise         ->  read data/scored_customers.csv into memory

The CSV fallback exists so the project runs on a clean laptop with one
command. 50,000 scored rows is about 15 MB in pandas - keeping it in memory
is the right call for a read-only analytical API, and it means the demo
never fails because a database was not running.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = Path(os.getenv("SCORED_CSV", ROOT / "data" / "scored_customers.csv"))
DATABASE_URL = os.getenv("DATABASE_URL")

RISK_THRESHOLD = float(os.getenv("RISK_THRESHOLD", "0.15"))


@lru_cache(maxsize=1)
def scored() -> pd.DataFrame:
    if DATABASE_URL:
        from sqlalchemy import create_engine
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        df = pd.read_sql("SELECT * FROM scored_customers", engine)
    else:
        if not CSV_PATH.exists():
            raise FileNotFoundError(
                f"No scored data at {CSV_PATH}. Run:\n"
                "  python ml/generate_data.py && python ml/build_features.py && python ml/train_model.py"
            )
        df = pd.read_csv(CSV_PATH)

    df["reasons"] = df["reasons"].apply(lambda v: json.loads(v) if isinstance(v, str) else (v or []))
    df["company_name"] = "Account-" + df["customer_id"].astype(int).astype(str).str.zfill(6)
    return df


def reload():
    scored.cache_clear()
    return scored()


# --- aggregations ---------------------------------------------------------

def kpis() -> dict:
    df = scored()
    at_risk = df[df.churn_probability_90d >= RISK_THRESHOLD]
    recoverable = float(df.get("recoverable_value", pd.Series(dtype=float)).sum()) if "recoverable_value" in df else None
    return {
        "active_customers": int(len(df)),
        "at_risk_customers": int(len(at_risk)),
        "predicted_churn_pct": round(float(df.churn_probability_90d.mean()) * 100, 2),
        "active_arr": float(df.arr.sum()),
        "revenue_at_risk": float(df.revenue_at_risk.sum()),
        "arr_in_at_risk_accounts": float(at_risk.arr.sum()),
        "avg_mrr": float(df.mrr.mean()),
        "scored_at": str(df.scored_at.iloc[0]),
        "risk_threshold": RISK_THRESHOLD,
        "recoverable_value": recoverable,
    }


def risk_bands() -> list[dict]:
    df = scored()
    order = ["Low", "Watch", "High", "Critical"]
    g = df.groupby("risk_band", observed=True).agg(
        accounts=("customer_id", "size"),
        arr=("arr", "sum"),
        revenue_at_risk=("revenue_at_risk", "sum"),
        avg_risk_pct=("churn_probability_90d", "mean"),
    ).reindex(order).fillna(0).reset_index()
    g["avg_risk_pct"] = (g.avg_risk_pct * 100).round(1)
    g["pct_of_arr"] = (100 * g.arr / max(g.arr.sum(), 1)).round(1)
    return g.to_dict("records")


def reasons_breakdown() -> list[dict]:
    df = scored()
    at_risk = df[df.churn_probability_90d >= RISK_THRESHOLD]
    g = at_risk.groupby("primary_reason").agg(
        accounts=("customer_id", "size"),
        revenue_at_risk=("revenue_at_risk", "sum"),
        avg_risk_pct=("churn_probability_90d", "mean"),
        avg_mrr=("mrr", "mean"),
    ).reset_index().sort_values("revenue_at_risk", ascending=False)
    g["avg_risk_pct"] = (g.avg_risk_pct * 100).round(1)
    g["avg_mrr"] = g.avg_mrr.round(0)
    return g.to_dict("records")


def segment_risk() -> list[dict]:
    df = scored()
    g = df.groupby(["segment", "tier"]).agg(
        accounts=("customer_id", "size"),
        predicted_churn_pct=("churn_probability_90d", "mean"),
        arr=("arr", "sum"),
        revenue_at_risk=("revenue_at_risk", "sum"),
        avg_seat_util_pct=("seat_utilisation", "mean"),
    ).reset_index()
    g["predicted_churn_pct"] = (g.predicted_churn_pct * 100).round(1)
    g["avg_seat_util_pct"] = (g.avg_seat_util_pct * 100).round(1)
    return g.sort_values("revenue_at_risk", ascending=False).to_dict("records")


def risk_distribution(bins: int = 20) -> list[dict]:
    """Histogram of accounts and ARR across the probability range."""
    df = scored()
    cut = pd.cut(df.churn_probability_90d, bins=[i / bins for i in range(bins + 1)],
                 include_lowest=True)
    g = df.groupby(cut, observed=True).agg(
        accounts=("customer_id", "size"), arr=("arr", "sum")
    ).reset_index()
    g["bucket"] = [f"{int(iv.left * 100)}-{int(iv.right * 100)}%" for iv in g.iloc[:, 0]]
    return g[["bucket", "accounts", "arr"]].to_dict("records")


def action_list(limit=50, offset=0, segment=None, band=None, reason=None,
                sort="revenue_at_risk", search=None) -> dict:
    df = scored()
    df = df[df.churn_probability_90d >= RISK_THRESHOLD]
    if segment:
        df = df[df.segment == segment]
    if band:
        df = df[df.risk_band == band]
    if reason:
        df = df[df.primary_reason == reason]
    if search:
        df = df[df.company_name.str.contains(search, case=False, na=False)]
    sort = sort if sort in df.columns else "revenue_at_risk"
    df = df.sort_values(sort, ascending=False)
    total = len(df)
    page = df.iloc[offset:offset + limit]
    return {"total": total, "items": page.to_dict("records")}


def customer(customer_id: int) -> dict | None:
    df = scored()
    row = df[df.customer_id == customer_id]
    return None if row.empty else row.iloc[0].to_dict()


def filter_options() -> dict:
    df = scored()
    return {
        "segments": sorted(df.segment.dropna().unique().tolist()),
        "bands": ["Critical", "High", "Watch", "Low"],
        "reasons": sorted(df.primary_reason.dropna().unique().tolist()),
    }
