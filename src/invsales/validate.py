"""Data-quality gate. Runs after cleaning; the ETL aborts (nothing is loaded) if any check fails."""
from __future__ import annotations

import pandas as pd


class DataQualityError(Exception):
    pass


def validate(sales: pd.DataFrame, products: pd.DataFrame, restocks: pd.DataFrame) -> list[str]:
    """Return a list of failed-check messages (empty = all good)."""
    problems: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            problems.append(msg)

    check(len(sales) > 0 and len(products) > 0 and len(restocks) > 0, "empty table")
    check(products.product_id.is_unique, "products.product_id not unique")
    check(sales.order_id.is_unique, "sales.order_id not unique")
    check(not sales.isna().any().any(), "nulls in sales")
    check(not products.isna().any().any(), "nulls in products")
    check(bool((sales.quantity > 0).all()), "non-positive sales quantity")
    check(bool((sales.unit_price > 0).all()), "non-positive unit price")
    check(bool((products.unit_price > products.unit_cost).all()), "price <= cost for some product")
    check(bool((products.current_stock >= 0).all()), "negative stock")
    check(bool((products.reorder_level >= 0).all()), "negative reorder level")
    check(bool(sales.product_id.isin(products.product_id).all()), "sales reference unknown products")
    check(bool(restocks.product_id.isin(products.product_id).all()), "restocks reference unknown products")
    check(bool(((sales.quantity * sales.unit_price - sales.revenue).abs() < 0.011).all()), "revenue != quantity*price")
    if len(sales):
        check(sales.order_date.min() > pd.Timestamp("2000-01-01") and sales.order_date.max() < pd.Timestamp("2100-01-01"),
              "implausible order dates")
    return problems


def assert_valid(sales, products, restocks) -> None:
    problems = validate(sales, products, restocks)
    if problems:
        raise DataQualityError("; ".join(problems))
