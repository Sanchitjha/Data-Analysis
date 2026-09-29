"""Raw data sources: synthetic simulator or a real Kaggle sales dataset."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .simulate import CATEGORIES, generate_raw, simulate_inventory

RAW_TABLES = ("warehouses", "products", "inventory", "restocks", "sales")


def write_raw(raw_dir: Path, frames: dict[str, pd.DataFrame]) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in RAW_TABLES:
        frames[name].to_csv(raw_dir / f"raw_{name}.csv", index=False)


def write_synthetic(raw_dir: Path, seed: int = 42, preset: str = "demo") -> None:
    write_raw(raw_dir, generate_raw(seed, preset))


def kaggle_download(target: Path, competition: str = "demand-forecasting-kernels-only") -> Path:
    """Download via the Kaggle CLI. Needs KAGGLE_USERNAME/KAGGLE_KEY (or ~/.kaggle/kaggle.json)
    and, for competitions, accepting the competition rules once on kaggle.com."""
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(["kaggle", "competitions", "download", "-c", competition, "-p", str(target)], check=True)
    for z in target.glob("*.zip"):
        with zipfile.ZipFile(z) as f:
            f.extractall(target)
    return target / "train.csv"


def adapt_store_item_demand(train: pd.DataFrame, seed: int = 42, n_items: int | None = None) -> dict[str, pd.DataFrame]:
    """Map Kaggle 'Store Item Demand Forecasting' (date, store, item, sales) to the raw schema.

    Real: dates, stores (used as warehouses), items, units sold. NOT in the dataset (derived, documented in the
    README): product names/categories/prices/costs/lead times and the whole inventory layer (stock, reorder level,
    restocks), which come from `simulate_inventory` run on the real daily demand.
    """
    rng = np.random.default_rng(seed)
    df = train.rename(columns=str.lower).copy()
    df["date"] = pd.to_datetime(df["date"])
    if n_items:
        df = df[df["item"] <= n_items]
    items, stores = sorted(df["item"].unique()), sorted(df["store"].unique())
    wh_ids = [f"S{int(s):02d}" for s in stores]
    warehouses = pd.DataFrame({"warehouse_id": wh_ids, "warehouse_name": [f"Store {int(s)}" for s in stores],
                               "region": "n/a"})
    catalog = pd.DataFrame({
        "product_id": [f"I{int(i):03d}" for i in items], "product_name": [f"Item {int(i):03d}" for i in items],
        "category": [CATEGORIES[int(i) % len(CATEGORIES)] for i in items]})
    catalog["unit_cost"] = np.round(rng.uniform(2, 20, len(catalog)), 2)
    catalog["unit_price"] = np.round(catalog.unit_cost * rng.uniform(1.25, 1.6, len(catalog)), 2)
    catalog["lead_time_days"] = rng.integers(3, 15, len(catalog))

    days = pd.DatetimeIndex(sorted(df["date"].unique()))
    demand = np.zeros((len(days), len(stores), len(items)), dtype=np.int32)
    di = days.get_indexer(df["date"])
    wi = pd.Index(stores).get_indexer(df["store"])
    pi = pd.Index(items).get_indexer(df["item"])
    demand[di, wi, pi] = df["sales"].to_numpy()
    fulfilled, restocks, inventory = simulate_inventory(demand, days, wh_ids, catalog, rng, constrain=False)

    d, w, p = np.nonzero(fulfilled)
    sales = pd.DataFrame({
        "order_id": [f"K{i:07d}" for i in range(1, len(d) + 1)], "order_date": days[d].strftime("%Y-%m-%d"),
        "warehouse_id": np.array(wh_ids)[w], "product_id": catalog.product_id.to_numpy()[p],
        "quantity": fulfilled[d, w, p], "unit_price": catalog.unit_price.to_numpy()[p]})
    restocks["restock_date"] = restocks.restock_date.dt.strftime("%Y-%m-%d")
    return {"warehouses": warehouses, "products": catalog, "inventory": inventory, "restocks": restocks, "sales": sales}


def write_kaggle(raw_dir: Path, train_csv: Path, seed: int = 42, n_items: int | None = None) -> None:
    write_raw(raw_dir, adapt_store_item_demand(pd.read_csv(train_csv), seed, n_items))
