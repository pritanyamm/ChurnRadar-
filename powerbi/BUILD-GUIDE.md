# Building the Power BI report

Written for someone who has never opened Power BI Desktop. Budget about four
hours. Everything here is free — Power BI Desktop is a free Windows download,
and you do not need a Pro licence unless you want to publish to the Power BI
Service.

Download: [Power BI Desktop from the Microsoft Store](https://apps.microsoft.com/detail/9NTXR16HNW1T)
(the Store version auto-updates; the standalone `.exe` does not).

---

## Step 0 — Produce the data

```powershell
python powerbi\export_for_powerbi.py --data data\ --out data\powerbi\
```

Six CSVs land in `data\powerbi\`. That folder is gitignored — it is generated,
and `fact_scored.csv` alone is 7 MB.

---

## Step 1 — Load

1. Open Power BI Desktop → **Blank report**
2. **Home → Get data → More → Folder → Connect**
3. Browse to `data\powerbi` → OK
4. On the preview screen click the dropdown next to **Combine** and choose
   **Transform Data** (not Combine — the six files have different columns and
   combining them would fail)

You are now in Power Query. In the left panel you will see one query. Delete
it, and instead load each file separately:

- **Home → New Source → Text/CSV**, pick `dim_date.csv`, click **Transform Data**
- Repeat for the other five

For each one, check that Power Query guessed the types correctly. The two that
usually need fixing:

- `dim_date[date_key]` → right-click the column header → **Change Type → Date**
- `fact_cohort[cohort_month]` → same

Then **Home → Close & Apply**.

---

## Step 2 — Build the model

Click the **Model** icon on the far left (third icon down). You will see six
boxes with some relationships auto-detected. Delete every auto-detected
relationship — Power BI guesses badly here — and drag these four yourself:

| From | To | Cardinality | Direction |
|---|---|---|---|
| `fact_scored[customer_id]` | `dim_customer[customer_id]` | Many to one | Single |
| `fact_scored[tier]` | `dim_plan[tier]` | Many to one | Single |
| `fact_monthly[date_key]` | `dim_date[date_key]` | Many to one | Single |
| `fact_scored[date_key]` | `dim_date[date_key]` | Many to one | Single |

`fact_cohort` stays unconnected. It has its own grain (cohort × months since
signup), and joining it to the date table would silently produce wrong numbers
on the heatmap.

**Mark the date table.** Click `dim_date` → **Table tools → Mark as date table**
→ choose `date_key`. Skip this and time intelligence returns wrong answers
without warning — this is the most common Power BI mistake there is.

**Fix the sort orders.** Power BI sorts text alphabetically, so "Apr, Aug, Dec"
and "0-5%, 10-15%, 5-10%". Fix both:

- Select `dim_date[month_name]` → **Column tools → Sort by column → month_sort**
- Select `fact_scored[risk_bucket]` → **Sort by column → risk_bucket_sort**

---

## Step 3 — Add the measures

1. **Home → Enter data**, name the table `_Measures`, click **Load**. It creates
   an empty table whose only job is to hold measures so they group together.
2. Open `powerbi/measures.dax` in a text editor.
3. For each measure: **Modeling → New measure**, paste, press Enter.

Start with the six you need for page 1 and add the rest as you build:
`Active Customers`, `At Risk Customers`, `Revenue at Risk`,
`Predicted Churn %`, `ARR`, `Risk Concentration`.

**Format them properly as you go.** Select the measure, then in **Measure
tools**:

| Measure | Format |
|---|---|
| Rupee measures | Custom format string: `#,##0,,,.0 "Cr"` |
| Percentage measures | Percentage, 1 decimal |
| Count measures | Whole number, comma separated |

That crore format string is worth the trouble. Power BI's default renders
₹1,136,858,088 and nobody reads that; `₹113.7 Cr` is what a CFO in Bengaluru
actually says out loud.

---

## Step 4 — Page 1: Executive

Rename the page tab to **Executive**.

**KPI cards** — five **Card** visuals across the top:
`Active Customers` · `At Risk Customers` · `Revenue at Risk` ·
`Predicted Churn %` · `Risk Concentration`

**Risk ladder** — Stacked column chart
- X axis: `fact_scored[risk_bucket]`
- Y axis: `ARR`
- Format → Data colors → **fx** → Format by **Field value** → pick a colour
  column, or just set four manual colours matching the web dashboard
  (`#29B6A0`, `#E8B23A`, `#E8843A`, `#E0574B`)

The point of this visual: bar height is **money, not headcount**. Most accounts
are safe; the revenue clusters on the right. Put that sentence in a text box
next to it — a chart nobody can interpret is decoration.

**Churn trend** — Line chart
- X axis: `dim_date[year_month]`
- Y axis: `Logo Churn %` and `Revenue Churn % `

**Risk band donut** — Donut chart
- Legend: `fact_scored[risk_band]`, Values: `ARR`

**Slicers** down the left: `dim_customer[segment]`, `dim_plan[tier]`,
`dim_customer[state]`

---

## Step 5 — Page 2: Diagnosis

**Why they are leaving** — Bar chart
- Y axis: `fact_scored[reason_1]`
- X axis: `Revenue at Risk`
- Filter: `churn_probability_90d` is greater than or equal to `0.15`

**Segment matrix** — Matrix visual
- Rows: `dim_customer[segment]`, Columns: `dim_plan[tier]`
- Values: `Predicted Churn %`, `Revenue at Risk`
- Format → Cell elements → Background color → **On** for `Predicted Churn %`

**Cohort heatmap** — Matrix visual
- Rows: `fact_cohort[cohort_month]`, Columns: `fact_cohort[months_since_signup]`
- Values: `Retention %`
- Cell elements → Background color → On, diverging, red low to green high

This is the visual that gets remembered. It shows whether newer cohorts retain
better than older ones — that is, whether anything the company changed actually
worked.

---

## Step 6 — Page 3: Action list and simulator

**The table** — Table visual with `dim_customer[company_name]`,
`fact_scored[churn_probability_90d]`, `fact_scored[mrr]`,
`fact_scored[revenue_at_risk]`, `fact_scored[risk_band]`,
`fact_scored[reason_1]`. Sort descending by `revenue_at_risk`.

Add **conditional formatting → Data bars** on `revenue_at_risk`.

**The what-if simulator**

1. **Modeling → New parameter → Numeric range**
2. Name `Discount %`, Minimum `0`, Maximum `40`, Increment `1`, Default `15`
3. Tick "Add slicer to this page"
4. Add the `Expected Revenue Saved`, `Retention Cost` and `Expected Benefit`
   measures from `measures.dax` as three Cards
5. On the `Expected Benefit` card: Format → Callout value → **fx** → Format by
   **Field value** → `Benefit Colour`

Drag the slider and the three numbers move.

**Be honest about what this version is.** The DAX simulator works at portfolio
level. The per-account version — with break-even bisection and a
recommendation that says *"do not discount, fix the root cause"* — lives in the
FastAPI service, because a bisection search in DAX would be slow and
unreadable. Add a text box on the page saying so, with a link to the web app.
Knowing where a tool stops being the right tool is a better answer in an
interview than forcing everything into one.

---

## Step 7 — Export and commit

Save as `powerbi/ChurnRadar.pbix`. Imported data makes it roughly 5–15 MB,
which is fine for GitHub (the limit is 100 MB per file, warning at 50 MB).

Then:

1. **File → Export → Export to PDF** → save as `powerbi/ChurnRadar.pdf`.
   This is the important one — GitHub renders PDFs inline, so anyone browsing
   the repo sees the report without installing Power BI.
2. Screenshot each page into `powerbi/screenshots/` and embed them in
   `powerbi/README.md`.

```powershell
git add powerbi/
git commit -m "feat(bi): Power BI report with star schema export and DAX library

Six-table star schema exported from the warehouse, 20 DAX measures, and a
three-page report (executive, diagnosis, action). Portfolio-level what-if
simulator via a numeric range parameter; the per-account version stays in
the API where bisection is cheap."
git push
```

---

## Optional — publish it live

If you have a work or college Microsoft account, **Home → Publish** puts the
report on the Power BI Service and gives you a shareable link. A free account
can publish to *My Workspace*, but sharing requires Pro. If you cannot share it,
the PDF export does the job.

---

## Two things that will go wrong

**Blank visuals after loading.** Almost always the relationships. Go back to
Model view and check the arrows point from fact to dimension, not the reverse.

**Time intelligence returning blank.** You did not mark `dim_date` as a date
table, or `date_key` is still typed as Text. Both are silent failures.
