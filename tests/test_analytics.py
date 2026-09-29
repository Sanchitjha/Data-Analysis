import math

import numpy as np
import pandas as pd
import pytest

from invsales import analytics


def make_sales(daily: dict, start="2025-01-01", days=100, wh="W1"):
    """daily: {product_id: callable(day_index) -> units}"""
    rows = []
    for pid, fn in daily.items():
        for i in range(days):
            q = fn(i)
            if q > 0:
                rows.append({"order_id": f"{pid}{i}{wh}", "order_date": pd.Timestamp(start) + pd.Timedelta(days=i),
                             "warehouse_id": wh, "product_id": pid, "quantity": q, "unit_price": 2.0, "revenue": 2.0 * q})
    return pd.DataFrame(rows)


def test_abc_classes_by_cumulative_revenue(products):
    s = make_sales({"A": lambda i: 21, "B": lambda i: 4, "C": lambda i: 1})    # revenue shares 80.8 / 15.4 / 3.8 %
    r = analytics.abc_xyz(s, products).set_index("product_id")
    assert r.loc["A", "abc"] == "A" and r.loc["B", "abc"] == "B" and r.loc["C", "abc"] == "C"
    assert r.revenue_share_pct.sum() == pytest.approx(100, abs=0.1)
    assert r.loc["A", "xyz"] == "X" and r.loc["A", "demand_cv"] < 0.15         # constant demand -> stable


def test_xyz_flags_erratic_demand(products):
    s = make_sales({"A": lambda i: 50 if (i // 30) % 2 == 0 else 1, "B": lambda i: 5}, days=180)
    r = analytics.abc_xyz(s, products).set_index("product_id")
    assert r.loc["A", "xyz"] == "Z" and r.loc["B", "xyz"] == "X"


def test_forecast_constant_demand_is_accurate(products):
    s = make_sales({"A": lambda i: 4, "B": lambda i: 7}, days=120)
    f = analytics.forecast(s, horizon=14)
    assert f.shape == (14, 2) and f.index[0] == pd.Timestamp("2025-01-01") + pd.Timedelta(days=120)
    assert f["A"].round(6).eq(4).all() and f["B"].round(6).eq(7).all()
    bt = analytics.backtest(s, horizon=14)
    assert bt["wape_model"] == 0 and bt["bias_model"] == 0


def test_forecast_uses_weekday_pattern_and_beats_naive():
    weekend_heavy = lambda i: 10 if (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).dayofweek >= 5 else 2  # noqa: E731
    s = make_sales({"A": weekend_heavy}, days=200)
    bt = analytics.backtest(s, horizon=28)
    assert bt["wape_model"] < 0.02 < bt["wape_naive"]                        # model captures weekly seasonality


def test_seasonal_ratio_uses_last_year():
    # 2 years of data: demand doubles every 2nd half-year -> yoy ratio should lift the forecast
    f = lambda i: 10 if (i % 365) >= 300 else 2  # noqa: E731
    s = make_sales({"A": f}, days=700)
    fc = analytics.forecast(s, horizon=30)            # anchors in the low season right before the high one
    assert fc["A"].mean() > 2.5


def test_demand_stats(sales):
    st = analytics.demand_stats(sales).set_index(["warehouse_id", "product_id"])
    n_days = 42                                            # 2025-01-01 .. 2025-02-11
    assert st.loc[("W1", "A"), "mean_daily"] == pytest.approx(30 / n_days)
    expected_std = math.sqrt((10 ** 2 + 20 ** 2) / n_days - (30 / n_days) ** 2)
    assert st.loc[("W1", "A"), "std_daily"] == pytest.approx(expected_std)


def test_replenishment_formulas(sales, inventory, products, warehouses):
    r = analytics.replenishment(sales, inventory, products, warehouses, z=1.65, ordering_cost=50, holding_rate=0.2)
    row = r[(r.warehouse_id == "W1") & (r.product_id == "A")].iloc[0]
    d, sd = 30 / 42, math.sqrt((10 ** 2 + 20 ** 2) / 42 - (30 / 42) ** 2)
    ss = math.ceil(1.65 * sd * math.sqrt(5))
    rop = math.ceil(d * 5 + ss)
    eoq = math.ceil(math.sqrt(2 * d * 365 * 50 / (0.2 * 1.0)))
    assert row.safety_stock == ss and row.reorder_point == rop and row.eoq == eoq
    assert row.below_rop and row.suggested_order_qty == rop + eoq - 5           # stock 5 <= ROP
    ok = r[(r.warehouse_id == "W2") & (r.product_id == "A")].iloc[0]
    assert (not ok.below_rop) == (ok.current_stock > ok.reorder_point)
    assert (r.loc[~r.below_rop, "suggested_order_qty"] == 0).all()
    assert r.suggested_order_cost.ge(0).all()


def test_replenishment_no_demand_product_is_safe(sales, inventory, products, warehouses):
    r = analytics.replenishment(sales, inventory, products, warehouses)
    row = r[(r.warehouse_id == "W2") & (r.product_id == "C")].iloc[0]           # never sold in W2
    assert row.mean_daily == 0 and row.eoq == 0 and row.reorder_point == 0 and pd.isna(row.days_of_cover)


def test_transfer_suggestions_greedy_and_bounded(products):
    repl = pd.DataFrame({
        "warehouse_id": ["W1", "W2", "W3"], "product_id": ["A"] * 3, "current_stock": [200, 100, 5],
        "reorder_point": [20, 20, 30], "eoq": [50, 50, 50]})
    t = analytics.transfer_suggestions(repl, products)
    # deficit W3 = 25 ; surplus W1 = 200-70 = 130, W2 = 100-70 = 30 -> all from W1 (largest surplus)
    assert t.to_dict("records")[0]["from_warehouse"] == "W1" and t.quantity.sum() == 25 and len(t) == 1
    assert t.value_at_cost.iloc[0] == 25 * 1.0


def test_transfer_split_across_sources_and_never_exceeds_surplus(products):
    repl = pd.DataFrame({
        "warehouse_id": ["W1", "W2", "W3"], "product_id": ["B"] * 3, "current_stock": [80, 75, 0],
        "reorder_point": [10, 10, 100], "eoq": [50, 50, 50]})
    t = analytics.transfer_suggestions(repl, products)
    surplus = {"W1": 80 - 60, "W2": 75 - 60}
    assert t.groupby("from_warehouse").quantity.sum().le(pd.Series(surplus)).all()
    assert t.quantity.sum() == 20 + 15 and set(t.to_warehouse) == {"W3"}


def test_no_transfers_when_nothing_short(products):
    repl = pd.DataFrame({"warehouse_id": ["W1", "W2"], "product_id": ["A", "A"], "current_stock": [50, 60],
                         "reorder_point": [10, 10], "eoq": [20, 20]})
    assert analytics.transfer_suggestions(repl, products).empty
    assert np.isclose(0, 0)


def test_grouped_forecast_runs_and_pools_weekday_shape(products):
    wk = lambda i: 10 if (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).dayofweek >= 5 else 2  # noqa: E731
    s = make_sales({"A": wk, "B": lambda i: 5}, days=200)
    groups = pd.Series({"A": "g1", "B": "g1"})
    f = analytics.forecast(s, horizon=14, groups=groups)
    assert f.shape == (14, 2) and (f >= 0).all().all()
    bt = analytics.backtest(s, horizon=28, groups=groups)
    assert {"wape_model", "wape_naive", "wape_weekly_model", "wape_weekly_naive"} <= set(bt)
