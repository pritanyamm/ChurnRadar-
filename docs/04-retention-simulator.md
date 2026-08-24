# 4. The Retention Simulator

> "If we give this customer 15% off, is it financially worth retaining them?"

## The naive answer, and why it is wrong

The obvious implementation:

```
retention cost   = 15% × annual revenue
expected revenue = annual revenue
expected benefit = revenue − cost
```

This always returns a large positive number, so it recommends discounting
everyone. The flaw is not arithmetic — it is that **the discount is given to
every customer you approach, but only a fraction of them were ever going to
leave.** You pay for all of them and earn incremental revenue from a few.

Concretely: an account with a 2% churn risk. Discount them and you have spent
15% of their revenue to protect a 2% chance of losing it. That is a guaranteed
loss dressed as a save.

## The incremental version

Value the account with and without the offer, and take the difference:

```
net benefit = E[margin | offer] − E[margin | no offer] − outreach cost
```

Expanding, with `M` = MRR, `m` = gross margin, `p₀` = churn probability without
the offer, `p₁` = with it, `d` = discount:

```
E[margin | no offer] = 12·M·m·(1 − p₀)
E[margin | offer]    = 12·M·m·(1 − d)·(1 − p₁)
```

Subtracting and regrouping gives three terms a business person can read:

```
revenue saved  = 12·M·m·(p₀ − p₁)          the churn we actually prevented
discount cost  = 12·M·m·d·(1 − p₁)         only paid if they stay
outreach cost  = fixed, by segment          the CSM's time

net benefit    = revenue saved − discount cost − outreach cost
```

`test_benefit_reconciles_with_its_components` in the test suite asserts this
identity holds, so the displayed lines always add up to the displayed total.

### Converting 90 days into 12 months

The model predicts 90 days. The offer runs for a year. Multiplying a quarterly
probability by annual revenue mixes units, so the probability is converted
first — surviving four consecutive quarters:

```
p₁₂ₘ = 1 − (1 − p₉₀)⁴
```

A 10% quarterly risk is a 34% annual risk. Skipping this understates risk by a
factor of three on the accounts that matter most.

## How much does a discount actually help?

This is the assumption the whole feature rests on, so it is stated explicitly
rather than hidden.

```
uplift(d) = ceiling × (1 − e^(−8d))
p₁ = p₀ × (1 − uplift)
```

Two properties, both deliberate:

**It saturates.** Going from 0% to 10% off moves the needle a lot. Going from
30% to 40% barely moves it, because by then the objection is not price. A
linear response would recommend absurd discounts.

**The ceiling depends on *why* they are leaving.** This is the part that makes
the feature more than a calculator. Each account carries a `price_sensitivity`
score — the share of its risk attributable to price and payment features, taken
from the same reason-code attribution the dashboard displays.

```
ceiling = 0.20 + 0.55 × price_sensitivity      # ranges 0.20 → 0.75
```

An account leaving because their CFO is cutting software spend has high price
sensitivity, and a discount can remove most of the risk. An account leaving
because nobody logs in has low price sensitivity — money will not bring them
back, and the simulator says so:

> **Do not discount — fix the root cause.** The risk here is 'Seats sitting
> unused'. A discount removes only 12% of the risk while costing ₹47,300.
> Spend the effort on the underlying problem instead.

The floor of 0.20 is not zero because a retention call has some goodwill effect
regardless of the offer. That is an assumption, and a soft one.

## Two outputs beyond the verdict

**The break-even ceiling.** Found by bisection: the largest discount at which
net benefit is still ≥ 0. This is the number a CSM actually wants going into a
negotiation — "I can go to 22%, not a rupee more".

**The benefit curve.** Net benefit swept across every discount level from 0% to
40%, with the optimum marked. The curve turns over, and *seeing* it turn over is
what makes the saturating-response argument land in a demo.

## Portfolio roll-up

"Potentially recoverable" on the dashboard is the sum of net benefit across
every at-risk account, at that account's own optimal discount, counting only
accounts where the best offer is positive. Accounts where no discount pays for
itself contribute zero — including them would inflate the number with revenue
that is not actually recoverable by this lever.

## Assumptions, all in one place

| Assumption | Value | Where it comes from |
|---|---|---|
| Gross margin | 78% | Typical B2B SaaS. Swap in the real number. |
| Horizon | 12 months | Matches how offers are contracted |
| Outreach cost | ₹800 / ₹2,500 / ₹8,000 | Loaded CSM cost by segment |
| Discount response `k` | 8.0 | Assumed curvature — the weakest link |
| Uplift ceiling | 0.20 – 0.75 | Assumed |

The bottom two rows are the honest weak point. In a real deployment they would
be estimated from historical offer and outcome data using an uplift model,
which is the single highest-value upgrade to this feature. They are constants
in `backend/app/simulator.py` precisely so that swapping them for a learned
model is a one-file change.
