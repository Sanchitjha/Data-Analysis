import pandas as pd

from invsales import kpis


def test_headline(sales, inventory):
    assert kpis.headline(sales, inventory) == {"total_sales": 100.0, "units_sold": 45, "total_stock": 117,
                                               "low_stock_items": 3}


def test_monthly_sales_and_growth(sales):
    m = kpis.monthly_sales(sales)
    assert list(m.revenue) == [60.0, 40.0]
    assert pd.isna(m.mom_growth_pct[0]) and m.mom_growth_pct[1] == -33.3


def test_stock_turnover_warehouse_level(sales, inventory, restocks, products):
    k = kpis.stock_turnover(sales, inventory, restocks, products).set_index(["warehouse_id", "product_id"])
    # W1-A: sold 30, opening 35, current 5 -> avg 20 -> 1.5, selling 15 days -> 10 days of inventory
    assert k.loc[("W1", "A"), "stock_turnover"] == 1.5
    assert k.loc[("W1", "A"), "days_of_inventory"] == 10
    assert k.loc[("W1", "C"), "stock_turnover"] == 0.2          # 1 / ((10 + 0) / 2)
    assert k.loc[("W2", "C"), "units_sold"] == 0                # never sold there
    assert k.loc[("W1", "A"), "movement_class"] == "Fast"


def test_stock_turnover_product_level(sales, inventory, restocks, products):
    k = kpis.stock_turnover(sales, inventory, restocks, products, level="product").set_index("product_id")
    assert len(k) == 3
    assert k.loc["A", "units_sold"] == 36 and k.loc["A", "stock_turnover"] == round(36 / ((85 + 45) / 2), 2)


def test_reorder_alerts(sales, inventory, products, warehouses):
    a = kpis.reorder_alerts(sales, inventory, products, warehouses)
    assert list(zip(a.warehouse_id, a.product_id, strict=True)) == [("W1", "C"), ("W1", "A"), ("W2", "B")]  # most urgent first
    assert a.severity.tolist() == ["Stockout", "Low", "Low"]
    assert a.shortfall.tolist() == [10, 5, 8] and a.warehouse_name[0] == "Delhi"


def test_category_summary(sales, products):
    c = kpis.category_summary(sales, products).set_index("category")
    assert c.loc["Snacks", "revenue"] == 96.0
    assert c.loc["Snacks", "gross_profit"] == 96.0 - (36 * 1 + 8 * 2)
    assert round(c.revenue_share_pct.sum(), 0) == 100


def test_warehouse_summary(sales, inventory, warehouses):
    w = kpis.warehouse_summary(sales, inventory, warehouses).set_index("warehouse_id")
    assert w.loc["W1", "revenue"] == 79.0 and w.loc["W1", "low_stock_items"] == 2
    assert w.loc["W2", "total_stock"] == 62 and w.loc["W2", "skus"] == 3
