-- PostgreSQL analysis queries (multi-warehouse). Requires sql/04_views.sql (the ETL creates the views).

-- 1. Headline KPIs -----------------------------------------------------------
SELECT * FROM v_kpi_summary;

-- 2. Top 10 products by revenue -------------------------------------------------
SELECT p.product_id, p.product_name, p.category, SUM(s.quantity) AS units_sold, SUM(s.revenue) AS revenue
FROM sales s JOIN products p USING (product_id)
GROUP BY p.product_id, p.product_name, p.category
ORDER BY revenue DESC LIMIT 10;

-- 3. Monthly sales with month-over-month growth -----------------------------------
SELECT * FROM v_monthly_sales ORDER BY month;

-- 4. Warehouse comparison ---------------------------------------------------------
SELECT * FROM v_warehouse_summary ORDER BY revenue DESC;

-- 5. Stock turnover: slowest 10 warehouse-product pairs (capital tied up) -----------------
SELECT warehouse_id, product_name, current_stock, stock_turnover, days_of_inventory, movement_class
FROM v_stock_turnover_classified ORDER BY stock_turnover LIMIT 10;

-- 6. Reorder alerts, most urgent first ----------------------------------------------------
SELECT warehouse_name, product_name, current_stock, reorder_level, shortfall, days_of_stock_left, lead_time_days
FROM v_reorder_alerts ORDER BY days_of_stock_left NULLS LAST, shortfall DESC;

-- 7. Category performance with share of revenue and gross margin ----------------------------
SELECT p.category, ROUND(SUM(s.revenue), 0) AS revenue,
       ROUND(100.0 * SUM(s.revenue) / SUM(SUM(s.revenue)) OVER (), 1)                      AS revenue_share_pct,
       ROUND(100.0 * SUM(s.revenue - s.quantity * p.unit_cost) / SUM(s.revenue), 1)        AS margin_pct
FROM sales s JOIN products p USING (product_id)
GROUP BY p.category ORDER BY revenue DESC;

-- 8. Transfer candidates: same product overstocked in one warehouse, short in another ---------
WITH stat AS (
    SELECT warehouse_id, product_id, current_stock, reorder_level,
           current_stock - 2 * reorder_level AS surplus,
           reorder_level - current_stock     AS deficit
    FROM inventory
)
SELECT d.product_id, s.warehouse_id AS from_wh, d.warehouse_id AS to_wh,
       LEAST(s.surplus, d.deficit) AS transfer_qty
FROM stat d JOIN stat s ON s.product_id = d.product_id AND s.warehouse_id <> d.warehouse_id
WHERE d.deficit > 0 AND s.surplus > 0
ORDER BY transfer_qty DESC LIMIT 20;

-- 9. Data-quality check after loading -----------------------------------------------------------
SELECT (SELECT COUNT(*) FROM sales)                                                     AS sales_rows,
       (SELECT COUNT(*) FROM sales WHERE revenue <> ROUND(quantity * unit_price, 2))   AS bad_revenue_rows,
       (SELECT COUNT(*) FROM inventory)                                                 AS inventory_rows;
