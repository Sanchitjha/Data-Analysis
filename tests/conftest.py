import pandas as pd
import pytest


@pytest.fixture
def warehouses():
    return pd.DataFrame({"warehouse_id": ["W1", "W2"], "warehouse_name": ["Delhi", "Mumbai"], "region": ["N", "W"]})


@pytest.fixture
def products():
    return pd.DataFrame({
        "product_id": ["A", "B", "C"], "product_name": ["Alpha", "Beta", "Gamma"],
        "category": ["Snacks", "Snacks", "Staples"], "unit_cost": [1.0, 2.0, 3.0], "unit_price": [2.0, 3.0, 4.0],
        "lead_time_days": [5, 5, 5]})


@pytest.fixture
def inventory():
    return pd.DataFrame({
        "warehouse_id": ["W1", "W1", "W1", "W2", "W2", "W2"], "product_id": ["A", "B", "C"] * 2,
        "current_stock": [5, 50, 0, 40, 2, 20], "reorder_level": [10] * 6})


@pytest.fixture
def sales():
    d = pd.to_datetime(["2025-01-01", "2025-01-15", "2025-02-01", "2025-02-10", "2025-02-10", "2025-02-11"])
    return pd.DataFrame({
        "order_id": ["1", "2", "3", "4", "5", "6"], "order_date": d, "warehouse_id": ["W1"] * 4 + ["W2"] * 2,
        "product_id": ["A", "A", "B", "C", "A", "B"], "quantity": [10, 20, 5, 1, 6, 3],
        "unit_price": [2.0, 2.0, 3.0, 4.0, 2.0, 3.0], "revenue": [20.0, 40.0, 15.0, 4.0, 12.0, 9.0]})


@pytest.fixture
def restocks():
    return pd.DataFrame({
        "restock_date": pd.to_datetime(["2025-01-01"] * 6), "warehouse_id": ["W1"] * 3 + ["W2"] * 3,
        "product_id": ["A", "B", "C"] * 2, "quantity": [35, 55, 10, 50, 20, 25]})


@pytest.fixture
def tables(warehouses, products, inventory, sales, restocks):
    return {"warehouses": warehouses, "products": products, "inventory": inventory, "sales": sales,
            "restocks": restocks}
