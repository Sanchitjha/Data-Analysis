-- Run from the repo root with psql (client-side \copy):
--   psql -d inventory -f sql/01_schema.sql -f sql/02_load_data.sql
-- Column order in the CSVs differs from the tables, so columns are listed explicitly.
\copy products (product_id, product_name, category, unit_cost, unit_price, lead_time_days, reorder_level, current_stock) FROM 'data/clean/products.csv' CSV HEADER
\copy sales (order_id, order_date, product_id, quantity, unit_price, store, revenue) FROM 'data/clean/sales.csv' CSV HEADER
\copy restocks (restock_date, product_id, quantity) FROM 'data/clean/restocks.csv' CSV HEADER
