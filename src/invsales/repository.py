"""Single entry point for the dashboard/API/alerts to read data:
PostgreSQL if reachable, else the cleaned parquet/CSV files of the active preset, else the committed demo."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .config import Settings
from .db import get_engine, read_tables

log = logging.getLogger(__name__)
TABLES = ("warehouses", "products", "inventory", "restocks", "sales")
DATE_COLS = {"sales": ["order_date"], "restocks": ["restock_date"]}


def save_clean(clean_dir: Path, tables: dict[str, pd.DataFrame], csv: bool = True) -> None:
    """Parquet is the canonical clean format (small, typed); CSV is written for Power BI/Excel/psql."""
    clean_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(clean_dir / f"{name}.parquet", index=False)
        if csv:
            df.to_csv(clean_dir / f"{name}.csv", index=False, date_format="%Y-%m-%d")


def load_clean(clean_dir: Path) -> dict[str, pd.DataFrame]:
    out = {}
    for name in TABLES:
        pq, csv = clean_dir / f"{name}.parquet", clean_dir / f"{name}.csv"
        out[name] = pd.read_parquet(pq) if pq.exists() else pd.read_csv(csv, parse_dates=DATE_COLS.get(name, []))
    return out


def load_data(settings: Settings) -> tuple[dict[str, pd.DataFrame], str]:
    """Returns (tables, source_label)."""
    try:
        return read_tables(get_engine(settings)), "PostgreSQL"
    except Exception as exc:  # DB down / not loaded yet
        log.warning("database unavailable (%s); falling back to files", type(exc).__name__)
    for preset_dir in (settings.clean_dir, settings.data_dir / "demo" / "clean"):
        if (preset_dir / "sales.parquet").exists() or (preset_dir / "sales.csv").exists():
            return load_clean(preset_dir), f"files ({preset_dir.parent.name})"
    raise FileNotFoundError("no data: run `invsales all` or point DATABASE_URL at a loaded database")
