"""Loads the pipeline output into a real PostgreSQL and checks SQL views == pandas KPIs.
Skipped automatically when no database is reachable (set DATABASE_URL to enable)."""
import pandas as pd
import pytest
from sqlalchemy import text

from invsales import kpis
from invsales.clean import clean_all
from invsales.config import Settings
from invsales.db import get_engine, load_tables, read_tables
from invsales.simulate import generate_raw


@pytest.fixture(scope="module")
def engine_and_data():
    settings = Settings()
    engine = get_engine(settings)
    try:
        engine.connect().close()
    except Exception:
        pytest.skip("PostgreSQL not reachable")
    raw = generate_raw(11, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-30"))
    sales, products, restocks, _ = clean_all(raw[0].astype(str).replace({"nan": None, "None": None}),
                                             raw[1].astype(str), raw[2].astype(str))
    load_tables(engine, settings, sales, products, restocks)
    return engine, read_tables(engine)


def test_load_is_idempotent(engine_and_data):
    engine, (sales, products, restocks) = engine_and_data
    n = len(sales)
    settings = Settings()
    load_tables(engine, settings, sales, products, restocks)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM sales")).scalar_one() == n


def test_kpi_summary_matches_pandas(engine_and_data):
    engine, (sales, products, restocks) = engine_and_data
    row = pd.read_sql("SELECT * FROM v_kpi_summary", engine).iloc[0]
    h = kpis.headline(sales, products)
    assert float(row.total_sales) == pytest.approx(h["total_sales"]) and int(row.low_stock_items) == h["low_stock_items"]
    assert int(row.total_stock) == h["total_stock"] and int(row.units_sold) == h["units_sold"]


def test_turnover_and_alert_views_match_pandas(engine_and_data):
    engine, (sales, products, restocks) = engine_and_data
    sql = pd.read_sql("SELECT * FROM v_stock_turnover_classified", engine).set_index("product_id")
    py = kpis.stock_turnover(sales, products, restocks).set_index("product_id")
    assert (sql.stock_turnover.astype(float) - py.stock_turnover).abs().max() < 0.011
    assert sql.movement_class.value_counts().to_dict() == py.movement_class.value_counts().to_dict()
    a_sql = pd.read_sql("SELECT * FROM v_reorder_alerts", engine)
    a_py = kpis.reorder_alerts(sales, products)
    assert set(a_sql.product_id) == set(a_py.product_id)


def test_monthly_view_matches_pandas(engine_and_data):
    engine, (sales, _, _) = engine_and_data
    sql = pd.read_sql("SELECT * FROM v_monthly_sales ORDER BY month", engine)
    py = kpis.monthly_sales(sales)
    assert list(sql.revenue.astype(float).round(2)) == list(py.revenue.round(2))
