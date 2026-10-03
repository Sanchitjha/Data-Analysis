# Design decisions and FAQ

Questions a reviewer (or an interviewer) is likely to ask about this project, with honest answers. Numbers are from the demo preset (seed 42).

## The 2-minute version
**Problem.** A warehouse or retailer has sales exports and stock sheets but no clear answer to: what do I order, how much, what will run out,
and where is cash stuck in stock that does not move?

**What I built.** A pipeline that cleans raw exports, validates them and loads PostgreSQL (up to 1.5M order lines); SQL views for the KPIs; a
Streamlit dashboard and REST API; a Power BI model and report; an Excel summary with PivotTables; and decision logic on top of the KPIs:
reorder points, EOQ, stockout probability, ABC-XYZ, forecasts with a backtest, transfer suggestions and what-if scenarios. A user can upload
their own sales (and stock) file and get the same outputs, with a report of every assumption made.

**Result (simulated data).** 5.36M sales across 3 warehouses; 36 of 180 warehouse-product pairs need an order now (about $63.6k); about 22% of
stock value sits above the order-up-to level; slower suppliers (+14 days) would roughly triple the purchase need.

**Honest framing.** The data is simulated (no public dataset has real stock levels). What is real is the engineering: cleaning, validation,
SQL, modelling, tests, CI, and the Power BI/Excel work.

## Formulas in plain words
| Metric | Definition | Meaning |
|---|---|---|
| Stock turnover | units sold / average stock; average stock = (opening + current) / 2 | how many times stock was sold and replaced; low = cash tied up |
| Days of inventory | days in period / turnover | how long current stock would last |
| Safety stock | z x sigma(daily demand) x sqrt(lead time) | buffer for demand variability; z = 1.65 means ~95% service level |
| Reorder point (ROP) | mean daily demand x lead time + safety stock | order when stock falls to this |
| EOQ | sqrt(2 x annual demand x ordering cost / (holding rate x unit cost)) | order size that balances ordering and holding cost |
| Order quantity | ROP + EOQ - stock (only when stock <= ROP) | order up to ROP + EOQ |
| Stockout risk | P(demand during lead time > stock), demand ~ Normal(mean x L, sigma x sqrt(L)) | likelihood of running out before the order arrives |
| ABC | cumulative revenue share: A = top 80%, B = next 15%, C = rest | value importance |
| XYZ | coefficient of variation of monthly demand rate: X <= 0.25, Y <= 0.5, Z above | how predictable demand is |
| WAPE | sum of absolute errors / sum of actuals | forecast error (lower is better) |

## Questions and answers
**Why simulated data? Is that a weakness?**
Real stock levels are private; Kaggle sales datasets have no inventory. I simulated demand (seasonality, trend, weekends, warehouse size) and a
reorder-point policy with supplier lead times, then deliberately corrupted the export (duplicates, missing values, three date formats, `$`
prices, inconsistent casing) so the cleaning is real work. The importer lets anyone run the same analysis on real files. I never present
simulated results as business findings.

**How did you clean the data and why those rules?**
Dedupe by `order_id` keeping the most complete row; parse three date formats; strip currency symbols; fill missing prices from the product
master; drop rows with missing or non-positive quantity or unknown product (they cannot be inferred). Counts of everything changed are written
to `cleaning_report.json`. A validation gate (20+ checks: keys, nulls, foreign keys, price > cost, revenue = quantity x price) aborts the load
if anything fails, so the database never holds half-clean data.

**Why PostgreSQL, and how do you know the SQL is right?**
Reporting views (`sql/04_views.sql`) compute turnover, NTILE classes, alerts and monthly growth in SQL. The same KPIs exist in pandas, and an
integration test loads data into a real PostgreSQL and asserts that the views equal the pandas results. That caught real differences
(for example how quartiles are assigned for small groups).

**How does it scale?**
Bulk `COPY` inside one transaction; a 1.47M-row load plus indexes plus views takes about 30 s, the whole ETL under a minute. Indexes make a
warehouse-and-month query about 7x faster (37 ms to 5 ms). Loading all tables into pandas takes 3.5 s and 103 MB. Limits: single machine,
full-refresh loads, no partitioning. Beyond ~10-50M rows I would partition by month, pre-aggregate daily marts and load incrementally
(see `docs/BENCHMARKS.md`).

**How good is the forecast?**
It is a transparent baseline: recent 28-day level x weekday profile x year-over-year seasonal ratio, with weekday profile and seasonality
pooled per category to reduce noise. On a 30-day holdout the weekly WAPE is 13.9% vs 15.8% for a flat recent average (10.7% vs 14.0% on the
large preset). Daily error is much higher (about 32%) because daily counts are small and noisy. It is not a tuned ML model, and the app shows
the error so users do not over-trust it.

**What does the replenishment logic assume, and where does it fail?**
Stable demand distribution, constant lead times, normally distributed lead-time demand, a single order-up-to policy. It ignores minimum
order quantities, pack sizes, budgets, promotions, and lost sales during stockouts (which make history understate demand). New products
or very short history give weak results; the app warns below 60 days of history.

**What is the what-if analysis?**
The same data with every lead time extended by N days or a different service level. On the demo data, +14 days raises the purchase need from
about $64k to about $180k and the number of items with 50%+ stockout risk from 19 to 40.

**Explain your Power BI model.**
Star schema: dimension tables `dim_products`, `dim_warehouses` and a generated `dim_date` (marked as the date table, `Month` sorted by
`Month Sort`) filter three fact tables (`fact_sales`, `fact_inventory`, `fact_restocks`) through one-to-many, single-direction relationships.
Measures live in a `_Measures` table. Three facts at different grains share the same dimensions, so a slicer on warehouse or category filters
sales, stock and restocks together.

**Walk me through some DAX.**
- `Total Sales = SUM(fact_sales[revenue])`: a simple aggregation whose result depends on the filter context (slicers, visual rows).
- `Low-Stock Items = COUNTROWS(FILTER(fact_inventory, current_stock <= reorder_level))`: row-by-row comparison on the inventory table.
- `Opening Stock = VAR d = CALCULATE(MIN(restock_date), ALL(fact_restocks)) RETURN CALCULATE(SUM(quantity), restock_date = d)`: finds the
  first date across all history (ALL removes filters), then sums the stock-in on that day for the current filter context.
- `Stock Turnover = DIVIDE(Units Sold, Average Stock)`: DIVIDE avoids divide-by-zero errors; per product it is evaluated through the relationships.
- `Sales LY = CALCULATE([Total Sales], SAMEPERIODLASTYEAR(dim_date[Date]))`: time intelligence, which needs a marked date table.
- `Movement Class`: uses `PERCENTILEX.INC` over all products to label top-quartile turnover Fast and bottom-quartile Slow.
A total-level `Sales YoY %` card looks wrong (106%) because with no date filter it compares two years against one; it is meaningful on a
month or year axis. Likewise `Reorder Status` and `Revenue Rank` are per-row measures.

**What went wrong while building it?**
- Power Query did not detect the header of the all-text `dim_warehouses` CSV (columns came in as Column1..3), so the relationship dialog showed
  wrong columns; fixed with "Use first row as headers".
- A price like `Rs. 1,200` parsed to NaN because the cleaner stripped symbols but kept the stray dot; tests for the importer found it.
- Stock turnover produced NaN (and crashed the quartile step) for items with zero stock and no restock history; the classes now label those `n/a`.
- Integration tests originally rewrote the development database; they now run only against a separate `TEST_DATABASE_URL`.
- The generated Power BI project files were missing their `$schema` lines; validating against Microsoft's published JSON schemas found it.

**How is it tested?**
87 tests: cleaning rules, validation, KPI formulas with hand-computed expectations, simulation invariants (stock conservation), importer edge
cases (date formats, returns, missing columns), replenishment formulas, API, CLI, Power BI project consistency, and SQL-vs-pandas parity on
PostgreSQL. CI runs lint, tests with a PostgreSQL service, an end-to-end ETL, API and dashboard smoke tests, a 1.5M-row scale job and a Docker build.

**What would you do next?**
Login and per-user data, connectors (Google Sheets, Tally/Zoho exports), incremental loads, minimum order quantities and budget constraints in
the replenishment step, promotion-aware forecasting, and a pilot with a real small business to validate the recommendations against what
they actually reordered.

## About tooling
This project was built with an AI coding assistant. Be ready to say so, and to explain any part you present: the formulas above, the cleaning
rules, the star schema and the DAX measures. You rebuilt the Power BI model and measures by hand and verified every number against pandas,
so that part is yours to defend. Read `src/invsales/analytics.py` and `src/invsales/importer.py` once before an interview.
