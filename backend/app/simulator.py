"""
Retention Simulator
===================

Answers the question a Customer Success manager actually has:

    "This account is 41% likely to leave. If I offer them 15% off for a year,
     is that a good use of my money - or am I just giving away margin to
     someone who was going to stay anyway?"

The naive version of this feature is wrong in a specific and expensive way.
It computes:

    benefit = annual revenue - cost of discount

...which says every discount is worth it, because revenue is always bigger
than the discount. The mistake is ignoring that **most customers you discount
would have stayed regardless.** You only earn the incremental revenue.

So we model the *incremental* effect:

    net benefit = (expected margin WITH the offer)
                - (expected margin WITHOUT the offer)
                - cost of making the offer

Which expands to three lines a business person can read:

    revenue saved   = margin x (churn without offer - churn with offer)
    discount cost   = margin x discount x P(they stay and use it)
    outreach cost   = the CSM's time, a fixed number

    net benefit     = revenue saved - discount cost - outreach cost

Two refinements that make it defensible:

1. The 90-day model probability is converted to a 12-month probability
   (surviving four consecutive quarters) before any money is multiplied,
   because we are valuing a year of revenue, not a quarter.

2. **A discount does not fix every problem.** If the model says this account
   is at risk because nobody logs in, money will not bring them back - you
   need onboarding. Each customer carries a `price_sensitivity` score (the
   share of their risk attributable to price and payment features), and the
   uplift a discount can deliver is scaled by it. That is why the simulator
   sometimes returns "don't discount, do this instead".
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

# --- Assumptions, all in one place so they can be argued about -------------

GROSS_MARGIN = 0.78          # SaaS gross margin: revenue minus hosting/support
HORIZON_MONTHS = 12          # we value one year forward
OUTREACH_COST = {            # loaded cost of a CSM running a save play (INR)
    "SMB": 800,
    "Mid-Market": 2500,
    "Enterprise": 8000,
}
MAX_UPLIFT_FLOOR = 0.20      # even a purely non-price problem gets some goodwill
MAX_UPLIFT_CEILING = 0.75    # a discount never guarantees retention
DISCOUNT_RESPONSE_K = 8.0    # curvature: most of the effect lands by ~20% off


def uplift(discount_pct: float, price_sensitivity: float) -> float:
    """
    Fraction of churn risk removed by a discount of `discount_pct` (0-1).

    Shape: saturating exponential. Going 0% -> 10% off moves the needle a lot;
    30% -> 40% barely moves it, because by then the objection is not price.

        u(d) = ceiling * (1 - e^(-k*d))

    `ceiling` is what a discount could achieve at best for this customer, and
    it is driven by *why* they are leaving.
    """
    d = max(0.0, min(discount_pct, 0.60))
    ceiling = MAX_UPLIFT_FLOOR + (MAX_UPLIFT_CEILING - MAX_UPLIFT_FLOOR) * max(0.0, min(price_sensitivity, 1.0))
    return ceiling * (1 - pow(2.718281828, -DISCOUNT_RESPONSE_K * d))


def to_annual(p90: float) -> float:
    """A 90-day churn probability turned into a 12-month one."""
    return 1 - (1 - max(0.0, min(p90, 0.999))) ** 4


@dataclass
class SimulationResult:
    # inputs echoed back
    customer_id: int
    mrr: float
    discount_pct: float
    # probabilities
    churn_probability_12m: float
    churn_probability_12m_with_offer: float
    risk_reduction_pp: float
    # money
    annual_revenue: float
    retention_cost: float
    expected_revenue_saved: float
    expected_benefit: float
    roi: float
    breakeven_discount_pct: float | None
    # advice
    recommendation: str
    rationale: str


def simulate(
    customer_id: int,
    mrr: float,
    churn_probability_90d: float,
    price_sensitivity: float,
    segment: str = "SMB",
    discount_pct: float = 0.15,
    primary_reason: str = "",
    horizon_months: int = HORIZON_MONTHS,
    gross_margin: float = GROSS_MARGIN,
) -> SimulationResult:
    annual_revenue = mrr * horizon_months
    margin_revenue = annual_revenue * gross_margin

    p0 = to_annual(churn_probability_90d)
    u = uplift(discount_pct, price_sensitivity)
    p1 = p0 * (1 - u)

    # Revenue we keep that we would otherwise have lost.
    revenue_saved = margin_revenue * (p0 - p1)

    # The discount is only actually paid out if they stay.
    discount_cost = margin_revenue * discount_pct * (1 - p1)
    outreach = OUTREACH_COST.get(segment, 1500)
    retention_cost = discount_cost + outreach

    benefit = revenue_saved - retention_cost
    roi = (benefit / retention_cost) if retention_cost > 0 else 0.0

    # Largest discount that still breaks even, found by bisection. This is the
    # number the CSM actually wants: "how far can I go?"
    breakeven = _breakeven_discount(margin_revenue, p0, price_sensitivity, outreach)

    if benefit > 0 and roi >= 1.0:
        rec = "Offer the discount"
        why = (f"A {discount_pct:.0%} discount cuts 12-month churn risk from {p0:.0%} to {p1:.0%}. "
               f"Net gain of Rs {benefit:,.0f} per year after the discount and the CSM's time.")
    elif benefit > 0:
        rec = "Offer, but the margin is thin"
        why = (f"Positive but thin: Rs {benefit:,.0f}. This account is not very price-driven, "
               f"so the discount buys only {u:.0%} risk reduction.")
    elif price_sensitivity < 0.35:
        rec = "Do not discount - fix the root cause"
        why = (f"The risk here is '{primary_reason or 'not price-related'}'. A discount removes only "
               f"{u:.0%} of the risk while costing Rs {retention_cost:,.0f}. "
               f"Spend the effort on the underlying problem instead.")
    else:
        rec = "Do not discount at this level"
        why = (f"At {discount_pct:.0%} the offer loses Rs {abs(benefit):,.0f}. "
               + (f"Break-even is around {breakeven:.0%}." if breakeven else
                  "No discount level breaks even for this account."))

    return SimulationResult(
        customer_id=customer_id,
        mrr=round(mrr, 2),
        discount_pct=round(discount_pct, 4),
        churn_probability_12m=round(p0, 4),
        churn_probability_12m_with_offer=round(p1, 4),
        risk_reduction_pp=round((p0 - p1) * 100, 2),
        annual_revenue=round(annual_revenue, 0),
        retention_cost=round(retention_cost, 0),
        expected_revenue_saved=round(revenue_saved, 0),
        expected_benefit=round(benefit, 0),
        roi=round(roi, 2),
        breakeven_discount_pct=round(breakeven * 100, 1) if breakeven else None,
        recommendation=rec,
        rationale=why,
    )


def _breakeven_discount(margin_revenue, p0, price_sensitivity, outreach, hi=0.60):
    """Largest discount where net benefit is still >= 0, to 0.5pp precision."""
    def net(d):
        u = uplift(d, price_sensitivity)
        p1 = p0 * (1 - u)
        return margin_revenue * (p0 - p1) - margin_revenue * d * (1 - p1) - outreach

    if net(0.005) < 0:
        return None
    lo = 0.005
    for _ in range(30):
        mid = (lo + hi) / 2
        if net(mid) >= 0:
            lo = mid
        else:
            hi = mid
    return round(lo, 3)


def optimal_offer(customer_id, mrr, churn_probability_90d, price_sensitivity,
                  segment="SMB", primary_reason="", step=0.01, max_discount=0.40):
    """Sweep discount levels and return the one with the highest net benefit."""
    best, curve = None, []
    d = 0.0
    while d <= max_discount + 1e-9:
        r = simulate(customer_id, mrr, churn_probability_90d, price_sensitivity,
                     segment, d, primary_reason)
        curve.append({"discount_pct": round(d * 100, 1),
                      "expected_benefit": r.expected_benefit,
                      "retention_cost": r.retention_cost,
                      "expected_revenue_saved": r.expected_revenue_saved})
        if best is None or r.expected_benefit > best.expected_benefit:
            best = r
        d += step
    return asdict(best), curve
