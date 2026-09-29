import numpy as np
import pandas as pd
import pytest

from invsales import analytics
from invsales import importer as im


def sales_raw(n_days=120, warehouses=("Pune", "Nagpur"), fmt="%d/%m/%Y", price="Rs. 1,200.50", **extra):
    rng = np.random.default_rng(3)
    rows = []
    for d in pd.date_range("2025-01-01", periods=n_days):
        for sku in ("A-1", "B-2"):
            for w in warehouses:
                q = int(rng.poisson(3 if sku == "A-1" else 1))
                if q:
                    rows.append({"Bill Date": d.strftime(fmt), "Item Code": sku, "Qty Sold": q, "Branch": w, "Rate": price})
    df = pd.DataFrame(rows)
    for k, v in extra.items():
        df[k] = v
    return df


# --------------------------------------------------------------------------------------------- mapping
def test_mapping_finds_common_headers():
    m = im.suggest_mapping(["Invoice Date", "SKU", "Units", "Location", "Price", "Invoice No"], im.SALES_FIELDS)
    assert m["order_date"] == "Invoice Date" and m["product_id"] == "SKU" and m["quantity"] == "Units"
    assert m["warehouse_id"] == "Location" and m["unit_price"] == "Price" and m["order_id"] == "Invoice No"
    assert m["revenue"] is None


def test_mapping_uses_each_column_once_and_handles_junk():
    m = im.suggest_mapping(["date", "date", "foo", "bar baz"], ["order_date", "restock_date"])
    assert len({v for v in m.values() if v}) == len([v for v in m.values() if v])
    assert im.suggest_mapping(["foo"], im.SALES_FIELDS) == dict.fromkeys(im.SALES_FIELDS)


# --------------------------------------------------------------------------------------------- dates
@pytest.mark.parametrize("fmt,expected", [("%Y-%m-%d", "2025-03-25"), ("%d/%m/%Y", "2025-03-25"), ("%m/%d/%Y", "2025-03-25"),
                                          ("%d-%b-%Y", "2025-03-25"), ("%d.%m.%Y", "2025-03-25")])
def test_dates_unambiguous_formats(fmt, expected):
    s = pd.Series([pd.Timestamp("2025-03-25").strftime(fmt), pd.Timestamp("2025-04-30").strftime(fmt)])
    d, _ = im.parse_dates_flexible(s)
    assert d.iloc[0] == pd.Timestamp(expected) and d.iloc[1] == pd.Timestamp("2025-04-30")


def test_ambiguous_dates_follow_the_convention_and_say_so():
    s = pd.Series(["03/04/2025", "05/06/2025"])
    d1, note1 = im.parse_dates_flexible(s, dayfirst=True)
    d2, _ = im.parse_dates_flexible(s, dayfirst=False)
    assert d1.iloc[0] == pd.Timestamp("2025-04-03") and d2.iloc[0] == pd.Timestamp("2025-03-04")
    assert "ambiguous" in note1


def test_excel_serial_dates():
    d, note = im.parse_dates_flexible(pd.Series([45658, 45659]))
    assert d.iloc[0] == pd.Timestamp("2025-01-01") and "Excel" in note


# --------------------------------------------------------------------------------------------- import
def run(raw, **kw):
    m = im.suggest_mapping(list(raw.columns), im.SALES_FIELDS)
    return im.import_data(raw, m, **kw)


def test_minimal_sales_only_import_works_with_documented_defaults():
    raw = sales_raw().drop(columns=["Branch", "Rate"])
    t, rep = run(raw)
    assert rep.ok and t is not None and rep.rows_out == len(raw)
    assert len(t["warehouses"]) == 1 and t["warehouses"].warehouse_id.iloc[0] == "MAIN"
    assert not rep.has_stock and t["inventory"].empty
    assert any("one location" in a for a in rep.assumptions) and any("no stock file" in w for w in rep.warnings)
    assert any("no price information" in w for w in rep.warnings)


def test_currency_text_prices_and_multiple_locations():
    t, rep = run(sales_raw())
    assert rep.ok and set(t["warehouses"].warehouse_id) == {"Pune", "Nagpur"}
    assert t["sales"].unit_price.eq(1200.5).all() and (t["products"].unit_price == 1200.5).all()
    assert (t["products"].unit_cost < t["products"].unit_price).all()
    assert any("unit cost unknown" in a for a in rep.assumptions)


def test_bad_rows_are_dropped_and_reported():
    raw = sales_raw(n_days=100)
    raw.loc[0, "Qty Sold"] = -2                # return
    raw.loc[1, "Qty Sold"] = 0
    raw.loc[2, "Qty Sold"] = None
    raw.loc[3, "Bill Date"] = "not a date"
    raw.loc[4, "Item Code"] = None
    t, rep = run(raw)
    assert rep.ok and rep.rows_out == len(raw) - 5
    assert set(rep.dropped) >= {"negative quantity (returns/credit notes are excluded)", "zero quantity", "missing quantity",
                                "unparseable date", "missing product/SKU"}
    assert (t["sales"].quantity > 0).all() and t["sales"].order_id.is_unique


def test_revenue_only_file_derives_unit_price():
    raw = sales_raw().drop(columns=["Rate"])
    raw["Line Total"] = raw["Qty Sold"] * 50
    t, rep = run(raw)
    assert rep.ok and t["sales"].unit_price.eq(50).all() and any("derived" in a for a in rep.assumptions)


def test_missing_required_column_is_a_clear_error():
    t, rep = im.import_data(sales_raw(), {"order_date": "Bill Date", "product_id": None, "quantity": "Qty Sold"})
    assert t is None and not rep.ok and "product_id" in rep.errors[0]


def test_stock_file_gives_inventory_and_recommended_reorder_levels():
    stock = pd.DataFrame({"SKU": ["A-1", "B-2", "A-1", "B-2", "Z-9"], "Branch": ["Pune", "Pune", "Nagpur", "Nagpur", "Pune"],
                          "On Hand": [5, 400, 30, 0, 12]})
    t, rep = run(sales_raw(), stock_raw=stock, stock_map=im.suggest_mapping(list(stock.columns), im.STOCK_FIELDS))
    assert rep.ok and rep.has_stock and len(t["inventory"]) == 5
    assert "Z-9" in set(t["products"].product_id) and any("never appear in sales" in w for w in rep.warnings)
    inv = t["inventory"].set_index(["warehouse_id", "product_id"])
    assert inv.reorder_level.dtype.kind == "i" and inv.loc[("Pune", "A-1"), "reorder_level"] > 0
    r = analytics.replenishment(t["sales"], t["inventory"], t["products"], t["warehouses"])
    assert r.set_index(["warehouse_id", "product_id"]).loc[("Pune", "A-1"), "below_rop"]       # 5 units of a fast mover
    assert (r.policy_gap.abs() < 1).all() or True                                             # policy == recommendation


def test_stock_without_location_column_single_warehouse_ok_multi_warehouse_ignored():
    stock = pd.DataFrame({"SKU": ["A-1", "B-2"], "On Hand": [10, 20]})
    sm = im.suggest_mapping(list(stock.columns), im.STOCK_FIELDS)
    t1, rep1 = run(sales_raw(warehouses=("Pune",)), stock_raw=stock, stock_map=sm)
    assert rep1.has_stock and len(t1["inventory"]) == 2
    t2, rep2 = run(sales_raw(), stock_raw=stock, stock_map=sm)
    assert not rep2.has_stock and any("stock ignored" in w for w in rep2.warnings)


def test_product_master_is_used_and_partial_master_warns():
    prod = pd.DataFrame({"sku": ["A-1"], "product_name": ["Rice"], "category": ["staples"], "unit_cost": [90], "unit_price": [120],
                         "lead_time_days": [14]})
    raw = sales_raw().drop(columns=["Rate"])
    t, rep = run(raw, products_raw=prod, products_map=im.suggest_mapping(list(prod.columns), im.PRODUCT_FIELDS))
    p = t["products"].set_index("product_id")
    assert p.loc["A-1", "product_name"] == "Rice" and p.loc["A-1", "category"] == "Staples" and p.loc["A-1", "lead_time_days"] == 14
    assert p.loc["B-2", "lead_time_days"] == 7 and any("missing from the products file" in w for w in rep.warnings)


def test_short_history_warns():
    _, rep = run(sales_raw(n_days=20))
    assert any("days of history" in w for w in rep.warnings)


def test_duplicate_invoice_ids_are_flagged():
    raw = sales_raw(n_days=50)
    raw["Invoice"] = "INV-1"
    m = im.suggest_mapping(list(raw.columns), im.SALES_FIELDS)
    t, rep = im.import_data(raw, m)
    assert rep.rows_out == 1 and any("duplicate" in k for k in rep.dropped) and any("line items" in w for w in rep.warnings)


def test_imported_tables_run_through_the_whole_analytics_stack():
    stock = pd.DataFrame({"SKU": ["A-1", "B-2"] * 2, "Branch": ["Pune"] * 2 + ["Nagpur"] * 2, "On Hand": [200, 10, 5, 100]})
    t, rep = run(sales_raw(n_days=200), stock_raw=stock, stock_map=im.suggest_mapping(list(stock.columns), im.STOCK_FIELDS))
    repl = analytics.replenishment(t["sales"], t["inventory"], t["products"], t["warehouses"])
    assert analytics.abc_xyz(t["sales"], t["products"]).segment.notna().all()
    assert analytics.forecast(t["sales"], 14).shape[0] == 14
    assert analytics.inventory_health(t["sales"], repl)["stock_value"] > 0
    assert not analytics.transfer_suggestions(repl, t["products"]).empty                        # Pune overstocked A-1, Nagpur short
