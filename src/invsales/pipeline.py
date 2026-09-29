"""ETL orchestration: extract (raw CSV) -> clean -> validate -> save -> load PostgreSQL."""
from __future__ import annotations

import json
import logging
import time

import pandas as pd

from .clean import clean_all
from .config import Settings
from .db import get_engine, load_tables
from .repository import save_clean
from .sources import RAW_TABLES
from .validate import assert_valid

log = logging.getLogger(__name__)


def run_etl(settings: Settings, load_db: bool = True) -> dict:
    raw = settings.raw_dir
    missing = [f"raw_{n}.csv" for n in RAW_TABLES if not (raw / f"raw_{n}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"missing raw files in {raw}: {missing} (run `invsales generate` or `invsales kaggle`)")
    t0 = time.perf_counter()
    frames = {n: pd.read_csv(raw / f"raw_{n}.csv", dtype=str) for n in RAW_TABLES}
    tables, report = clean_all(frames)
    t1 = time.perf_counter()
    assert_valid(tables)          # raises -> nothing is written or loaded
    save_clean(settings.clean_dir, tables)
    report.update({"seconds_clean": round(t1 - t0, 1), "rows": {k: len(v) for k, v in tables.items()}})
    if load_db:
        t2 = time.perf_counter()
        load_tables(get_engine(settings), settings, tables)
        report["seconds_load"] = round(time.perf_counter() - t2, 1)
    (settings.clean_dir / "cleaning_report.json").write_text(json.dumps(report, indent=2))
    log.info("etl report: %s", report)
    return report
