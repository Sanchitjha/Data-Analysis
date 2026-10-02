"""Generates the Power BI Project (PBIP): a TMDL semantic model (tables, relationships, DAX measures,
Power Query sources) plus an empty report bound to it.

Open powerbi/Inventory.pbip in Power BI Desktop (enable File > Options > Preview features:
'Power BI Project (.pbip) save option' and 'Store semantic model using TMDL format'), set the
DataFolder parameter to the absolute path of this repo's powerbi folder, then build the visuals
following powerbi/BUILD_GUIDE.md.

NOTE: generated without Power BI Desktop and NOT opened/verified in it.
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "powerbi"
SM = ROOT / "Inventory.SemanticModel"
RP = ROOT / "Inventory.Report"


def uid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "inventory-analytics/" + name))  # stable ids -> clean diffs


def w(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def table(name, cols, fmt=None):
    """cols: list of (column, TMDL dataType, Power Query type, summarizeBy)"""
    fmt = fmt or {}
    out = [f"table {name}", f"\tlineageTag: {uid(name)}", ""]
    for c, dt, _, summ in cols:
        out += [f"\tcolumn {c}", f"\t\tdataType: {dt}", f"\t\tlineageTag: {uid(name + c)}",
                f"\t\tsummarizeBy: {summ}", f"\t\tsourceColumn: {c}"]
        if c in fmt:
            out.append(f"\t\tformatString: {fmt[c]}")
        out.append("")
    types = ", ".join(f'{{"{c}", {m}}}' for c, _, m, _ in cols)
    out += [f"\tpartition {name} = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet",
            f'\t\t\t\t    Source = Csv.Document(File.Contents(DataFolder & "\\{name}.csv"), '
            '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
            "\t\t\t\t    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),",
            f'\t\t\t\t    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")',
            "\t\t\t\tin", "\t\t\t\t    Typed", ""]
    return "\n".join(out)


def measure(name, expr, fmt=None, folder=None):
    q = f"'{name}'" if any(ch in name for ch in " -%") else name
    lines = [f"\tmeasure {q} = {expr.strip()}", f"\t\tlineageTag: {uid('m' + name)}"]
    if fmt:
        lines.append(f"\t\tformatString: {fmt}")
    if folder:
        lines.append(f"\t\tdisplayFolder: {folder}")
    return "\n".join(lines) + "\n"


MEASURE_DEFS = [
    ("Total Sales", "SUM(fact_sales[revenue])", "$#,0", "Sales"),
    ("Units Sold", "SUM(fact_sales[quantity])", "#,0", "Sales"),
    ("Gross Profit", "SUMX(fact_sales, fact_sales[revenue] - fact_sales[quantity] * RELATED(dim_products[unit_cost]))", "$#,0", "Sales"),
    ("Gross Margin %", "DIVIDE([Gross Profit], [Total Sales])", "0.0%", "Sales"),
    ("Sales LY", "CALCULATE([Total Sales], SAMEPERIODLASTYEAR(dim_date[Date]))", "$#,0", "Sales"),
    ("Sales YoY %", "DIVIDE([Total Sales] - [Sales LY], [Sales LY])", "0.0%", "Sales"),
    ("Revenue Rank", "RANKX(ALL(dim_products[product_name]), [Total Sales], , DESC)", "0", "Sales"),
    ("Total Stock", "SUM(fact_inventory[current_stock])", "#,0", "Inventory"),
    ("Low-Stock Items",
     "COUNTROWS(FILTER(fact_inventory, fact_inventory[current_stock] <= fact_inventory[reorder_level]))", "#,0", "Inventory"),
    # opening stock = the stock-in on the first day of history (the simulator/ETL writes one opening row per warehouse x product)
    ("Opening Stock",
     "VAR d = CALCULATE(MIN(fact_restocks[restock_date]), ALL(fact_restocks)) "
     "RETURN CALCULATE(SUM(fact_restocks[quantity]), fact_restocks[restock_date] = d)", "#,0", "Inventory"),
    ("Average Stock", "DIVIDE([Opening Stock] + [Total Stock], 2)", "#,0.0", "Inventory"),
    ("Stock Turnover", "DIVIDE([Units Sold], [Average Stock])", "0.00", "Inventory"),
    ("Days in Period",
     "DATEDIFF(CALCULATE(MIN(fact_sales[order_date]), ALL(fact_sales)), CALCULATE(MAX(fact_sales[order_date]), ALL(fact_sales)), DAY) + 1",
     "0", "Inventory"),
    ("Days of Inventory", "DIVIDE([Days in Period], [Stock Turnover])", "0", "Inventory"),
    ("Reorder Status", 'IF(SUM(fact_inventory[current_stock]) <= SUM(fact_inventory[reorder_level]), "REORDER", "OK")', None, "Inventory"),
    ("Shortfall", "MAX(0, SUM(fact_inventory[reorder_level]) - SUM(fact_inventory[current_stock]))", "#,0", "Inventory"),
    ("Movement Class",
     'VAR t = [Stock Turnover] VAR p75 = PERCENTILEX.INC(ALL(dim_products), [Stock Turnover], 0.75) '
     'VAR p25 = PERCENTILEX.INC(ALL(dim_products), [Stock Turnover], 0.25) '
     'RETURN IF(t >= p75, "Fast", IF(t <= p25, "Slow", "Medium"))', None, "Inventory"),
]
MEASURES = [measure(*m) for m in MEASURE_DEFS]

S, I, D, T = "string", "int64", "double", "dateTime"
SALES = [("order_id", S, "type text", "none"), ("order_date", T, "type date", "none"), ("warehouse_id", S, "type text", "none"),
         ("product_id", S, "type text", "none"), ("quantity", I, "Int64.Type", "sum"), ("unit_price", D, "type number", "none"),
         ("revenue", D, "type number", "sum")]
PRODUCTS = [("product_id", S, "type text", "none"), ("product_name", S, "type text", "none"), ("category", S, "type text", "none"),
            ("unit_cost", D, "type number", "none"), ("unit_price", D, "type number", "none"),
            ("lead_time_days", I, "Int64.Type", "none")]
WAREHOUSES = [("warehouse_id", S, "type text", "none"), ("warehouse_name", S, "type text", "none"), ("region", S, "type text", "none")]
INVENTORY = [("warehouse_id", S, "type text", "none"), ("product_id", S, "type text", "none"),
             ("current_stock", I, "Int64.Type", "sum"), ("reorder_level", I, "Int64.Type", "sum")]
RESTOCKS = [("restock_date", T, "type date", "none"), ("warehouse_id", S, "type text", "none"), ("product_id", S, "type text", "none"),
            ("quantity", I, "Int64.Type", "sum")]

DATE_TABLE = f"""table dim_date
\tlineageTag: {uid('dim_date')}
\tdataCategory: Time

\tcolumn Date
\t\tdataType: dateTime
\t\tisKey
\t\tlineageTag: {uid('dd1')}
\t\tformatString: yyyy-mm-dd
\t\tsummarizeBy: none
\t\tsourceColumn: [Date]

\tcolumn Year
\t\tdataType: int64
\t\tlineageTag: {uid('dd2')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Year]

\tcolumn 'Month No'
\t\tdataType: int64
\t\tlineageTag: {uid('dd3')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Month No]

\tcolumn Month
\t\tdataType: string
\t\tlineageTag: {uid('dd4')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Month]
\t\tsortByColumn: 'Month Sort'

\tcolumn 'Month Sort'
\t\tdataType: int64
\t\tlineageTag: {uid('dd5')}
\t\tsummarizeBy: none
\t\tsourceColumn: [Month Sort]

\tpartition dim_date = calculated
\t\tmode: import
\t\tsource =
\t\t\t\tADDCOLUMNS(
\t\t\t\t    CALENDAR(DATE(2024, 1, 1), DATE(2025, 12, 31)),
\t\t\t\t    "Year", YEAR([Date]),
\t\t\t\t    "Month No", MONTH([Date]),
\t\t\t\t    "Month", FORMAT([Date], "MMM yyyy"),
\t\t\t\t    "Month Sort", YEAR([Date]) * 100 + MONTH([Date])
\t\t\t\t)
"""

FAB = "https://developer.microsoft.com/json-schemas/fabric/"
w(SM / "definition.pbism", json.dumps({"$schema": FAB + "item/semanticModel/definitionProperties/1.0.0/schema.json",
                                      "version": "4.0", "settings": {}}, indent=2))
w(SM / "definition" / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
w(SM / "definition" / "model.tmdl",
  "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tdiscourageImplicitMeasures\n\n"
  "ref table fact_sales\nref table fact_inventory\nref table fact_restocks\nref table dim_products\nref table dim_warehouses\nref table dim_date\nref table _Measures\n"
  "ref expression DataFolder\n")
w(SM / "definition" / "expressions.tmdl",
  'expression DataFolder = "C:\\path\\to\\Data-Analysis\\powerbi" '
  '/* CHANGE ME */ meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
  f"\tlineageTag: {uid('DataFolder')}\n")
RELS = [("fact_sales.product_id", "dim_products.product_id"), ("fact_sales.warehouse_id", "dim_warehouses.warehouse_id"),
        ("fact_sales.order_date", "dim_date.Date"), ("fact_inventory.product_id", "dim_products.product_id"),
        ("fact_inventory.warehouse_id", "dim_warehouses.warehouse_id"), ("fact_restocks.product_id", "dim_products.product_id"),
        ("fact_restocks.warehouse_id", "dim_warehouses.warehouse_id")]
w(SM / "definition" / "relationships.tmdl",
  "\n".join(f"relationship {uid('rel' + a)}\n\tfromColumn: {a}\n\ttoColumn: {b}\n" for a, b in RELS))
tables = SM / "definition" / "tables"
w(tables / "fact_sales.tmdl", table("fact_sales", SALES, {"revenue": "$#,0.00", "order_date": "yyyy-mm-dd"}))
w(tables / "fact_restocks.tmdl", table("fact_restocks", RESTOCKS, {"restock_date": "yyyy-mm-dd"}))
w(tables / "dim_products.tmdl", table("dim_products", PRODUCTS))
w(tables / "dim_warehouses.tmdl", table("dim_warehouses", WAREHOUSES))
w(tables / "fact_inventory.tmdl", table("fact_inventory", INVENTORY))
w(tables / "dim_date.tmdl", DATE_TABLE)
w(tables / "_Measures.tmdl",
  f"table _Measures\n\tlineageTag: {uid('_Measures')}\n\n" + "\n".join(MEASURES) +
  f"\n\tcolumn x\n\t\tdataType: int64\n\t\tisHidden\n\t\tlineageTag: {uid('_Measures_x')}\n\t\tsummarizeBy: none\n\t\tsourceColumn: [x]\n" +
  '\n\tpartition _Measures = calculated\n\t\tmode: import\n\t\tsource = ROW("x", 1)\n')

w(ROOT / "Inventory.pbip", json.dumps({"$schema": FAB + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0", "artifacts": [{"report": {"path": "Inventory.Report"}}],
                                       "settings": {"enableAutoRecovery": True}}, indent=2))
w(RP / "definition.pbir", json.dumps({"$schema": FAB + "item/report/definitionProperties/2.0.0/schema.json", "version": "4.0", "datasetReference": {"byPath": {"path": "../Inventory.SemanticModel"}}},
                                     indent=2))
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
w(RP / "definition" / "version.json", json.dumps({"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json",
                                                  "version": "2.0.0"}, indent=2))
w(RP / "definition" / "report.json", json.dumps({
    "$schema": f"{SCHEMA}/report/1.0.0/schema.json",
    "themeCollection": {"baseTheme": {"name": "CY24SU10", "reportVersionAtImport": "5.59", "type": "SharedResources"}},
    "layoutOptimization": "None"}, indent=2))
w(RP / "definition" / "pages" / "pages.json", json.dumps({
    "$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json", "pageOrder": ["InventoryOverview"],
    "activePageName": "InventoryOverview"}, indent=2))
w(RP / "definition" / "pages" / "InventoryOverview" / "page.json", json.dumps({
    "$schema": f"{SCHEMA}/page/1.0.0/schema.json", "name": "InventoryOverview", "displayName": "Inventory Overview",
    "displayOption": "FitToPage", "height": 720, "width": 1280}, indent=2))
w(ROOT / ".gitignore", ".pbi/\n")
dax = ["// Generated by scripts/build_pbip.py from the same definitions as the TMDL model - do not edit by hand.",
       "// Model: dim_products (1)-(*) fact_sales / fact_inventory / fact_restocks; dim_warehouses (1)-(*) the same three;",
       "//        dim_date (1)-(*) fact_sales via order_date", "",
       "// Calculated table (Modeling > New table):",
       'dim_date = ADDCOLUMNS(CALENDAR(DATE(2024, 1, 1), DATE(2025, 12, 31)), "Year", YEAR([Date]), "Month No", MONTH([Date]),',
       '    "Month", FORMAT([Date], "MMM yyyy"), "Month Sort", YEAR([Date]) * 100 + MONTH([Date]))',
       "// then: Month -> Sort by column -> Month Sort ; mark as date table on [Date]", ""]
for name, expr, _, folder in MEASURE_DEFS:
    dax.append(f"// [{folder}]")
    dax.append(f"{name} = {expr}")
    dax.append("")
(ROOT / "measures.dax").write_text("\n".join(dax), encoding="utf-8")

# ------------------------------------------------------------------------------------------ report visuals (PBIR)
VC = FAB + "item/report/definition/visualContainer/2.0.0/schema.json"
PAGE_DIR = RP / "definition" / "pages" / "InventoryOverview" / "visuals"


def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": prop}}


def agg(entity, prop, fn):          # fn: 0 sum, 3 min, 4 max
    return {"Aggregation": {"Expression": col(entity, prop), "Function": fn}}


def proj(field, ref, native, active=None):
    p = {"field": field, "queryRef": ref, "nativeQueryRef": native}
    return p


def mproj(name):
    return proj(meas(name), f"_Measures.{name}", name)


def cproj(entity, prop):
    return proj(col(entity, prop), f"{entity}.{prop}", prop)


def visual(name, x, y, w, h, vtype, state, *, sort=None, objects=None, container=None, filters=None):
    q = {"queryState": state}
    if sort:
        q["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort]}
    v = {"visualType": vtype, "query": q, "drillFilterOtherVisuals": True}
    if objects:
        v["objects"] = objects
    if container:
        v["visualContainerObjects"] = container
    doc = {"$schema": VC, "name": name, "position": {"x": x, "y": y, "z": 0, "height": h, "width": w, "tabOrder": len(list(PAGE_DIR.glob("*")))},
           "visual": v}
    if filters:
        doc["filterConfig"] = {"filters": filters}
    w_(PAGE_DIR / name / "visual.json", json.dumps(doc, indent=2))


def w_(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def title(text):
    return {"title": [{"properties": {"show": lit("true"), "text": lit(f"'{text}'")}}]}


import shutil
shutil.rmtree(PAGE_DIR, ignore_errors=True)
RED, GREEN, BLUE = "'#C0392B'", "'#27AE60'", "'#1F3A5F'"

# KPI cards (display units: None -> full numbers)
for i, (m, color) in enumerate([("Total Sales", BLUE), ("Units Sold", BLUE), ("Total Stock", BLUE), ("Low-Stock Items", RED)]):
    visual(f"card_{i + 1}", 20 + i * 200, 20, 185, 100, "card", {"Values": {"projections": [mproj(m)]}},
           objects={"labels": [{"properties": {"labelDisplayUnits": lit("1D"), "color": {"solid": {"color": lit(color)}}}}]})

# slicers
visual("slicer_warehouse", 840, 20, 140, 100, "slicer", {"Values": {"projections": [cproj("dim_warehouses", "warehouse_name")]}},
       objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]}, container=title("Warehouse"))
visual("slicer_category", 990, 20, 140, 100, "slicer", {"Values": {"projections": [cproj("dim_products", "category")]}},
       objects={"data": [{"properties": {"mode": lit("'Dropdown'")}}]}, container=title("Category"))
visual("slicer_date", 1140, 20, 120, 100, "slicer", {"Values": {"projections": [cproj("dim_date", "Date")]}}, container=title("Date range"))

# monthly trend + warehouse comparison
visual("line_monthly", 20, 140, 520, 280, "lineChart",
       {"Category": {"projections": [cproj("dim_date", "Month")]}, "Y": {"projections": [mproj("Total Sales")]}},
       container=title("Monthly sales"))
visual("column_warehouse", 560, 140, 320, 280, "clusteredColumnChart",
       {"Category": {"projections": [cproj("dim_warehouses", "warehouse_name")]}, "Y": {"projections": [mproj("Total Sales")]}},
       sort=[(meas("Total Sales"), "Descending")], container=title("Sales by warehouse"))


def topn_filter(name, n, direction):
    """Classic visual-level Top/Bottom N on product_name by [Stock Turnover]. direction: 2 = descending (top), 1 = ascending (bottom)."""
    d = {"Name": "d", "Entity": "dim_products", "Type": 0}
    m = {"Name": "m", "Entity": "_Measures", "Type": 0}
    sub = {"Version": 2, "From": [d, m],
           "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "product_name"}, "Name": "field"}],
           "OrderBy": [{"Direction": direction, "Expression": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "Stock Turnover"}}}],
           "Top": n}
    return {"name": name, "field": col("dim_products", "product_name"), "type": "TopN",
            "filter": {"Version": 2,
                       "From": [{"Name": "subquery", "Expression": {"Subquery": {"Query": sub}}, "Type": 2}, d],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "product_name"}}],
                                                       "Table": {"SourceRef": {"Source": "subquery"}}}}}]}}


def fill(color):
    return {"dataPoint": [{"properties": {"fill": {"solid": {"color": lit(color)}}}}]}


visual("bar_fast", 900, 140, 360, 280, "clusteredBarChart",
       {"Category": {"projections": [cproj("dim_products", "product_name")]}, "Y": {"projections": [mproj("Stock Turnover")]}},
       sort=[(meas("Stock Turnover"), "Descending")], objects=fill(GREEN), container=title("Fastest movers (Top 10 stock turnover)"),
       filters=[topn_filter("flt_top10", 10, 2)])
visual("bar_slow", 820, 440, 440, 260, "clusteredBarChart",
       {"Category": {"projections": [cproj("dim_products", "product_name")]}, "Y": {"projections": [mproj("Stock Turnover")]}},
       sort=[(meas("Stock Turnover"), "Ascending")], objects=fill(RED), container=title("Slowest movers (Bottom 10 stock turnover)"),
       filters=[topn_filter("flt_bottom10", 10, 1)])

# reorder alert table, REORDER rows only, zero stock highlighted
stock = agg("fact_inventory", "current_stock", 0)
reorder_filter = {"name": "flt_reorder", "field": meas("Reorder Status"), "type": "Categorical",
                  "filter": {"Version": 2, "From": [{"Name": "m", "Entity": "_Measures", "Type": 0}],
                             "Where": [{"Condition": {"In": {"Expressions": [{"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": "Reorder Status"}}],
                                                             "Values": [[{"Literal": {"Value": "'REORDER'"}}]]}}}]}}
zero_red = {"values": [{"selector": {"metadata": "Sum(fact_inventory.current_stock)"},
                        "properties": {"backColor": {"solid": {"color": {"expr": {"Conditional": {"Cases": [
                            {"Condition": {"Comparison": {"ComparisonKind": 0, "Left": stock, "Right": {"Literal": {"Value": "0D"}}}},
                             "Value": {"Literal": {"Value": "'#F8CBAD'"}}}]}}}}}}}]}
visual("table_reorder", 20, 440, 780, 260, "tableEx",
       {"Values": {"projections": [
           cproj("dim_warehouses", "warehouse_name"), cproj("dim_products", "product_name"),
           proj(stock, "Sum(fact_inventory.current_stock)", "Sum of current_stock"),
           proj(agg("fact_inventory", "reorder_level", 0), "Sum(fact_inventory.reorder_level)", "Sum of reorder_level"),
           mproj("Shortfall"),
           proj(agg("dim_products", "lead_time_days", 4), "Max(dim_products.lead_time_days)", "Max of lead_time_days")]}},
       objects=zero_red, container=title("Reorder alerts (stock at or below reorder level)"), filters=[reorder_filter])
print("PBIP written to", ROOT)
