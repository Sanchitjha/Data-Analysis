"""Bring your own data: turn a business's own exports (sales, optionally stock / products / receipts) into the
canonical tables the pipeline, dashboard and API use.

Only a sales export is required (date, item, quantity). Everything else is optional; whatever is missing is
replaced by a documented default and listed in the report, so the user always knows what the numbers rest on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import analytics
from .clean import to_number
from .validate import validate

# ---------------------------------------------------------------------------------------------- column mapping
SYNONYMS: dict[str, list[str]] = {
    "order_date": ["order_date", "date", "invoice_date", "sale_date", "sales_date", "transaction_date", "txn_date",
                   "bill_date", "posting_date", "billing_date", "day"],
    "product_id": ["product_id", "sku", "item", "item_id", "item_code", "product", "product_code", "article", "material",
                   "part_no", "part_number", "sku_code"],
    "quantity": ["quantity", "qty", "units", "units_sold", "sold_qty", "sales_qty", "pieces", "volume", "qty_sold"],
    "warehouse_id": ["warehouse_id", "warehouse", "location", "store", "store_id", "branch", "site", "dc", "plant",
                     "outlet", "location_id"],
    "unit_price": ["unit_price", "price", "rate", "selling_price", "sale_price", "mrp", "price_per_unit"],
    "revenue": ["revenue", "amount", "total", "net_amount", "line_total", "value", "sales_amount", "net_sales"],
    "order_id": ["order_id", "invoice", "invoice_no", "invoice_number", "bill_no", "order_no", "order_number", "txn_id",
                 "transaction_id"],
    "product_name": ["product_name", "item_name", "description", "name", "product_description", "item_description"],
    "category": ["category", "product_category", "group", "item_group", "department", "class"],
    "unit_cost": ["unit_cost", "cost", "cost_price", "purchase_price", "buy_price", "std_cost", "landed_cost"],
    "lead_time_days": ["lead_time_days", "lead_time", "leadtime", "supplier_lead_time", "lt_days", "delivery_days"],
    "current_stock": ["current_stock", "stock", "on_hand", "qty_on_hand", "quantity_on_hand", "closing_stock", "inventory",
                      "stock_on_hand", "balance", "available"],
    "reorder_level": ["reorder_level", "reorder_point", "min_stock", "min_qty", "rop", "reorder_qty_level", "minimum_stock"],
    "restock_date": ["restock_date", "receipt_date", "grn_date", "received_date", "date"],
}
SALES_FIELDS = ["order_date", "product_id", "quantity", "warehouse_id", "unit_price", "revenue", "order_id"]
STOCK_FIELDS = ["product_id", "current_stock", "warehouse_id", "reorder_level"]
PRODUCT_FIELDS = ["product_id", "product_name", "category", "unit_cost", "unit_price", "lead_time_days"]
REQUIRED = {"sales": ["order_date", "product_id", "quantity"], "stock": ["product_id", "current_stock"],
            "products": ["product_id"]}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def suggest_mapping(columns: list[str], fields: list[str]) -> dict[str, str | None]:
    """field -> best matching source column (or None). Exact synonym match first, then token containment.
    Every source column is used at most once."""
    norm = {c: _norm(c) for c in columns}
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for f in fields:                                             # pass 1: exact synonyms, in synonym priority order
        out[f] = None
        for syn in SYNONYMS.get(f, [f]):
            hit = next((c for c, n in norm.items() if n == syn and c not in used), None)
            if hit:
                out[f] = hit
                used.add(hit)
                break
    for f in fields:                                             # pass 2: a synonym contained in the header
        if out[f] is None:
            for syn in SYNONYMS.get(f, [f]):
                hit = next((c for c, n in norm.items() if c not in used and len(syn) >= 3 and syn in n.split("_")), None)
                if hit:
                    out[f] = hit
                    used.add(hit)
                    break
    return out


# ---------------------------------------------------------------------------------------------- dates
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d",
                "%d.%m.%Y", "%Y%m%d", "%d-%b-%y", "%d/%m/%y", "%m/%d/%y"]


def parse_dates_flexible(s: pd.Series, dayfirst: bool = True) -> tuple[pd.Series, str]:
    """Parse a messy date column. Returns (dates, description of what was assumed).
    Chooses the format that parses the most values; when day/month order is ambiguous (all values <= 12)
    it follows `dayfirst`."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s), "already dates"
    if pd.api.types.is_numeric_dtype(s):                             # Excel serial numbers
        nums = pd.to_numeric(s, errors="coerce")
        if nums.dropna().between(20000, 80000).mean() > 0.9:
            return pd.to_datetime(nums, unit="D", origin="1899-12-30", errors="coerce"), "Excel serial numbers"
    txt = s.astype("string").str.strip()
    best, best_rate, best_fmt = None, -1.0, ""
    ambiguous = {"%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%y", "%m/%d/%y"}
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(txt, format=fmt, errors="coerce")
        rate = float(parsed.notna().mean())
        if fmt in ambiguous and not dayfirst and fmt.startswith("%d"):
            rate -= 1e-6                                              # tie-break towards the configured convention
        if fmt in ambiguous and dayfirst and fmt.startswith("%m"):
            rate -= 1e-6
        if rate > best_rate:
            best, best_rate, best_fmt = parsed, rate, fmt
    if best_rate < 0.5:                                               # last resort: pandas inference
        best = pd.to_datetime(txt, errors="coerce", dayfirst=dayfirst)
        best_fmt = "pandas inference"
    note = f"format {best_fmt}"
    if best_fmt in ambiguous and best.notna().any():
        first = txt.str.extract(r"^(\d{1,2})[/-]")[0].astype(float)
        if not (first > 12).any():
            note += f" (day/month order ambiguous, assumed {'DD/MM' if dayfirst else 'MM/DD'})"
    return best, note


# ---------------------------------------------------------------------------------------------- import
@dataclass
class ImportDefaults:
    warehouse_id: str = "MAIN"
    category: str = "Uncategorized"
    lead_time_days: int = 7
    cost_to_price_ratio: float = 0.75          # unit_cost = ratio * price when cost is unknown
    dayfirst: bool = True
    service_level_z: float = 1.65
    ordering_cost: float = 50.0
    holding_rate: float = 0.20


@dataclass
class ImportReport:
    rows_in: int = 0
    rows_out: int = 0
    dropped: dict[str, int] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    has_stock: bool = False
    has_restocks: bool = False
    date_min: str | None = None
    date_max: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _pick(df: pd.DataFrame, mapping: dict[str, str | None], f: str) -> pd.Series | None:
    col = mapping.get(f)
    return df[col] if col and col in df.columns else None


def _missing(kind: str, mapping: dict[str, str | None]) -> list[str]:
    return [f for f in REQUIRED[kind] if not mapping.get(f)]


def import_data(sales_raw: pd.DataFrame, sales_map: dict[str, str | None], *,
                stock_raw: pd.DataFrame | None = None, stock_map: dict[str, str | None] | None = None,
                products_raw: pd.DataFrame | None = None, products_map: dict[str, str | None] | None = None,
                defaults: ImportDefaults | None = None) -> tuple[dict[str, pd.DataFrame] | None, ImportReport]:
    """Returns (tables, report). tables is None if a fatal error prevents building them (see report.errors)."""
    d = defaults or ImportDefaults()
    rep = ImportReport(rows_in=len(sales_raw))
    if miss := _missing("sales", sales_map):
        rep.errors.append(f"sales file: could not find column(s) for {', '.join(miss)}; map them manually")
        return None, rep

    # ---------------- sales
    s = pd.DataFrame({"order_date": _pick(sales_raw, sales_map, "order_date"),
                      "product_id": _pick(sales_raw, sales_map, "product_id"),
                      "quantity": _pick(sales_raw, sales_map, "quantity")})
    wh = _pick(sales_raw, sales_map, "warehouse_id")
    s["warehouse_id"] = wh if wh is not None else d.warehouse_id
    if wh is None:
        rep.assumptions.append(f"no warehouse/location column: everything treated as one location '{d.warehouse_id}'")
    price, rev = _pick(sales_raw, sales_map, "unit_price"), _pick(sales_raw, sales_map, "revenue")
    s["unit_price"] = to_number(price) if price is not None else np.nan
    s["_revenue"] = to_number(rev) if rev is not None else np.nan
    oid = _pick(sales_raw, sales_map, "order_id")
    s["order_id"] = oid.astype("string").str.strip() if oid is not None else pd.NA

    dates, note = parse_dates_flexible(s.order_date, d.dayfirst)
    s["order_date"] = dates
    rep.assumptions.append(f"dates parsed with {note}")
    s["product_id"] = s.product_id.astype("string").str.strip()
    s["warehouse_id"] = s.warehouse_id.astype("string").str.strip().fillna(d.warehouse_id)
    s["quantity"] = to_number(s.quantity)

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal s
        n = int(mask.sum())
        if n:
            rep.dropped[reason] = rep.dropped.get(reason, 0) + n
            s = s[~mask].copy()

    drop(s.order_date.isna(), "unparseable date")
    drop(s.product_id.isna() | (s.product_id == ""), "missing product/SKU")
    drop(s.quantity.isna(), "missing quantity")
    drop(s.quantity < 0, "negative quantity (returns/credit notes are excluded)")
    drop(s.quantity == 0, "zero quantity")
    if s.empty:
        rep.errors.append("no usable sales rows after cleaning; check the column mapping and date format")
        return None, rep

    # price / revenue
    have_price = s.unit_price.notna() & (s.unit_price > 0)
    derived = s._revenue.notna() & (s._revenue > 0) & ~have_price
    s.loc[derived, "unit_price"] = s.loc[derived, "_revenue"] / s.loc[derived, "quantity"]
    if derived.any():
        rep.assumptions.append(f"unit price derived from amount / quantity for {int(derived.sum()):,} rows")
    if s.order_id.isna().any():
        gen = pd.Series([f"L{i:08d}" for i in range(1, len(s) + 1)], index=s.index, dtype="string")
        s["order_id"] = s.order_id.fillna(gen)
    n = len(s)
    s = s.drop_duplicates("order_id")
    if len(s) < n:
        rep.dropped["duplicate order id"] = rep.dropped.get("duplicate order id", 0) + (n - len(s))
        rep.warnings.append("some rows shared an order/invoice id and were treated as duplicates; if the id repeats across "
                            "line items, remove the order-id mapping so line numbers are generated instead")
    s["quantity"] = s.quantity.round().astype(int)

    # ---------------- products
    ids = sorted(s.product_id.unique())
    prod = pd.DataFrame({"product_id": ids})
    if products_raw is not None:
        pm = products_map or suggest_mapping(list(products_raw.columns), PRODUCT_FIELDS)
        if _missing("products", pm):
            rep.warnings.append("products file ignored: no SKU/product id column found")
        else:
            p = pd.DataFrame({f: _pick(products_raw, pm, f) for f in PRODUCT_FIELDS if _pick(products_raw, pm, f) is not None})
            p["product_id"] = p.product_id.astype("string").str.strip()
            prod = prod.merge(p.drop_duplicates("product_id"), on="product_id", how="left")
            unknown = len(set(ids) - set(p.product_id))
            if unknown:
                rep.warnings.append(f"{unknown} SKUs in sales are missing from the products file; defaults used for them")
    med_price = s.groupby("product_id").unit_price.median()
    for col in ("product_name", "category", "lead_time_days", "unit_price", "unit_cost"):
        if col not in prod:
            prod[col] = np.nan
    prod["product_name"] = prod.product_name.astype("string").fillna(prod.product_id)
    prod["category"] = prod.category.astype("string").str.strip().fillna(d.category).str.title()
    prod["unit_price"] = to_number(prod.unit_price).fillna(prod.product_id.map(med_price))
    if prod.unit_price.isna().any() or (prod.unit_price <= 0).any():
        prod["unit_price"] = prod.unit_price.where(prod.unit_price > 0).fillna(1.0)
        rep.warnings.append("no price information for some SKUs: value/revenue metrics use 1.0 per unit for them "
                            "(quantity-based results are unaffected)")
    prod["unit_cost"] = to_number(prod.unit_cost)
    unknown_cost = prod.unit_cost.isna() | (prod.unit_cost <= 0)
    prod.loc[unknown_cost, "unit_cost"] = (prod.unit_price * d.cost_to_price_ratio).round(4)
    if unknown_cost.any():
        rep.assumptions.append(f"unit cost unknown for {int(unknown_cost.sum())} SKUs: assumed {d.cost_to_price_ratio:.0%} of price "
                               "(affects order values, EOQ and margins; provide costs for accuracy)")
    prod["unit_cost"] = np.minimum(prod.unit_cost, prod.unit_price * 0.999)         # keep price > cost invariant
    lt = to_number(prod.lead_time_days)
    if lt.isna().any():
        rep.assumptions.append(f"lead time unknown for {int(lt.isna().sum())} SKUs: assumed {d.lead_time_days} days")
    prod["lead_time_days"] = lt.fillna(d.lead_time_days).clip(lower=1).round().astype(int)
    prod = prod[["product_id", "product_name", "category", "unit_cost", "unit_price", "lead_time_days"]]
    # a sales row without its own price gets the product price
    price_map = prod.set_index("product_id").unit_price
    nop = ~(s.unit_price > 0)
    s.loc[nop, "unit_price"] = s.loc[nop, "product_id"].map(price_map)
    s["unit_price"] = s.unit_price.astype(float).round(4)
    s["revenue"] = (s.quantity * s.unit_price).round(2)

    # ---------------- warehouses
    wh_ids = sorted(s.warehouse_id.unique())
    wt = pd.DataFrame({"warehouse_id": wh_ids, "warehouse_name": wh_ids, "region": "n/a"})

    # ---------------- inventory (optional)
    inv = pd.DataFrame(columns=["warehouse_id", "product_id", "current_stock", "reorder_level"]).astype(
        {"warehouse_id": "string", "product_id": "string", "current_stock": "int64", "reorder_level": "int64"})
    if stock_raw is not None:
        sm = stock_map or suggest_mapping(list(stock_raw.columns), STOCK_FIELDS)
        if miss := _missing("stock", sm):
            rep.warnings.append(f"stock file ignored: missing column(s) {', '.join(miss)}")
        else:
            i = pd.DataFrame({"product_id": _pick(stock_raw, sm, "product_id").astype("string").str.strip(),
                              "current_stock": to_number(_pick(stock_raw, sm, "current_stock"))})
            w = _pick(stock_raw, sm, "warehouse_id")
            i["warehouse_id"] = w.astype("string").str.strip() if w is not None else (wh_ids[0] if len(wh_ids) == 1 else pd.NA)
            if w is None and len(wh_ids) > 1:
                rep.warnings.append("stock file has no warehouse column but sales has several locations: stock ignored")
            else:
                rl = _pick(stock_raw, sm, "reorder_level")
                i["reorder_level"] = to_number(rl) if rl is not None else np.nan
                bad = i.current_stock.isna() | (i.current_stock < 0) | i.warehouse_id.isna() | i.product_id.isna()
                if bad.any():
                    rep.dropped["invalid stock rows"] = int(bad.sum())
                i = i[~bad].drop_duplicates(["warehouse_id", "product_id"], keep="last")
                extra_wh = sorted(set(i.warehouse_id) - set(wh_ids))
                if extra_wh:
                    wt = pd.concat([wt, pd.DataFrame({"warehouse_id": extra_wh, "warehouse_name": extra_wh, "region": "n/a"})])
                extra_p = sorted(set(i.product_id) - set(prod.product_id))
                if extra_p:                                          # stocked but never sold: still needs a product row
                    medp = float(prod.unit_price.median())
                    prod = pd.concat([prod, pd.DataFrame({
                        "product_id": extra_p, "product_name": extra_p, "category": d.category,
                        "unit_cost": round(medp * d.cost_to_price_ratio, 4), "unit_price": medp,
                        "lead_time_days": d.lead_time_days})])
                    rep.warnings.append(f"{len(extra_p)} stocked SKUs never appear in sales (dead stock candidates); "
                                        "price/cost set to the median")
                i["current_stock"] = i.current_stock.round().astype(int)
                inv, rep.has_stock = i.copy(), True
                if inv.reorder_level.isna().any():
                    inv["reorder_level"] = inv.reorder_level.fillna(0)
                    rep.assumptions.append("reorder levels not (fully) provided: set to the recommended reorder point "
                                           "(so 'low stock' means 'below the model's reorder point')")
    if not rep.has_stock:
        rep.warnings.append("no stock file: sales analytics, ABC-XYZ and demand forecasts are available; reorder "
                            "recommendations, alerts and stock KPIs need current stock on hand")

    tables = {"warehouses": wt.reset_index(drop=True), "products": prod.reset_index(drop=True),
              "inventory": inv.reset_index(drop=True),
              "restocks": pd.DataFrame({"restock_date": pd.Series(dtype="datetime64[ns]"), "warehouse_id": pd.Series(dtype="string"),
                                        "product_id": pd.Series(dtype="string"), "quantity": pd.Series(dtype="int64")}),
              "sales": s[["order_id", "order_date", "warehouse_id", "product_id", "quantity", "unit_price", "revenue"]]
              .sort_values(["order_date", "order_id"]).reset_index(drop=True)}
    for name in ("order_id", "warehouse_id", "product_id"):
        tables["sales"][name] = tables["sales"][name].astype(str)
    for name in ("warehouse_id", "product_id"):
        tables["inventory"][name] = tables["inventory"][name].astype(str)
    for name in ("warehouse_id", "warehouse_name", "region"):
        tables["warehouses"][name] = tables["warehouses"][name].astype(str)
    tables["products"] = tables["products"].astype({"product_id": str, "product_name": str, "category": str})

    if rep.has_stock:                       # recommended reorder point where the user gave none
        blank = tables["inventory"].reorder_level == 0
        if blank.any():
            repl = analytics.replenishment(tables["sales"], tables["inventory"], tables["products"], tables["warehouses"],
                                           d.service_level_z, d.ordering_cost, d.holding_rate)
            rop = repl.set_index(["warehouse_id", "product_id"]).reorder_point
            keys = pd.MultiIndex.from_frame(tables["inventory"][["warehouse_id", "product_id"]])
            tables["inventory"].loc[blank.to_numpy(), "reorder_level"] = (
                rop.reindex(keys[blank.to_numpy()]).fillna(0).astype(int).to_numpy())

    tables["inventory"] = tables["inventory"].astype({"current_stock": int, "reorder_level": int})
    rep.rows_out = len(tables["sales"])
    rep.date_min = str(tables["sales"].order_date.min().date())
    rep.date_max = str(tables["sales"].order_date.max().date())
    span = (tables["sales"].order_date.max() - tables["sales"].order_date.min()).days + 1
    if span < 60:
        rep.warnings.append(f"only {span} days of history: forecasts and variability estimates will be weak (60+ days recommended, "
                            "365+ for seasonality)")
    problems = validate(tables, strict=False)
    rep.errors.extend(problems)
    return (tables if rep.ok else None), rep
