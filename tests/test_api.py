import pytest
from fastapi.testclient import TestClient

from invsales.api import create_app
from invsales.config import Settings


@pytest.fixture
def client(tables):
    return TestClient(create_app(tables, Settings()))


def test_health_and_warehouses(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["sales_rows"] == 6 and h["warehouses"] == 2
    w = client.get("/warehouses").json()
    assert {x["warehouse_id"] for x in w} == {"W1", "W2"} and w[0]["revenue"] == 79.0


def test_kpis_filters(client):
    assert client.get("/kpis").json() == {"total_sales": 100.0, "units_sold": 45, "total_stock": 117, "low_stock_items": 3}
    w1 = client.get("/kpis", params={"warehouse_id": "W1"}).json()
    assert w1["total_sales"] == 79.0 and w1["low_stock_items"] == 2
    assert client.get("/kpis", params={"category": "Staples"}).json()["units_sold"] == 1
    assert client.get("/kpis", params={"warehouse_id": "NOPE"}).status_code == 404
    assert client.get("/kpis", params={"category": "NOPE"}).status_code == 404


def test_alerts(client):
    a = client.get("/alerts").json()
    assert a["count"] == 3 and a["items"][0]["product_id"] == "C" and a["items"][0]["severity"] == "Stockout"
    assert client.get("/alerts", params={"severity": "Stockout"}).json()["count"] == 1
    assert client.get("/alerts", params={"warehouse_id": "W2"}).json()["count"] == 1
    assert client.get("/alerts", params={"severity": "bogus"}).status_code == 422


def test_replenishment_transfers_abc(client):
    r = client.get("/replenishment", params={"only_due": False}).json()
    assert r["count"] == 6 and r["total_cost"] >= 0
    assert all(i["suggested_order_qty"] == 0 for i in r["items"] if not i["below_rop"])
    assert isinstance(client.get("/transfers").json()["items"], list)
    abc = client.get("/abc").json()
    assert abc["count"] == 3 and set(abc["items"][0]) >= {"abc", "xyz", "segment"}


def test_product_and_forecast(client):
    p = client.get("/products/A").json()
    assert p["product"]["product_name"] == "Alpha" and len(p["by_warehouse"]) == 2
    assert client.get("/products/ZZZ").status_code == 404
    assert client.get("/forecast/ZZZ").status_code == 404
    assert client.get("/forecast/A", params={"horizon": 3}).status_code == 422       # below minimum of 7


def test_forecast_endpoint_with_enough_history(tables):
    import pandas as pd
    s = tables["sales"]
    rows = [dict(order_id=f"x{i}", order_date=pd.Timestamp("2025-01-01") + pd.Timedelta(days=i), warehouse_id="W1",
                 product_id="A", quantity=3, unit_price=2.0, revenue=6.0) for i in range(60)]
    big = {**tables, "sales": pd.concat([s, pd.DataFrame(rows)], ignore_index=True)
           .drop_duplicates("order_id")}
    c = TestClient(create_app(big, Settings()))
    f = c.get("/forecast/A", params={"horizon": 10}).json()
    assert len(f["daily"]) == 10 and f["total_units"] > 0 and "wape_model" in f["model_check"]


def test_api_key_enforced_when_configured(tables, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    c = TestClient(create_app(tables, Settings()))
    assert c.get("/health").status_code == 401
    assert c.get("/health", headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.get("/health", headers={"X-API-Key": "secret"}).status_code == 200


def test_inventory_health_and_what_if(client):
    base = client.get("/inventory/health").json()
    slow = client.get("/inventory/health", params={"delay_days": 14}).json()
    assert base["delay_days"] == 0 and base["stock_value"] > 0 and 0 <= base["excess_pct"] <= 100
    assert slow["at_risk_items"] >= base["at_risk_items"] and slow["suggested_po_value"] >= base["suggested_po_value"]
    assert client.get("/inventory/health", params={"delay_days": -1}).status_code == 422
