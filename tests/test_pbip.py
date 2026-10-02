"""Offline consistency checks of the generated Power BI project: every field a visual uses exists in the TMDL model,
relationships point at real columns, and the JSON files parse. (Schema validation: scripts/validate_pbip.py, needs internet.)"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "powerbi"
TABLES = ROOT / "Inventory.SemanticModel" / "definition" / "tables"
VISUALS = ROOT / "Inventory.Report" / "definition" / "pages" / "InventoryOverview" / "visuals"


def model():
    cols, measures = {}, {}
    for f in TABLES.glob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        table = re.match(r"table (\S+)", text).group(1)
        cols[table] = set(re.findall(r"^\tcolumn ('([^']+)'|(\S+))", text, re.M) and
                          [a or b for _, a, b in re.findall(r"^\tcolumn ('([^']+)'|(\S+))", text, re.M)])
        measures[table] = {a or b for _, a, b in re.findall(r"^\tmeasure ('([^']+)'|([^\s=]+)) =", text, re.M)}
    return cols, measures


def refs(node):
    """Yield (kind, entity, property) for every Column/Measure reference in a JSON tree."""
    if isinstance(node, dict):
        for kind in ("Column", "Measure"):
            if kind in node and isinstance(node[kind], dict) and "Property" in node[kind]:
                src = node[kind]["Expression"]["SourceRef"]
                if "Entity" in src:
                    yield kind, src["Entity"], node[kind]["Property"]
        for v in node.values():
            yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


def test_model_files_exist_and_expected_objects_present():
    cols, measures = model()
    assert set(cols) >= {"fact_sales", "fact_inventory", "fact_restocks", "dim_products", "dim_warehouses", "dim_date", "_Measures"}
    assert len(measures["_Measures"]) == 17 and "Stock Turnover" in measures["_Measures"] and "Low-Stock Items" in measures["_Measures"]
    assert {"Date", "Month", "Month Sort"} <= cols["dim_date"]


def test_visuals_exist_and_reference_only_real_fields():
    cols, measures = model()
    files = sorted(VISUALS.glob("*/visual.json"))
    assert len(files) == 12
    names = set()
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        assert doc["name"] == f.parent.name and doc["name"] not in names
        names.add(doc["name"])
        for kind, entity, prop in refs(doc):
            pool = cols if kind == "Column" else measures
            assert entity in pool and prop in pool[entity], f"{f.parent.name}: {kind} {entity}[{prop}] not in model"


def test_relationships_point_at_real_columns():
    cols, _ = model()
    text = (ROOT / "Inventory.SemanticModel" / "definition" / "relationships.tmdl").read_text(encoding="utf-8")
    pairs = re.findall(r"fromColumn: (\w+)\.(\w+)\n\ttoColumn: (\w+)\.(\w+)", text)
    assert len(pairs) == 7
    for ft, fc, tt, tc in pairs:
        assert fc in cols[ft] and tc in cols[tt], (ft, fc, tt, tc)


@pytest.mark.parametrize("path", ["Inventory.pbip", "Inventory.SemanticModel/definition.pbism", "Inventory.Report/definition.pbir"])
def test_item_files_declare_a_schema(path):
    doc = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert doc["$schema"].startswith("https://developer.microsoft.com/json-schemas/fabric/")


def test_visual_layout_fits_the_page_without_overlap():
    page = json.loads((ROOT / "Inventory.Report" / "definition" / "pages" / "InventoryOverview" / "page.json").read_text(encoding="utf-8"))
    boxes = []
    for f in sorted(VISUALS.glob("*/visual.json")):
        p = json.loads(f.read_text(encoding="utf-8"))["position"]
        boxes.append((f.parent.name, p["x"], p["y"], p["x"] + p["width"], p["y"] + p["height"]))
    for name, x0, y0, x1, y1 in boxes:
        assert 0 <= x0 < x1 <= page["width"] and 0 <= y0 < y1 <= page["height"], name
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[3] <= b[1] or b[3] <= a[1] or a[4] <= b[2] or b[4] <= a[2], f"{a[0]} overlaps {b[0]}"
