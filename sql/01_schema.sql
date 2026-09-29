-- PostgreSQL schema (multi-warehouse). Recreated by the ETL on every run.
DROP TABLE IF EXISTS sales, restocks, inventory, products, warehouses CASCADE;

CREATE TABLE warehouses (
    warehouse_id   VARCHAR(10) PRIMARY KEY,
    warehouse_name TEXT NOT NULL,
    region         TEXT NOT NULL
);

CREATE TABLE products (
    product_id     VARCHAR(10) PRIMARY KEY,
    product_name   TEXT NOT NULL,
    category       TEXT NOT NULL,
    unit_cost      NUMERIC(10,2) NOT NULL,
    unit_price     NUMERIC(10,2) NOT NULL,
    lead_time_days INT NOT NULL
);

-- closing stock snapshot per warehouse and product
CREATE TABLE inventory (
    warehouse_id  VARCHAR(10) NOT NULL REFERENCES warehouses,
    product_id    VARCHAR(10) NOT NULL REFERENCES products,
    current_stock INT NOT NULL CHECK (current_stock >= 0),
    reorder_level INT NOT NULL CHECK (reorder_level >= 0),
    PRIMARY KEY (warehouse_id, product_id)
);

CREATE TABLE sales (
    order_id     VARCHAR(12) PRIMARY KEY,
    order_date   DATE NOT NULL,
    warehouse_id VARCHAR(10) NOT NULL REFERENCES warehouses,
    product_id   VARCHAR(10) NOT NULL REFERENCES products,
    quantity     INT NOT NULL CHECK (quantity > 0),
    unit_price   NUMERIC(10,2) NOT NULL,
    revenue      NUMERIC(12,2) NOT NULL
);

CREATE TABLE restocks (
    restock_date DATE NOT NULL,
    warehouse_id VARCHAR(10) NOT NULL REFERENCES warehouses,
    product_id   VARCHAR(10) NOT NULL REFERENCES products,
    quantity     INT NOT NULL
);

-- access paths for the dashboard / API / Power BI: time filters, per-product and per-warehouse rollups
CREATE INDEX idx_sales_date         ON sales (order_date);
CREATE INDEX idx_sales_product_date ON sales (product_id, order_date);
CREATE INDEX idx_sales_wh_date      ON sales (warehouse_id, order_date);
CREATE INDEX idx_restocks_wp_date   ON restocks (warehouse_id, product_id, restock_date);
