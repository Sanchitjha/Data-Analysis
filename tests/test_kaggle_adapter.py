import numpy as np
import pandas as pd

from invsales.clean import clean_all
from invsales.sources import adapt_store_item_demand
from invsales.validate import validate


def fake_train():
    rng = np.random.default_rng(0)
    idx = pd.MultiIndex.from_product([pd.date_range("2017-01-01", periods=90), [1, 2], [1, 2, 3]], names=["date", "store", "item"])
    return idx.to_frame(index=False).assign(sales=rng.poisson(8, len(idx)))


def test_adapter_preserves_real_sales_and_passes_pipeline():
    train = fake_train()
    sales, products, restocks = adapt_store_item_demand(train, seed=1)
    assert sales.quantity.sum() == train.sales.sum()                     # real units untouched
    assert set(products.product_id) == {"I001", "I002", "I003"}
    s, p, r, _ = clean_all(sales.astype(str), products.astype(str), restocks.astype(str))
    assert validate(s, p, r) == []
    assert s.quantity.sum() == train.sales.sum()
