"""Adds two REAL Excel PivotTables to excel/Inventory_Sales_Summary.xlsx using LibreOffice (UNO), because openpyxl cannot author pivots.
Needs: libreoffice-calc + python3-uno. Usage: python scripts/add_pivot_tables.py   (run after scripts/build_excel_and_exports.py)"""
import os
import subprocess
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.table import CellAddress, CellRangeAddress

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "excel" / "Inventory_Sales_Summary.xlsx"
PORT = 2002


def prop(name, value):
    p = PropertyValue()
    p.Name, p.Value = name, value
    return p


def connect():
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(60):
        try:
            return resolver.resolve(f"uno:socket,host=localhost,port={PORT};urp;StarOffice.ComponentContext")
        except Exception:
            time.sleep(1)
    raise RuntimeError("could not connect to LibreOffice")


def add_pivot(sheet, src, name, row_field, col_field, data_field, at):
    dpt = sheet.getDataPilotTables()
    desc = dpt.createDataPilotDescriptor()
    desc.setSourceRange(src)
    fields = desc.getDataPilotFields()
    if os.environ.get('PIVOT_DEBUG'):
        print('fields:', list(fields.getElementNames()), 'source', src.StartRow, src.EndRow, src.EndColumn)
    from com.sun.star.sheet.DataPilotFieldOrientation import COLUMN, DATA, ROW
    from com.sun.star.sheet.GeneralFunction import SUM
    for fname, orient in ((row_field, ROW), (col_field, COLUMN), (data_field, DATA)):
        f = fields.getByName(fname)
        f.Orientation = orient
        if orient == DATA:
            f.Function = SUM
    dpt.insertNewByName(name, at, desc)


def main() -> int:
    profile = os.environ.get("LO_PROFILE", "/tmp/lo_profile")
    proc = subprocess.Popen(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{profile}",
                             f"--accept=socket,host=localhost,port={PORT};urp;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ctx = connect()
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(XLSX.as_uri(), "_blank", 0, (prop("Hidden", True),))
        sheets = doc.getSheets()
        if sheets.hasByName("Pivot"):
            sheets.removeByName("Pivot")
        sheets.insertNewByName("Pivot", 0)               # insert first: sheet indexes shift, so look the data sheet up afterwards
        data = sheets.getByName("Sales_Data")
        cur = data.createCursor()
        cur.gotoEndOfUsedArea(False)
        last_row, last_col = cur.getRangeAddress().EndRow, cur.getRangeAddress().EndColumn
        src = CellRangeAddress(data.getRangeAddress().Sheet, 0, 0, last_col, last_row)
        sheet = sheets.getByName("Pivot")
        idx = sheet.getRangeAddress().Sheet
        sheet.getCellByPosition(0, 0).setString("PivotTables on the Sales_Data table (Excel: click a pivot, PivotTable Analyze -> Refresh after changing data)")
        add_pivot(sheet, src, "Revenue_by_Category_Year", "category", "year", "revenue", CellAddress(idx, 0, 2))
        add_pivot(sheet, src, "Revenue_by_Warehouse_Category", "warehouse", "category", "revenue", CellAddress(idx, 0, 14))
        doc.storeToURL(XLSX.as_uri(), (prop("FilterName", "Calc MS Excel 2007 XML"),))
        doc.close(True)
        print("pivot tables written to", XLSX)
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
