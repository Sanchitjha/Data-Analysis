"""Benchmarks the pipeline and key queries on a loaded database.
Usage: DATABASE_URL=... python scripts/benchmark.py [--json-out docs/benchmark.json]"""
import argparse
import json
import statistics
import time

import pandas as pd
from sqlalchemy import text

from invsales import analytics
from invsales.config import get_settings
from invsales.db import get_engine, read_tables

QUERIES = {
    "KPI summary (v_kpi_summary)": "SELECT * FROM v_kpi_summary",
    "Monthly sales + MoM growth": "SELECT * FROM v_monthly_sales",
    "Top 10 products by revenue": "SELECT product_id, SUM(revenue) r FROM sales GROUP BY 1 ORDER BY r DESC LIMIT 10",
    "Warehouse summary": "SELECT * FROM v_warehouse_summary",
    "Reorder alerts (v_reorder_alerts)": "SELECT * FROM v_reorder_alerts",
    "Stock turnover, classified": "SELECT * FROM v_stock_turnover_classified",
    "One warehouse, one month (index range scan)":
        "SELECT SUM(revenue) FROM sales WHERE warehouse_id = 'W03' AND order_date >= '2025-06-01' AND order_date < '2025-07-01'",
    "One product, daily series (index scan)":
        "SELECT order_date, SUM(quantity) FROM sales WHERE product_id = 'P1001' GROUP BY 1 ORDER BY 1",
}
INDEXED = ["One warehouse, one month (index range scan)", "One product, daily series (index scan)"]


def median_ms(conn, sql, runs=5):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        conn.execute(text(sql)).fetchall()
        times.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(times), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out")
    args = ap.parse_args()
    engine = get_engine(get_settings())
    out = {}
    with engine.connect() as c:
        out["rows"] = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in ("sales", "inventory", "restocks")}
        out["table_size_mb"] = round(c.execute(text("SELECT pg_total_relation_size('sales')/1e6")).scalar_one(), 1)
        out["queries_ms"] = {name: median_ms(c, sql) for name, sql in QUERIES.items()}
    with engine.begin() as c:                                             # same queries without the indexes
        idx = [r[0] for r in c.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename='sales' AND indexname LIKE 'idx_%'"))]
        names = [r[0] for r in c.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='sales' AND indexname LIKE 'idx_%'"))]
        for n in names:
            c.execute(text(f"DROP INDEX {n}"))
        out["no_index_ms"] = {name: median_ms(c, QUERIES[name], runs=3) for name in INDEXED}
        for d in idx:
            c.execute(text(d))
        c.execute(text("ANALYZE sales"))
    t0 = time.perf_counter()
    t = read_tables(engine)
    out["load_into_pandas_s"] = round(time.perf_counter() - t0, 1)
    out["pandas_mem_mb"] = round(sum(v.memory_usage(deep=True).sum() for v in t.values()) / 1e6)
    s, inv, prod, wh = t["sales"], t["inventory"], t["products"], t["warehouses"]
    groups = prod.set_index("product_id").category
    timings = {}
    for name, fn in {
        "ABC-XYZ": lambda: analytics.abc_xyz(s, prod),
        "Replenishment (ROP/EOQ) for all warehouse x product": lambda: analytics.replenishment(s, inv, prod, wh),
        "Forecast 30d + backtest": lambda: (analytics.forecast(s, 30, groups), analytics.backtest(s, 30, groups)),
    }.items():
        t0 = time.perf_counter()
        fn()
        timings[name] = round(time.perf_counter() - t0, 2)
    out["analytics_s"] = timings
    if args.json_out:
        pd.Series(out).to_json(args.json_out, indent=2)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
