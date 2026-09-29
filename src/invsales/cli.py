"""Command line interface:  invsales {generate|kaggle|etl|alerts|all}"""
from __future__ import annotations

import argparse
import logging
import sys

from . import sources
from .alerts import dispatch
from .config import get_settings
from .kpis import reorder_alerts
from .pipeline import run_etl
from .repository import load_data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="invsales")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="write synthetic raw CSVs to data/raw")
    k = sub.add_parser("kaggle", help="download the Kaggle Store-Item-Demand data and map it to the raw schema")
    k.add_argument("--train-csv", help="use an already-downloaded train.csv instead of calling Kaggle")
    k.add_argument("--items", type=int, help="only the first N items (faster)")
    e = sub.add_parser("etl", help="clean, validate and load into PostgreSQL")
    e.add_argument("--no-db", action="store_true", help="only write data/clean CSVs")
    a = sub.add_parser("alerts", help="send reorder alerts")
    a.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    al = sub.add_parser("all", help="generate + etl")
    al.add_argument("--no-db", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    if args.cmd in ("generate", "all"):
        sources.write_synthetic(s.raw_dir, s.seed)
    if args.cmd == "kaggle":
        from pathlib import Path
        train = Path(args.train_csv) if args.train_csv else sources.kaggle_download(s.data_dir / "kaggle")
        sources.write_kaggle(s.raw_dir, train, s.seed, args.items)
    if args.cmd in ("etl", "all"):
        run_etl(s, load_db=not args.no_db)
    if args.cmd == "alerts":
        sales, products, _, src = load_data(s)
        logging.getLogger(__name__).info("data source: %s", src)
        print(dispatch(reorder_alerts(sales, products), s, send=args.send))
    return 0


if __name__ == "__main__":
    sys.exit(main())
