"""PostgreSQL loading (idempotent full refresh in one transaction, bulk COPY) and read access."""
from __future__ import annotations

import io
import logging

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import Settings

log = logging.getLogger(__name__)
LOAD_ORDER = ("warehouses", "products", "inventory", "sales", "restocks")
CHUNK = 250_000


def get_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)


def _copy(cursor, table: str, df: pd.DataFrame) -> None:
    cols = ", ".join(df.columns)
    for start in range(0, len(df), CHUNK):
        buf = io.StringIO()
        df.iloc[start:start + CHUNK].to_csv(buf, index=False, header=False, date_format="%Y-%m-%d")
        buf.seek(0)
        cursor.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", buf)


def load_tables(engine: Engine, settings: Settings, tables: dict[str, pd.DataFrame]) -> None:
    """Recreate schema, bulk-load all tables and create views atomically: readers never see a half-load."""
    schema = (settings.sql_dir / "01_schema.sql").read_text()
    views = (settings.sql_dir / "04_views.sql").read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(schema)
        cur = conn.connection.cursor()
        for name in LOAD_ORDER:
            _copy(cur, name, tables[name])
        cur.close()
        conn.exec_driver_sql(views)
        conn.exec_driver_sql("ANALYZE")
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in LOAD_ORDER}
    log.info("loaded rows: %s", counts)


def read_tables(engine: Engine) -> dict[str, pd.DataFrame]:
    t = {
        "warehouses": pd.read_sql("SELECT * FROM warehouses", engine),
        "products": pd.read_sql("SELECT * FROM products", engine),
        "inventory": pd.read_sql("SELECT * FROM inventory", engine),
        "restocks": pd.read_sql("SELECT * FROM restocks", engine, parse_dates=["restock_date"]),
        "sales": pd.read_sql("SELECT * FROM sales", engine, parse_dates=["order_date"]),
    }
    for col in ("unit_cost", "unit_price"):
        t["products"][col] = t["products"][col].astype(float)
    for col in ("unit_price", "revenue"):
        t["sales"][col] = t["sales"][col].astype(float)
    return t
