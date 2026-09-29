"""Generate a synthetic retail inventory & sales dataset (raw, deliberately messy).

Kaggle datasets usually lack stock/restock info, so this simulates a small
retail warehouse: daily demand, a reorder policy, supplier lead times, and
then injects realistic data-quality problems for the cleaning step.
Seeded, so the output is reproducible.
"""
import numpy as np, pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
OUT = Path(__file__).resolve().parent.parent / "data" / "raw"
START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")
days = pd.date_range(START, END)

catalog = {
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

rows = []
pid = 1000
for cat, names in catalog.items():
    for n in names:
        pid += 1
        cost = round(float(rng.uniform(1.5, 22)), 2)
        rows.append(dict(product_id=f"P{pid}", product_name=n, category=cat, unit_cost=cost,
                         unit_price=round(cost * float(rng.uniform(1.25, 1.6)), 2),
                         base_rate=float(rng.choice([0.15, 0.3, 0.6, 1.0, 1.6, 2.5], p=[.12, .2, .28, .2, .12, .08])),
                         lead_time_days=int(rng.integers(3, 15))))
prod = pd.DataFrame(rows)
prod["reorder_level"] = 0
prod["current_stock"] = 0

sales, restocks = [], []
oid = 100000
delayed = set(rng.choice(prod.product_id, 7, replace=False))  # supplier trouble -> ends below reorder level
for i, p in prod.iterrows():
    season = 1 + 0.25 * np.sin((days.dayofyear.values - 60) / 365 * 2 * np.pi)
    if p.category == "Beverages":
        season = 1 + 0.5 * np.sin((days.dayofyear.values - 100) / 365 * 2 * np.pi)   # summer peak
    trend = np.linspace(1, 1.15, len(days))
    weekend = np.where(days.dayofweek >= 5, 1.3, 1.0)
    demand = rng.poisson(p.base_rate * season * trend * weekend * 3)
    avg = max(p.base_rate * 3, 0.5)
    reorder_level = int(np.ceil(avg * p.lead_time_days * 1.3))
    mult = float(rng.choice([0.8, 1, 1.5, 3, 6], p=[.15, .3, .25, .2, .1]))   # over-/under-stocking policy
    order_qty = int(np.ceil(avg * 30 * mult))
    prod.loc[i, "reorder_level"] = reorder_level
    stock = order_qty + reorder_level
    prod.loc[i, "_opening"] = stock
    pending = []  # (arrival_day_idx, qty)
    for d_idx, day in enumerate(days):
        for arr in [a for a in pending if a[0] == d_idx]:
            stock += arr[1]
            restocks.append(dict(restock_date=day, product_id=p.product_id, quantity=arr[1]))
        pending = [a for a in pending if a[0] != d_idx]
        want = int(demand[d_idx])
        sold = min(want, stock)
        # split into order lines of 1-4 units
        while sold > 0:
            q = min(sold, int(rng.integers(1, 5)))
            oid += 1
            sales.append(dict(order_id=f"O{oid}", order_date=day, product_id=p.product_id, quantity=q,
                              unit_price=p.unit_price, store=str(rng.choice(["North", "South", "East", "West"]))))
            sold -= q
        stock -= min(want, stock)
        if stock <= reorder_level and not pending:
            lt = p.lead_time_days
            if p.product_id in delayed and day > pd.Timestamp("2025-10-01"):
                lt = 400  # supplier stopped delivering
            pending.append((d_idx + lt, order_qty))
    prod.loc[i, "current_stock"] = stock

sales = pd.DataFrame(sales)
restocks = pd.DataFrame(restocks)
opening = prod[["product_id", "_opening"]].rename(columns={"_opening": "quantity"})
opening["restock_date"] = START
restocks["quantity"] = restocks.quantity.astype(int)
restocks = pd.concat([opening[["restock_date", "product_id", "quantity"]], restocks]).sort_values(["restock_date", "product_id"])
prod = prod.drop(columns=["base_rate", "_opening"])

# ---- inject realistic mess -------------------------------------------------
s = sales.copy()
dup = s.sample(frac=0.012, random_state=1)
s = pd.concat([s, dup]).sample(frac=1, random_state=2).reset_index(drop=True)          # duplicate rows
fmt = rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"], len(s), p=[.7, .2, .1])
s["order_date"] = [d.strftime(f) for d, f in zip(s.order_date, fmt)]                    # mixed date formats
s["unit_price"] = s.unit_price.map(lambda v: f"${v:.2f}")                               # price as text
s = s.astype({"quantity": "object"})
s.loc[s.sample(frac=0.006, random_state=3).index, "quantity"] = np.nan                  # missing qty
s.loc[s.sample(frac=0.01, random_state=4).index, "unit_price"] = np.nan                 # missing price
s.loc[s.sample(frac=0.004, random_state=5).index, "store"] = None                       # missing store

p = prod.copy()
p["category"] = [c.upper() if rng.random() < .1 else (" " + c.lower() + " " if rng.random() < .1 else c) for c in p.category]
p["unit_price"] = p.unit_price.map(lambda v: f"${v:.2f}")

r = restocks.copy()
r["restock_date"] = r.restock_date.dt.strftime("%Y-%m-%d")

s.to_csv(OUT / "raw_sales.csv", index=False)
p.to_csv(OUT / "raw_products.csv", index=False)
r.to_csv(OUT / "raw_restocks.csv", index=False)
print(len(s), "sales rows,", len(p), "products,", len(r), "restock rows")
