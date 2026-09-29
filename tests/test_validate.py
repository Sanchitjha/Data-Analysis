import pandas as pd
import pytest

from invsales.validate import DataQualityError, assert_valid, validate


def test_valid_data_passes(tables):
    assert validate(tables) == []


def test_detects_orphans_and_bad_values(tables):
    bad = {**tables, "sales": tables["sales"].copy()}
    bad["sales"].loc[0, "product_id"] = "ZZZ"
    bad["sales"].loc[1, "quantity"] = -1
    bad["sales"].loc[2, "warehouse_id"] = "W9"
    problems = validate(bad)
    assert any("sales reference unknown products" in p for p in problems)
    assert any("sales reference unknown warehouses" in p for p in problems)
    assert any("quantity" in p for p in problems)
    with pytest.raises(DataQualityError):
        assert_valid(bad)


def test_detects_duplicate_ids_and_negative_stock(tables):
    dup = {**tables, "sales": tables["sales"].copy()}
    dup["sales"].loc[1, "order_id"] = "1"
    neg = {**tables, "inventory": tables["inventory"].copy()}
    neg["inventory"].loc[0, "current_stock"] = -3
    twice = {**tables, "inventory": pd.concat([tables["inventory"], tables["inventory"].iloc[[0]]])}
    assert any("order_id" in p for p in validate(dup))
    assert any("negative stock" in p for p in validate(neg))
    assert any("not unique" in p for p in validate(twice))
