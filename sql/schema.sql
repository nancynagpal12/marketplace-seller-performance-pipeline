
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id VARCHAR(36) PRIMARY KEY,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,
    rows_processed BIGINT DEFAULT 0,
    error_message TEXT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_issue (
    issue_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL,
    rule_id VARCHAR(10) NOT NULL,
    order_id VARCHAR(50) NULL,
    order_item_id INT NULL,
    issue_type VARCHAR(100) NOT NULL,
    description TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_dq_pipeline_run
        FOREIGN KEY (run_id)
        REFERENCES pipeline_run(run_id),

    INDEX idx_dq_run_id (run_id),
    INDEX idx_dq_rule_id (rule_id),
    INDEX idx_dq_order_id (order_id)
);


-- Customer dimension (R1)
CREATE TABLE IF NOT EXISTS dim_customer (
    customer_unique_id VARCHAR(32) PRIMARY KEY,
    home_state CHAR(2),
    state_name VARCHAR(100),
    region VARCHAR(30)
) ENGINE=InnoDB;


-- Seller dimension
CREATE TABLE IF NOT EXISTS dim_seller (
    seller_id VARCHAR(32) PRIMARY KEY,
    seller_zip_code_prefix VARCHAR(5),
    seller_city VARCHAR(100),
    seller_state CHAR(2),
    state_name VARCHAR(100),
    region VARCHAR(30)
) ENGINE=InnoDB;


-- Product dimension
CREATE TABLE IF NOT EXISTS dim_product (
    product_id VARCHAR(32) PRIMARY KEY,
    product_category_name VARCHAR(100),
    english_category VARCHAR(100) NOT NULL,
    product_name_length INT,
    product_description_length INT,
    product_photos_qty INT,
    product_weight_g DECIMAL(10,2),
    product_length_cm DECIMAL(10,2),
    product_height_cm DECIMAL(10,2),
    product_width_cm DECIMAL(10,2)
) ENGINE=InnoDB;


-- Order-level fact table
CREATE TABLE IF NOT EXISTS fact_order (
    order_id VARCHAR(32) PRIMARY KEY,
    customer_unique_id VARCHAR(32),
    order_status VARCHAR(30),
    order_purchase_timestamp DATETIME,
    order_approved_at DATETIME,
    order_delivered_carrier_date DATETIME,
    order_delivered_customer_date DATETIME,
    order_estimated_delivery_date DATETIME,
    revenue_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    order_revenue_brl DECIMAL(15,2),
    order_revenue_usd DECIMAL(15,2),
    on_time_delivery BOOLEAN,

    INDEX idx_order_purchase (order_purchase_timestamp),
    INDEX idx_order_customer (customer_unique_id),

    CONSTRAINT fk_order_customer
        FOREIGN KEY (customer_unique_id)
        REFERENCES dim_customer(customer_unique_id)
) ENGINE=InnoDB;


-- Order-item-level fact table
CREATE TABLE IF NOT EXISTS fact_order_item (
    order_id VARCHAR(32) NOT NULL,
    order_item_id INT NOT NULL,
    product_id VARCHAR(32),
    seller_id VARCHAR(32),
    category_name VARCHAR(100),

    price_brl DECIMAL(15,2),
    freight_value_brl DECIMAL(15,2),
    item_gross_brl DECIMAL(15,2),
    item_gross_usd DECIMAL(15,2),

    fx_rate DECIMAL(12,6),
    fx_rate_date DATE,
    fx_transaction_date DATE NULL,

    commission_rate DECIMAL(8,6),
    commission_brl DECIMAL(15,2),
    commission_usd DECIMAL(15,2),

    distance_km DECIMAL(12,4),
    campaign_id VARCHAR(50),

    PRIMARY KEY (order_id, order_item_id),

    INDEX idx_item_product (product_id),
    INDEX idx_item_seller (seller_id),
    INDEX idx_item_campaign (campaign_id),

    CONSTRAINT fk_item_order
        FOREIGN KEY (order_id)
        REFERENCES fact_order(order_id),

    CONSTRAINT fk_item_product
        FOREIGN KEY (product_id)
        REFERENCES dim_product(product_id),

    CONSTRAINT fk_item_seller
        FOREIGN KEY (seller_id)
        REFERENCES dim_seller(seller_id)
) ENGINE=InnoDB;


-- Monthly seller performance and tier (R12)
CREATE TABLE IF NOT EXISTS fact_seller_monthly (
    seller_id VARCHAR(32) NOT NULL,
    order_month DATE NOT NULL,
    eligible_revenue_brl DECIMAL(15,2) DEFAULT 0,
    seller_tier VARCHAR(20) NOT NULL,

    PRIMARY KEY (seller_id, order_month),

    CONSTRAINT fk_monthly_seller
        FOREIGN KEY (seller_id)
        REFERENCES dim_seller(seller_id)
) ENGINE=InnoDB;


-- Seller-level delivery responsibility (R11)
CREATE TABLE IF NOT EXISTS fact_seller_order_delivery (
    order_id VARCHAR(32) NOT NULL,
    seller_id VARCHAR(32) NOT NULL,
    earliest_shipping_limit_date DATETIME,
    carrier_handoff_date DATETIME,
    delivered_customer_date DATETIME,
    estimated_delivery_date DATETIME,
    delivery_responsibility VARCHAR(30),

    PRIMARY KEY (order_id, seller_id),

    CONSTRAINT fk_delivery_order
        FOREIGN KEY (order_id)
        REFERENCES fact_order(order_id),

    CONSTRAINT fk_delivery_seller
        FOREIGN KEY (seller_id)
        REFERENCES dim_seller(seller_id)
) ENGINE=InnoDB;


-- Deduplicated order reviews attributed to sellers (R14)
CREATE TABLE IF NOT EXISTS fact_order_review (
    order_id VARCHAR(32) NOT NULL,
    seller_id VARCHAR(32) NOT NULL,
    review_score INT,
    review_answer_timestamp DATETIME,

    PRIMARY KEY (order_id, seller_id),

    CONSTRAINT fk_review_order
        FOREIGN KEY (order_id)
        REFERENCES fact_order(order_id),

    CONSTRAINT fk_review_seller
        FOREIGN KEY (seller_id)
        REFERENCES dim_seller(seller_id)
) ENGINE=InnoDB;


CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_id VARCHAR(50) PRIMARY KEY,
    campaign_name VARCHAR(150),
    start_date DATETIME(6),
    end_date DATETIME(6),
    priority INT,
    target_states JSON,
    target_regions JSON,
    categories JSON
) ENGINE=InnoDB;

