"""Multi-warehouse inventory simulation and synthetic data generation.

`simulate_inventory` turns a (day x warehouse x product) demand array into stock levels, restocks and
reorder levels using a (reorder point, fixed order quantity) policy with supplier lead times. It is used both
for fully synthetic data and to derive the inventory layer for real sales data (`constrain=False`: real sales
already happened, so they are never capped by simulated stock).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Preset:
    warehouses: int
    products: int
    start: str
    end: str


PRESETS = {
    # compact: committed to git and used by the free cloud demo
    "demo": Preset(warehouses=3, products=60, start="2024-01-01", end="2025-12-31"),
    # scale test: ~1M+ fact rows, run locally / Docker / hosted PostgreSQL
    "large": Preset(warehouses=6, products=300, start="2023-01-01", end="2025-12-31"),
}

WAREHOUSES = [("W01", "Delhi DC", "North"), ("W02", "Mumbai DC", "West"), ("W03", "Chennai DC", "South"),
              ("W04", "Kolkata DC", "East"), ("W05", "Bengaluru DC", "South"), ("W06", "Ahmedabad DC", "West")]

CATALOG = {
    "Beverages": ["Orange Juice 1L", "Cola 2L", "Green Tea 25 bags", "Mineral Water 1L", "Energy Drink 250ml",
                  "Coffee Beans 500g", "Mango Drink 1L", "Soda Water 500ml", "Iced Tea 500ml", "Coconut Water 330ml",
                  "Apple Juice 1L", "Lemonade 1L"],
    "Snacks": ["Potato Chips 150g", "Salted Peanuts 200g", "Chocolate Bar 50g", "Cookies 300g", "Popcorn 100g",
               "Namkeen Mix 400g", "Granola Bar 6pk", "Cream Biscuits 200g", "Cashew Nuts 250g", "Wafers 75g",
               "Trail Mix 300g", "Rice Crackers 120g"],
    "Household": ["Dish Soap 500ml", "Laundry Detergent 2kg", "Toilet Paper 12pk", "Trash Bags 30pk",
                  "Floor Cleaner 1L", "Paper Towels 6pk", "Sponges 5pk", "Air Freshener 300ml", "Hand Wash 250ml",
                  "Bleach 1L", "Glass Cleaner 500ml", "Aluminium Foil 30m"],
    "Personal Care": ["Shampoo 340ml", "Toothpaste 150g", "Body Lotion 400ml", "Deodorant 150ml", "Face Wash 100ml",
                      "Soap Bar 4pk", "Razor 3pk", "Sunscreen 100ml", "Hair Oil 200ml", "Mouthwash 500ml",
                      "Hand Cream 75ml", "Lip Balm"],
    "Staples": ["Basmati Rice 5kg", "Wheat Flour 5kg", "Sunflower Oil 1L", "Sugar 1kg", "Toor Dal 1kg",
                "Salt 1kg", "Tea Powder 500g", "Pasta 500g", "Oats 1kg", "Ghee 500ml",
                "Chickpeas 1kg", "Honey 500g"],
}
VARIANTS = ["", " - Family Pack", " - Mini", " - Premium", " - Value Pack"]
CATEGORIES = list(CATALOG)


def make_warehouses(n: int) -> pd.DataFrame:
    return pd.DataFrame(WAREHOUSES[:n], columns=["warehouse_id", "warehouse_name", "region"])


def make_catalog(rng: np.random.Generator, n_products: int = 60) -> pd.DataFrame:
    base = [(cat, name) for cat, names in CATALOG.items() for name in names]      # 60 base products
    rows = []
    for i in range(n_products):
        cat, name = base[i % len(base)]
        cost = round(float(rng.uniform(1.5, 22)), 2)
        rows.append({
            "product_id": f"P{1001 + i}", "product_name": name + VARIANTS[(i // len(base)) % len(VARIANTS)],
            "category": cat, "unit_cost": cost, "unit_price": round(cost * float(rng.uniform(1.25, 1.6)), 2),
            "lead_time_days": int(rng.integers(3, 15)),
            "base_rate": float(rng.choice([0.15, 0.3, 0.6, 1.0, 1.6, 2.5], p=[.12, .2, .28, .2, .12, .08])),
        })
    return pd.DataFrame(rows)


def make_demand(catalog: pd.DataFrame, days: pd.DatetimeIndex, n_wh: int, rng: np.random.Generator) -> np.ndarray:
    """Daily demand array shaped (days, warehouses, products): seasonality, trend, weekends, warehouse size."""
    doy = days.dayofyear.to_numpy()
    trend = np.linspace(1, 1.15, len(days))[:, None, None]
    weekend = np.where(days.dayofweek >= 5, 1.3, 1.0)[:, None, None]
    peak = {c: (100 if c == "Beverages" else 60) for c in CATEGORIES}
    amp = {c: (0.5 if c == "Beverages" else 0.25) for c in CATEGORIES}
    season = np.stack([1 + amp[c] * np.sin((doy - peak[c]) / 365 * 2 * np.pi) for c in catalog.category], axis=1)
    wh_size = rng.uniform(0.6, 1.4, n_wh)[None, :, None]
    lam = catalog.base_rate.to_numpy()[None, None, :] * 3 * season[:, None, :] * trend * weekend * wh_size
    return rng.poisson(lam).astype(np.int32)


def simulate_inventory(demand: np.ndarray, days: pd.DatetimeIndex, wh_ids: list[str], catalog: pd.DataFrame,
                       rng: np.random.Generator, *, constrain: bool = True, outages: frozenset = frozenset(),
                       outage_start: pd.Timestamp | None = None):
    """Run a reorder-point policy per (warehouse, product).

    Returns (fulfilled, restocks, inventory): fulfilled demand array, restock events (including the opening
    stock-in on day one) and the closing inventory snapshot with reorder levels.
    """
    n_days, n_wh, n_p = demand.shape
    pids = catalog.product_id.tolist()
    lead = catalog.lead_time_days.to_numpy()
    fulfilled = demand.copy()
    rs_day, rs_w, rs_p, rs_q = [], [], [], []
    snap = []
    out_from = None if outage_start is None else int(days.searchsorted(outage_start, side="right"))
    for w in range(n_wh):
        for p in range(n_p):
            d = demand[:, w, p].tolist()
            avg = max(sum(d) / n_days, 0.5)
            lt = int(lead[p])
            reorder_level = int(np.ceil(avg * lt * 1.3))
            order_qty = int(np.ceil(avg * 45 * float(rng.choice([1, 1.5, 2, 3, 5], p=[.2, .3, .25, .15, .1]))))
            stock = order_qty + reorder_level
            rs_day.append(0); rs_w.append(w); rs_p.append(p); rs_q.append(stock)   # noqa: E702
            arrive, blocked = -1, (w, p) in outages
            sold_series = d if not constrain else [0] * n_days
            for i in range(n_days):
                if arrive == i:
                    stock += order_qty
                    rs_day.append(i); rs_w.append(w); rs_p.append(p); rs_q.append(order_qty)   # noqa: E702
                    arrive = -1
                want = d[i]
                if constrain:
                    sold = want if want <= stock else stock
                    sold_series[i] = sold
                else:
                    sold = want
                stock = stock - sold if stock > sold else 0
                if stock <= reorder_level and arrive < 0:
                    arrive = i + (400 if (blocked and out_from is not None and i >= out_from) else lt)
            if constrain:
                fulfilled[:, w, p] = sold_series
            snap.append((wh_ids[w], pids[p], stock, reorder_level))
    restocks = pd.DataFrame({"restock_date": days[rs_day], "warehouse_id": np.array(wh_ids)[rs_w],
                             "product_id": np.array(pids)[rs_p], "quantity": rs_q})
    restocks = restocks.sort_values(["restock_date", "warehouse_id", "product_id"]).reset_index(drop=True)
    inventory = pd.DataFrame(snap, columns=["warehouse_id", "product_id", "current_stock", "reorder_level"])
    return fulfilled, restocks, inventory


def to_order_lines(fulfilled: np.ndarray, days: pd.DatetimeIndex, wh_ids: list[str], catalog: pd.DataFrame) -> pd.DataFrame:
    """One order line per (day, warehouse, product) with units > 0."""
    di, wi, pi = np.nonzero(fulfilled)
    n = len(di)
    price = catalog.unit_price.to_numpy()
    return pd.DataFrame({
        "order_id": np.char.add("O", np.char.zfill(np.arange(1, n + 1).astype(str), 8)),
        "order_date": days[di], "warehouse_id": np.array(wh_ids)[wi], "product_id": catalog.product_id.to_numpy()[pi],
        "quantity": fulfilled[di, wi, pi], "unit_price": price[pi],
    })


def inject_mess(sales: pd.DataFrame, products: pd.DataFrame, inventory: pd.DataFrame, restocks: pd.DataFrame,
                rng: np.random.Generator):
    """Corrupt clean frames the way real exports are corrupted (for the cleaning step to fix)."""
    s = sales.copy()
    dup = s.sample(frac=0.012, random_state=1)
    s = pd.concat([s, dup]).sample(frac=1, random_state=2).reset_index(drop=True)
    fmt_idx = rng.choice(3, len(s), p=[.7, .2, .1])
    dates = pd.Series(index=s.index, dtype=object)
    for k, fmt in enumerate(["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"]):
        m = fmt_idx == k
        dates[m] = s.loc[m, "order_date"].dt.strftime(fmt)
    s["order_date"] = dates
    s["unit_price"] = ("$" + s.unit_price.map("{:.2f}".format))
    s = s.astype({"quantity": "object", "warehouse_id": "object"})
    s.loc[s.sample(frac=0.006, random_state=3).index, "quantity"] = np.nan
    s.loc[s.sample(frac=0.01, random_state=4).index, "unit_price"] = np.nan
    s.loc[s.sample(frac=0.002, random_state=5).index, "warehouse_id"] = None

    p = products.copy()
    r1, r2 = rng.random(len(p)), rng.random(len(p))
    p["category"] = [c.upper() if a < .1 else (f" {c.lower()} " if b < .1 else c)
                     for c, a, b in zip(p.category, r1, r2, strict=True)]
    p["unit_price"] = "$" + p.unit_price.map("{:.2f}".format)
    r = restocks.copy()
    r["restock_date"] = r.restock_date.dt.strftime("%Y-%m-%d")
    return s, p, inventory.copy(), r


def generate_raw(seed: int = 42, preset: str = "demo", start: str | None = None, end: str | None = None):
    """Full synthetic raw dataset -> dict of raw frames (warehouses, products, inventory, restocks, sales)."""
    cfg = PRESETS[preset]
    rng = np.random.default_rng(seed)
    days = pd.date_range(start or cfg.start, end or cfg.end)
    wh = make_warehouses(cfg.warehouses)
    wh_ids = wh.warehouse_id.tolist()
    catalog = make_catalog(rng, cfg.products)
    demand = make_demand(catalog, days, len(wh_ids), rng)
    # supplier outage in the last 90 days for ~2% of (warehouse, product) series
    n_out = max(3, int(0.02 * len(wh_ids) * len(catalog)))
    flat = rng.choice(len(wh_ids) * len(catalog), n_out, replace=False)
    outages = frozenset((int(i // len(catalog)), int(i % len(catalog))) for i in flat)
    fulfilled, restocks, inventory = simulate_inventory(
        demand, days, wh_ids, catalog, rng, outages=outages, outage_start=days[-1] - pd.Timedelta(days=90))
    sales = to_order_lines(fulfilled, days, wh_ids, catalog)
    products = catalog.drop(columns="base_rate")
    s, p, i, r = inject_mess(sales, products, inventory, restocks, rng)
    return {"warehouses": wh, "products": p, "inventory": i, "restocks": r, "sales": s}
