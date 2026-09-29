import pandas as pd
import pytest


@pytest.fixture
def products():
    return pd.DataFrame({
        "product_id": ["A", "B", "C"], "product_name": ["Alpha", "Beta", "Gamma"],
        "category": ["Snacks", "Snacks", "Staples"], "unit_cost": [1.0, 2.0, 3.0], "unit_price": [2.0, 3.0, 4.0],
        "lead_time_days": [5, 5, 5], "reorder_level": [10, 10, 10], "current_stock": [5, 50, 0]})


@pytest.fixture
def sales():
    d = pd.to_datetime(["2025-01-01", "2025-01-15", "2025-02-01", "2025-02-10"])
    return pd.DataFrame({
        "order_id": ["1", "2", "3", "4"], "order_date": d, "product_id": ["A", "A", "B", "C"],
        "quantity": [10, 20, 5, 1], "unit_price": [2.0, 2.0, 3.0, 4.0], "store": ["N"] * 4,
        "revenue": [20.0, 40.0, 15.0, 4.0]})


@pytest.fixture
def restocks():
    return pd.DataFrame({"restock_date": pd.to_datetime(["2025-01-01"] * 3), "product_id": ["A", "B", "C"],
                         "quantity": [35, 55, 10]})
