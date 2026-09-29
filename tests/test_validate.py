import pytest

from invsales.validate import DataQualityError, assert_valid, validate


def test_valid_data_passes(sales, products, restocks):
    assert validate(sales, products, restocks) == []


def test_detects_orphans_and_bad_values(sales, products, restocks):
    bad = sales.copy()
    bad.loc[0, "product_id"] = "ZZZ"
    bad.loc[1, "quantity"] = -1
    problems = validate(bad, products, restocks)
    assert any("unknown products" in p for p in problems) and any("quantity" in p for p in problems)
    with pytest.raises(DataQualityError):
        assert_valid(bad, products, restocks)


def test_detects_duplicate_ids_and_negative_stock(sales, products, restocks):
    dup = sales.copy()
    dup.loc[1, "order_id"] = "1"
    neg = products.copy()
    neg.loc[0, "current_stock"] = -3
    assert any("order_id" in p for p in validate(dup, products, restocks))
    assert any("negative stock" in p for p in validate(sales, neg, restocks))
