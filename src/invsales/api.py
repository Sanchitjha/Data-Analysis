"""REST API over the same data and models as the dashboard.  Run:  uvicorn invsales.api:app --port 8000
Docs: /docs (Swagger UI) and /redoc.  Optional auth: set API_KEY and send it as the X-API-Key header."""
from __future__ import annotations

import os
import threading
from functools import cached_property

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from . import analytics, kpis
from .config import Settings, get_settings
from .repository import load_data


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN/inf -> null, timestamps -> ISO strings)."""
    out = df.replace([np.inf, -np.inf], np.nan).astype(object).where(df.notna(), None)
    return [{k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in row.items()}
            for row in out.to_dict("records")]


class Store:
    """Lazily loaded data + cached model outputs (computed once per process)."""

    def __init__(self, settings: Settings, tables: dict | None = None, source: str = "injected"):
        self.settings = settings
        self._tables, self.source = tables, source
        self._lock = threading.Lock()

    @property
    def t(self) -> dict[str, pd.DataFrame]:
        with self._lock:
            if self._tables is None:
                self._tables, self.source = load_data(self.settings)
        return self._tables

    @cached_property
    def groups(self) -> pd.Series:
        return self.t["products"].set_index("product_id").category

    @cached_property
    def repl(self) -> pd.DataFrame:
        t, s = self.t, self.settings
        return analytics.replenishment(t["sales"], t["inventory"], t["products"], t["warehouses"],
                                       s.service_level_z, s.ordering_cost, s.holding_rate)

    @cached_property
    def abc(self) -> pd.DataFrame:
        return analytics.abc_xyz(self.t["sales"], self.t["products"])

    @cached_property
    def transfers(self) -> pd.DataFrame:
        return analytics.transfer_suggestions(self.repl, self.t["products"])

    @cached_property
    def backtest(self) -> dict:
        return analytics.backtest(self.t["sales"], 30, self.groups)

    @cached_property
    def history(self) -> pd.DataFrame:
        return analytics.daily_matrix(self.t["sales"])


def create_app(tables: dict | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = Store(settings, tables)
    api_key = os.getenv("API_KEY")

    def auth(x_api_key: str | None = Header(default=None)) -> None:
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    app = FastAPI(title="Inventory & Sales Analytics API", version="1.0.0", dependencies=[Depends(auth)],
                  description="KPIs, reorder alerts, replenishment recommendations, demand forecasts and transfer "
                              "suggestions for a multi-warehouse inventory.")

    def _wh(df: pd.DataFrame, warehouse_id: str | None, col: str = "warehouse_id") -> pd.DataFrame:
        if warehouse_id:
            if warehouse_id not in set(store.t["warehouses"].warehouse_id):
                raise HTTPException(404, f"unknown warehouse {warehouse_id}")
            return df[df[col] == warehouse_id]
        return df

    @app.get("/health", tags=["meta"])
    def health():
        t = store.t
        return {"status": "ok", "source": store.source, "sales_rows": len(t["sales"]), "products": len(t["products"]),
                "warehouses": len(t["warehouses"])}

    @app.get("/warehouses", tags=["meta"])
    def warehouses():
        t = store.t
        return records(kpis.warehouse_summary(t["sales"], t["inventory"], t["warehouses"]))

    @app.get("/kpis", tags=["kpis"])
    def get_kpis(warehouse_id: str | None = None, category: str | None = None):
        t = store.t
        prod = t["products"] if not category else t["products"][t["products"].category == category]
        if category and prod.empty:
            raise HTTPException(404, f"unknown category {category}")
        s = _wh(t["sales"], warehouse_id)
        i = _wh(t["inventory"], warehouse_id)
        s, i = s[s.product_id.isin(prod.product_id)], i[i.product_id.isin(prod.product_id)]
        return kpis.headline(s, i)

    @app.get("/sales/monthly", tags=["kpis"])
    def monthly(warehouse_id: str | None = None):
        return records(kpis.monthly_sales(_wh(store.t["sales"], warehouse_id)))

    @app.get("/alerts", tags=["inventory"])
    def alerts(warehouse_id: str | None = None, severity: str | None = Query(None, pattern="^(Stockout|Critical|Low)$"),
               limit: int = Query(100, ge=1, le=1000)):
        t = store.t
        a = kpis.reorder_alerts(t["sales"], t["inventory"], t["products"], t["warehouses"])
        a = _wh(a, warehouse_id)
        if severity:
            a = a[a.severity == severity]
        return {"count": len(a), "items": records(a.head(limit))}

    @app.get("/inventory/health", tags=["inventory"])
    def health_summary(delay_days: float = Query(0, ge=0, le=90)):
        """Cash and risk summary: stock value, excess, dead stock, items likely to stock out. `delay_days`: what-if supplier delay."""
        t, s = store.t, store.settings
        repl = store.repl if not delay_days else analytics.replenishment(
            t["sales"], t["inventory"], t["products"], t["warehouses"], s.service_level_z, s.ordering_cost, s.holding_rate, delay_days)
        return {"delay_days": delay_days, **analytics.inventory_health(t["sales"], repl)}

    @app.get("/replenishment", tags=["inventory"])
    def replenishment(warehouse_id: str | None = None, only_due: bool = True, limit: int = Query(100, ge=1, le=5000)):
        r = _wh(store.repl, warehouse_id)
        if only_due:
            r = r[r.below_rop]
        r = r.sort_values("suggested_order_cost", ascending=False)
        return {"count": len(r), "total_cost": round(float(r.suggested_order_cost.sum()), 2), "items": records(r.head(limit))}

    @app.get("/transfers", tags=["inventory"])
    def transfers(limit: int = Query(100, ge=1, le=5000)):
        return {"count": len(store.transfers), "items": records(store.transfers.head(limit))}

    @app.get("/abc", tags=["analytics"])
    def abc(segment: str | None = Query(None, pattern="^[ABC][XYZ]$"), limit: int = Query(1000, ge=1, le=5000)):
        a = store.abc if not segment else store.abc[store.abc.segment == segment]
        return {"count": len(a), "items": records(a.head(limit))}

    @app.get("/forecast/{product_id}", tags=["analytics"])
    def forecast(product_id: str, horizon: int = Query(30, ge=7, le=90)):
        if product_id not in set(store.t["products"].product_id):
            raise HTTPException(404, f"unknown product {product_id}")
        fc = analytics.forecast(store.t["sales"], horizon, store.groups)[product_id]
        bt = store.backtest
        return {"product_id": product_id, "horizon_days": horizon, "total_units": round(float(fc.sum()), 1),
                "daily": [{"date": d.date().isoformat(), "units": round(float(v), 2)} for d, v in fc.items()],
                "model_check": {k: v for k, v in bt.items() if k != "per_product"}}

    @app.get("/products/{product_id}", tags=["inventory"])
    def product(product_id: str):
        t = store.t
        p = t["products"][t["products"].product_id == product_id]
        if p.empty:
            raise HTTPException(404, f"unknown product {product_id}")
        r = store.repl[store.repl.product_id == product_id]
        return {"product": records(p)[0], "by_warehouse": records(r), "abc_xyz": records(store.abc[store.abc.product_id == product_id])[0]}

    return app


app = create_app()
