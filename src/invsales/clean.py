"""Cleaning rules: raw CSV frames -> typed, deduplicated tables + a report of what changed."""
from __future__ import annotations

import pandas as pd

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y")


def to_number(s: pd.Series) -> pd.Series:
    """'$12.50' / '1,200' / 12.5 -> float (unparseable -> NaN)."""
    return pd.to_numeric(s.astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")


def parse_dates(s: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        out = out.fillna(pd.to_datetime(s, format=fmt, errors="coerce"))
    return out


def clean_products(raw: pd.DataFrame) -> pd.DataFrame:
    p = raw.copy()
    p["product_name"] = p.product_name.str.strip()
    p["category"] = p.category.str.strip().str.title()
    for c in ("unit_cost", "unit_price"):
        p[c] = to_number(p[c])
    for c in ("lead_time_days", "reorder_level", "current_stock"):
        p[c] = pd.to_numeric(p[c], errors="raise").astype(int)
    p = p.drop_duplicates("product_id")
    return p[["product_id", "product_name", "category", "unit_cost", "unit_price",
              "lead_time_days", "reorder_level", "current_stock"]].reset_index(drop=True)


def clean_sales(raw: pd.DataFrame, products: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    s = raw.copy()
    report = {"rows_in": len(s)}
    s["order_date"] = parse_dates(s.order_date.astype(str))
    report["unparseable_dates_dropped"] = int(s.order_date.isna().sum())
    s = s.dropna(subset=["order_date"])
    s["unit_price"] = to_number(s.unit_price)
    s["quantity"] = pd.to_numeric(s.quantity, errors="coerce")
    # duplicates: same order_id -> keep the most complete row
    s["_nulls"] = s.isna().sum(axis=1)
    n = len(s)
    s = s.sort_values(["order_id", "_nulls"]).drop_duplicates("order_id").drop(columns="_nulls")
    report["duplicates_removed"] = n - len(s)
    price_map = products.set_index("product_id").unit_price
    report["prices_filled_from_master"] = int(s.unit_price.isna().sum())
    s["unit_price"] = s.unit_price.fillna(s.product_id.map(price_map))
    s["store"] = s.store.fillna("Unknown")
    bad = s.quantity.isna() | (s.quantity <= 0) | s.unit_price.isna() | ~s.product_id.isin(products.product_id)
    report["invalid_rows_dropped"] = int(bad.sum())
    s = s[~bad].copy()
    s["quantity"] = s.quantity.astype(int)
    s["revenue"] = (s.quantity * s.unit_price).round(2)
    s = s.sort_values(["order_date", "order_id"]).reset_index(drop=True)
    report["rows_out"] = len(s)
    return s[["order_id", "order_date", "product_id", "quantity", "unit_price", "store", "revenue"]], report


def clean_restocks(raw: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    r = raw.copy()
    r["restock_date"] = parse_dates(r.restock_date.astype(str))
    r["quantity"] = pd.to_numeric(r.quantity, errors="coerce")
    r = r.dropna().drop_duplicates()
    r = r[r.product_id.isin(products.product_id) & (r.quantity > 0)]
    r["quantity"] = r.quantity.astype(int)
    return r.sort_values(["restock_date", "product_id"]).reset_index(drop=True)


def clean_all(raw_sales, raw_products, raw_restocks):
    products = clean_products(raw_products)
    sales, report = clean_sales(raw_sales, products)
    restocks = clean_restocks(raw_restocks, products)
    return sales, products, restocks, report
