-- PostgreSQL analysis queries: Inventory & Sales Analytics

-- 1. Headline KPIs -----------------------------------------------------------
SELECT SUM(revenue)                         AS total_sales,
       SUM(quantity)                        AS units_sold,
       COUNT(DISTINCT order_id)             AS order_lines,
       (SELECT SUM(current_stock) FROM products) AS total_stock_units,
       (SELECT COUNT(*) FROM products WHERE current_stock <= reorder_level) AS low_stock_items
FROM sales;

-- 2. Top 10 products by revenue -------------------------------------------------
SELECT p.product_id, p.product_name, p.category,
       SUM(s.quantity) AS units_sold,
       SUM(s.revenue)  AS revenue
FROM sales s JOIN products p USING (product_id)
GROUP BY p.product_id, p.product_name, p.category
ORDER BY revenue DESC
LIMIT 10;

-- 3. Monthly sales with month-over-month growth ------------------------------------
WITH monthly AS (
    SELECT DATE_TRUNC('month', order_date)::date AS month,
           SUM(revenue) AS revenue, SUM(quantity) AS units
    FROM sales GROUP BY 1
)
SELECT month, revenue, units,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 1) AS mom_growth_pct
FROM monthly ORDER BY month;

-- 4. Stock turnover per product ------------------------------------------------------
-- turnover = units sold / average stock,  average stock = (opening stock + current stock) / 2
-- opening stock = the first restock row (initial stock-in on the first day)
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

SELECT * FROM v_stock_turnover ORDER BY stock_turnover DESC;

-- 5. Fast vs slow movers (quartiles of turnover) -----------------------------------------
SELECT product_name, category, stock_turnover, days_of_inventory,
       CASE NTILE(4) OVER (ORDER BY stock_turnover DESC)
            WHEN 1 THEN 'Fast'
            WHEN 4 THEN 'Slow'
            ELSE 'Medium' END AS movement_class
FROM v_stock_turnover
ORDER BY stock_turnover DESC;

-- 6. Reorder alerts: stock at or below reorder level ------------------------------------------
-- average daily demand over the last 90 days -> how many days of stock are left
WITH recent AS (
    SELECT product_id, SUM(quantity) / 90.0 AS daily_demand
    FROM sales
    WHERE order_date > (SELECT MAX(order_date) FROM sales) - 90
    GROUP BY product_id
)
SELECT p.product_id, p.product_name, p.category,
       p.current_stock, p.reorder_level,
       p.reorder_level - p.current_stock                    AS shortfall,
       ROUND(r.daily_demand, 2)                             AS daily_demand,
       ROUND(p.current_stock / NULLIF(r.daily_demand, 0), 1) AS days_of_stock_left,
       p.lead_time_days
FROM products p LEFT JOIN recent r USING (product_id)
WHERE p.current_stock <= p.reorder_level
ORDER BY days_of_stock_left;

-- 7. Category performance and share of revenue -----------------------------------------------------
SELECT p.category, SUM(s.revenue) AS revenue,
       ROUND(100.0 * SUM(s.revenue) / SUM(SUM(s.revenue)) OVER (), 1) AS revenue_share_pct
FROM sales s JOIN products p USING (product_id)
GROUP BY p.category ORDER BY revenue DESC;

-- 8. Gross margin by category -------------------------------------------------------------------------
SELECT p.category,
       ROUND(SUM(s.revenue), 0)                                    AS revenue,
       ROUND(SUM(s.revenue - s.quantity * p.unit_cost), 0)         AS gross_profit,
       ROUND(100.0 * SUM(s.revenue - s.quantity * p.unit_cost) / SUM(s.revenue), 1) AS margin_pct
FROM sales s JOIN products p USING (product_id)
GROUP BY p.category ORDER BY gross_profit DESC;

-- 9. Data-quality check after loading ---------------------------------------------------------------------
SELECT (SELECT COUNT(*) FROM sales)    AS sales_rows,
       (SELECT COUNT(*) FROM sales WHERE revenue <> ROUND(quantity * unit_price, 2)) AS bad_revenue_rows,
       (SELECT COUNT(*) FROM sales s LEFT JOIN products p USING (product_id) WHERE p.product_id IS NULL) AS orphan_sales;
