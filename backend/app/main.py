"""
ChurnRadar API
==============

A read-only analytical API over the scored customer table, plus one write-free
"what-if" endpoint for the retention simulator.

Design note: the model does NOT run here. Scoring happens in a batch job
(ml/train_model.py) and lands in a table. The API just serves numbers. This
is how churn scoring works in almost every real company - churn is a slow
signal, so re-scoring nightly is plenty, and it keeps the API sub-100ms
instead of loading a 40 MB model on every request.

Docs are auto-generated: http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import data
from .simulator import optimal_offer, simulate

ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(
    title="ChurnRadar API",
    version="1.0.0",
    description="Customer churn prediction, revenue-at-risk analytics and retention simulation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health():
    try:
        n = len(data.scored())
        return {"status": "ok", "scored_rows": n, "source": "postgres" if data.DATABASE_URL else "csv"}
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))


@app.get("/api/model/metrics", tags=["meta"])
def model_metrics():
    """Validation metrics written by the training job - shown in the UI footer."""
    p = ROOT / "ml" / "artifacts" / "metrics.json"
    if not p.exists():
        raise HTTPException(404, "Train the model first: python ml/train_model.py")
    return json.loads(p.read_text())


# --- dashboard ------------------------------------------------------------

@lru_cache(maxsize=1)
def _recoverable_value() -> float:
    """
    Portfolio-level "Potentially Recoverable": for every at-risk account, find
    the best offer, and add up the net benefit wherever that offer is worth
    making. Deliberately excludes accounts where no discount pays for itself -
    a recoverable number that includes unrecoverable accounts is a lie.

    Cached because it is a few tens of thousands of arithmetic ops and the
    underlying scores only change when the nightly batch runs.
    """
    df = data.scored()
    at_risk = df[df.churn_probability_90d >= data.RISK_THRESHOLD]
    total = 0.0
    for r in at_risk.itertuples():
        best, _ = optimal_offer(int(r.customer_id), float(r.mrr),
                                float(r.churn_probability_90d), float(r.price_sensitivity),
                                r.segment, r.primary_reason, step=0.05, max_discount=0.30)
        if best["expected_benefit"] > 0:
            total += best["expected_benefit"]
    return round(total)


@app.get("/api/kpis", tags=["dashboard"])
def kpis():
    """The headline strip: active, at risk, revenue at risk, predicted churn."""
    k = data.kpis()
    k["recoverable_value"] = _recoverable_value()
    return k


@app.get("/api/risk-bands", tags=["dashboard"])
def risk_bands():
    return data.risk_bands()


@app.get("/api/risk-distribution", tags=["dashboard"])
def risk_distribution(bins: int = Query(20, ge=5, le=50)):
    return data.risk_distribution(bins)


@app.get("/api/reasons", tags=["dashboard"])
def reasons():
    """Revenue at risk grouped by the model's primary reason for each account."""
    return data.reasons_breakdown()


@app.get("/api/segments", tags=["dashboard"])
def segments():
    return data.segment_risk()


@app.get("/api/filters", tags=["dashboard"])
def filters():
    return data.filter_options()


# --- accounts -------------------------------------------------------------

@app.get("/api/customers", tags=["accounts"])
def customers(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    segment: str | None = None,
    band: str | None = None,
    reason: str | None = None,
    search: str | None = None,
    sort: str = "revenue_at_risk",
):
    """The prioritised action list. Sorted by expected rupees lost, not by score."""
    return data.action_list(limit, offset, segment, band, reason, sort, search)


@app.get("/api/customers/{customer_id}", tags=["accounts"])
def customer_detail(customer_id: int):
    c = data.customer(customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


# --- simulator ------------------------------------------------------------

class SimulateRequest(BaseModel):
    customer_id: int
    discount_pct: float = Field(0.15, ge=0, le=0.6, description="0.15 = 15% off")
    horizon_months: int = Field(12, ge=1, le=36)


@app.post("/api/simulate", tags=["simulator"])
def run_simulation(req: SimulateRequest):
    """
    "If we give this customer X% off, is it financially worth retaining them?"

    Returns the three numbers a CS lead needs (cost, revenue saved, net
    benefit), the break-even discount, and a plain-English recommendation.
    """
    c = data.customer(req.customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")

    result = simulate(
        customer_id=req.customer_id,
        mrr=float(c["mrr"]),
        churn_probability_90d=float(c["churn_probability_90d"]),
        price_sensitivity=float(c["price_sensitivity"]),
        segment=str(c["segment"]),
        discount_pct=req.discount_pct,
        primary_reason=str(c.get("primary_reason", "")),
        horizon_months=req.horizon_months,
    )
    best, curve = optimal_offer(req.customer_id, float(c["mrr"]),
                                float(c["churn_probability_90d"]),
                                float(c["price_sensitivity"]), str(c["segment"]),
                                str(c.get("primary_reason", "")))
    return {"result": result, "optimal": best, "curve": curve,
            "company_name": c.get("company_name"), "reasons": c.get("reasons", [])}
