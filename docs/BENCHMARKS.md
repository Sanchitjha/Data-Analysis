# Benchmarks

Measured on the `large` preset (6 warehouses x 300 products x 3 years) with a local PostgreSQL 16 on a 4 vCPU / 16 GB sandbox VM.
Reproduce: `invsales --preset large all` then `DATABASE_URL=... python scripts/benchmark.py`. Raw numbers: `benchmark.json`.
Absolute numbers depend on hardware; the point is the shape (linear ETL, index effect, model cost).

## Data volume
| Table | Rows |
|---|---|
| sales (order lines) | 1,474,989 (230 MB with indexes) |
| inventory (warehouse x product) | 1,800 |
| restocks | 26,110 |

## ETL (raw CSV -> clean -> validate -> PostgreSQL)
| Step | Time |
|---|---|
| Generate raw data (simulation + injected dirt), 1.50M raw rows | ~20 s |
| Clean + validate 1.50M rows (dedupe, date parsing, price fill) | 9.7 s |
| Bulk load with COPY, schema + indexes + views + ANALYZE, one transaction | 31.6 s |
| **Whole `invsales --preset large all`** | **59 s** |

## Query latency (median of 5 runs, ms)
| Query | ms |
|---|---|
| KPI summary | 108 |
| Monthly sales + MoM growth | 176 |
| Top 10 products by revenue | 120 |
| Warehouse summary | 92 |
| Reorder alerts | 25 |
| Stock turnover with NTILE classes | 188 |
| One warehouse, one month | 5.0 (37.2 without index, 7x) |
| One product, daily series | 9.7 (56.6 without index, 6x) |

## Application layer
| Item | Result |
|---|---|
| Load all tables into pandas via COPY | 3.5 s, 103 MB RAM (was ~12.6 s with `read_sql`) |
| ABC-XYZ, all 300 products | 0.45 s |
| Replenishment (safety stock / ROP / EOQ) for 1,800 warehouse-product pairs | 0.86 s |
| 30-day forecast + backtest for 300 products | 0.32 s |
| API after warm-up: `/kpis` 43 ms, `/alerts` 64 ms, `/forecast/{id}` 269 ms, `/replenishment` 0.7 s | |

## What this does not show
Everything runs on one machine and the largest table is ~1.5M rows. Beyond roughly 10-50M rows you would want partitioning by month,
pre-aggregated daily marts and an incremental (not full-refresh) load; the schema and views are designed so those are additive changes.
