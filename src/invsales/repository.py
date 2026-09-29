"""Single entry point for the dashboard/alerts to read data: PostgreSQL if reachable, else clean CSVs."""
from __future__ import annotations

import logging

import pandas as pd

from .config import Settings
from .db import get_engine, read_tables

log = logging.getLogger(__name__)


def load_from_csv(settings: Settings):
    d = settings.clean_dir
    return (pd.read_csv(d / "sales.csv", parse_dates=["order_date"]), pd.read_csv(d / "products.csv"),
            pd.read_csv(d / "restocks.csv", parse_dates=["restock_date"]))


def load_data(settings: Settings):
    """Returns (sales, products, restocks, source_label)."""
    try:
        return (*read_tables(get_engine(settings)), "PostgreSQL")
    except Exception as exc:  # DB down / not loaded yet
        log.warning("database unavailable (%s); falling back to CSV files", type(exc).__name__)
        return (*load_from_csv(settings), "CSV files")
