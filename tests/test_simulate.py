import numpy as np
import pandas as pd

from invsales.clean import clean_all
from invsales.simulate import (
    generate_raw,
    make_catalog,
    make_demand,
    make_warehouses,
    simulate_inventory,
    to_order_lines,
)
from invsales.validate import validate


def small(n_wh=2, n_p=6, days=120):
    rng = np.random.default_rng(1)
    cat = make_catalog(rng, n_p)
    idx = pd.date_range("2025-01-01", periods=days)
    wh = make_warehouses(n_wh).warehouse_id.tolist()
    return rng, cat, idx, wh, make_demand(cat, idx, n_wh, rng)


def test_stock_conservation_and_caps():
    rng, cat, days, wh, demand = small()
    fulfilled, restocks, inv = simulate_inventory(demand, days, wh, cat, rng)
    assert (inv.current_stock >= 0).all() and (fulfilled <= demand).all()
    for w, wid in enumerate(wh):
        for p, pid in enumerate(cat.product_id):
            stocked = restocks[(restocks.warehouse_id == wid) & (restocks.product_id == pid)].quantity.sum()
            closing = inv[(inv.warehouse_id == wid) & (inv.product_id == pid)].current_stock.iloc[0]
            assert stocked - fulfilled[:, w, p].sum() == closing      # opening + restocks - sold = closing


def test_unconstrained_mode_keeps_real_sales():
    rng, cat, days, wh, demand = small()
    fulfilled, _, _ = simulate_inventory(demand, days, wh, cat, rng, constrain=False)
    assert (fulfilled == demand).all()


def test_order_lines_match_units():
    rng, cat, days, wh, demand = small()
    fulfilled, _, _ = simulate_inventory(demand, days, wh, cat, rng)
    lines = to_order_lines(fulfilled, days, wh, cat)
    assert lines.quantity.sum() == fulfilled.sum() and lines.order_id.is_unique and (lines.quantity > 0).all()


def test_deterministic_for_seed():
    a = generate_raw(7, "demo", "2025-01-01", "2025-02-15")
    b = generate_raw(7, "demo", "2025-01-01", "2025-02-15")
    assert all(a[k].equals(b[k]) for k in a)


def test_raw_is_dirty_and_cleaning_makes_it_valid():
    raw = generate_raw(3, "demo", "2025-01-01", "2025-03-01")
    assert raw["sales"].order_id.duplicated().any() and raw["sales"].quantity.isna().any()
    tables, rep = clean_all({k: v.astype(str).replace({"nan": None, "None": None}) for k, v in raw.items()})
    assert validate(tables) == []
    assert rep["duplicates_removed"] > 0
