"""Advanced analytics: ABC-XYZ classification, demand forecast + backtest, safety stock / reorder point / EOQ
replenishment, and warehouse-to-warehouse transfer suggestions."""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------------------------- ABC / XYZ

def _monthly_daily_rate(sales: pd.DataFrame) -> pd.DataFrame:
    """Average units/day per product for each FULL calendar month (partial first/last months and month length
    would otherwise inflate the variability). Falls back to all months if fewer than 3 are complete."""
    lo, hi = sales.order_date.min(), sales.order_date.max()
    per = sales.groupby(["product_id", sales.order_date.dt.to_period("M")]).quantity.sum().unstack(fill_value=0)
    full = [m for m in per.columns if m.start_time >= lo.normalize() and m.end_time.normalize() <= hi.normalize()]
    keep = full if len(full) >= 3 else list(per.columns)
    return per[keep] / np.array([m.days_in_month for m in keep])


def abc_xyz(sales: pd.DataFrame, products: pd.DataFrame, a_cut: float = 0.80, b_cut: float = 0.95,
            x_cv: float = 0.25, y_cv: float = 0.50) -> pd.DataFrame:
    """ABC = value class by cumulative revenue share (A: top 80%, B: next 15%, C: rest).
    XYZ = demand variability class from the coefficient of variation of MONTHLY units
    (X: stable CV <= 0.25, Y: 0.25-0.5, Z: erratic)."""
    rev = sales.groupby("product_id").revenue.sum().sort_values(ascending=False)
    share = rev / rev.sum()
    cum_before = share.cumsum() - share                     # a product is A if it starts inside the top-80% band
    abc = np.where(cum_before < a_cut, "A", np.where(cum_before < b_cut, "B", "C"))
    monthly = _monthly_daily_rate(sales)
    cv = (monthly.std(axis=1, ddof=0) / monthly.mean(axis=1)).reindex(rev.index)
    xyz = np.where(cv <= x_cv, "X", np.where(cv <= y_cv, "Y", "Z"))
    out = pd.DataFrame({"product_id": rev.index, "revenue": rev.to_numpy(), "revenue_share_pct": (share * 100).round(2).to_numpy(),
                        "cum_share_pct": (share.cumsum() * 100).round(2).to_numpy(), "abc": abc,
                        "demand_cv": cv.round(3).to_numpy(), "xyz": xyz})
    out["segment"] = out.abc + out.xyz
    return out.merge(products[["product_id", "product_name", "category"]], on="product_id").reset_index(drop=True)


# ---------------------------------------------------------------------------------------------- forecasting

def daily_matrix(sales: pd.DataFrame) -> pd.DataFrame:
    """Units per day (rows, full calendar) x product (columns), zero-filled."""
    d = sales.groupby(["order_date", "product_id"]).quantity.sum().unstack(fill_value=0)
    return d.reindex(pd.date_range(d.index.min(), d.index.max()), fill_value=0)


def _forecast_at(mat: pd.DataFrame, end: int, horizon: int, seasonal: bool = True, level_days: int = 28,
                 groups: pd.Series | None = None) -> pd.DataFrame:
    """Forecast `horizon` days after row `end` (exclusive) using only history before it.
    forecast = recent level x weekday profile x year-over-year seasonal ratio (when >= 1 year of history).
    Weekday profile and yoy ratio are estimated per group (category) when `groups` is given: far less noisy for
    slow sellers than per-product estimates. The level itself stays per product."""
    hist = mat.iloc[:end]
    level = hist.iloc[-level_days:].mean()
    last = hist.iloc[-56:]
    prof_src = last.groupby(last.index.dayofweek).mean()
    dow = _pooled_dow(prof_src, groups) if groups is not None else prof_src
    dow = (dow / dow.mean().replace(0, np.nan)).fillna(1.0)                          # weekday x product
    ratio = pd.Series(1.0, index=mat.columns)
    if seasonal and end >= 365 + level_days:
        ly_future = mat.iloc[end - 365:end - 365 + horizon].mean()
        ly_level = mat.iloc[end - 365 - level_days:end - 365].mean()
        if groups is not None:
            g = groups.reindex(mat.columns).to_numpy()
            ly_future, ly_level = ly_future.groupby(g).transform("sum"), ly_level.groupby(g).transform("sum")
        ratio = (ly_future / ly_level.replace(0, np.nan)).clip(0.6, 1.6).fillna(1.0)
    future = pd.date_range(hist.index[-1] + pd.Timedelta(days=1), periods=horizon)
    base = (level * ratio) if seasonal else level
    prof = dow.reindex(future.dayofweek).to_numpy() if seasonal else np.ones((horizon, 1))
    return pd.DataFrame(prof * base.to_numpy()[None, :], index=future, columns=mat.columns)


def _pooled_dow(prof_src: pd.DataFrame, groups: pd.Series) -> pd.DataFrame:
    """Weekday profile shape pooled per group, scaled back to each product's own level."""
    g = groups.reindex(prof_src.columns).to_numpy()
    shape = prof_src / prof_src.mean().replace(0, np.nan)                            # per product, mean 1
    pooled = shape.T.groupby(g).transform("mean").T
    return pooled.fillna(1.0)


def forecast(sales: pd.DataFrame, horizon: int = 30, groups: pd.Series | None = None) -> pd.DataFrame:
    """Next-`horizon`-days demand forecast per product (rows: dates, columns: products).
    `groups`: optional Series product_id -> category used to pool seasonality estimates."""
    mat = daily_matrix(sales)
    return _forecast_at(mat, len(mat), horizon, groups=groups)


def backtest(sales: pd.DataFrame, horizon: int = 30, groups: pd.Series | None = None) -> dict:
    """Hold out the last `horizon` days. Compares the model with a flat naive baseline (recent average).
    WAPE = sum|actual - forecast| / sum(actual): lower is better. Reported daily (noisy, dominated by Poisson-like
    randomness of small counts) and weekly (the planning granularity)."""
    mat = daily_matrix(sales)
    end = len(mat) - horizon
    actual = mat.iloc[end:]
    model = _forecast_at(mat, end, horizon, groups=groups)
    naive = _forecast_at(mat, end, horizon, seasonal=False)

    def wape(a: pd.DataFrame, f: pd.DataFrame) -> float:
        return float((a.to_numpy() - f.to_numpy()).__abs__().sum() / a.to_numpy().sum())

    weekly = lambda x: x.resample("7D").sum()  # noqa: E731
    per_product = pd.DataFrame({
        "wape_model": (actual - model.to_numpy()).abs().sum() / actual.sum().replace(0, np.nan),
        "wape_naive": (actual - naive.to_numpy()).abs().sum() / actual.sum().replace(0, np.nan)})
    return {"horizon_days": horizon,
            "wape_model": round(wape(actual, model), 4), "wape_naive": round(wape(actual, naive), 4),
            "wape_weekly_model": round(wape(weekly(actual), weekly(model)), 4),
            "wape_weekly_naive": round(wape(weekly(actual), weekly(naive)), 4),
            "bias_model": round(float(model.to_numpy().sum() / actual.to_numpy().sum() - 1), 4),
            "per_product": per_product.reset_index(names="product_id")}


# ---------------------------------------------------------------------------------------------- replenishment

def demand_stats(sales: pd.DataFrame) -> pd.DataFrame:
    """Mean and std of DAILY units per warehouse x product over the whole window (zero days included)."""
    n_days = (sales.order_date.max() - sales.order_date.min()).days + 1
    daily = sales.groupby(["warehouse_id", "product_id", "order_date"]).quantity.sum()
    g = daily.groupby(level=[0, 1]).agg(total="sum", sq=lambda s: float((s.astype(float) ** 2).sum()))
    g["mean_daily"] = g.total / n_days
    g["std_daily"] = np.sqrt((g.sq / n_days - g.mean_daily ** 2).clip(lower=0))
    return g[["mean_daily", "std_daily"]].reset_index()


def replenishment(sales: pd.DataFrame, inventory: pd.DataFrame, products: pd.DataFrame, warehouses: pd.DataFrame,
                  z: float = 1.65, ordering_cost: float = 50.0, holding_rate: float = 0.20) -> pd.DataFrame:
    """Recommended policy per warehouse x product.

    safety stock  SS  = z * sigma_daily * sqrt(lead_time)
    reorder point ROP = mean_daily * lead_time + SS
    EOQ           = sqrt(2 * annual_demand * ordering_cost / (holding_rate * unit_cost))
    suggested order (when stock <= ROP) = ROP + EOQ - stock   (order-up-to level = ROP + EOQ)
    """
    r = inventory.merge(demand_stats(sales), on=["warehouse_id", "product_id"], how="left")
    r = r.merge(products[["product_id", "product_name", "category", "unit_cost", "lead_time_days"]], on="product_id")
    r = r.merge(warehouses[["warehouse_id", "warehouse_name"]], on="warehouse_id")
    r[["mean_daily", "std_daily"]] = r[["mean_daily", "std_daily"]].fillna(0.0)
    r["safety_stock"] = np.ceil(z * r.std_daily * np.sqrt(r.lead_time_days))
    r["reorder_point"] = np.ceil(r.mean_daily * r.lead_time_days + r.safety_stock)
    holding = (holding_rate * r.unit_cost).where(lambda s: s > 0)
    r["eoq"] = np.ceil(np.sqrt(2 * r.mean_daily * 365 * ordering_cost / holding)).fillna(0)
    r["order_up_to"] = r.reorder_point + r.eoq
    r["below_rop"] = r.current_stock <= r.reorder_point
    r["suggested_order_qty"] = np.where(r.below_rop, (r.order_up_to - r.current_stock).clip(lower=0), 0).astype(int)
    r["suggested_order_cost"] = (r.suggested_order_qty * r.unit_cost).round(2)
    r["policy_gap"] = r.reorder_point - r.reorder_level          # >0: current reorder level is too low
    r["days_of_cover"] = (r.current_stock / r.mean_daily.where(r.mean_daily > 0)).round(1)
    cols = ["warehouse_id", "warehouse_name", "product_id", "product_name", "category", "current_stock", "reorder_level",
            "mean_daily", "std_daily", "lead_time_days", "safety_stock", "reorder_point", "eoq", "order_up_to",
            "below_rop", "suggested_order_qty", "suggested_order_cost", "policy_gap", "days_of_cover"]
    return r[cols].round({"mean_daily": 3, "std_daily": 3})


def transfer_suggestions(repl: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """Move stock from warehouses holding more than ROP + EOQ to warehouses at/below ROP for the same product.
    Greedy per product: biggest deficit first, biggest surplus first."""
    df = repl[["warehouse_id", "product_id", "current_stock", "reorder_point", "eoq"]].copy()
    df["deficit"] = (df.reorder_point - df.current_stock).clip(lower=0)
    df["surplus"] = (df.current_stock - (df.reorder_point + df.eoq)).clip(lower=0)
    rows = []
    for pid, g in df[(df.deficit > 0) | (df.surplus > 0)].groupby("product_id"):
        need = g[g.deficit > 0].sort_values("deficit", ascending=False)
        give = g[g.surplus > 0].sort_values("surplus", ascending=False)
        avail = dict(zip(give.warehouse_id, give.surplus, strict=True))
        for _, n in need.iterrows():
            gap = int(n.deficit)
            for wh in list(avail):
                if gap <= 0:
                    break
                qty = int(min(avail[wh], gap))
                if qty > 0:
                    rows.append((pid, wh, n.warehouse_id, qty))
                    avail[wh] -= qty
                    gap -= qty
    out = pd.DataFrame(rows, columns=["product_id", "from_warehouse", "to_warehouse", "quantity"])
    out = out.merge(products[["product_id", "product_name", "unit_cost"]], on="product_id")
    out["value_at_cost"] = (out.quantity * out.unit_cost).round(2)
    return out.drop(columns="unit_cost").sort_values("value_at_cost", ascending=False).reset_index(drop=True)
