-- PostgreSQL schema. Load order: products -> sales, restocks
DROP TABLE IF EXISTS sales, restocks, products CASCADE;

CREATE TABLE products (
    product_id     VARCHAR(10) PRIMARY KEY,
    product_name   TEXT NOT NULL,
    category       TEXT NOT NULL,
    unit_cost      NUMERIC(10,2) NOT NULL,
    unit_price     NUMERIC(10,2) NOT NULL,
    lead_time_days INT NOT NULL,
    reorder_level  INT NOT NULL,
    current_stock  INT NOT NULL
);

CREATE TABLE sales (
    order_id    VARCHAR(12) PRIMARY KEY,
    order_date  DATE NOT NULL,
    product_id  VARCHAR(10) NOT NULL REFERENCES products,
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(10,2) NOT NULL,
    store       TEXT NOT NULL,
    revenue     NUMERIC(12,2) NOT NULL
);

CREATE TABLE restocks (
    restock_date DATE NOT NULL,
    product_id   VARCHAR(10) NOT NULL REFERENCES products,
    quantity     INT NOT NULL
);

CREATE INDEX idx_sales_date ON sales(order_date);
CREATE INDEX idx_sales_product ON sales(product_id);
