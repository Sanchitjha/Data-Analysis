"""ETL orchestration: extract (raw CSV) -> clean -> validate -> save -> load PostgreSQL."""
from __future__ import annotations

import json
import logging

import pandas as pd

from .clean import clean_all
from .config import Settings
from .db import get_engine, load_tables
from .validate import assert_valid

log = logging.getLogger(__name__)


def run_etl(settings: Settings, load_db: bool = True) -> dict:
    raw = settings.raw_dir
    missing = [f for f in ("raw_sales.csv", "raw_products.csv", "raw_restocks.csv") if not (raw / f).exists()]
    if missing:
        raise FileNotFoundError(f"missing raw files in {raw}: {missing} (run `invsales generate` or `invsales kaggle`)")
    sales, products, restocks, report = clean_all(
        pd.read_csv(raw / "raw_sales.csv", dtype=str), pd.read_csv(raw / "raw_products.csv", dtype=str),
        pd.read_csv(raw / "raw_restocks.csv", dtype=str))
    assert_valid(sales, products, restocks)          # raises -> nothing is written or loaded
    settings.clean_dir.mkdir(parents=True, exist_ok=True)
    sales.to_csv(settings.clean_dir / "sales.csv", index=False, date_format="%Y-%m-%d")
    products.to_csv(settings.clean_dir / "products.csv", index=False)
    restocks.to_csv(settings.clean_dir / "restocks.csv", index=False, date_format="%Y-%m-%d")
    (settings.clean_dir / "cleaning_report.json").write_text(json.dumps(report, indent=2))
    log.info("cleaning report: %s", report)
    if load_db:
        load_tables(get_engine(settings), settings, sales, products, restocks)
    return report
