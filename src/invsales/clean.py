"""Cleaning rules: raw frames -> typed, deduplicated tables + a report of what changed."""
from __future__ import annotations

import pandas as pd

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y")


def to_number(s: pd.Series) -> pd.Series:
    """'$12.50' / 'Rs. 1,200' / '₹1,200.5' / '12.5 USD' / 12.5 -> float: commas dropped, then the first number is taken
    (unparseable -> NaN). Plain '1234.56' style numbers only: European '1.234,56' is not supported."""
    txt = s.astype("string").str.replace(",", "", regex=False)
    return pd.to_numeric(txt.str.extract(r"(-?\d+(?:\.\d+)?|-?\.\d+)")[0], errors="coerce")


def parse_dates(s: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    s = s.astype("string")
    for fmt in DATE_FORMATS:
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def clean_warehouses(raw: pd.DataFrame) -> pd.DataFrame:
    w = raw.copy()
    for c in ("warehouse_id", "warehouse_name", "region"):
        w[c] = w[c].astype("string").str.strip()
    return w.drop_duplicates("warehouse_id").reset_index(drop=True)


def clean_products(raw: pd.DataFrame) -> pd.DataFrame:
    p = raw.copy()
    p["product_name"] = p.product_name.str.strip()
    p["category"] = p.category.str.strip().str.title()
    for c in ("unit_cost", "unit_price"):
        p[c] = to_number(p[c]).astype(float)
    p["lead_time_days"] = pd.to_numeric(p.lead_time_days, errors="raise").astype(int)
    p = p.drop_duplicates("product_id")
    return p[["product_id", "product_name", "category", "unit_cost", "unit_price", "lead_time_days"]].reset_index(drop=True)


def clean_inventory(raw: pd.DataFrame, products: pd.DataFrame, warehouses: pd.DataFrame) -> pd.DataFrame:
    i = raw.copy()
    for c in ("current_stock", "reorder_level"):
        i[c] = pd.to_numeric(i[c], errors="coerce")
    i = i.dropna().drop_duplicates(["warehouse_id", "product_id"])
    i = i[i.product_id.isin(products.product_id) & i.warehouse_id.isin(warehouses.warehouse_id)]
    i[["current_stock", "reorder_level"]] = i[["current_stock", "reorder_level"]].astype(int)
    return i[["warehouse_id", "product_id", "current_stock", "reorder_level"]].reset_index(drop=True)


def clean_sales(raw: pd.DataFrame, products: pd.DataFrame, warehouses: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    s = raw.copy()
    report = {"rows_in": len(s)}
    s["order_date"] = parse_dates(s.order_date)
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
    bad = (s.quantity.isna() | (s.quantity <= 0) | s.unit_price.isna() | s.warehouse_id.isna()
           | ~s.product_id.isin(products.product_id) | ~s.warehouse_id.isin(warehouses.warehouse_id))
    report["invalid_rows_dropped"] = int(bad.sum())
    s = s[~bad].copy()
    s["quantity"] = s.quantity.astype(int)
    s["revenue"] = (s.quantity * s.unit_price).round(2)
    s = s.sort_values(["order_date", "order_id"]).reset_index(drop=True)
    report["rows_out"] = len(s)
    return s[["order_id", "order_date", "warehouse_id", "product_id", "quantity", "unit_price", "revenue"]], report


def clean_restocks(raw: pd.DataFrame, products: pd.DataFrame, warehouses: pd.DataFrame) -> pd.DataFrame:
    r = raw.copy()
    r["restock_date"] = parse_dates(r.restock_date)
    r["quantity"] = pd.to_numeric(r.quantity, errors="coerce")
    r = r.dropna().drop_duplicates()
    r = r[r.product_id.isin(products.product_id) & r.warehouse_id.isin(warehouses.warehouse_id) & (r.quantity > 0)]
    r["quantity"] = r.quantity.astype(int)
    return r.sort_values(["restock_date", "warehouse_id", "product_id"]).reset_index(drop=True)


def clean_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict]:
    warehouses = clean_warehouses(raw["warehouses"])
    products = clean_products(raw["products"])
    sales, report = clean_sales(raw["sales"], products, warehouses)
    tables = {
        "warehouses": warehouses, "products": products, "sales": sales,
        "inventory": clean_inventory(raw["inventory"], products, warehouses),
        "restocks": clean_restocks(raw["restocks"], products, warehouses),
    }
    return tables, report
