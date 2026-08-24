# ChurnRadar

**Customer churn prediction and revenue rescue for B2B SaaS.**

Most churn projects stop at "this customer will probably leave". That is the
least useful part. A retention team already has more at-risk accounts than it
has hours. What it does not have is an answer to the three questions that
actually decide where those hours go:

1. **Who is likely to leave** — in the next 90 days, with a calibrated probability
2. **Why** — a per-account reason, not a global feature-importance chart
3. **What it costs us, and what we can get back** — in rupees, and whether a
   discount is worth making

ChurnRadar answers all three, and then closes the loop with a **Retention
Simulator**: given this account's risk, revenue and reason for leaving, is a
15% discount a good trade — and if not, what is?

```
                                         ┌─→  FastAPI  →  React dashboard
SQL (PostgreSQL) → Python (scikit-learn) ─┤        (live retention simulator)
                                         └─→  Power BI report
                                                  (executive / diagnosis / action)
```

Both front ends read the **same** views, so the number on the web dashboard and
the number in Power BI are the same number by construction — the metric logic
lives in `sql/03_views.sql`, not in either client.

---

## Results

Trained on a September 2025 snapshot, validated **out of time** on a December
2025 snapshot — different quarter, different accounts, no random splitting.

| Metric | Value | What it means |
|---|---|---|
| ROC AUC | **0.937** | Ranks a random churner above a random stayer 94% of the time |
| PR AUC | **0.678** | Against an 8.4% base rate — the number that matters on imbalanced data |
| Brier score | **0.046** | Predicted probabilities are close to observed frequencies |
| Lift, top decile | **6.8×** | The riskiest 10% of accounts churn at 58% vs an 8.4% base |
| Coverage | **86%** | The top 20% of accounts by score contain 86% of all churn |

That last row is the business case in one line: a CS team that works 20% of
the base catches 86% of the loss.

On the current 29,376-account book: **2,412 accounts at risk**, **₹113.7 Cr of
expected annual revenue at risk**, and the simulator identifies where a
discount actually pays for itself.

---

## Why this is not another Telco churn notebook

Four things are done deliberately differently, and each one is a thing to talk
about in an interview:

**Point-in-time features, not whole-table aggregates.** Features are built only
from rows dated on or before the snapshot; the label is what happened in the 90
days after. Compute "tickets in the last 90 days" over the whole table instead
and you leak the future into the past, score 0.99 AUC, and ship a model that
does nothing. See [`docs/03-modeling.md`](docs/03-modeling.md).

**Out-of-time validation.** A random train/test split lies on churn data,
because one customer's September row and December row are nearly the same row.
Train on one quarter, test on the next.

**Calibrated probabilities, because we multiply them by money.** If the model
says 30% and only 12% actually leave, every rupee on the dashboard is wrong.
Isotonic calibration plus a printed reliability table.

**Incremental economics in the simulator.** The naive version computes
`benefit = revenue − discount`, which says every discount is worth it. The
mistake is ignoring that most discounted customers would have stayed anyway.
ChurnRadar values only the *incremental* retention, and scales the effect of a
discount by *why* the account is leaving — money does not fix an onboarding
problem. See [`docs/04-retention-simulator.md`](docs/04-retention-simulator.md).

---

## Run it

Everything runs from CSV files by default. PostgreSQL is optional.

```bash
git clone https://github.com/<your-username>/churnradar.git
cd churnradar

# 1. Data science pipeline (about 90 seconds for 50,000 accounts)
pip install -r ml/requirements.txt
python ml/generate_data.py --customers 50000 --out data/
python ml/build_features.py --data data/ --out data/
python ml/train_model.py --data data/ --artifacts ml/artifacts/

# 2. API
pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend
# docs at http://localhost:8000/docs

# 3. Dashboard  (new terminal)
cd frontend && npm install && npm run dev
# http://localhost:5173
```

On Windows PowerShell, the commands are identical apart from activating a
virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ml\requirements.txt
```

**Want to skip step 1?** A 500-account sample is committed to the repo:

```bash
# macOS / Linux
SCORED_CSV=data/sample/scored_customers.csv uvicorn app.main:app --app-dir backend
# PowerShell
$env:SCORED_CSV="data/sample/scored_customers.csv"; uvicorn app.main:app --app-dir backend
```

### With PostgreSQL

```bash
docker compose up -d
export PGURL=postgresql://churn:churn@localhost:5433/churnradar
psql $PGURL -f sql/01_schema.sql
psql $PGURL -f sql/02_load.sql      # run after the pipeline has written data/
psql $PGURL -f sql/03_views.sql
export DATABASE_URL=postgresql+psycopg2://churn:churn@localhost:5433/churnradar
```

---

## How it works, end to end

```mermaid
flowchart LR
    subgraph GEN["1 · Generate"]
        A["generate_data.py<br/>hidden health + 3 failure channels<br/>→ 50k accounts, 24 months"]
    end
    subgraph WH["2 · Warehouse"]
        B[("PostgreSQL<br/>8 tables · 7 views")]
    end
    subgraph FE["3 · Features"]
        C["build_features.py<br/>point-in-time snapshots<br/>train · valid · score"]
    end
    subgraph ML["4 · Model"]
        D["train_model.py<br/>HistGradientBoosting<br/>+ isotonic calibration<br/>+ reason codes"]
    end
    subgraph OUT["5 · Serve"]
        E[("scored_customers<br/>probability · reasons · ₹ at risk")]
        F["FastAPI<br/>+ retention simulator"]
        G["React dashboard"]
        H["Power BI report"]
    end

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F --> G
    E --> H
    B -.->|same views| H
```

The one arrow that matters is `B → C`. The feature builder reads the warehouse
*as of a snapshot date* and nothing after it. Every leakage bug in a churn
project lives on that arrow.

Scoring is a batch job, not a request path — churn is a slow signal, so nightly
re-scoring is plenty, and it keeps the API responses in milliseconds instead of
loading a model per request.

---

## What is in here

```
churnradar/
├── ml/
│   ├── generate_data.py       synthetic 24-month SaaS dataset with real churn causes
│   ├── build_features.py      point-in-time snapshots — the leakage-safe part
│   └── train_model.py         training, out-of-time validation, scoring, reason codes
├── sql/
│   ├── 01_schema.sql          8-table warehouse schema with the indexes explained
│   ├── 02_load.sql            \copy loader that works on managed Postgres
│   ├── 03_views.sql           the views the dashboard reads
│   └── 04_analysis_queries.sql  6 standalone analyst queries (cohorts, NRR, Pareto)
├── backend/
│   ├── app/simulator.py       retention economics — the killer feature
│   ├── app/data.py            Postgres or CSV, chosen automatically
│   ├── app/main.py            FastAPI, 10 endpoints, auto-generated docs
│   └── tests/                 8 tests encoding the business rules
├── frontend/                  React + Vite + Recharts dashboard
├── powerbi/
│   ├── export_for_powerbi.py  star-schema export (dim_date, facts, flattened reasons)
│   ├── measures.dax           20 DAX measures including the what-if simulator
│   ├── BUILD-GUIDE.md         click-by-click build for a first-time Power BI user
│   └── ChurnRadar.pbix        the report itself (+ PDF export, renders on GitHub)
└── docs/                      the reasoning behind every decision
```

---

## The data

There is no public churn dataset with 50,000 B2B accounts, 24 months of usage,
support and billing history. So the project generates one — and generates it
*causally*, which is the point. Each account carries a hidden health trajectory
plus three independent failure channels (a support crisis, a billing squeeze, a
CFO hunting for savings). Observable columns are produced from those states, and
churn is then sampled from a hazard function.

The consequence: we know the ground truth, so we can check whether the model
recovers the real drivers instead of memorising an artefact. It also means the
reason codes are meaningfully different across accounts, rather than every
unhappy customer being labelled "low adoption".

Full column-level documentation: [`docs/02-data-dictionary.md`](docs/02-data-dictionary.md).

**An honest caveat:** an AUC of 0.94 is higher than you would see on real
production data, where 0.75–0.85 is a good result. Synthetic data has less
irreducible noise than reality. The pipeline, the validation design and the
economics are what transfer — the headline number is not a claim about the real
world, and saying so unprompted is worth more than the number.

---

## API

| Endpoint | Returns |
|---|---|
| `GET /api/kpis` | The headline strip, including recoverable value |
| `GET /api/risk-bands` | Accounts and ARR per risk band |
| `GET /api/risk-distribution` | Histogram behind the risk ladder |
| `GET /api/reasons` | Revenue at risk grouped by primary driver |
| `GET /api/segments` | Risk by segment and plan tier |
| `GET /api/customers` | Filterable, paginated action list |
| `GET /api/customers/{id}` | One account with its reason codes |
| `POST /api/simulate` | Retention simulation + the full benefit curve |
| `GET /api/model/metrics` | Validation metrics from the last training run |

Interactive docs at `/docs` once the server is running.

---

## Docs

- [Problem and metrics](docs/01-problem-and-metrics.md) — what we predict, and why 90 days
- [Data dictionary](docs/02-data-dictionary.md) — every table and column
- [Modeling](docs/03-modeling.md) — snapshots, leakage, calibration, reason codes
- [Retention simulator](docs/04-retention-simulator.md) — the economics, derived
- [Power BI build guide](powerbi/BUILD-GUIDE.md) — step by step from zero
- [Power BI connection notes](powerbi/README.md) — star schema and DAX

## Licence

MIT.
