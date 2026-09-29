"""Interactive Inventory & Sales dashboard.  Run:  streamlit run app/streamlit_app.py"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from invsales import analytics, kpis  # noqa: E402
from invsales.config import get_settings  # noqa: E402
from invsales.repository import load_data  # noqa: E402

st.set_page_config(page_title="Inventory & Sales Analytics", page_icon=":package:", layout="wide")
SETTINGS = get_settings()


@st.cache_data(ttl=600, show_spinner="Loading data...")
def get_data():
    return load_data(SETTINGS)


@st.cache_data(show_spinner="Computing analytics...")
def get_analytics(_t, source: str):
    """Heavy model outputs computed once on the full history (cache keyed by data source label)."""
    s, inv, prod, wh = _t["sales"], _t["inventory"], _t["products"], _t["warehouses"]
    groups = prod.set_index("product_id").category
    repl = analytics.replenishment(s, inv, prod, wh, SETTINGS.service_level_z, SETTINGS.ordering_cost, SETTINGS.holding_rate)
    return {
        "abc": analytics.abc_xyz(s, prod),
        "repl": repl,
        "transfers": analytics.transfer_suggestions(repl, prod),
        "backtest": analytics.backtest(s, 30, groups),
        "forecast": analytics.forecast(s, 30, groups),
        "history": analytics.daily_matrix(s),
    }


tables, source = get_data()
sales, products, inventory = tables["sales"], tables["products"], tables["inventory"]
warehouses, restocks = tables["warehouses"], tables["restocks"]
A = get_analytics(tables, source)

# ---- sidebar filters ---------------------------------------------------------
st.sidebar.header("Filters")
wh_names = dict(zip(warehouses.warehouse_id, warehouses.warehouse_name, strict=True))
sel_wh = st.sidebar.multiselect("Warehouse", list(wh_names), default=list(wh_names), format_func=wh_names.get)
cats = sorted(products.category.unique())
sel_cats = st.sidebar.multiselect("Category", cats, default=cats)
dmin, dmax = sales.order_date.min().date(), sales.order_date.max().date()
date_range = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
if len(date_range) != 2:
    st.info("Pick both a start and an end date.")
    st.stop()
st.sidebar.caption(f"Data source: {source}  \n{len(sales):,} order lines - {len(products)} products - {len(warehouses)} warehouses")

p_f = products[products.category.isin(sel_cats)]
inv_f = inventory[inventory.warehouse_id.isin(sel_wh) & inventory.product_id.isin(p_f.product_id)]
s_f = sales[sales.warehouse_id.isin(sel_wh) & sales.product_id.isin(p_f.product_id)
            & sales.order_date.between(pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]))]
if s_f.empty or inv_f.empty:
    st.warning("No data matches the current filters.")
    st.stop()

st.title("Inventory & Sales Analytics")
h = kpis.headline(s_f, inv_f)
repl_f = A["repl"][A["repl"].warehouse_id.isin(sel_wh) & A["repl"].product_id.isin(p_f.product_id)]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Sales", f"${h['total_sales']:,.0f}")
c2.metric("Units Sold", f"{h['units_sold']:,}")
c3.metric("Stock (units)", f"{h['total_stock']:,}")
c4.metric("Low-Stock Items", h["low_stock_items"], help="warehouse x product pairs with stock <= reorder level")
c5.metric("Suggested PO value", f"${repl_f.suggested_order_cost.sum():,.0f}", help="cost of the replenishment orders recommended in the Replenishment tab")

tab_over, tab_move, tab_abc, tab_fc, tab_repl, tab_tr, tab_alert = st.tabs(
    ["Overview", "Fast vs slow", "ABC-XYZ", "Forecast", "Replenishment", "Transfers", "Reorder alerts"])

with tab_over:
    left, right = st.columns(2)
    m = kpis.monthly_sales(s_f)
    left.plotly_chart(px.line(m, x="month", y="revenue", markers=True, title="Monthly sales"), width="stretch")
    cat = kpis.category_summary(s_f, p_f)
    right.plotly_chart(px.bar(cat, x="revenue", y="category", orientation="h", title="Revenue by category",
                              hover_data=["margin_pct", "revenue_share_pct"]), width="stretch")
    ws = kpis.warehouse_summary(s_f, inv_f, warehouses[warehouses.warehouse_id.isin(sel_wh)])
    a, b = st.columns(2)
    a.plotly_chart(px.bar(ws, x="warehouse_name", y="revenue", title="Revenue by warehouse", text_auto=".2s"), width="stretch")
    b.dataframe(ws[["warehouse_name", "region", "revenue", "units", "total_stock", "skus", "low_stock_items"]].style.format(
        {"revenue": "${:,.0f}", "units": "{:,.0f}", "total_stock": "{:,.0f}", "skus": "{:.0f}", "low_stock_items": "{:.0f}"}),
        width="stretch", hide_index=True)
    top = (s_f.merge(products[["product_id", "product_name"]], on="product_id").groupby("product_name")
           .agg(units=("quantity", "sum"), revenue=("revenue", "sum")).nlargest(10, "revenue").reset_index())
    st.plotly_chart(px.bar(top, x="revenue", y="product_name", orientation="h", title="Top 10 products by revenue")
                    .update_yaxes(autorange="reversed"), width="stretch")

with tab_move:
    level = st.radio("Level", ["Product (all selected warehouses)", "Warehouse x product"], horizontal=True)
    lvl = "product" if level.startswith("Product") else "warehouse_product"
    turn = kpis.stock_turnover(s_f, inv_f, restocks[restocks.warehouse_id.isin(sel_wh)], products, level=lvl)
    if lvl == "warehouse_product":
        turn["product_name"] = turn.product_name + " @ " + turn.warehouse_id.map(wh_names)
    n = st.slider("Items per chart", 5, 15, 10)
    fast, slow = turn.nlargest(n, "stock_turnover"), turn.nsmallest(n, "stock_turnover")
    a, b = st.columns(2)
    a.plotly_chart(px.bar(fast, x="stock_turnover", y="product_name", orientation="h", title="Fastest (highest turnover)",
                          color_discrete_sequence=["#27AE60"]).update_yaxes(autorange="reversed"), width="stretch")
    b.plotly_chart(px.bar(slow, x="stock_turnover", y="product_name", orientation="h", title="Slowest (lowest turnover)",
                          color_discrete_sequence=["#C0392B"]).update_yaxes(autorange="reversed"), width="stretch")
    st.caption("Turnover = units sold / average stock; average stock = (opening + current) / 2. Slow movers tie up cash in stock.")

with tab_abc:
    abc = A["abc"][A["abc"].product_id.isin(p_f.product_id)]
    seg = abc.groupby("segment").agg(products=("product_id", "count"), revenue=("revenue", "sum")).reset_index()
    a, b = st.columns([1, 2])
    a.dataframe(seg.style.format({"revenue": "${:,.0f}"}), hide_index=True, width="stretch")
    b.plotly_chart(px.scatter(abc, x="demand_cv", y="revenue", color="abc", hover_name="product_name", log_y=True,
                              title="Value (revenue) vs demand variability (CV)"), width="stretch")
    st.caption("A/B/C = value class by cumulative revenue (80% / 15% / 5%). X/Y/Z = demand variability of monthly units "
               "(CV <= 0.25 stable, <= 0.5 moderate, above erratic). AX items deserve tight control; CZ items can be made to order.")
    st.dataframe(abc[["product_name", "category", "revenue", "revenue_share_pct", "abc", "demand_cv", "xyz", "segment"]],
                 hide_index=True, width="stretch")

with tab_fc:
    bt = A["backtest"]
    st.markdown(f"**Model check (holdout of the last {bt['horizon_days']} days):** weekly error (WAPE) "
                f"**{bt['wape_weekly_model']:.1%}** vs {bt['wape_weekly_naive']:.1%} for a flat recent-average baseline "
                f"(daily: {bt['wape_model']:.1%} vs {bt['wape_naive']:.1%}); bias {bt['bias_model']:+.1%}.")
    prod_pick = st.selectbox("Product", p_f.sort_values("product_name").product_id, format_func=dict(
        zip(products.product_id, products.product_name, strict=True)).get)
    hist = A["history"][prod_pick].iloc[-120:]
    fc = A["forecast"][prod_pick]
    fig = go.Figure()
    fig.add_scatter(x=hist.index, y=hist.rolling(7).mean(), name="Actual (7-day avg)")
    fig.add_scatter(x=fc.index, y=fc.rolling(7, min_periods=1).mean(), name="Forecast (7-day avg)", line={"dash": "dash"})
    fig.update_layout(title="Daily units, all warehouses (smoothed)", yaxis_title="units/day")
    st.plotly_chart(fig, width="stretch")
    st.metric("Forecast: next 30 days", f"{fc.sum():,.0f} units", delta=f"{fc.sum() / max(hist.iloc[-30:].sum(), 1) - 1:+.1%} vs last 30 days")
    st.caption("Method: recent 28-day level x weekday profile x year-over-year seasonal ratio, with the profile and ratio pooled per category. "
               "It is a transparent baseline, not a tuned ML model.")

with tab_repl:
    st.markdown("**Recommended policy per warehouse x product** - safety stock = z × σ(daily demand) × √lead time; "
                "reorder point = mean demand × lead time + safety stock; order quantity = EOQ. "
                f"(service z={SETTINGS.service_level_z}, ordering cost ${SETTINGS.ordering_cost:.0f}, holding {SETTINGS.holding_rate:.0%}/yr)")
    only = st.checkbox("Only items that need an order now", value=True)
    view = repl_f[repl_f.below_rop] if only else repl_f
    st.metric("Orders to place", f"{int((view.suggested_order_qty > 0).sum())}", delta=f"${view.suggested_order_cost.sum():,.0f} at cost", delta_color="off")
    cols = ["warehouse_name", "product_name", "current_stock", "reorder_level", "reorder_point", "safety_stock", "eoq",
            "suggested_order_qty", "suggested_order_cost", "days_of_cover", "lead_time_days"]
    st.dataframe(view.sort_values("suggested_order_cost", ascending=False)[cols], hide_index=True, width="stretch")
    st.download_button("Download purchase suggestions (CSV)", view[cols].to_csv(index=False), "purchase_suggestions.csv", "text/csv")
    gap = (repl_f.policy_gap > 0).mean()
    st.caption(f"{gap:.0%} of items have a current reorder level below the recommended reorder point (policy gap).")

with tab_tr:
    tr = A["transfers"]
    tr = tr[tr.from_warehouse.isin(sel_wh) & tr.to_warehouse.isin(sel_wh) & tr.product_id.isin(p_f.product_id)].copy()
    tr["from_warehouse"] = tr.from_warehouse.map(wh_names)
    tr["to_warehouse"] = tr.to_warehouse.map(wh_names)
    st.markdown("**Rebalance before buying:** move surplus (stock above reorder point + EOQ) to warehouses that are short on the same product.")
    st.metric("Transfers", f"{len(tr)}", delta=f"${tr.value_at_cost.sum():,.0f} of stock moved instead of purchased", delta_color="off")
    st.dataframe(tr, hide_index=True, width="stretch")

with tab_alert:
    alerts = kpis.reorder_alerts(s_f, inv_f, products, warehouses)
    st.subheader(f"{len(alerts)} item(s) at or below reorder level")
    if alerts.empty:
        st.success("Nothing to reorder.")
    else:
        show = alerts[["warehouse_name", "product_name", "category", "current_stock", "reorder_level", "shortfall",
                       "daily_demand", "days_of_stock_left", "lead_time_days", "severity"]]
        colors = {"Stockout": "background-color:#F8CBAD", "Critical": "background-color:#FCE4D6", "Low": ""}
        st.dataframe(show.style.apply(lambda r: [colors[r.severity]] * len(r), axis=1).format(
            {"daily_demand": "{:.2f}", "days_of_stock_left": "{:.1f}"}), width="stretch", hide_index=True)
        st.download_button("Download reorder list (CSV)", show.to_csv(index=False), "reorder_alerts.csv", "text/csv")
