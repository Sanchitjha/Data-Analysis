"""Reference rendering of the generated Power BI page (NOT a Power BI screenshot): positions come from the PBIP visual.json files,
numbers from powerbi/*.csv. Use it to compare with what Power BI Desktop shows. Output: powerbi/expected_layout.png"""
import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parent.parent / "powerbi"
V = ROOT / "Inventory.Report" / "definition" / "pages" / "InventoryOverview" / "visuals"
page = json.loads((V.parent / "page.json").read_text())
W, H = page["width"], page["height"]

sales = pd.read_csv(ROOT / "fact_sales.csv", parse_dates=["order_date"])
inv = pd.read_csv(ROOT / "fact_inventory.csv")
rs = pd.read_csv(ROOT / "fact_restocks.csv", parse_dates=["restock_date"])
prod = pd.read_csv(ROOT / "dim_products.csv")
wh = pd.read_csv(ROOT / "dim_warehouses.csv")

opening = rs[rs.restock_date == rs.restock_date.min()].groupby("product_id").quantity.sum()
turn = (sales.groupby("product_id").quantity.sum() / ((opening + inv.groupby("product_id").current_stock.sum()) / 2)).rename("turn")
turn = turn.reset_index().merge(prod[["product_id", "product_name"]], on="product_id")
low = inv[inv.current_stock <= inv.reorder_level].merge(prod[["product_id", "product_name", "lead_time_days"]], on="product_id").merge(wh, on="warehouse_id")
low = low.assign(shortfall=low.reorder_level - low.current_stock).sort_values(["current_stock", "shortfall"], ascending=[True, False])
monthly = sales.groupby(sales.order_date.dt.to_period("M").dt.to_timestamp()).revenue.sum()
by_wh = sales.groupby("warehouse_id").revenue.sum().rename("rev").reset_index().merge(wh, on="warehouse_id").sort_values("rev", ascending=False)

fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor="#F4F6F9")


def box(name, pad=(0, 0, 0, 0)):
    """Draw the visual's white container, then an axes inset by pad=(left, bottom, right, top) fractions so labels stay inside it."""
    p = json.loads((V / name / "visual.json").read_text())["position"]
    x, y, w, h = p["x"] / W, 1 - (p["y"] + p["height"]) / H, p["width"] / W, p["height"] / H
    fig.add_artist(Rectangle((x, y), w, h, transform=fig.transFigure, facecolor="white", edgecolor="#DDD", zorder=0))
    ax = fig.add_axes([x + pad[0] * w, y + pad[1] * h, w * (1 - pad[0] - pad[2]), h * (1 - pad[1] - pad[3])])
    ax.set_facecolor("white")
    return ax


def card(name, label, value, color="#1F3A5F"):
    ax = box(name)
    ax.set_xticks([]); ax.set_yticks([])
    ax.text(.5, .58, value, ha="center", va="center", fontsize=22, fontweight="bold", color=color)
    ax.text(.5, .18, label, ha="center", fontsize=10, color="#555")


card("card_1", "Total Sales", f"{sales.revenue.sum():,.0f}")
card("card_2", "Units Sold", f"{sales.quantity.sum():,}")
card("card_3", "Total Stock", f"{inv.current_stock.sum():,}")
card("card_4", "Low-Stock Items", f"{len(low)}", "#C0392B")
for name, label, vals in (("slicer_warehouse", "Warehouse", wh.warehouse_name.tolist()), ("slicer_category", "Category", sorted(prod.category.unique())),
                          ("slicer_date", "Date range", [f"{sales.order_date.min():%d-%m-%Y}", f"{sales.order_date.max():%d-%m-%Y}"])):
    ax = box(name); ax.set_xticks([]); ax.set_yticks([]); ax.set_title(label, fontsize=9, loc="left")
    ax.text(.05, .7, "\n".join(vals[:3]), va="top", fontsize=8, color="#444")
ax = box("line_monthly", (0.12, 0.14, 0.04, 0.14)); ax.plot(monthly.index, monthly.values, color="#2E86C1"); ax.set_title("Monthly sales", fontsize=10, loc="left", pad=8); ax.tick_params(labelsize=7); ax.grid(alpha=.3)
ax = box("column_warehouse", (0.12, 0.14, 0.04, 0.14)); ax.bar(by_wh.warehouse_name, by_wh.rev, color="#2E86C1"); ax.set_title("Sales by warehouse", fontsize=10, loc="left"); ax.tick_params(labelsize=7)
for name, d, color, ttl in (("bar_fast", turn.nlargest(10, "turn").iloc[::-1], "#27AE60", "Fastest movers (Top 10 stock turnover)"),
                            ("bar_slow", turn.nsmallest(10, "turn").iloc[::-1], "#C0392B", "Slowest movers (Bottom 10 stock turnover)")):
    ax = box(name, (0.40, 0.10, 0.05, 0.14)); ax.barh(d.product_name, d.turn, color=color); ax.set_title(ttl, fontsize=10, loc="left"); ax.tick_params(labelsize=7)
ax = box("table_reorder", (0.01, 0.02, 0.01, 0.12)); ax.axis("off"); ax.set_title(f"Reorder alerts (stock at or below reorder level)  -  {len(low)} rows", fontsize=10, loc="left", pad=10)
t = low.head(8)[["warehouse_name", "product_name", "current_stock", "reorder_level", "shortfall", "lead_time_days"]]
tb = ax.table(cellText=t.values, colLabels=["warehouse", "product", "stock", "reorder level", "shortfall", "lead time"], loc="upper center", cellLoc="center")
tb.auto_set_font_size(False); tb.set_fontsize(8); tb.scale(1, 1.3)
tb.set_zorder(5)
for (r, c), cell in tb.get_celld().items():
    if r == 0:
        cell.set_facecolor("#1F3A5F"); cell.set_text_props(color="white")
    elif t.iloc[r - 1].current_stock == 0 and c == 2:
        cell.set_facecolor("#F8CBAD")
fig.text(.995, .012, "reference rendering (matplotlib), not a Power BI screenshot", ha="right", fontsize=7, color="#888")
fig.savefig(ROOT / "expected_layout.png")
print("written", ROOT / "expected_layout.png")
