import numpy as np
import pandas as pd

from invsales.clean import clean_products, clean_sales, parse_dates, to_number


def test_to_number_handles_currency_and_garbage():
    out = to_number(pd.Series(["$12.50", "1,200", "7", "abc", None]))
    assert out.iloc[0] == 12.5 and out.iloc[1] == 1200 and out.iloc[2] == 7
    assert out.iloc[3:].isna().all()


def test_parse_dates_mixed_formats():
    out = parse_dates(pd.Series(["2024-03-05", "05/03/2024", "05-Mar-2024", "nonsense"]))
    assert (out.iloc[:3] == pd.Timestamp("2024-03-05")).all()
    assert pd.isna(out.iloc[3])


def test_clean_products_normalises_category_and_price():
    raw = pd.DataFrame({"product_id": ["A", "A"], "product_name": [" X ", " X "], "category": [" snacks ", "SNACKS"],
                        "unit_cost": ["1.0", "1.0"], "unit_price": ["$2.00", "$2.00"], "lead_time_days": ["3", "3"],
                        "reorder_level": ["5", "5"], "current_stock": ["9", "9"]})
    p = clean_products(raw)
    assert len(p) == 1 and p.category[0] == "Snacks" and p.unit_price[0] == 2.0 and p.product_name[0] == "X"


def _raw_sales(**over):
    base = {"order_id": ["1", "2", "3", "3", "4", "5"], "order_date": ["2025-01-01"] * 6,
            "product_id": ["A", "A", "A", "A", "A", "Z"], "quantity": ["1", "2", "3", np.nan, "4", "1"],
            "unit_price": ["$2.00", None, "$2.00", "$2.00", "$2.00", "$2.00"], "store": ["N", "N", "N", None, None, "N"]}
    base.update(over)
    return pd.DataFrame(base)


def test_clean_sales_rules(products):
    s, rep = clean_sales(_raw_sales(), products)
    assert rep["duplicates_removed"] == 1
    assert rep["prices_filled_from_master"] == 1
    assert rep["invalid_rows_dropped"] == 1            # order 5: unknown product Z
    assert s.order_id.is_unique and len(s) == 4
    assert s.loc[s.order_id == "2", "unit_price"].iloc[0] == 2.0                 # filled from product master
    assert s.loc[s.order_id == "3", "quantity"].iloc[0] == 3                     # kept the complete duplicate
    assert s.loc[s.order_id == "4", "store"].iloc[0] == "Unknown"
    assert (s.revenue == s.quantity * s.unit_price).all()


def test_clean_sales_drops_zero_and_missing_quantity(products):
    s, _ = clean_sales(_raw_sales(quantity=["0", None, "1", "1", "1", "1"]), products)
    assert set(s.order_id) == {"3", "4"}
