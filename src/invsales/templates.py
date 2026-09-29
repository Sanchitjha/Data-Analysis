"""Sample input files for `invsales import` (and for the dashboard's 'download template' buttons)."""
from __future__ import annotations

from pathlib import Path

SALES = """date,sku,quantity,location,unit_price
2025-01-02,SKU-1001,12,Pune,120.00
2025-01-02,SKU-1002,3,Pune,80.00
2025-01-03,SKU-1001,9,Nagpur,120.00
2025-01-03,SKU-1003,1,Nagpur,450.00
"""
STOCK = """sku,location,stock_on_hand,reorder_level
SKU-1001,Pune,140,60
SKU-1002,Pune,25,
SKU-1001,Nagpur,20,60
SKU-1003,Nagpur,4,
"""
PRODUCTS = """sku,product_name,category,unit_cost,unit_price,lead_time_days
SKU-1001,Basmati Rice 5kg,Staples,95,120,7
SKU-1002,Sunflower Oil 1L,Staples,60,80,5
SKU-1003,Hand Blender,Appliances,300,450,14
"""
FILES = {"sales_template.csv": SALES, "stock_template.csv": STOCK, "products_template.csv": PRODUCTS}


def write_templates(folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        (folder / name).write_text(text)
    return [str(folder / n) for n in FILES]
