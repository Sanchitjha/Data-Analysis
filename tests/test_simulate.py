import numpy as np
import pandas as pd

from invsales.clean import clean_all
from invsales.simulate import generate_raw, make_catalog, make_demand, simulate_inventory
from invsales.validate import validate


def small():
    rng = np.random.default_rng(1)
    cat = make_catalog(rng).head(6)
    days = pd.date_range("2025-01-01", periods=120)
    return rng, cat, make_demand(cat, days, rng)


def test_stock_never_negative_and_sales_capped_by_stock():
    rng, cat, demand = small()
    fulfilled, restocks, state = simulate_inventory(demand, cat, rng)
    assert (state.current_stock >= 0).all()
    assert (fulfilled <= demand).all().all()
    # stock conservation: opening + restocks - fulfilled = closing
    for pid in demand.columns:
        stocked = restocks[restocks.product_id == pid].quantity.sum()
        assert stocked - fulfilled[pid].sum() == state.set_index("product_id").current_stock[pid]


def test_unconstrained_mode_keeps_real_sales():
    rng, cat, demand = small()
    fulfilled, _, _ = simulate_inventory(demand, cat, rng, constrain=False)
    assert fulfilled.equals(demand)


def test_deterministic_for_seed():
    a = generate_raw(7, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-15"))
    b = generate_raw(7, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-15"))
    assert all(x.equals(y) for x, y in zip(a, b))


def test_raw_is_dirty_and_cleaning_makes_it_valid():
    raw_s, raw_p, raw_r = generate_raw(3, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-03-01"))
    assert raw_s.order_id.duplicated().any() and raw_s.quantity.isna().any()
    sales, products, restocks, rep = clean_all(raw_s.astype(str).replace({"nan": None, "None": None}),
                                               raw_p.astype(str), raw_r.astype(str))
    assert validate(sales, products, restocks) == []
    assert rep["duplicates_removed"] > 0
