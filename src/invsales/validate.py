"""Data-quality gate. Runs after cleaning; the ETL aborts (nothing is loaded) if any check fails."""
from __future__ import annotations

import pandas as pd


class DataQualityError(Exception):
    pass


def validate(t: dict[str, pd.DataFrame], strict: bool = True) -> list[str]:
    """Return a list of failed-check messages (empty = all good). `t` holds the 5 cleaned tables.
    strict=False (imported customer data) allows empty inventory/restocks tables."""
    sales, products, inventory = t["sales"], t["products"], t["inventory"]
    restocks, warehouses = t["restocks"], t["warehouses"]
    problems: list[str] = []

    def check(ok: bool, msg: str) -> None:
        if not ok:
            problems.append(msg)

    required = t.values() if strict else (t["sales"], t["products"], t["warehouses"])
    check(all(len(x) > 0 for x in required), "empty table")
    check(warehouses.warehouse_id.is_unique, "warehouses.warehouse_id not unique")
    check(products.product_id.is_unique, "products.product_id not unique")
    check(sales.order_id.is_unique, "sales.order_id not unique")
    check(not inventory.duplicated(["warehouse_id", "product_id"]).any(), "inventory (warehouse, product) not unique")
    for name in ("sales", "products", "inventory", "restocks", "warehouses"):
        check(not t[name].isna().any().any(), f"nulls in {name}")
    check(bool((sales.quantity > 0).all()), "non-positive sales quantity")
    check(bool((sales.unit_price > 0).all()), "non-positive unit price")
    check(bool((products.unit_price > products.unit_cost).all()), "price <= cost for some product")
    check(bool((inventory.current_stock >= 0).all()), "negative stock")
    check(bool((inventory.reorder_level >= 0).all()), "negative reorder level")
    for name, df in (("sales", sales), ("inventory", inventory), ("restocks", restocks)):
        check(bool(df.product_id.isin(products.product_id).all()), f"{name} reference unknown products")
        check(bool(df.warehouse_id.isin(warehouses.warehouse_id).all()), f"{name} reference unknown warehouses")
    check(bool(((sales.quantity * sales.unit_price - sales.revenue).abs() < 0.011).all()), "revenue != quantity*price")
    if len(sales):
        check(sales.order_date.min() > pd.Timestamp("2000-01-01") and sales.order_date.max() < pd.Timestamp("2100-01-01"),
              "implausible order dates")
    return problems


def assert_valid(t: dict[str, pd.DataFrame], strict: bool = True) -> None:
    problems = validate(t, strict)
    if problems:
        raise DataQualityError("; ".join(problems))
