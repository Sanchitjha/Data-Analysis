# User guide: using this with your own business data

This is for a shop, distributor or warehouse that can export sales from Excel, Tally, Zoho, a POS or an ERP and wants to know
**what to order, how much, what is overstocked and what may run out**. You do not need to be a data person.

## 1. What you need (15 minutes)
| File | Required? | Columns (names can differ, they are auto-detected) |
|---|---|---|
| **Sales export** | yes | date, item/SKU, quantity sold. Optional: location/branch, unit price or amount, invoice number |
| **Current stock** | for reorder advice | item/SKU, stock on hand. Optional: location, your current reorder level |
| **Product master** | optional | SKU, name, category, unit cost, unit price, supplier lead time (days) |

Templates: `invsales templates` (writes `templates/`) or the download buttons in the app. **At least 3 months of sales** is needed for
anything useful, 12+ months for seasonality. CSV or Excel (`.xlsx`, first sheet).

## 2. Run it
- **Try in the browser** (data stays in your session, but the public demo is not for confidential data): open the app, choose
  *My data (upload)*, drop the files, check the column mapping, press **Analyze my data**.
- **Private, on your own machine/server:** `docker compose up` then use the same page, or from the command line:
  ```bash
  pip install -e ".[dashboard,api]"
  invsales import --sales sales.xlsx --stock stock.csv --products products.csv        # writes data/demo/clean/*.parquet
  invsales import --sales sales.csv --map quantity="Units Sold" --map warehouse_id=Godown   # fix a wrong auto-mapping
  invsales import ... --load-db        # optionally load PostgreSQL (recreates the tables!), then use the API / Power BI
  ```
  (`--month-first` reads ambiguous dates such as 03/04/2025 as MM/DD; the default is DD/MM.)

## 3. Read the import report first
It lists what was dropped (returns/credit notes, rows without a date/SKU/quantity, duplicates), and every **assumption** made for
missing information: e.g. "unit cost unknown: assumed 75% of price", "lead time unknown: 7 days", "no warehouse column: one location".
Order values and EOQ depend on cost and lead time, so provide them in the product master where you can.

## 4. What the outputs mean
| Output | Meaning | How to use it |
|---|---|---|
| **Reorder plan** | per location x SKU: reorder point, safety stock, EOQ, suggested order qty and cost | Place the listed orders; ignore items you do not reorder |
| **Stockout risk %** | chance that demand during the supplier lead time exceeds what you hold | Work down from the highest; 100% = already out and it sells |
| **Excess stock** | stock above the order-up-to level (reorder point + EOQ), valued at cost | Stop reordering, discount, or transfer |
| **Dead stock** | on hand, no sales in 90 days | Liquidate / return / write down |
| **Transfers** | move surplus to a location short on the same SKU | Cheaper than buying |
| **ABC-XYZ** | A = top 80% of revenue, X = steady demand | Tight control for AX; make-to-order or minimal stock for CZ |
| **Forecast** | next 30 days per SKU with a holdout accuracy check | Judge by the shown error, not by the chart |
| **What-if** | same data with slower suppliers or a different service level | Decide how much buffer is worth paying for |
| **Action pack (Excel)** | orders, risks, transfers, excess, ABC-XYZ, assumptions | Hand to purchasing / warehouse |

Service level 95% means about 1 lead time in 20 ends with a stockout for that item. Raising it to 99% adds safety stock (cash) quickly:
use the sidebar slider and compare.

## 5. Known limits (please read before acting on numbers)
- Demand is assumed roughly stable in distribution; promotions, price changes, stockouts (lost sales look like low demand) and new
  products are not modelled. If an item was out of stock for weeks, its history understates real demand.
- Lead times are treated as constant per SKU; no minimum order quantities, pack sizes, shelf life, budget or storage limits.
- With little history the risk and forecast figures are weak; the app warns you (< 60 days) and skips the accuracy check (< 3 months).
- Amounts are used as given: one currency, no tax handling. Numbers like `1.234,56` (European format) are not supported; use `1234.56`.
- Returns/credit notes (negative quantities) are excluded, not netted.
- This is decision support, not an autopilot: review the top items before ordering.

## 6. Privacy
The browser app keeps uploads in memory for your session only. For confidential data, run it on your own machine or server
(`docker compose up`); nothing leaves it. Do not upload confidential data to a public demo URL.
