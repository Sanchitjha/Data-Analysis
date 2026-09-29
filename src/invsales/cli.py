"""Command line interface:  invsales {generate|kaggle|etl|alerts|all}"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

from . import sources
from .alerts import dispatch
from .config import get_settings
from .kpis import reorder_alerts
from .pipeline import run_etl
from .repository import load_data


def run_import(args, settings) -> int:
    from .db import get_engine, load_tables
    from .importer import PRODUCT_FIELDS, SALES_FIELDS, STOCK_FIELDS, ImportDefaults, import_data, suggest_mapping
    from .repository import save_clean

    def read(path):
        p = Path(path)
        return pd.read_excel(p, dtype=object) if p.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(p, dtype=object)

    def mapping(df, fields):
        m = suggest_mapping(list(df.columns), fields)
        for item in args.map:
            k, _, v = item.partition("=")
            if k in m:
                m[k] = v
        return m

    sales = read(args.sales)
    stock = read(args.stock) if args.stock else None
    prods = read(args.products) if args.products else None
    sm = mapping(sales, SALES_FIELDS)
    print("sales column mapping:", {k: v for k, v in sm.items()})
    tables, rep = import_data(
        sales, sm, stock_raw=stock, stock_map=mapping(stock, STOCK_FIELDS) if stock is not None else None,
        products_raw=prods, products_map=mapping(prods, PRODUCT_FIELDS) if prods is not None else None,
        defaults=ImportDefaults(dayfirst=not args.month_first, service_level_z=settings.service_level_z,
                                ordering_cost=settings.ordering_cost, holding_rate=settings.holding_rate))
    for level, items in (("ERROR", rep.errors), ("WARNING", rep.warnings), ("ASSUMPTION", rep.assumptions)):
        for m in items:
            print(f"{level}: {m}")
    print(f"rows in {rep.rows_in:,} -> out {rep.rows_out:,}; dropped: {rep.dropped or 'none'}; period {rep.date_min}..{rep.date_max}")
    if tables is None:
        return 1
    out = Path(args.out) if args.out else settings.clean_dir
    save_clean(out, tables)
    print(f"clean tables written to {out}")
    if args.load_db:
        load_tables(get_engine(settings), settings, tables)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="invsales")
    ap.add_argument("--preset", choices=["demo", "large"], help="dataset size (overrides PRESET env)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="write synthetic raw CSVs (preset: PRESET env, demo|large)")
    k = sub.add_parser("kaggle", help="download the Kaggle Store-Item-Demand data and map it to the raw schema")
    k.add_argument("--train-csv", help="use an already-downloaded train.csv instead of calling Kaggle")
    k.add_argument("--items", type=int, help="only the first N items (faster)")
    e = sub.add_parser("etl", help="clean, validate and load into PostgreSQL")
    e.add_argument("--no-db", action="store_true", help="only write data/clean CSVs")
    a = sub.add_parser("alerts", help="send reorder alerts")
    a.add_argument("--send", action="store_true", help="actually send (default: dry run)")
    im = sub.add_parser("import", help="import YOUR OWN csv/xlsx exports (sales required; stock and products optional)")
    im.add_argument("--sales", required=True, help="sales export (csv/xlsx): date, item, quantity [, location, price]")
    im.add_argument("--stock", help="current stock on hand (csv/xlsx): item, stock [, location, reorder level]")
    im.add_argument("--products", help="product master (csv/xlsx): item, name, category, cost, price, lead time")
    im.add_argument("--out", help="output folder for the clean tables (default data/<preset>/clean)")
    im.add_argument("--load-db", action="store_true", help="also load PostgreSQL (recreates the tables!)")
    im.add_argument("--map", action="append", default=[], metavar="FIELD=COLUMN",
                    help="override column mapping, e.g. --map quantity='Units Sold' (repeatable)")
    im.add_argument("--month-first", action="store_true", help="treat ambiguous dates as MM/DD instead of DD/MM")
    sub.add_parser("templates", help="write sample input files for `invsales import` to ./templates")
    al = sub.add_parser("all", help="generate + etl")
    al.add_argument("--no-db", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.preset:
        os.environ["PRESET"] = args.preset
    s = get_settings()
    if args.cmd in ("generate", "all"):
        sources.write_synthetic(s.raw_dir, s.seed, s.preset)
    if args.cmd == "kaggle":
        train = Path(args.train_csv) if args.train_csv else sources.kaggle_download(s.data_dir / "kaggle")
        sources.write_kaggle(s.raw_dir, train, s.seed, args.items)
    if args.cmd in ("etl", "all"):
        run_etl(s, load_db=not args.no_db)
    if args.cmd == "templates":
        from .templates import write_templates
        print("written:", *write_templates(Path("templates")))
    if args.cmd == "import":
        return run_import(args, s)
    if args.cmd == "alerts":
        tables, src = load_data(s)
        logging.getLogger(__name__).info("data source: %s", src)
        print(dispatch(reorder_alerts(tables["sales"], tables["inventory"], tables["products"], tables["warehouses"]), s,
                       send=args.send))
    return 0


if __name__ == "__main__":
    sys.exit(main())
