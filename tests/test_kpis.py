import pandas as pd

from invsales import kpis


def test_headline(sales, products):
    h = kpis.headline(sales, products)
    assert h == {"total_sales": 79.0, "units_sold": 36, "total_stock": 55, "low_stock_items": 2}


def test_monthly_sales_and_growth(sales):
    m = kpis.monthly_sales(sales)
    assert list(m.revenue) == [60.0, 19.0]
    assert pd.isna(m.mom_growth_pct[0]) and m.mom_growth_pct[1] == -68.3


def test_stock_turnover_formula(sales, products, restocks):
    k = kpis.stock_turnover(sales, products, restocks).set_index("product_id")
    # A: sold 30, opening 35, current 5 -> avg 20 -> 1.5 ; B: 5 / ((55+50)/2) ; C: 1 / ((10+0)/2)
    assert k.loc["A", "stock_turnover"] == 1.5
    assert k.loc["B", "stock_turnover"] == round(5 / 52.5, 2)
    assert k.loc["C", "stock_turnover"] == 0.2
    assert k.loc["A", "movement_class"] == "Fast"           # NTILE(4) over 3 rows -> buckets 1,2,3
    assert k.loc["B", "movement_class"] == "Medium"


def test_reorder_alerts(sales, products):
    a = kpis.reorder_alerts(sales, products).set_index("product_id")
    assert set(a.index) == {"A", "C"}                    # B (50 > 10) is fine
    assert a.loc["C", "severity"] == "Stockout" and a.loc["C", "shortfall"] == 10
    assert a.loc["A", "shortfall"] == 5 and a.index[0] == "C"   # most urgent first


def test_category_summary(sales, products):
    c = kpis.category_summary(sales, products).set_index("category")
    assert c.loc["Snacks", "revenue"] == 75.0
    assert c.loc["Snacks", "gross_profit"] == 75.0 - (30 * 1 + 5 * 2)
    assert round(c.revenue_share_pct.sum(), 0) == 100
