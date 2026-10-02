"""Inventory & Sales decision-support dashboard.  Run:  streamlit run app/streamlit_app.py

Demo data (simulated) or YOUR data: upload a sales export (+ optional stock / product files) and get replenishment
recommendations, stockout risk, excess/dead stock, ABC-XYZ, forecasts, transfers and an Excel action pack."""
import hashlib
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from invsales import analytics, kpis  # noqa: E402
from invsales.config import get_settings  # noqa: E402
from invsales.importer import (  # noqa: E402
    PRODUCT_FIELDS,
    SALES_FIELDS,
    STOCK_FIELDS,
    ImportDefaults,
    import_data,
    suggest_mapping,
)
from invsales.reports import action_pack  # noqa: E402
from invsales.repository import load_data  # noqa: E402
from invsales.templates import FILES as TEMPLATES  # noqa: E402

st.set_page_config(page_title="Inventory Sales Dashboard", page_icon=":package:", layout="wide")
SETTINGS = get_settings()
NOTE_DEMO = "Demo data is simulated. Results describe the simulation, not a real business."


@st.cache_data(ttl=600, show_spinner="Loading demo data...")
def get_demo():
    return load_data(SETTINGS)


def data_key(t: dict) -> str:
    h = hashlib.md5(pd.util.hash_pandas_object(t["sales"], index=False).values.tobytes())
    h.update(pd.util.hash_pandas_object(t["inventory"], index=False).values.tobytes())
    return h.hexdigest()


@st.cache_data(show_spinner="Computing analytics...", max_entries=8)
def compute(_t, key: str, z: float, ordering_cost: float, holding_rate: float, delay: float, has_stock: bool):
    """All model outputs, cached per (data, planning assumptions)."""
    s, inv, prod, wh = _t["sales"], _t["inventory"], _t["products"], _t["warehouses"]
    groups = prod.set_index("product_id").category
    out = {"abc": analytics.abc_xyz(s, prod), "backtest": analytics.backtest(s, 30, groups) if s.order_date.nunique() > 90 else None,
           "forecast": analytics.forecast(s, 30, groups), "history": analytics.daily_matrix(s)}
    if has_stock:
        repl = analytics.replenishment(s, inv, prod, wh, z, ordering_cost, holding_rate, delay)
        out.update(repl=repl, transfers=analytics.transfer_suggestions(repl, prod), health=analytics.inventory_health(s, repl))
    return out


@st.cache_data(show_spinner=False, max_entries=16)
def delay_curve(_t, key: str, z: float, ordering_cost: float, holding_rate: float):
    rows = []
    for d in (0, 3, 7, 14, 21):
        r = analytics.replenishment(_t["sales"], _t["inventory"], _t["products"], _t["warehouses"], z, ordering_cost, holding_rate, d)
        rows.append({"supplier_delay_days": d, "purchase_order_value": r.suggested_order_cost.sum(),
                     "items_at_risk": int((r.stockout_risk_pct >= 50).sum())})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------ sidebar: data + assumptions
st.sidebar.title("Inventory decisions")
mode = st.sidebar.radio("Data", ["Demo (simulated)", "My data (upload)"])
with st.sidebar.expander("Planning assumptions", expanded=False):
    sl = st.slider("Service level", 0.80, 0.995, 0.95, 0.005, format="%.3f", help="Probability of not stocking out during a lead time")
    z = NormalDist().inv_cdf(sl)
    ordering_cost = st.number_input("Cost per purchase order", 0.0, 100000.0, float(SETTINGS.ordering_cost), 5.0)
    holding_rate = st.slider("Holding cost per year (% of unit cost)", 0.05, 0.60, float(SETTINGS.holding_rate), 0.01)
    delay = st.slider("What-if: suppliers are N days slower", 0, 30, 0)


def upload_wizard():
    """Collect files, map columns, import. Returns (tables, report) from session state when available."""
    st.info("Your files are processed in memory for this session only and are not stored. This public demo is not a place for confidential "
            "data: for private data run the app yourself (`docker compose up`, see README).", icon=":material/lock:")
    c1, c2, c3 = st.columns(3)
    sales_f = c1.file_uploader("1. Sales export (required)", type=["csv", "xlsx"], help="One row per sale line: date, item/SKU, quantity "
                               "(+ optional location, price or amount)")
    stock_f = c2.file_uploader("2. Current stock on hand (recommended)", type=["csv", "xlsx"], help="Needed for reorder recommendations")
    prod_f = c3.file_uploader("3. Product master (optional)", type=["csv", "xlsx"], help="Names, categories, unit cost, lead time")
    with st.expander("Templates (download, fill in, upload)"):
        cols = st.columns(len(TEMPLATES))
        for col, (name, text) in zip(cols, TEMPLATES.items(), strict=True):
            col.download_button(name, text, name, "text/csv")
    if sales_f is None:
        st.caption("Upload at least the sales export. Column names are detected automatically and can be corrected below.")
        return

    def read(f):
        return pd.read_excel(f, dtype=object) if f.name.lower().endswith(".xlsx") else pd.read_csv(f, dtype=object, encoding_errors="replace")

    sales_raw = read(sales_f)
    stock_raw = read(stock_f) if stock_f else None
    prod_raw = read(prod_f) if prod_f else None
    st.caption(f"Sales file: {len(sales_raw):,} rows, columns: {', '.join(map(str, sales_raw.columns))}")

    def mapping_ui(label, df, fields, required):
        sug = suggest_mapping(list(df.columns), fields)
        opts = ["(none)", *map(str, df.columns)]
        m = {}
        cols = st.columns(min(len(fields), 4))
        for i, f in enumerate(fields):
            idx = opts.index(str(sug[f])) if sug[f] is not None and str(sug[f]) in opts else 0
            pick = cols[i % len(cols)].selectbox(f"{label}: {f}" + (" *" if f in required else ""), opts, index=idx, key=f"{label}{f}")
            m[f] = None if pick == "(none)" else pick
        return m

    st.markdown("**Check the column mapping** (* = required)")
    sm = mapping_ui("sales", sales_raw, SALES_FIELDS, ["order_date", "product_id", "quantity"])
    stm = mapping_ui("stock", stock_raw, STOCK_FIELDS, ["product_id", "current_stock"]) if stock_raw is not None else None
    pm = mapping_ui("products", prod_raw, PRODUCT_FIELDS, ["product_id"]) if prod_raw is not None else None
    a, b, c = st.columns(3)
    lead = a.number_input("Default lead time (days)", 1, 180, 7)
    dayfirst = b.radio("Ambiguous dates (e.g. 03/04/2025)", ["DD/MM", "MM/DD"], horizontal=True) == "DD/MM"
    ratio = c.slider("Unit cost if unknown (% of price)", 30, 95, 75) / 100
    if st.button("Analyze my data", type="primary"):
        defaults = ImportDefaults(lead_time_days=int(lead), dayfirst=dayfirst, cost_to_price_ratio=ratio, service_level_z=z,
                                  ordering_cost=ordering_cost, holding_rate=holding_rate)
        with st.spinner("Importing and validating..."):
            tables, rep = import_data(sales_raw, sm, stock_raw=stock_raw, stock_map=stm, products_raw=prod_raw, products_map=pm,
                                      defaults=defaults)
        st.session_state["user_report"] = rep
        st.session_state["user_tables"] = tables
        st.session_state["user_key"] = data_key(tables) if tables else None


def show_report(rep):
    with st.expander("Import report: what was cleaned, dropped and assumed", expanded=not rep.ok):
        st.write(f"{rep.rows_in:,} rows read, {rep.rows_out:,} used ({rep.date_min} to {rep.date_max})")
        if rep.dropped:
            st.write("Dropped rows:", ", ".join(f"{v:,} {k}" for k, v in rep.dropped.items()))
        for e in rep.errors:
            st.error(e)
        for w in rep.warnings:
            st.warning(w)
        for a in rep.assumptions:
            st.caption(f"Assumption: {a}")


if mode.startswith("Demo"):
    tables, source = get_demo()
    key, has_stock, assumptions = data_key(tables) + "demo", True, [NOTE_DEMO]
    st.sidebar.caption(f"Data source: {source}")
else:
    with st.expander("Your data files and column mapping", expanded="user_report" not in st.session_state):
        upload_wizard()
    rep = st.session_state.get("user_report")
    if rep is None:
        st.stop()
    show_report(rep)
    tables = st.session_state.get("user_tables")
    if tables is None:
        st.stop()
    key, has_stock = st.session_state["user_key"], rep.has_stock
    assumptions = [*rep.assumptions, *rep.warnings]
    st.sidebar.caption(f"Your data: {len(tables['sales']):,} rows, {tables['products'].shape[0]} SKUs, {tables['warehouses'].shape[0]} locations")

sales, products, inventory = tables["sales"], tables["products"], tables["inventory"]
warehouses, restocks = tables["warehouses"], tables["restocks"]
A = compute(tables, key, z, ordering_cost, holding_rate, float(delay), has_stock)
assumptions = [*assumptions, f"Service level {sl:.1%} (z={z:.2f}), ordering cost {ordering_cost:,.0f}/order, holding {holding_rate:.0%}/yr"
               + (f", suppliers assumed {delay} days slower" if delay else "")]

# ---- filters -------------------------------------------------------------------------------------------------------------
st.sidebar.header("Filters")
wh_names = dict(zip(warehouses.warehouse_id, warehouses.warehouse_name, strict=True))
sel_wh = st.sidebar.multiselect("Warehouse / location", list(wh_names), default=list(wh_names), format_func=wh_names.get)
cats = sorted(products.category.unique())
sel_cats = st.sidebar.multiselect("Category", cats, default=cats)
dmin, dmax = sales.order_date.min().date(), sales.order_date.max().date()
date_range = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
if len(date_range) != 2:
    st.info("Pick both a start and an end date.")
    st.stop()

p_f = products[products.category.isin(sel_cats)]
inv_f = inventory[inventory.warehouse_id.isin(sel_wh) & inventory.product_id.isin(p_f.product_id)]
s_f = sales[sales.warehouse_id.isin(sel_wh) & sales.product_id.isin(p_f.product_id)
            & sales.order_date.between(pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]))]
if s_f.empty:
    st.warning("No sales match the current filters.")
    st.stop()

st.title("Inventory Sales Dashboard")
st.caption(f"{len(sales):,} sales lines - {len(products)} SKUs - {len(warehouses)} locations - {dmin} to {dmax}")
if has_stock:
    repl_f = A["repl"][A["repl"].warehouse_id.isin(sel_wh) & A["repl"].product_id.isin(p_f.product_id)]
    h = kpis.headline(s_f, inv_f)
    health = analytics.inventory_health(s_f, repl_f) if len(repl_f) else A["health"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Sales", f"{h['total_sales']:,.0f}")
    c2.metric("Units Sold", f"{h['units_sold']:,}")
    c3.metric("Items to reorder now", int(repl_f.below_rop.sum()), help="warehouse x SKU pairs at/below the recommended reorder point")
    c4.metric("Suggested PO value", f"{health['suggested_po_value']:,.0f}", help="cost of the recommended orders")
    c5.metric("Excess stock", f"{health['excess_value']:,.0f}", delta=f"{health['excess_pct']}% of stock value", delta_color="off")
    pack = action_pack(repl=repl_f, health=health, abc=A["abc"], transfers=A["transfers"], assumptions=assumptions)
    st.sidebar.download_button("Download weekly action pack (Excel)", pack, "inventory_action_pack.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
else:
    h = {"total_sales": float(s_f.revenue.sum()), "units_sold": int(s_f.quantity.sum())}
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Sales", f"{h['total_sales']:,.0f}")
    c2.metric("Units Sold", f"{h['units_sold']:,}")
    c3.metric("SKUs sold", s_f.product_id.nunique())
    st.info("No stock file was provided, so reorder recommendations, alerts and stock KPIs are hidden. Upload current stock on hand to enable them.")

names = ["Overview", "ABC-XYZ", "Forecast"] + (["Reorder plan", "Cash & risk", "What-if", "Transfers", "Fast vs slow", "Alerts"] if has_stock else [])
tabs = dict(zip(names, st.tabs(names), strict=True))
pname = dict(zip(products.product_id, products.product_name, strict=True))

with tabs["Overview"]:
    left, right = st.columns(2)
    m = kpis.monthly_sales(s_f)
    left.plotly_chart(px.line(m, x="month", y="revenue", markers=True, title="Monthly sales"), width="stretch")
    cat = kpis.category_summary(s_f, p_f)
    right.plotly_chart(px.bar(cat, x="revenue", y="category", orientation="h", title="Revenue by category",
                              hover_data=["margin_pct", "revenue_share_pct"]), width="stretch")
    ws = kpis.warehouse_summary(s_f, inv_f, warehouses[warehouses.warehouse_id.isin(sel_wh)])
    if len(ws) > 1:
        st.plotly_chart(px.bar(ws, x="warehouse_name", y="revenue", title="Revenue by location", text_auto=".2s"), width="stretch")
    top = (s_f.assign(product_name=s_f.product_id.map(pname)).groupby("product_name")
           .agg(units=("quantity", "sum"), revenue=("revenue", "sum")).nlargest(10, "revenue").reset_index())
    st.plotly_chart(px.bar(top, x="revenue", y="product_name", orientation="h", title="Top 10 products by revenue")
                    .update_yaxes(autorange="reversed"), width="stretch")

with tabs["ABC-XYZ"]:
    abc = A["abc"][A["abc"].product_id.isin(p_f.product_id)]
    seg = abc.groupby("segment").agg(products=("product_id", "count"), revenue=("revenue", "sum")).reset_index()
    a, b = st.columns([1, 2])
    a.dataframe(seg.style.format({"revenue": "{:,.0f}"}), hide_index=True, width="stretch")
    b.plotly_chart(px.scatter(abc, x="demand_cv", y="revenue", color="abc", hover_name="product_name", log_y=True,
                              title="Value vs demand variability"), width="stretch")
    st.caption("A/B/C = value class by cumulative revenue (80% / 15% / 5%). X/Y/Z = variability of monthly demand rate "
               "(CV <= 0.25 stable, <= 0.5 moderate, above erratic). AX: control tightly; CZ: consider make-to-order.")
    st.dataframe(abc[["product_name", "category", "revenue", "revenue_share_pct", "abc", "demand_cv", "xyz", "segment"]],
                 hide_index=True, width="stretch")

with tabs["Forecast"]:
    bt = A["backtest"]
    if bt:
        st.markdown(f"**Model check (holdout of the last {bt['horizon_days']} days):** weekly error (WAPE) **{bt['wape_weekly_model']:.1%}** "
                    f"vs {bt['wape_weekly_naive']:.1%} for a flat recent-average baseline (daily {bt['wape_model']:.1%} vs "
                    f"{bt['wape_naive']:.1%}); bias {bt['bias_model']:+.1%}. Trust the forecast about as far as this error suggests.")
    else:
        st.warning("Less than ~3 months of history: forecast accuracy cannot be checked and will be weak.")
    pick = st.selectbox("Product", p_f.sort_values("product_name").product_id, format_func=pname.get)
    hist, fc = A["history"][pick].iloc[-120:], A["forecast"][pick]
    fig = go.Figure()
    fig.add_scatter(x=hist.index, y=hist.rolling(7).mean(), name="Actual (7-day avg)")
    fig.add_scatter(x=fc.index, y=fc.rolling(7, min_periods=1).mean(), name="Forecast (7-day avg)", line={"dash": "dash"})
    fig.update_layout(title="Daily units, all locations (smoothed)", yaxis_title="units/day")
    st.plotly_chart(fig, width="stretch")
    st.metric("Forecast: next 30 days", f"{fc.sum():,.0f} units", delta=f"{fc.sum() / max(hist.iloc[-30:].sum(), 1) - 1:+.1%} vs last 30 days")
    st.caption("Method: recent 28-day level x weekday profile x year-over-year seasonal ratio (needs 13+ months), pooled per category. "
               "A transparent statistical baseline, not a tuned ML model.")

if has_stock:
    with tabs["Reorder plan"]:
        st.markdown("**Recommended policy per location x SKU.** Safety stock = z x sigma(daily demand) x sqrt(lead time); reorder point = mean "
                    "demand x lead time + safety stock; order quantity = EOQ; order-up-to = reorder point + EOQ.")
        only = st.checkbox("Only items that need an order now", value=True)
        view = repl_f[repl_f.below_rop] if only else repl_f
        st.metric("Orders to place", int((view.suggested_order_qty > 0).sum()), delta=f"{view.suggested_order_cost.sum():,.0f} at cost",
                  delta_color="off")
        cols = ["warehouse_name", "product_name", "current_stock", "reorder_level", "reorder_point", "safety_stock", "eoq",
                "suggested_order_qty", "suggested_order_cost", "stockout_risk_pct", "days_of_cover", "lead_time_days"]
        st.dataframe(view.sort_values("suggested_order_cost", ascending=False)[cols], hide_index=True, width="stretch")
        st.download_button("Download purchase suggestions (CSV)", view[cols].to_csv(index=False), "purchase_suggestions.csv", "text/csv")
        st.caption(f"{(repl_f.policy_gap > 0).mean():.0%} of items have a current reorder level below the recommended reorder point. "
                   "Assumes constant lead times; ignores minimum order quantities, pack sizes and budget limits.")

    with tabs["Cash & risk"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stock value (at cost)", f"{health['stock_value']:,.0f}")
        c2.metric("Excess stock", f"{health['excess_value']:,.0f}", help="stock above the order-up-to level")
        c3.metric("Dead stock", f"{health['dead_stock_value']:,.0f}", delta=f"{health['dead_stock_items']} items, no sales in 90 days",
                  delta_color="off")
        c4.metric("Items at stockout risk", health["at_risk_items"], help="P(demand during lead time > stock) >= 50%")
        a, b = st.columns(2)
        ex = repl_f.groupby("category").excess_value.sum().reset_index().sort_values("excess_value")
        a.plotly_chart(px.bar(ex, x="excess_value", y="category", orientation="h", title="Excess stock value by category"), width="stretch")
        b.plotly_chart(px.histogram(repl_f, x="stockout_risk_pct", nbins=20, title="Stockout risk during lead time (% probability)"),
                       width="stretch")
        st.markdown("**Largest excess positions**")
        st.dataframe(repl_f.nlargest(15, "excess_value")[["warehouse_name", "product_name", "current_stock", "order_up_to", "excess_units",
                                                          "excess_value", "days_of_cover"]], hide_index=True, width="stretch")

    with tabs["What-if"]:
        st.markdown("**How exposed are we to slower suppliers?** Same data, every lead time extended; purchase needs and stockout risk recomputed.")
        dc = delay_curve(tables, key, z, ordering_cost, holding_rate)
        a, b = st.columns(2)
        a.plotly_chart(px.line(dc, x="supplier_delay_days", y="purchase_order_value", markers=True, title="Purchase order value needed"),
                       width="stretch")
        b.plotly_chart(px.line(dc, x="supplier_delay_days", y="items_at_risk", markers=True, title="Items with >= 50% stockout risk"),
                       width="stretch")
        st.dataframe(dc, hide_index=True, width="stretch")
        st.caption("Use the sidebar slider to apply a delay (and a different service level) to every other tab.")

    with tabs["Transfers"]:
        tr = A["transfers"]
        tr = tr[tr.from_warehouse.isin(sel_wh) & tr.to_warehouse.isin(sel_wh) & tr.product_id.isin(p_f.product_id)].copy()
        tr["from_warehouse"], tr["to_warehouse"] = tr.from_warehouse.map(wh_names), tr.to_warehouse.map(wh_names)
        st.markdown("**Rebalance before buying:** move surplus (stock above reorder point + EOQ) to locations short on the same SKU.")
        st.metric("Transfers", len(tr), delta=f"{tr.value_at_cost.sum():,.0f} of stock moved instead of purchased", delta_color="off")
        st.dataframe(tr, hide_index=True, width="stretch")
        if len(warehouses) < 2:
            st.caption("Transfers need at least two locations.")

    with tabs["Fast vs slow"]:
        level = st.radio("Level", ["SKU (all selected locations)", "Location x SKU"], horizontal=True)
        lvl = "product" if level.startswith("SKU") else "warehouse_product"
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
        st.caption("Turnover = units sold / average stock; average stock = (opening + current) / 2 "
                   "(current stock only when no receipts history is available).")

    with tabs["Alerts"]:
        alerts = kpis.reorder_alerts(s_f, inv_f, products, warehouses)
        st.subheader(f"{len(alerts)} item(s) at or below their current reorder level")
        if alerts.empty:
            st.success("Nothing below its reorder level.")
        else:
            show = alerts[["warehouse_name", "product_name", "category", "current_stock", "reorder_level", "shortfall",
                           "daily_demand", "days_of_stock_left", "lead_time_days", "severity"]]
            colors = {"Stockout": "background-color:#F8CBAD", "Critical": "background-color:#FCE4D6", "Low": ""}
            st.dataframe(show.style.apply(lambda r: [colors[r.severity]] * len(r), axis=1).format(
                {"daily_demand": "{:.2f}", "days_of_stock_left": "{:.1f}"}), width="stretch", hide_index=True)
            st.download_button("Download reorder list (CSV)", show.to_csv(index=False), "reorder_alerts.csv", "text/csv")
