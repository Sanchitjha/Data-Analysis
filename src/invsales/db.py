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


def _read_copy(engine: Engine, query: str, **read_csv_kwargs) -> pd.DataFrame:
    """Server-side COPY -> pandas: several times faster than read_sql for million-row tables."""
    raw = engine.raw_connection()
    try:
        buf = io.StringIO()
        with raw.cursor() as cur:
            cur.copy_expert(f"COPY ({query}) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
        buf.seek(0)
        return pd.read_csv(buf, **read_csv_kwargs)
    finally:
        raw.close()


def read_tables(engine: Engine) -> dict[str, pd.DataFrame]:
    return {
        "warehouses": _read_copy(engine, "SELECT * FROM warehouses"),
        "products": _read_copy(engine, "SELECT * FROM products"),
        "inventory": _read_copy(engine, "SELECT * FROM inventory"),
        "restocks": _read_copy(engine, "SELECT * FROM restocks", parse_dates=["restock_date"]),
        "sales": _read_copy(engine, "SELECT order_id, order_date, warehouse_id, product_id, quantity, unit_price, revenue "
                                    "FROM sales", parse_dates=["order_date"],
                            dtype={"quantity": "int32", "unit_price": "float64", "revenue": "float64"}),
    }
