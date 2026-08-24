"""
Tests for the retention economics. These encode the business rules - if
someone "simplifies" the maths later, these fail loudly.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.simulator import simulate, uplift, to_annual, optimal_offer


def test_annual_conversion():
    # A 10% chance of leaving each quarter compounds over four quarters.
    assert round(to_annual(0.10), 4) == round(1 - 0.9 ** 4, 4)
    assert to_annual(0.0) == 0.0


def test_uplift_saturates():
    # Doubling the discount must not double the effect.
    a, b = uplift(0.10, 1.0), uplift(0.20, 1.0)
    assert b > a
    assert b < 2 * a


def test_uplift_respects_price_sensitivity():
    # Same discount, different reason for leaving -> different effect.
    price_driven = uplift(0.15, 0.9)
    adoption_driven = uplift(0.15, 0.05)
    assert price_driven > adoption_driven * 2


def test_low_risk_customer_is_not_worth_discounting():
    # The core insight: never pay to retain someone who was staying anyway.
    r = simulate(1, mrr=10_000, churn_probability_90d=0.01,
                 price_sensitivity=0.9, segment="SMB", discount_pct=0.15)
    assert r.expected_benefit < 0
    assert "not" in r.recommendation.lower() or "do not" in r.recommendation.lower()


def test_high_risk_price_sensitive_customer_is_worth_discounting():
    r = simulate(2, mrr=50_000, churn_probability_90d=0.40,
                 price_sensitivity=0.9, segment="Mid-Market", discount_pct=0.15)
    assert r.expected_benefit > 0
    assert r.churn_probability_12m_with_offer < r.churn_probability_12m


def test_discount_does_not_fix_adoption_problems():
    # Same risk and revenue, but the problem is not price.
    price = simulate(3, 50_000, 0.40, 0.95, "Mid-Market", 0.15)
    adoption = simulate(4, 50_000, 0.40, 0.02, "Mid-Market", 0.15,
                        primary_reason="Seats sitting unused")
    assert adoption.expected_benefit < price.expected_benefit


def test_benefit_reconciles_with_its_components():
    r = simulate(5, 30_000, 0.30, 0.6, "SMB", 0.12)
    assert abs(r.expected_benefit - (r.expected_revenue_saved - r.retention_cost)) < 1.0


def test_optimal_offer_beats_arbitrary_offer():
    args = dict(customer_id=6, mrr=40_000, churn_probability_90d=0.35,
                price_sensitivity=0.7, segment="SMB")
    best, curve = optimal_offer(**args)
    fixed = simulate(**args, discount_pct=0.30)
    assert best["expected_benefit"] >= fixed.expected_benefit
    assert len(curve) > 10
