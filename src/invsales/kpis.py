"""KPI logic in pandas (mirrors sql/04_views.sql; an integration test keeps the two in agreement)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def headline(sales: pd.DataFrame, products: pd.DataFrame) -> dict:
    return {
        "total_sales": float(sales.revenue.sum()),
        "units_sold": int(sales.quantity.sum()),
        "total_stock": int(products.current_stock.sum()),
        "low_stock_items": int((products.current_stock <= products.reorder_level).sum()),
    }


def monthly_sales(sales: pd.DataFrame) -> pd.DataFrame:
    m = sales.groupby(sales.order_date.dt.to_period("M").dt.to_timestamp()).agg(
        revenue=("revenue", "sum"), units=("quantity", "sum")).reset_index(names="month")
    m["mom_growth_pct"] = (m.revenue.pct_change() * 100).round(1)
    return m


def _ntile_class(turnover: pd.Series) -> pd.Series:
    """Same buckets as SQL NTILE(4) OVER (ORDER BY turnover DESC): 1 -> Fast, 4 -> Slow, else Medium."""
    base, extra = len(turnover) // 4, len(turnover) % 4
    sizes = [base + (1 if i < extra else 0) for i in range(4)]
    bucket = np.repeat([1, 2, 3, 4], sizes)
    order = turnover.rank(method="first", ascending=False).astype(int).to_numpy() - 1
    return pd.Series(np.where(bucket[order] == 1, "Fast", np.where(bucket[order] == 4, "Slow", "Medium")),
                     index=turnover.index)


def stock_turnover(sales: pd.DataFrame, products: pd.DataFrame, restocks: pd.DataFrame) -> pd.DataFrame:
    """turnover = units sold / average stock; average stock = (opening + current) / 2.
    Opening stock = first restock row per product (initial stock-in)."""
    opening = restocks.sort_values("restock_date").groupby("product_id").quantity.first().rename("opening_stock")
    agg = sales.groupby("product_id").agg(units_sold=("quantity", "sum"), revenue=("revenue", "sum"),
                                          first=("order_date", "min"), last=("order_date", "max"))
    k = products.set_index("product_id").join(agg).join(opening)
    k["units_sold"] = k.units_sold.fillna(0).astype(int)
    k["revenue"] = k.revenue.fillna(0.0)
    k["avg_stock"] = (k.opening_stock + k.current_stock) / 2
    k["stock_turnover"] = (k.units_sold / k.avg_stock.where(k.avg_stock > 0)).round(2)
    days = ((k["last"] - k["first"]).dt.days + 1)
    k["days_of_inventory"] = (days / k.stock_turnover.where(k.stock_turnover > 0)).round(0)
    k = k.drop(columns=["first", "last"]).reset_index()
    k["movement_class"] = _ntile_class(k.stock_turnover)
    return k


def reorder_alerts(sales: pd.DataFrame, products: pd.DataFrame, window_days: int = 90) -> pd.DataFrame:
    """Products at/below reorder level, with days of stock left at the recent sales rate."""
    end = sales.order_date.max()
    recent = sales[sales.order_date > end - pd.Timedelta(days=window_days)]
    daily = (recent.groupby("product_id").quantity.sum() / window_days).rename("daily_demand")
    a = products[products.current_stock <= products.reorder_level].merge(daily, on="product_id", how="left")
    a["shortfall"] = a.reorder_level - a.current_stock
    a["days_of_stock_left"] = (a.current_stock / a.daily_demand.where(a.daily_demand > 0)).round(1)
    a["severity"] = pd.cut(a.days_of_stock_left.fillna(9999), [-1, 0, 3, 9999], labels=["Stockout", "Critical", "Low"]).astype(str)
    return a.sort_values(["days_of_stock_left", "shortfall"], ascending=[True, False]).reset_index(drop=True)


def category_summary(sales: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    j = sales.merge(products[["product_id", "category", "unit_cost"]], on="product_id")
    j["profit"] = j.revenue - j.quantity * j.unit_cost
    c = j.groupby("category").agg(revenue=("revenue", "sum"), gross_profit=("profit", "sum")).reset_index()
    c["margin_pct"] = (100 * c.gross_profit / c.revenue).round(1)
    c["revenue_share_pct"] = (100 * c.revenue / c.revenue.sum()).round(1)
    return c.sort_values("revenue", ascending=False).reset_index(drop=True)
