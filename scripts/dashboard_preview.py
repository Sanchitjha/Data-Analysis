"""Static preview of the dashboard layout, rendered with matplotlib from the same clean data.
NOT a Power BI screenshot - the real dashboard lives in powerbi/ (see powerbi/BUILD_GUIDE.md)."""
import matplotlib
import pandas as pd

matplotlib.use("Agg")
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
s = pd.read_csv(ROOT/"data/clean/sales.csv", parse_dates=["order_date"])
p = pd.read_csv(ROOT/"data/clean/products.csv")
r = pd.read_csv(ROOT/"data/clean/restocks.csv", parse_dates=["restock_date"])

opening = r.sort_values("restock_date").groupby("product_id").quantity.first()
k = p.set_index("product_id").join(s.groupby("product_id").agg(units=("quantity", "sum"), revenue=("revenue", "sum")))
k["turnover"] = k.units / ((opening + k.current_stock) / 2)
alerts = k[k.current_stock <= k.reorder_level].sort_values("current_stock")

fig = plt.figure(figsize=(16, 10), facecolor="#F4F6F9")
fig.suptitle("Inventory & Sales Analytics Dashboard  (layout preview)", x=0.03, ha="left", fontsize=18, fontweight="bold", color="#1F3A5F")
kpis = [("Total Sales", f"${s.revenue.sum():,.0f}", "#1F3A5F"), ("Units Sold", f"{s.quantity.sum():,}", "#1F3A5F"),
        ("Total Stock (units)", f"{p.current_stock.sum():,}", "#1F3A5F"), ("Low-Stock Items", f"{len(alerts)}", "#C0392B")]
for i, (t, v, c) in enumerate(kpis):
    ax = fig.add_axes([0.03 + i * 0.24, 0.80, 0.22, 0.10]); ax.set_facecolor("white"); ax.set_xticks([]); ax.set_yticks([])
    ax.text(0.5, 0.62, v, ha="center", va="center", fontsize=24, fontweight="bold", color=c); ax.text(0.5, 0.2, t, ha="center", fontsize=11, color="#555")
    for sp in ax.spines.values(): sp.set_color("#DDD")

m = s.groupby(s.order_date.dt.to_period("M")).revenue.sum(); m.index = m.index.to_timestamp()
ax = fig.add_axes([0.05, 0.47, 0.42, 0.26]); ax.plot(m.index, m.values, color="#2E86C1", marker="o", ms=3); ax.set_title("Monthly sales trend", loc="left", fontweight="bold")
ax.grid(alpha=.3); ax.yaxis.set_major_formatter(lambda x, _: f"${x/1000:.0f}k")

top = k.nlargest(5, "turnover"); slow = k.nsmallest(5, "turnover")
ax = fig.add_axes([0.62, 0.47, 0.34, 0.26]); d = pd.concat([slow, top]).sort_values("turnover")
ax.barh(d.product_name, d.turnover, color=["#C0392B" if i in slow.index else "#27AE60" for i in d.index])
ax.set_title("Fast (green) vs slow (red) movers - stock turnover", loc="left", fontweight="bold", fontsize=10); ax.tick_params(labelsize=8)

ax = fig.add_axes([0.03, 0.04, 0.94, 0.36]); ax.axis("off"); ax.set_title(f"Reorder alerts - stock at/below reorder level ({len(alerts)} items, showing 9 lowest)", loc="left", fontweight="bold", color="#C0392B")
tb = alerts.head(9).reset_index()[["product_id", "product_name", "category", "current_stock", "reorder_level", "lead_time_days"]]
tb.columns = ["ID", "Product", "Category", "Stock", "Reorder level", "Lead time (d)"]
t = ax.table(cellText=tb.values, colLabels=tb.columns, loc="upper center", cellLoc="center"); t.auto_set_font_size(False); t.set_fontsize(9); t.scale(1, 1.5)
for (i, j), c in t.get_celld().items():
    if i == 0: c.set_facecolor("#1F3A5F"); c.set_text_props(color="white", fontweight="bold")
    elif tb.iloc[i - 1]["Stock"] == 0: c.set_facecolor("#F8CBAD")
fig.text(0.97, 0.965, "Filters in Power BI: Category | Date range | Store", ha="right", fontsize=10, color="#555")
fig.savefig(ROOT/"screenshots/dashboard_layout_preview.png", dpi=110)
