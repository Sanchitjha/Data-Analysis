"""Inventory simulation and synthetic data generation.

`simulate_inventory` turns a daily demand matrix into stock levels, restocks and
reorder levels using a (reorder point, fixed order quantity) policy with supplier
lead times. It is used both for fully synthetic data and to derive the inventory
layer for real sales data (where `constrain=False`: real sales already happened,
so they are never capped by simulated stock).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")

CATALOG = {
    "Beverages": ["Orange Juice 1L", "Cola 2L", "Green Tea 25 bags", "Mineral Water 1L", "Energy Drink 250ml",
                  "Coffee Beans 500g", "Mango Drink 1L", "Soda Water 500ml", "Iced Tea 500ml", "Coconut Water 330ml",
                  "Apple Juice 1L", "Lemonade 1L"],
    "Snacks": ["Potato Chips 150g", "Salted Peanuts 200g", "Chocolate Bar 50g", "Cookies 300g", "Popcorn 100g",
               "Namkeen Mix 400g", "Granola Bar 6pk", "Cream Biscuits 200g", "Cashew Nuts 250g", "Wafers 75g",
               "Trail Mix 300g", "Rice Crackers 120g"],
    "Household": ["Dish Soap 500ml", "Laundry Detergent 2kg", "Toilet Paper 12pk", "Trash Bags 30pk", "Floor Cleaner 1L",
                  "Paper Towels 6pk", "Sponges 5pk", "Air Freshener 300ml", "Hand Wash 250ml", "Bleach 1L",
                  "Glass Cleaner 500ml", "Aluminium Foil 30m"],
    "Personal Care": ["Shampoo 340ml", "Toothpaste 150g", "Body Lotion 400ml", "Deodorant 150ml", "Face Wash 100ml",
                      "Soap Bar 4pk", "Razor 3pk", "Sunscreen 100ml", "Hair Oil 200ml", "Mouthwash 500ml",
                      "Hand Cream 75ml", "Lip Balm"],
    "Staples": ["Basmati Rice 5kg", "Wheat Flour 5kg", "Sunflower Oil 1L", "Sugar 1kg", "Toor Dal 1kg",
                "Salt 1kg", "Tea Powder 500g", "Pasta 500g", "Oats 1kg", "Ghee 500ml",
                "Chickpeas 1kg", "Honey 500g"],
}
STORES = ["North", "South", "East", "West"]


def make_catalog(rng: np.random.Generator) -> pd.DataFrame:
    rows, pid = [], 1000
    for cat, names in CATALOG.items():
        for name in names:
            pid += 1
            cost = round(float(rng.uniform(1.5, 22)), 2)
            rows.append({
                "product_id": f"P{pid}", "product_name": name, "category": cat, "unit_cost": cost,
                "unit_price": round(cost * float(rng.uniform(1.25, 1.6)), 2),
                "lead_time_days": int(rng.integers(3, 15)),
                "base_rate": float(rng.choice([0.15, 0.3, 0.6, 1.0, 1.6, 2.5], p=[.12, .2, .28, .2, .12, .08])),
            })
    return pd.DataFrame(rows)


def make_demand(catalog: pd.DataFrame, days: pd.DatetimeIndex, rng: np.random.Generator) -> pd.DataFrame:
    """Daily demand matrix (rows = dates, columns = product_id) with seasonality, trend, weekends."""
    doy = days.dayofyear.values
    trend = np.linspace(1, 1.15, len(days))
    weekend = np.where(days.dayofweek >= 5, 1.3, 1.0)
    cols = {}
    for p in catalog.itertuples():
        peak = 100 if p.category == "Beverages" else 60
        amp = 0.5 if p.category == "Beverages" else 0.25
        season = 1 + amp * np.sin((doy - peak) / 365 * 2 * np.pi)
        cols[p.product_id] = rng.poisson(p.base_rate * 3 * season * trend * weekend)
    return pd.DataFrame(cols, index=days)


def simulate_inventory(demand: pd.DataFrame, catalog: pd.DataFrame, rng: np.random.Generator, *,
                       constrain: bool = True, outage_products: frozenset[str] = frozenset(),
                       outage_start: pd.Timestamp | None = None):
    """Run a reorder-point policy per product.

    Returns (fulfilled, restocks, state): fulfilled demand matrix, restock events (incl. the
    opening stock-in on day one) and per-product reorder_level / current_stock.
    """
    days = demand.index
    fulfilled = demand.copy()
    restocks, state = [], []
    lead = catalog.set_index("product_id").lead_time_days
    for pid in demand.columns:
        d = demand[pid].to_numpy()
        avg = max(float(d.mean()), 0.5)
        lt = int(lead[pid])
        reorder_level = int(np.ceil(avg * lt * 1.3))
        order_qty = int(np.ceil(avg * 45 * float(rng.choice([1, 1.5, 2, 3, 5], p=[.2, .3, .25, .15, .1]))))
        stock = order_qty + reorder_level
        restocks.append((days[0], pid, stock))
        pending: list[tuple[int, int]] = []
        for i, day in enumerate(days):
            for arr in [a for a in pending if a[0] == i]:
                stock += arr[1]
                restocks.append((day, pid, arr[1]))
            pending = [a for a in pending if a[0] != i]
            sold = min(int(d[i]), stock) if constrain else int(d[i])
            fulfilled.iat[i, fulfilled.columns.get_loc(pid)] = sold
            stock = max(stock - sold, 0)
            if stock <= reorder_level and not pending:
                wait = 400 if (pid in outage_products and outage_start is not None and day > outage_start) else lt
                pending.append((i + wait, order_qty))
        state.append({"product_id": pid, "reorder_level": reorder_level, "current_stock": stock})
    restock_df = pd.DataFrame(restocks, columns=["restock_date", "product_id", "quantity"])
    restock_df = restock_df.sort_values(["restock_date", "product_id"]).reset_index(drop=True)
    return fulfilled, restock_df, pd.DataFrame(state)


def to_order_lines(fulfilled: pd.DataFrame, catalog: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Split each product-day's units into order lines of 1-4 units, assigning a store."""
    price = catalog.set_index("product_id").unit_price
    rows, oid = [], 100000
    for pid in fulfilled.columns:
        for day, units in fulfilled[pid][fulfilled[pid] > 0].items():
            left = int(units)
            while left > 0:
                q = min(left, int(rng.integers(1, 5)))
                oid += 1
                rows.append((f"O{oid}", day, pid, q, float(price[pid]), STORES[int(rng.integers(0, len(STORES)))]))
                left -= q
    return pd.DataFrame(rows, columns=["order_id", "order_date", "product_id", "quantity", "unit_price", "store"])


def inject_mess(sales: pd.DataFrame, products: pd.DataFrame, restocks: pd.DataFrame, rng: np.random.Generator):
    """Corrupt clean frames the way real exports are corrupted (for the cleaning step to fix)."""
    s = sales.copy()
    dup = s.sample(frac=0.012, random_state=1)
    s = pd.concat([s, dup]).sample(frac=1, random_state=2).reset_index(drop=True)
    fmt = rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"], len(s), p=[.7, .2, .1])
    s["order_date"] = [d.strftime(f) for d, f in zip(s.order_date, fmt)]
    s["unit_price"] = s.unit_price.map(lambda v: f"${v:.2f}")
    s = s.astype({"quantity": "object"})
    s.loc[s.sample(frac=0.006, random_state=3).index, "quantity"] = np.nan
    s.loc[s.sample(frac=0.01, random_state=4).index, "unit_price"] = np.nan
    s.loc[s.sample(frac=0.004, random_state=5).index, "store"] = None

    p = products.copy()
    p["category"] = [c.upper() if rng.random() < .1 else (f" {c.lower()} " if rng.random() < .1 else c) for c in p.category]
    p["unit_price"] = p.unit_price.map(lambda v: f"${v:.2f}")
    r = restocks.copy()
    r["restock_date"] = r.restock_date.dt.strftime("%Y-%m-%d")
    return s, p, r


def generate_raw(seed: int = 42, start: pd.Timestamp = START, end: pd.Timestamp = END):
    """Full synthetic raw dataset -> (raw_sales, raw_products, raw_restocks)."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end)
    catalog = make_catalog(rng)
    demand = make_demand(catalog, days, rng)
    outage = frozenset(rng.choice(catalog.product_id, 7, replace=False))
    fulfilled, restocks, state = simulate_inventory(
        demand, catalog, rng, outage_products=outage, outage_start=pd.Timestamp(end) - pd.Timedelta(days=90))
    sales = to_order_lines(fulfilled, catalog, rng)
    products = catalog.drop(columns="base_rate").merge(state, on="product_id")
    return inject_mess(sales, products, restocks, rng)
