"""PostgreSQL loading (idempotent full refresh in a single transaction) and read access."""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import Settings

log = logging.getLogger(__name__)
TABLES = ("products", "sales", "restocks")


def get_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def run_sql_file(engine: Engine, path) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(path.read_text())


def load_tables(engine: Engine, settings: Settings, sales: pd.DataFrame, products: pd.DataFrame,
                restocks: pd.DataFrame) -> None:
    """Recreate schema, load all tables and create views atomically: readers never see a half-load."""
    schema = (settings.sql_dir / "01_schema.sql").read_text()
    views = (settings.sql_dir / "04_views.sql").read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(schema)
        products.to_sql("products", conn, if_exists="append", index=False, method="multi", chunksize=2000)
        sales.to_sql("sales", conn, if_exists="append", index=False, method="multi", chunksize=5000)
        restocks.to_sql("restocks", conn, if_exists="append", index=False, method="multi", chunksize=5000)
        conn.exec_driver_sql(views)
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in TABLES}
    log.info("loaded rows: %s", counts)


def read_tables(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sales = pd.read_sql("SELECT * FROM sales", engine, parse_dates=["order_date"])
    products = pd.read_sql("SELECT * FROM products", engine)
    restocks = pd.read_sql("SELECT * FROM restocks", engine, parse_dates=["restock_date"])
    for col in ("unit_cost", "unit_price"):
        products[col] = products[col].astype(float)
    sales["unit_price"] = sales.unit_price.astype(float)
    sales["revenue"] = sales.revenue.astype(float)
    return sales, products, restocks
