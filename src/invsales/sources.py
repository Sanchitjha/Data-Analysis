"""Raw data sources: synthetic simulator or a real Kaggle sales dataset."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .simulate import generate_raw, simulate_inventory

RAW_FILES = ("raw_sales.csv", "raw_products.csv", "raw_restocks.csv")
DEFAULT_KAGGLE_DATASET = "competitions/demand-forecasting-kernels-only"  # Store Item Demand Forecasting


def write_synthetic(raw_dir: Path, seed: int = 42) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    sales, products, restocks = generate_raw(seed)
    sales.to_csv(raw_dir / "raw_sales.csv", index=False)
    products.to_csv(raw_dir / "raw_products.csv", index=False)
    restocks.to_csv(raw_dir / "raw_restocks.csv", index=False)


def kaggle_download(target: Path, competition: str = "demand-forecasting-kernels-only") -> Path:
    """Download via the Kaggle CLI. Needs KAGGLE_USERNAME/KAGGLE_KEY (or ~/.kaggle/kaggle.json)
    and, for competitions, accepting the competition rules once on kaggle.com."""
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "competitions", "download", "-c", competition, "-p", str(target)], check=True)
    for z in target.glob("*.zip"):
        with zipfile.ZipFile(z) as f:
            f.extractall(target)
    return target / "train.csv"


def adapt_store_item_demand(train: pd.DataFrame, seed: int = 42, n_items: int | None = None):
    """Map Kaggle 'Store Item Demand Forecasting' (date, store, item, sales) to the raw schema.

    Real: dates, stores, items, units sold. NOT in the dataset (derived, documented in README):
    product names/categories/prices/costs/lead times and the whole inventory layer (stock,
    reorder level, restocks) which come from `simulate_inventory` on the real daily demand.
    """
    rng = np.random.default_rng(seed)
    df = train.rename(columns=str.lower).copy()
    df["date"] = pd.to_datetime(df["date"])
    if n_items:
        df = df[df["item"] <= n_items]
    items = sorted(df["item"].unique())
    cats = ["Beverages", "Snacks", "Household", "Personal Care", "Staples"]
    catalog = pd.DataFrame({
        "product_id": [f"I{int(i):03d}" for i in items],
        "product_name": [f"Item {int(i):03d}" for i in items],
        "category": [cats[int(i) % len(cats)] for i in items],
    })
    catalog["unit_cost"] = np.round(rng.uniform(2, 20, len(catalog)), 2)
    catalog["unit_price"] = np.round(catalog.unit_cost * rng.uniform(1.25, 1.6, len(catalog)), 2)
    catalog["lead_time_days"] = rng.integers(3, 15, len(catalog))

    df["product_id"] = df["item"].map(lambda i: f"I{int(i):03d}")
    demand = df.pivot_table(index="date", columns="product_id", values="sales", aggfunc="sum", fill_value=0)
    demand = demand[catalog.product_id]
    _, restocks, state = simulate_inventory(demand, catalog, rng, constrain=False)

    sales = df[df["sales"] > 0][["date", "store", "product_id", "sales"]].rename(
        columns={"date": "order_date", "sales": "quantity"})
    sales["store"] = "Store " + sales["store"].astype(str)
    sales = sales.merge(catalog[["product_id", "unit_price"]], on="product_id").sort_values(
        ["order_date", "product_id", "store"]).reset_index(drop=True)
    sales.insert(0, "order_id", [f"K{i:07d}" for i in range(1, len(sales) + 1)])
    sales["order_date"] = sales.order_date.dt.strftime("%Y-%m-%d")
    products = catalog.merge(state, on="product_id")
    restocks["restock_date"] = restocks.restock_date.dt.strftime("%Y-%m-%d")
    return sales, products, restocks


def write_kaggle(raw_dir: Path, train_csv: Path, seed: int = 42, n_items: int | None = None) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    sales, products, restocks = adapt_store_item_demand(pd.read_csv(train_csv), seed, n_items)
    sales.to_csv(raw_dir / "raw_sales.csv", index=False)
    products.to_csv(raw_dir / "raw_products.csv", index=False)
    restocks.to_csv(raw_dir / "raw_restocks.csv", index=False)
