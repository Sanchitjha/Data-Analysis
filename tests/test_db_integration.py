"""Loads pipeline output into a real PostgreSQL and checks SQL views == pandas KPIs.
These tests DROP and recreate the tables, so they only run against TEST_DATABASE_URL (never DATABASE_URL);
skipped when it is unset or unreachable."""
import os

import pandas as pd
import pytest
from sqlalchemy import text

from invsales import kpis
from invsales.clean import clean_all
from invsales.config import Settings
from invsales.db import get_engine, load_tables, read_tables
from invsales.simulate import generate_raw


@pytest.fixture(scope="module")
def env():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    settings = Settings(database_url=url)
    engine = get_engine(settings)
    try:
        engine.connect().close()
    except Exception:
        pytest.skip("PostgreSQL not reachable")
    raw = generate_raw(11, "demo", "2025-01-01", "2025-06-30")
    tables, _ = clean_all({k: v.astype(str).replace({"nan": None, "None": None}) for k, v in raw.items()})
    load_tables(engine, settings, tables)
    return engine, read_tables(engine), settings


def test_load_is_idempotent_and_complete(env):
    engine, t, settings = env
    n = len(t["sales"])
    load_tables(engine, settings, t)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM sales")).scalar_one() == n
    assert len(t["inventory"]) == len(t["warehouses"]) * len(t["products"])


def test_kpi_summary_matches_pandas(env):
    engine, t, _ = env
    row = pd.read_sql("SELECT * FROM v_kpi_summary", engine).iloc[0]
    h = kpis.headline(t["sales"], t["inventory"])
    assert float(row.total_sales) == pytest.approx(h["total_sales"])
    assert int(row.low_stock_items) == h["low_stock_items"]
    assert int(row.total_stock) == h["total_stock"] and int(row.units_sold) == h["units_sold"]


def test_turnover_view_matches_pandas(env):
    engine, t, _ = env
    sql = pd.read_sql("SELECT * FROM v_stock_turnover_classified", engine).set_index(["warehouse_id", "product_id"])
    py = kpis.stock_turnover(t["sales"], t["inventory"], t["restocks"], t["products"]).set_index(
        ["warehouse_id", "product_id"])
    diff = (sql.stock_turnover.astype(float) - py.stock_turnover.reindex(sql.index)).abs().max()
    assert diff < 0.011
    assert sql.movement_class.value_counts().to_dict() == py.movement_class.value_counts().to_dict()


def test_alert_view_matches_pandas(env):
    engine, t, _ = env
    a_sql = pd.read_sql("SELECT * FROM v_reorder_alerts", engine)
    a_py = kpis.reorder_alerts(t["sales"], t["inventory"], t["products"], t["warehouses"])
    assert set(zip(a_sql.warehouse_id, a_sql.product_id, strict=True)) == set(zip(a_py.warehouse_id, a_py.product_id, strict=True))


def test_monthly_and_warehouse_views_match_pandas(env):
    engine, t, _ = env
    sql = pd.read_sql("SELECT * FROM v_monthly_sales ORDER BY month", engine)
    assert list(sql.revenue.astype(float).round(2)) == list(kpis.monthly_sales(t["sales"]).revenue.round(2))
    w_sql = pd.read_sql("SELECT * FROM v_warehouse_summary", engine).set_index("warehouse_id")
    w_py = kpis.warehouse_summary(t["sales"], t["inventory"], t["warehouses"]).set_index("warehouse_id")
    assert (w_sql.revenue.astype(float) - w_py.revenue).abs().max() < 0.01
    assert (w_sql.low_stock_items - w_py.low_stock_items).abs().max() == 0
