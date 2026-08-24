# 1. Problem definition and metrics

## The prediction target

> Will an account that is active today still be active in 90 days?

Three choices are buried in that sentence, and each one is a decision a
stakeholder can push back on.

**Why account-level, not user-level?** Revenue churns at the contract. A single
user leaving a 200-seat account is a support ticket; the account leaving is a
budget problem.

**Why 90 days?** Two constraints meet here. Too short (30 days) and there are
almost no positive cases to learn from, and no time to act anyway — a save play
takes weeks. Too long (12 months) and the prediction is useless: everything
looks risky eventually, and the features that mattered a year ago are stale.
90 days matches how long a retention play actually takes and gives enough
positive labels to train on. It also lines up with quarterly business reviews,
which is when this list gets read.

**Why "still active", not "downgraded"?** Downgrade and contraction are real
revenue events, and a v2 of this project should model them. They are excluded
here because mixing "left entirely" and "cut 3 seats" into one binary label
makes the probability uninterpretable, and the whole dashboard depends on the
probability meaning something.

## Metrics, and why accuracy is not one of them

The base rate is about 8%. A model that predicts "nobody churns" scores 92%
accuracy and is worth nothing. Accuracy is never reported in this project.

| Metric | Why it is here |
|---|---|
| **ROC AUC** | Ranking quality. Does the model put churners above stayers? Insensitive to the base rate, which makes it comparable across quarters. |
| **PR AUC** | The honest one on imbalanced data. Baseline equals the base rate (0.084), so 0.68 is a real signal, not a rounding artefact. |
| **Brier score** | Calibration. This project multiplies probabilities by rupees, so a probability that is not a probability corrupts every downstream number. |
| **Lift by decile** | The operational metric. "The riskiest 10% churn at 6.8× the base rate" is the sentence that gets budget approved. |
| **Coverage at top 20%** | Directly answers "if my team can only work 20% of the book, how much churn do we see?" |

## What we do *not* optimise

There is no classification threshold tuned for F1, because the model never
outputs a class. It outputs a probability, which then gets multiplied by MRR
and sorted. The "at risk" cut at 0.15 is a display filter, configurable via
`RISK_THRESHOLD` — not a decision boundary the model was trained against.

This matters. A team with two CSMs and a team with twenty should work different
cut-offs off the same model. Baking a threshold into the model takes that
choice away from them.

## The metric that would actually prove this works

None of the above. The real one is a **holdout experiment**: take the at-risk
list, randomly withhold 20% of accounts from any outreach, and compare 90-day
survival between the treated and untreated groups. That measures whether the
intervention worked, which is a different question from whether the prediction
was right.

That cannot be done on synthetic data, and it is the first thing to build if
this were deployed. Saying so is more convincing than any offline number.
