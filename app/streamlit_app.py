"""Interactive Inventory & Sales dashboard.  Run:  streamlit run app/streamlit_app.py"""
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from invsales import kpis  # noqa: E402
from invsales.config import get_settings  # noqa: E402
from invsales.repository import load_data  # noqa: E402

st.set_page_config(page_title="Inventory & Sales Analytics", page_icon=":package:", layout="wide")


@st.cache_data(ttl=300, show_spinner="Loading data...")
def get_data():
    return load_data(get_settings())


sales, products, restocks, source = get_data()

# ---- sidebar filters ---------------------------------------------------------
st.sidebar.header("Filters")
cats = sorted(products.category.unique())
sel_cats = st.sidebar.multiselect("Category", cats, default=cats)
stores = sorted(sales.store.unique())
sel_stores = st.sidebar.multiselect("Store", stores, default=stores)
dmin, dmax = sales.order_date.min().date(), sales.order_date.max().date()
date_range = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
if len(date_range) != 2:
    st.info("Pick both a start and an end date.")
    st.stop()
st.sidebar.caption(f"Data source: {source}")

p_f = products[products.category.isin(sel_cats)]
s_f = sales[sales.product_id.isin(p_f.product_id) & sales.store.isin(sel_stores)
            & sales.order_date.between(pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]))]
if s_f.empty:
    st.warning("No sales match the current filters.")
    st.stop()

st.title("Inventory & Sales Analytics")

h = kpis.headline(s_f, p_f)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Sales", f"${h['total_sales']:,.0f}")
c2.metric("Units Sold", f"{h['units_sold']:,}")
c3.metric("Total Stock (units)", f"{h['total_stock']:,}")
c4.metric("Low-Stock Items", h["low_stock_items"], help="current stock <= reorder level")

turn = kpis.stock_turnover(sales, products, restocks)          # turnover is computed on the full history
turn = turn[turn.product_id.isin(p_f.product_id)]

left, right = st.columns(2)
with left:
    m = kpis.monthly_sales(s_f)
    st.plotly_chart(px.line(m, x="month", y="revenue", markers=True, title="Monthly sales"), width="stretch")
with right:
    cat = kpis.category_summary(s_f, p_f)
    st.plotly_chart(px.bar(cat, x="revenue", y="category", orientation="h", title="Revenue by category",
                           hover_data=["margin_pct", "revenue_share_pct"]), width="stretch")

tab1, tab2, tab3 = st.tabs(["Fast vs slow movers", "Top products", "Reorder alerts"])
with tab1:
    n = st.slider("Products per chart", 5, 15, 10)
    fast, slow = turn.nlargest(n, "stock_turnover"), turn.nsmallest(n, "stock_turnover")
    a, b = st.columns(2)
    a.plotly_chart(px.bar(fast, x="stock_turnover", y="product_name", orientation="h", title="Fastest (highest turnover)",
                          color_discrete_sequence=["#27AE60"]).update_yaxes(autorange="reversed"), width="stretch")
    b.plotly_chart(px.bar(slow, x="stock_turnover", y="product_name", orientation="h", title="Slowest (lowest turnover)",
                          color_discrete_sequence=["#C0392B"]).update_yaxes(autorange="reversed"), width="stretch")
    st.caption("Turnover = units sold / average stock over the full history (opening + current) / 2.")
with tab2:
    top = (s_f.merge(products[["product_id", "product_name"]], on="product_id").groupby("product_name")
           .agg(units=("quantity", "sum"), revenue=("revenue", "sum")).nlargest(10, "revenue").reset_index())
    st.plotly_chart(px.bar(top, x="revenue", y="product_name", orientation="h", title="Top 10 products by revenue")
                    .update_yaxes(autorange="reversed"), width="stretch")
with tab3:
    alerts = kpis.reorder_alerts(sales, p_f)
    st.subheader(f"{len(alerts)} product(s) at or below reorder level")
    if alerts.empty:
        st.success("Nothing to reorder.")
    else:
        show = alerts[["product_id", "product_name", "category", "current_stock", "reorder_level", "shortfall",
                       "daily_demand", "days_of_stock_left", "lead_time_days", "severity"]]
        colors = {"Stockout": "background-color:#F8CBAD", "Critical": "background-color:#FCE4D6", "Low": ""}
        st.dataframe(show.style.apply(lambda r: [colors[r.severity]] * len(r), axis=1).format(
            {"daily_demand": "{:.2f}", "days_of_stock_left": "{:.1f}"}), width="stretch", hide_index=True)
        st.download_button("Download reorder list (CSV)", show.to_csv(index=False), "reorder_alerts.csv", "text/csv")
