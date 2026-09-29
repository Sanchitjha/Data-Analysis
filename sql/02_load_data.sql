-- Manual load with psql (the ETL uses COPY through psycopg2 and does not need this file).
-- Run from the repo root after `invsales etl --no-db`; adjust the preset folder if needed:
--   psql -d inventory -f sql/01_schema.sql -f sql/02_load_data.sql -f sql/04_views.sql
\copy warehouses FROM 'data/demo/clean/warehouses.csv' CSV HEADER
\copy products FROM 'data/demo/clean/products.csv' CSV HEADER
\copy inventory FROM 'data/demo/clean/inventory.csv' CSV HEADER
\copy sales (order_id, order_date, warehouse_id, product_id, quantity, unit_price, revenue) FROM 'data/demo/clean/sales.csv' CSV HEADER
\copy restocks FROM 'data/demo/clean/restocks.csv' CSV HEADER
