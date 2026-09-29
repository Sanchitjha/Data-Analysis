-- Reporting views used by Power BI, the Streamlit dashboard and the alerting job.
-- Created automatically by the ETL (invsales etl); safe to re-run.

CREATE OR REPLACE VIEW v_stock_turnover AS
WITH opening AS (
    SELECT DISTINCT ON (product_id) product_id, quantity AS opening_stock
    FROM restocks ORDER BY product_id, restock_date
), sold AS (
    SELECT product_id, SUM(quantity) AS units_sold, SUM(revenue) AS revenue,
           MAX(order_date) - MIN(order_date) + 1 AS days_selling
    FROM sales GROUP BY product_id
), stocked AS (
    SELECT product_id, SUM(quantity) AS units_restocked, COUNT(*) - 1 AS restock_events
    FROM restocks GROUP BY product_id
)
SELECT p.product_id, p.product_name, p.category,
       p.current_stock, p.reorder_level,
       sd.units_sold, st.units_restocked, st.restock_events,
       ROUND((o.opening_stock + p.current_stock) / 2.0, 1)                        AS avg_stock,
       ROUND(sd.units_sold / ((o.opening_stock + p.current_stock) / 2.0), 2)      AS stock_turnover,
       ROUND(sd.days_selling / (sd.units_sold / ((o.opening_stock + p.current_stock) / 2.0)), 0) AS days_of_inventory
FROM products p
JOIN opening o USING (product_id)
JOIN sold sd USING (product_id)
JOIN stocked st USING (product_id);

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

CREATE OR REPLACE VIEW v_reorder_alerts AS
WITH recent AS (
    SELECT product_id, SUM(quantity) / 90.0 AS daily_demand
    FROM sales
    WHERE order_date > (SELECT MAX(order_date) FROM sales) - 90
    GROUP BY product_id
)
SELECT p.product_id, p.product_name, p.category, p.current_stock, p.reorder_level,
       p.reorder_level - p.current_stock                      AS shortfall,
       ROUND(r.daily_demand, 2)                               AS daily_demand,
       ROUND(p.current_stock / NULLIF(r.daily_demand, 0), 1)  AS days_of_stock_left,
       p.lead_time_days
FROM products p LEFT JOIN recent r USING (product_id)
WHERE p.current_stock <= p.reorder_level;

CREATE OR REPLACE VIEW v_kpi_summary AS
SELECT (SELECT SUM(revenue) FROM sales)                                    AS total_sales,
       (SELECT SUM(quantity) FROM sales)                                   AS units_sold,
       (SELECT SUM(current_stock) FROM products)                           AS total_stock,
       (SELECT COUNT(*) FROM products WHERE current_stock <= reorder_level) AS low_stock_items;
