-- Reporting views used by Power BI, the Streamlit dashboard, the API and the alerting job.
-- Created automatically by the ETL (invsales etl); safe to re-run.

-- Stock turnover per warehouse x product
-- turnover = units sold / average stock,  average stock = (opening stock + current stock) / 2
-- opening stock = first restock row (initial stock-in on the first day)
CREATE OR REPLACE VIEW v_stock_turnover AS
WITH opening AS (
    SELECT DISTINCT ON (warehouse_id, product_id) warehouse_id, product_id, quantity AS opening_stock
    FROM restocks ORDER BY warehouse_id, product_id, restock_date
), sold AS (
    SELECT warehouse_id, product_id, SUM(quantity) AS units_sold, SUM(revenue) AS revenue,
           MAX(order_date) - MIN(order_date) + 1 AS days_selling
    FROM sales GROUP BY warehouse_id, product_id
), stocked AS (
    SELECT warehouse_id, product_id, SUM(quantity) AS units_restocked, COUNT(*) - 1 AS restock_events
    FROM restocks GROUP BY warehouse_id, product_id
)
SELECT i.warehouse_id, i.product_id, p.product_name, p.category,
       i.current_stock, i.reorder_level,
       sd.units_sold, st.units_restocked, st.restock_events,
       ROUND((o.opening_stock + i.current_stock) / 2.0, 1)                            AS avg_stock,
       ROUND(sd.units_sold / ((o.opening_stock + i.current_stock) / 2.0), 2)          AS stock_turnover,
       ROUND(sd.days_selling / (sd.units_sold / ((o.opening_stock + i.current_stock) / 2.0)), 0) AS days_of_inventory
FROM inventory i
JOIN products p USING (product_id)
JOIN opening o USING (warehouse_id, product_id)
JOIN sold sd USING (warehouse_id, product_id)
JOIN stocked st USING (warehouse_id, product_id);

CREATE OR REPLACE VIEW v_stock_turnover_classified AS
SELECT t.*,
       CASE NTILE(4) OVER (ORDER BY stock_turnover DESC)
            WHEN 1 THEN 'Fast' WHEN 4 THEN 'Slow' ELSE 'Medium' END AS movement_class
FROM v_stock_turnover t;

CREATE OR REPLACE VIEW v_monthly_sales AS
WITH m AS (
    SELECT DATE_TRUNC('month', order_date)::date AS month, SUM(revenue) AS revenue, SUM(quantity) AS units
    FROM sales GROUP BY 1
)
SELECT month, revenue, units,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 1) AS mom_growth_pct
FROM m;

-- Reorder alerts per warehouse x product, with days of stock left at the last-90-day sales rate
CREATE OR REPLACE VIEW v_reorder_alerts AS
WITH recent AS (
    SELECT warehouse_id, product_id, SUM(quantity) / 90.0 AS daily_demand
    FROM sales
    WHERE order_date > (SELECT MAX(order_date) FROM sales) - 90
    GROUP BY warehouse_id, product_id
)
SELECT i.warehouse_id, w.warehouse_name, i.product_id, p.product_name, p.category,
       i.current_stock, i.reorder_level,
       i.reorder_level - i.current_stock                       AS shortfall,
       ROUND(r.daily_demand, 2)                                AS daily_demand,
       ROUND(i.current_stock / NULLIF(r.daily_demand, 0), 1)   AS days_of_stock_left,
       p.lead_time_days
FROM inventory i
JOIN products p USING (product_id)
JOIN warehouses w USING (warehouse_id)
LEFT JOIN recent r USING (warehouse_id, product_id)
WHERE i.current_stock <= i.reorder_level;

CREATE OR REPLACE VIEW v_warehouse_summary AS
SELECT w.warehouse_id, w.warehouse_name, w.region,
       COALESCE(s.revenue, 0) AS revenue, COALESCE(s.units, 0) AS units,
       i.total_stock, i.low_stock_items, i.skus
FROM warehouses w
LEFT JOIN (SELECT warehouse_id, SUM(revenue) AS revenue, SUM(quantity) AS units FROM sales GROUP BY 1) s USING (warehouse_id)
LEFT JOIN (SELECT warehouse_id, SUM(current_stock) AS total_stock, COUNT(*) AS skus,
                  COUNT(*) FILTER (WHERE current_stock <= reorder_level) AS low_stock_items
           FROM inventory GROUP BY 1) i USING (warehouse_id);

CREATE OR REPLACE VIEW v_kpi_summary AS
SELECT (SELECT SUM(revenue) FROM sales)                                      AS total_sales,
       (SELECT SUM(quantity) FROM sales)                                     AS units_sold,
       (SELECT SUM(current_stock) FROM inventory)                            AS total_stock,
       (SELECT COUNT(*) FROM inventory WHERE current_stock <= reorder_level) AS low_stock_items;
