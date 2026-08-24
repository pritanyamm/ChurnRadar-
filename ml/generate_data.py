"""
ChurnRadar - synthetic data generator
=====================================

Creates a realistic B2B SaaS dataset for an Indian software company.

Why synthetic data?
-------------------
Real churn datasets are either tiny (Telco, 7k rows) or confidential. We
generate our own so that:
  1. We control the *ground truth* - we know which signals actually cause
     churn, so we can check whether the model recovers them.
  2. The volume is realistic (tens of thousands of customers, 24 months of
     history) instead of a toy CSV.
  3. There is no leakage by accident - we build features only from data that
     existed *before* the prediction date.

How the churn signal is created
-------------------------------
Every customer gets a hidden "health trajectory". Each month we:
  - turn health into observable behaviour (logins, seats used, tickets, late
    payments),
  - convert health + tenure + recent behaviour into a churn *hazard*,
  - roll a dice against that hazard.

So the observable columns are correlated with churn for a *reason*, the way
they are in real life. Nothing in the output tells the model the answer
directly.

Run:
    python ml/generate_data.py --customers 50000 --out data/
"""

from __future__ import annotations

import argparse
import os
from datetime import date

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

HISTORY_MONTHS = 24
DATA_END = pd.Timestamp("2026-06-30")          # last day we have data for
DATA_START = (DATA_END - pd.DateOffset(months=HISTORY_MONTHS - 1)).replace(day=1)

PLANS = [
    # plan_id, name, tier, base price per seat per month (INR), features available
    (1, "Starter",    "Starter",    300,  12),
    (2, "Growth",     "Growth",     650,  28),
    (3, "Business",   "Business",  1200,  45),
    (4, "Enterprise", "Enterprise", 2000, 60),
]

SEGMENTS = ["SMB", "Mid-Market", "Enterprise"]
SEGMENT_P = [0.62, 0.28, 0.10]

INDUSTRIES = [
    "Retail", "Manufacturing", "Logistics", "Healthcare", "Education",
    "Financial Services", "Agritech", "IT Services", "Hospitality", "Real Estate",
]

CHANNELS = ["Organic Search", "Paid Ads", "Partner", "Outbound Sales", "Referral", "Marketplace"]
CHANNEL_P = [0.24, 0.18, 0.14, 0.22, 0.14, 0.08]

CITIES = [
    ("Bengaluru", "Karnataka"), ("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"),
    ("Hyderabad", "Telangana"), ("Chennai", "Tamil Nadu"), ("Delhi", "Delhi"),
    ("Gurugram", "Haryana"), ("Noida", "Uttar Pradesh"), ("Ahmedabad", "Gujarat"),
    ("Kolkata", "West Bengal"), ("Jaipur", "Rajasthan"), ("Kochi", "Kerala"),
    ("Indore", "Madhya Pradesh"), ("Coimbatore", "Tamil Nadu"), ("Shivamogga", "Karnataka"),
]

TICKET_CATEGORIES = ["Billing", "Bug", "How-to", "Integration", "Performance", "Feature Request", "Outage"]
CHURN_REASONS = ["Price", "Product gaps", "Poor support", "Low adoption", "Competitor", "Company shut down", "Budget cut"]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------
# 1. Customer base
# --------------------------------------------------------------------------

def make_customers(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """One row per customer account with static attributes."""
    cid = np.arange(1, n + 1)

    # Signups are spread over 5 years, skewed towards recent (company is growing).
    age_days = (rng.beta(1.6, 3.0, n) * 1800).astype(int)
    signup = DATA_END.normalize() - pd.to_timedelta(age_days, unit="D")

    segment = rng.choice(SEGMENTS, n, p=SEGMENT_P)

    # Bigger segments buy bigger plans.
    plan_id = np.empty(n, dtype=int)
    plan_id[segment == "SMB"] = rng.choice([1, 2, 3], (segment == "SMB").sum(), p=[0.55, 0.35, 0.10])
    plan_id[segment == "Mid-Market"] = rng.choice([2, 3, 4], (segment == "Mid-Market").sum(), p=[0.35, 0.48, 0.17])
    plan_id[segment == "Enterprise"] = rng.choice([3, 4], (segment == "Enterprise").sum(), p=[0.30, 0.70])

    seats = np.where(
        segment == "SMB", rng.integers(2, 15, n),
        np.where(segment == "Mid-Market", rng.integers(15, 80, n), rng.integers(60, 220, n)),
    )

    city_idx = rng.integers(0, len(CITIES), n)
    city = np.array([CITIES[i][0] for i in city_idx])
    state = np.array([CITIES[i][1] for i in city_idx])

    # Discount: sales gives more away on bigger deals and on outbound.
    channel = rng.choice(CHANNELS, n, p=CHANNEL_P)
    discount = np.clip(
        rng.gamma(1.5, 4.0, n)
        + np.where(segment == "Enterprise", 6, np.where(segment == "Mid-Market", 3, 0))
        + np.where(channel == "Outbound Sales", 3, 0),
        0, 45,
    ).round(0)

    billing = rng.choice(["Monthly", "Annual"], n, p=[0.68, 0.32])
    # Annual contracts skew towards larger customers.
    flip = (segment == "Enterprise") & (rng.random(n) < 0.55)
    billing[flip] = "Annual"

    # Hidden health trait: some accounts were simply never a good fit.
    latent_fit = rng.normal(0, 1, n)

    df = pd.DataFrame({
        "customer_id": cid,
        "company_name": [f"Account-{i:06d}" for i in cid],
        "signup_date": signup,
        "segment": segment,
        "industry": rng.choice(INDUSTRIES, n),
        "acquisition_channel": channel,
        "city": city,
        "state": state,
        "plan_id": plan_id,
        "seats_licensed": seats,
        "discount_pct": discount,
        "billing_cycle": billing,
        "_latent_fit": latent_fit,
    })

    price = df["plan_id"].map({p[0]: p[3] for p in PLANS})
    # Volume discount on seat price, then the negotiated discount.
    seat_price = price * np.clip(1.0 - np.log1p(df["seats_licensed"]) * 0.045, 0.55, 1.0)
    df["mrr"] = (seat_price * df["seats_licensed"] * (1 - df["discount_pct"] / 100)).round(0)
    return df


# --------------------------------------------------------------------------
# 2. Month-by-month simulation
# --------------------------------------------------------------------------

def simulate(customers: pd.DataFrame, rng: np.random.Generator):
    """
    Walk forward month by month. Each month we emit usage, tickets and an
    invoice, then decide whether the account churns.

    Everything is vectorised across customers - 24 loop iterations total,
    not 24 x 50,000.
    """
    n = len(customers)
    months = pd.date_range(DATA_START, DATA_END, freq="MS")

    features_available = customers["plan_id"].map({p[0]: p[4] for p in PLANS}).to_numpy(float)
    seats_lic = customers["seats_licensed"].to_numpy(float)
    signup = customers["signup_date"].to_numpy("datetime64[ns]")
    latent_fit = customers["_latent_fit"].to_numpy()
    discount = customers["discount_pct"].to_numpy(float)
    mrr = customers["mrr"].to_numpy(float)
    is_annual = (customers["billing_cycle"] == "Annual").to_numpy()
    seg = customers["segment"].to_numpy()

    # Health starts near the latent fit and drifts. A slice of the base gets a
    # persistent negative drift - these become the "silent decliners" that a
    # good model should catch months before they leave.
    health = latent_fit + rng.normal(0, 0.4, n)
    drift = rng.normal(0.0, 0.09, n) - (rng.random(n) < 0.22) * rng.gamma(2.0, 0.06, n)

    # Independent failure channels. Without these, every unhappy account looks
    # identical ("low adoption") and the reason codes are useless. In reality a
    # perfectly engaged account can still leave over a botched migration or a
    # finance freeze, so we model those as separate causes.
    support_shock = rng.random(n) < 0.16      # a bad implementation / recurring bug
    billing_stress = rng.random(n) < 0.13     # cash-flow trouble on their side
    price_pressure = rng.random(n) < 0.18     # their CFO is hunting for savings

    # Adoption and seat usage are *proxies* for health, not health itself.
    # Some teams use three features brilliantly and renew forever; others buy
    # everything and log in once. These offsets keep the proxy honest, which
    # in turn stops one feature from absorbing the whole model.
    adoption_offset = rng.normal(0, 0.85, n)
    seat_offset = rng.normal(0, 0.70, n)

    # Price-pressured accounts also negotiated harder at signature, so the
    # discount column carries real information rather than being noise.
    discount = np.clip(discount + price_pressure * rng.uniform(6, 20, n), 0, 55)
    customers = customers.assign(discount_pct=discount)
    mrr = (mrr * (1 - price_pressure * rng.uniform(0.05, 0.16, n))).round(0)
    customers = customers.assign(mrr=mrr)

    alive = np.ones(n, dtype=bool)
    churn_month = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    churn_reason = np.full(n, "", dtype=object)

    usage_rows, ticket_rows, invoice_rows = [], [], []
    ticket_seq = 1
    invoice_seq = 1

    # Rolling memory used by the hazard function.
    tickets_recent = np.zeros(n)
    late_recent = np.zeros(n)

    for m in months:
        m_end = m + pd.offsets.MonthEnd(0)
        active = alive & (signup <= np.datetime64(m_end))
        if not active.any():
            continue

        health = health + drift + rng.normal(0, 0.22, n)
        health = np.clip(health, -4, 4)

        tenure_m = ((m.year - pd.DatetimeIndex(signup).year) * 12
                    + (m.month - pd.DatetimeIndex(signup).month)).to_numpy()
        tenure_m = np.maximum(tenure_m, 0)

        # ---- usage -------------------------------------------------------
        # Healthy accounts log in most working days; sick ones drop off.
        login_rate = sigmoid(0.9 * health + 0.6)
        active_days = np.clip(rng.binomial(22, np.clip(login_rate, 0.02, 0.98)), 0, 22).astype(float)
        logins = np.round(active_days * (1.2 + np.clip(health, -1, 3) * 0.55)
                          * rng.uniform(0.8, 1.3, n)).astype(int)
        logins = np.maximum(logins, 0)

        seats_active = np.clip(
            np.round(seats_lic * np.clip(sigmoid(0.8 * health + seat_offset + 0.35), 0.03, 0.99)
                     * rng.uniform(0.85, 1.05, n)),
            0, seats_lic,
        )
        features_used = np.clip(
            np.round(features_available * np.clip(
                sigmoid(0.7 * health + adoption_offset + rng.normal(0, 0.25, n) + 0.1), 0.02, 0.95)),
            0, features_available
        )
        api_calls = np.round(np.maximum(0, seats_active * rng.gamma(2.2, 60, n) * (0.5 + sigmoid(health)))).astype(int)

        idx = np.where(active)[0]
        usage_rows.append(pd.DataFrame({
            "customer_id": customers["customer_id"].to_numpy()[idx],
            "month_start": m,
            "logins": logins[idx],
            "active_days": active_days[idx].astype(int),
            "seats_active": seats_active[idx].astype(int),
            "features_used": features_used[idx].astype(int),
            "features_available": features_available[idx].astype(int),
            "api_calls": api_calls[idx],
        }))

        # ---- support tickets ---------------------------------------------
        # Unhealthy accounts raise more tickets, and get worse outcomes.
        ticket_rate = np.clip(0.35 + np.exp(-0.8 * health) * 0.45
                              + support_shock * rng.uniform(1.2, 3.0, n), 0.05, 6.0)
        n_tickets = rng.poisson(ticket_rate)
        n_tickets[~active] = 0
        total_t = int(n_tickets.sum())
        if total_t:
            owner = np.repeat(np.arange(n), n_tickets)
            h_owner = health[owner]
            sev = rng.choice(["Low", "Medium", "High", "Critical"], total_t,
                             p=[0.42, 0.33, 0.19, 0.06])
            sev_weight = pd.Series(sev).map({"Low": 0, "Medium": 1, "High": 2, "Critical": 3}).to_numpy()
            res_hours = np.round(np.clip(
                rng.gamma(2.0, 6.0, total_t) * (1 + sev_weight * 0.8) * (1 + np.clip(-h_owner, 0, 3) * 0.35),
                0.5, 400), 1)
            csat = np.clip(np.round(rng.normal(4.1 + 0.25 * h_owner - 0.35 * sev_weight, 0.9)), 1, 5)
            day = rng.integers(1, m.days_in_month + 1, total_t)
            ticket_rows.append(pd.DataFrame({
                "ticket_id": np.arange(ticket_seq, ticket_seq + total_t),
                "customer_id": customers["customer_id"].to_numpy()[owner],
                "created_at": pd.to_datetime(dict(year=m.year, month=m.month, day=day)),
                "category": rng.choice(TICKET_CATEGORIES, total_t),
                "severity": sev,
                "resolution_hours": res_hours,
                "csat_score": csat.astype(int),
                "is_escalated": ((sev_weight >= 2) & (rng.random(total_t) < 0.35)).astype(int),
            }))
            ticket_seq += total_t
        tickets_recent = 0.6 * tickets_recent + n_tickets

        # ---- invoices / payments -----------------------------------------
        # Annual plans only bill in their anniversary month.
        anniv = pd.DatetimeIndex(signup).month.to_numpy()
        bills = active & (~is_annual | (anniv == m.month))
        bidx = np.where(bills)[0]
        if len(bidx):
            amount = np.where(is_annual[bidx], mrr[bidx] * 12 * 0.9, mrr[bidx])
            # Cash-flow stress correlates with unhappiness and with big discounts
            # (heavily discounted deals are usually price-sensitive accounts).
            late_p = np.clip(sigmoid(-0.9 * health[bidx] - 1.4 + discount[bidx] * 0.02
                                     + billing_stress[bidx] * 2.2), 0.01, 0.85)
            is_late = rng.random(len(bidx)) < late_p
            days_late = np.where(is_late, rng.gamma(2.0, 9.0, len(bidx)).round(0), 0)
            failed = is_late & (rng.random(len(bidx)) < 0.28)
            invoice_rows.append(pd.DataFrame({
                "invoice_id": np.arange(invoice_seq, invoice_seq + len(bidx)),
                "customer_id": customers["customer_id"].to_numpy()[bidx],
                "invoice_date": m,
                "amount": amount.round(0),
                "days_late": days_late.astype(int),
                "status": np.where(failed, "Failed", np.where(is_late, "Paid Late", "Paid")),
            }))
            invoice_seq += len(bidx)
            late_recent[bidx] = 0.7 * late_recent[bidx] + is_late.astype(float)
        late_recent *= 0.95

        # ---- churn hazard -------------------------------------------------
        # This is the ground truth we want the model to rediscover.
        seat_util = np.divide(seats_active, seats_lic, out=np.zeros(n), where=seats_lic > 0)
        logit = (
            -5.40                                   # base rate
            - 0.62 * health                         # engagement is the strongest driver
            - 0.030 * np.minimum(tenure_m, 36)      # loyalty builds over the first 3 years
            + 0.30 * np.clip(tickets_recent, 0, 12)  # support load
            + 0.85 * np.clip(late_recent, 0, 5)     # payment friction
            + 0.055 * discount                      # deep discounts = price sensitivity
            + 0.85 * price_pressure                 # their side is cutting software spend
            - 1.35 * seat_util                      # unused seats are a leading indicator
            + np.where(is_annual, -0.45, 0.0)       # annual contracts lock people in
            + np.where(seg == "SMB", 0.38, np.where(seg == "Enterprise", -0.50, 0.0))
        )
        # Annual customers can realistically only leave at renewal.
        _gap = np.abs(((anniv - m.month + 6) % 12) - 6)     # months away from renewal
        renewal_window = np.where(is_annual, (_gap <= 1).astype(float), 1.0)
        p_churn = sigmoid(logit) * renewal_window

        rolls = rng.random(n) < p_churn
        newly = active & rolls & (tenure_m >= 1)
        if newly.any():
            churn_month[newly] = np.datetime64(m_end.normalize())
            # Attribute a business reason based on the dominant driver.
            reason = np.where(discount[newly] > 20, "Price",
                     np.where(tickets_recent[newly] > 3, "Poor support",
                     np.where(seat_util[newly] < 0.25, "Low adoption",
                     np.where(late_recent[newly] > 1.2, "Budget cut",
                     np.where(health[newly] < -1.0, "Product gaps", "Competitor")))))
            shut = rng.random(newly.sum()) < 0.05
            reason = np.where(shut, "Company shut down", reason)
            churn_reason[newly] = reason
            alive[newly] = False

    usage = pd.concat(usage_rows, ignore_index=True)
    tickets = pd.concat(ticket_rows, ignore_index=True) if ticket_rows else pd.DataFrame()
    invoices = pd.concat(invoice_rows, ignore_index=True)

    subs = pd.DataFrame({
        "subscription_id": customers["customer_id"],
        "customer_id": customers["customer_id"],
        "plan_id": customers["plan_id"],
        "start_date": customers["signup_date"],
        "end_date": pd.to_datetime(churn_month),
        "status": np.where(alive, "Active", "Churned"),
        "mrr": customers["mrr"],
        "discount_pct": customers["discount_pct"],
        "billing_cycle": customers["billing_cycle"],
        "seats_licensed": customers["seats_licensed"],
    })

    churn = pd.DataFrame({
        "customer_id": customers["customer_id"],
        "churn_date": pd.to_datetime(churn_month),
        "churn_reason": churn_reason,
    })
    churn = churn[churn["churn_date"].notna()].reset_index(drop=True)

    return usage, tickets, invoices, subs, churn


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)

    print(f"Generating {args.customers:,} customers over {HISTORY_MONTHS} months...")
    customers = make_customers(args.customers, rng)
    usage, tickets, invoices, subs, churn = simulate(customers, rng)

    plans = pd.DataFrame(PLANS, columns=["plan_id", "plan_name", "tier", "base_price_per_seat", "features_available"])
    customers = customers.drop(columns=["_latent_fit", "plan_id", "seats_licensed", "discount_pct",
                                        "billing_cycle", "mrr"])

    out = {
        "plans": plans,
        "customers": customers,
        "subscriptions": subs,
        "usage_monthly": usage,
        "support_tickets": tickets,
        "invoices": invoices,
        "churn_events": churn,
    }
    for name, df in out.items():
        path = os.path.join(args.out, f"{name}.csv")
        df.to_csv(path, index=False)
        print(f"  {name:<18} {len(df):>10,} rows  ->  {path}")

    churned = len(churn)
    print(f"\nChurned accounts: {churned:,} ({churned / len(subs):.1%} of base over {HISTORY_MONTHS} months)")
    print(f"Currently active : {(subs['status'] == 'Active').sum():,}")
    print(f"Active MRR       : Rs {subs.loc[subs['status'] == 'Active', 'mrr'].sum():,.0f}")


if __name__ == "__main__":
    main()
