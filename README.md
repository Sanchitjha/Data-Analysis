# Inventory_Sales_Dashboard

[![CI](https://github.com/Sanchitjha/Inventory_Sales_Dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/Sanchitjha/Inventory_Sales_Dashboard/actions)
[![Live demo](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://data-analysis-05.streamlit.app/)

**Live demo:** https://data-analysis-05.streamlit.app/ (simulated data; free-tier apps sleep when idle, the first load may take ~30 s)

An **inventory decision-support tool** you can point at your own data. Export sales (and optionally stock and a product list) from Excel,
Tally, Zoho, a POS or an ERP, upload it, and get: **what to order and how much** (safety stock / reorder point / EOQ), **what may stock out**
(probability during the supplier lead time), **cash tied up** in excess and dead stock, **transfers** between locations, demand forecasts
with a backtest, ABC-XYZ segmentation and a **weekly Excel action pack**, plus **what-if** analysis for slower suppliers or higher service
levels. Under the hood: a tested ETL pipeline, PostgreSQL (1.5M+ order lines), SQL views, a REST API and a Power BI model.

New here? Read the [user guide](docs/USER_GUIDE.md): what files you need, what each number means, and the limits you should know before acting on it.

**Stack:** Python (Pandas, NumPy, SQLAlchemy) · PostgreSQL · FastAPI · Streamlit/Plotly · Power BI (DAX/TMDL) · Excel · Docker · GitHub Actions

![overview](screenshots/app_overview.png)
![reorder plan](screenshots/app_reorder_plan.png)

## What it does
| Area | Details |
|---|---|
| **Bring your own data** | upload CSV/XLSX (or `invsales import`): auto column mapping (SKU/Item Code/Qty Sold/Branch...), messy dates (DD/MM vs MM/DD, Excel serials), currency text (`Rs. 1,200`), returns excluded, and an **import report** listing every drop and assumption. Only sales are required; missing stock/cost/lead time get documented defaults |
| **Data pipeline** | raw CSV -> clean (dedupe, 3 date formats, `$` prices, missing values) -> quality gate (20+ checks) -> parquet/CSV -> PostgreSQL via bulk `COPY` in one transaction (idempotent) |
| **Scale** | `demo` preset: 60 SKUs x 3 warehouses (103k rows, committed, used by the live demo). `large`: 300 SKUs x 6 warehouses x 3 years = **1.47M order lines**, full ETL in 59 s. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) |
| **KPIs / SQL** | sales, stock, turnover, days of inventory, fast/slow quartiles (`NTILE`), MoM growth, margin, warehouse comparison: reporting views in `sql/04_views.sql`, cross-checked against pandas in tests |
| **Replenishment** | per warehouse x product: safety stock `z*sigma*sqrt(L)`, reorder point, EOQ, suggested order qty and cost, gap vs current reorder level |
| **Forecasting** | 30-day demand per product (level x weekday profile x yoy seasonality, pooled per category) with a holdout **backtest vs a naive baseline** |
| **ABC-XYZ** | value class (cumulative revenue) x demand variability (CV of monthly rate) |
| **Risk and cash** | stockout probability during lead time, excess stock value, dead stock (no sales in 90 days), median days of cover |
| **What-if** | slower suppliers (+N days) and service level 80-99.5%: purchase need and at-risk items recomputed (dashboard tab, sidebar, `/inventory/health?delay_days=`) |
| **Action pack** | one-click Excel: orders to place, stockout risk, transfers, excess stock, ABC-XYZ, and the assumptions ([sample](docs/sample_action_pack.xlsx)) |
| **Transfers** | greedy rebalancing: surplus (> ROP + EOQ) to warehouses short on the same product, before buying |
| **Dashboard** | 9 tabs (overview, ABC-XYZ, forecast, reorder plan, cash & risk, what-if, transfers, fast/slow, alerts), filters by location/category/date, CSV/Excel downloads; works without a stock file (sales analytics only) |
| **REST API** | `/kpis /alerts /replenishment /inventory/health /forecast/{id} /abc /transfers /products/{id}` + Swagger at `/docs`, optional `X-API-Key` |
| **Automation** | daily GitHub Actions job: ETL + alerts (Slack / SMTP), hosted-PostgreSQL ready (Neon/Supabase via `DATABASE_URL`) |
| **Quality** | 87 tests (82 without a test database; unit, importer edge cases, API, CLI, Power BI project consistency, **SQL-vs-pandas on real PostgreSQL**), ruff, CI incl. a 1.5M-row scale job, Docker build |

## Architecture
```
data/<preset>/raw/*.csv ─► clean ─► validate ─► data/<preset>/clean/*.parquet ─► PostgreSQL (tables, indexes, views)
 synthetic simulator                   (abort on failure)                              │
 or Kaggle adapter                                                                      ├─► Streamlit dashboard  (falls back to parquet if no DB)
                                                                                        ├─► FastAPI  /docs
                                                                                        ├─► Power BI (PBIP/DAX) and Excel
                                                                                        └─► alerts: Slack / email (cron)
```
| Path | Purpose |
|---|---|
| `src/invsales/` | `importer` (bring your own data), `simulate`, `sources`, `clean`, `validate`, `db`, `repository`, `kpis`, `analytics`, `reports`, `alerts`, `api`, `pipeline`, `cli` |
| `sql/` | `01_schema` (5 tables, PK/FK/checks, 4 indexes) · `03_analysis_queries` · `04_views` (reporting views) |
| `app/streamlit_app.py` | dashboard |
| `powerbi/` | `Inventory.pbip` (generated TMDL model), `measures.dax`, `BUILD_GUIDE.md`, model CSVs |
| `excel/` | workbook: SUMIFS summaries, warehouse chart, inventory flags, Python replenishment sheet |
| `notebooks/01_exploration.ipynb` | executed walk-through of the results |
| `scripts/` | benchmark, Excel/Power BI exports, PBIP + notebook generators |
| `docs/` | `USER_GUIDE.md`, `BENCHMARKS.md`, `DESIGN_DECISIONS_FAQ.md`, sample action pack |
| `templates/` | sample input files (`invsales templates`) |

## About the data (please read)
- **Default: synthetic.** `invsales generate` simulates warehouses x products x days of demand (seasonality, trend, weekends, warehouse size), a
  reorder-point policy with supplier lead times, restocks and supplier outages, then corrupts the export the way real ones are so cleaning is
  real. Seeded and reproducible. All results below are properties of the simulation, not real-world findings.
- **Real sales (optional): Kaggle.** `invsales kaggle` downloads *Store Item Demand Forecasting* and maps stores to warehouses. Real: dates, stores,
  items, units sold. **Derived, not in that dataset:** product names/categories/prices/costs/lead times and the whole inventory layer
  (stock, reorder levels, restocks). Needs `KAGGLE_USERNAME`/`KAGGLE_KEY` and accepting the competition rules; the adapter is unit-tested on a
  same-schema fixture but **has not been run against the real download**.
- No public dataset ships true stock levels for a specific business; say the inventory layer is simulated when discussing the project.

## Quick start
**Use your own data:** open the dashboard, choose *My data (upload)* (or `invsales import --sales sales.xlsx --stock stock.csv`). For confidential data, run it yourself: `docker compose up`.
```bash
# Docker: PostgreSQL + ETL + dashboard (:8501) + API (:8000)
docker compose up --build            # PRESET=large docker compose up --build  for the 1.5M-row dataset
docker compose run --rm alerts       # dry-run alert (add --send after configuring .env)

# Local
pip install -e ".[dashboard,api,dev]"
cp .env.example .env
invsales all                         # generate -> clean -> validate -> load PostgreSQL   (invsales --preset large all)
streamlit run app/streamlit_app.py   # falls back to data/demo/clean if PostgreSQL is unreachable
uvicorn invsales.api:app --port 8000 # http://localhost:8000/docs
invsales alerts                      # dry run;  --send to post to Slack / email
pytest                               # DB integration tests need TEST_DATABASE_URL pointing at a scratch database (they drop tables!)
```
`invsales kaggle [--train-csv path] [--items N]` then `invsales etl` switches the source to Kaggle data.
Compose uses development credentials (`inventory/inventory`); set `POSTGRES_PASSWORD` for anything shared.

## Model details
- **Stock turnover** = units sold ÷ average stock, average stock = (opening + current) ÷ 2; **days of inventory** = days selling ÷ turnover
- **Safety stock** = z · σ(daily demand) · √lead time (z = 1.65 ≈ 95% service level, `SERVICE_LEVEL_Z`)
- **Reorder point** = mean daily demand · lead time + safety stock · **EOQ** = √(2 · annual demand · ordering cost ÷ (holding rate · unit cost))
- **Order** (when stock ≤ ROP) = ROP + EOQ − stock · **Transfer surplus** = stock − (ROP + EOQ)
- **Forecast check** (holdout last 30 days, demo data): weekly WAPE 13.9% vs 15.8% for a flat baseline; on the large preset 10.7% vs 14.0%.
  It is a transparent statistical baseline, not a tuned ML model; daily error is dominated by small-count noise.

## Results with the default demo data (seed 42)
- $5.36M sales, 344k units across 3 warehouses; Beverages lead with a summer peak and a Q4 trough
- 36 of 180 warehouse-product pairs need an order now (≈ $63.6k at cost); 82% have a reorder level below the recommended reorder point
- 21 "AX" products (high value, stable demand) generate 55% of revenue; 5 transfers could avoid ≈ $850 of purchases

## Deployment
- **Dashboard:** Streamlit Community Cloud from `main` (`app/streamlit_app.py`, deps from `requirements.txt`); it reads the committed `data/demo/clean/*.parquet`,
  so no database is needed online. Every push to `main` redeploys.
- **Hosted database (optional):** create a Neon/Supabase PostgreSQL, set `DATABASE_URL=postgresql+psycopg2://USER:PASS@HOST/DB?sslmode=require`
  (as an app secret / repo secret), run `invsales all` once; the dashboard, API and alerts then read from it.
- **API / full stack:** `docker compose up` on any Docker host (Render, Fly.io, Railway, a VM).
- **Scheduled alerts:** `.github/workflows/scheduled.yml` runs daily; add repository secrets `SLACK_WEBHOOK_URL` and/or `SMTP_*` to enable sending.
- Vercel/Netlify do not fit (Streamlit needs a long-running server).

## Power BI and Excel
- `powerbi/Inventory.pbip`: model plus a finished 12-visual report page (`powerbi/expected_layout.png` shows the intended look). Generated by
  `scripts/build_pbip.py`, checked offline by `tests/test_pbip.py` and against Microsoft's JSON schemas by `scripts/validate_pbip.py`. The generator
  did **not** open it in Power BI Desktop; the model and measures were separately rebuilt by hand in Desktop and matched every number.
  See `powerbi/BUILD_GUIDE.md` (fast path + manual fallback). `powerbi/Inventory_Sales_Dashboard.pbix` is the hand-built report (full model + 17 measures; page 1 = measure checks, page 2 = KPI cards, slicers, monthly trend, sales by warehouse).
- `excel/Inventory_Sales_Summary.xlsx`: two **real PivotTables** (revenue by category x year, by warehouse x category) on the `Sales_Data` table, plus
  SUMIFS summaries, a monthly chart, inventory reorder flags and the Python replenishment sheet. Built with `python scripts/build_excel_and_exports.py`
  then `python scripts/add_pivot_tables.py` (the second step drives LibreOffice, because openpyxl cannot author pivots). All formulas were recalculated
  in LibreOffice and the totals match pandas (grand total 5,358,458.85); it has not been opened in Microsoft Excel itself, where pivots show
  "Grand Total" labels after a refresh.

