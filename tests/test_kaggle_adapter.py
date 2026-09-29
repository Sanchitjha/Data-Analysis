import numpy as np
import pandas as pd

from invsales.clean import clean_all
from invsales.sources import adapt_store_item_demand
from invsales.validate import validate


def fake_train():
    rng = np.random.default_rng(0)
    idx = pd.MultiIndex.from_product([pd.date_range("2017-01-01", periods=90), [1, 2], [1, 2, 3]],
                                     names=["date", "store", "item"])
    return idx.to_frame(index=False).assign(sales=rng.poisson(8, len(idx)))


def test_adapter_preserves_real_sales_and_passes_pipeline():
    train = fake_train()
    raw = adapt_store_item_demand(train, seed=1)
    assert raw["sales"].quantity.sum() == train.sales.sum()                 # real units untouched
    assert set(raw["products"].product_id) == {"I001", "I002", "I003"}
    assert set(raw["warehouses"].warehouse_id) == {"S01", "S02"}
    tables, _ = clean_all({k: v.astype(str) for k, v in raw.items()})
    assert validate(tables) == []
    assert tables["sales"].quantity.sum() == train.sales.sum()
