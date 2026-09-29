"""Builds and executes notebooks/01_exploration.ipynb (a readable walk-through of the pipeline outputs)."""
from pathlib import Path

import nbformat as nbf
from nbconvert.preprocessors import ExecutePreprocessor

ROOT = Path(__file__).resolve().parent.parent
nb = nbf.v4.new_notebook()
md = lambda s: nb.cells.append(nbf.v4.new_markdown_cell(s.strip()))  # noqa: E731
code = lambda s: nb.cells.append(nbf.v4.new_code_cell(s.strip()))  # noqa: E731

md("# Inventory & Sales Analytics: pipeline walk-through\nProduction logic lives in `src/invsales/`; this notebook only *uses* it to explain the results. "
   "Data: the committed demo preset (simulated, see README).")
code("""
import json
from pathlib import Path
import pandas as pd, plotly.express as px
from invsales import analytics, kpis
from invsales.repository import load_clean
ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
CLEAN = ROOT / 'data' / 'demo' / 'clean'
t = load_clean(CLEAN)
sales, products, inventory, restocks, warehouses = (t[k] for k in ('sales', 'products', 'inventory', 'restocks', 'warehouses'))
print({k: len(v) for k, v in t.items()})
""")
md("## 1. What cleaning changed\nThe raw export was deliberately corrupted (duplicates, missing values, 3 date formats, `$` prices, inconsistent category text); "
   "`clean.py` fixes it and `validate.py` gates the load.")
code("print(json.dumps(json.loads((CLEAN / 'cleaning_report.json').read_text()), indent=1))")
md("## 2. Headline KPIs and trend")
code("""
print(kpis.headline(sales, inventory))
px.line(kpis.monthly_sales(sales), x='month', y='revenue', markers=True, title='Monthly sales')
""")
md("## 3. Warehouses and categories")
code("""
print(kpis.warehouse_summary(sales, inventory, warehouses).to_string(index=False))
kpis.category_summary(sales, products)
""")
md("## 4. Fast and slow movers (stock turnover)\nTurnover = units sold / average stock; slow movers tie up cash.")
code("""
turn = kpis.stock_turnover(sales, inventory, restocks, products, level='product')
print(turn.nsmallest(5, 'stock_turnover')[['product_name', 'units_sold', 'avg_stock', 'stock_turnover', 'days_of_inventory']].to_string(index=False))
print(turn.nlargest(5, 'stock_turnover')[['product_name', 'units_sold', 'avg_stock', 'stock_turnover', 'days_of_inventory']].to_string(index=False))
""")
md("## 5. ABC-XYZ segmentation")
code("""
abc = analytics.abc_xyz(sales, products)
print(abc.groupby('segment').agg(products=('product_id', 'count'), revenue=('revenue', 'sum')).round(0))
px.scatter(abc, x='demand_cv', y='revenue', color='abc', hover_name='product_name', log_y=True)
""")
md("## 6. Forecast accuracy (holdout of the last 30 days)\nModel = recent level x weekday profile x yoy seasonal ratio, pooled per category; baseline = flat recent average.")
code("""
groups = products.set_index('product_id').category
bt = analytics.backtest(sales, 30, groups)
print({k: v for k, v in bt.items() if k != 'per_product'})
""")
md("## 7. Replenishment: what to order now")
code("""
repl = analytics.replenishment(sales, inventory, products, warehouses)
due = repl[repl.below_rop].sort_values('suggested_order_cost', ascending=False)
print(f'{len(due)} of {len(repl)} warehouse-product pairs at/below the recommended reorder point; order value ${due.suggested_order_cost.sum():,.0f}')
print(f'{(repl.policy_gap > 0).mean():.0%} have a current reorder level below the recommended one')
due[['warehouse_name', 'product_name', 'current_stock', 'reorder_point', 'eoq', 'suggested_order_qty', 'suggested_order_cost']].head(10)
""")
ExecutePreprocessor(timeout=300, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(ROOT / "notebooks")}})
nbf.write(nb, ROOT / "notebooks" / "01_exploration.ipynb")
print("notebook written")
