-- Sample data for LARS SQL connection testing
-- Oracle version (runs as APP_USER)

-- Customers table
CREATE TABLE customers (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR2(100) NOT NULL,
    email VARCHAR2(100) UNIQUE,
    company VARCHAR2(100),
    industry VARCHAR2(50),
    country VARCHAR2(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Alice Johnson', 'alice@techcorp.com', 'TechCorp Inc', 'Technology', 'USA');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Bob Smith', 'bob@acme.co', 'Acme Corporation', 'Manufacturing', 'USA');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Carlos Garcia', 'carlos@globex.mx', 'Globex SA', 'Retail', 'Mexico');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Diana Chen', 'diana@innovate.cn', 'Innovate Ltd', 'Technology', 'China');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Erik Mueller', 'erik@deutsche.de', 'Deutsche GmbH', 'Finance', 'Germany');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Fatima Al-Hassan', 'fatima@gulf.ae', 'Gulf Trading', 'Trading', 'UAE');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('George Brown', 'george@aussie.au', 'Aussie Co', 'Mining', 'Australia');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Hannah Lee', 'hannah@seoul.kr', 'Seoul Tech', 'Technology', 'South Korea');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Ivan Petrov', 'ivan@moscow.ru', 'Moscow Corp', 'Energy', 'Russia');
INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Julia Santos', 'julia@saopaulo.br', 'SP Industries', 'Manufacturing', 'Brazil');

-- Products table
CREATE TABLE products (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku VARCHAR2(20) UNIQUE NOT NULL,
    name VARCHAR2(100) NOT NULL,
    category VARCHAR2(50),
    price NUMBER(10,2),
    stock_quantity NUMBER DEFAULT 0,
    description CLOB
);

INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('LAPTOP-001', 'ProBook 15', 'Electronics', 1299.99, 50, 'Professional laptop with 15" display');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('LAPTOP-002', 'UltraSlim 13', 'Electronics', 999.99, 75, 'Lightweight ultrabook');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('PHONE-001', 'SmartPhone X', 'Electronics', 799.99, 200, 'Latest flagship smartphone');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('TABLET-001', 'TabPro 10', 'Electronics', 499.99, 100, '10-inch tablet with stylus');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('CHAIR-001', 'ErgoChair Pro', 'Furniture', 399.99, 30, 'Ergonomic office chair');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('DESK-001', 'Standing Desk L', 'Furniture', 599.99, 20, 'Electric standing desk');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('MONITOR-001', '4K Display 27', 'Electronics', 449.99, 60, '27-inch 4K monitor');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('KEYBOARD-001', 'MechKey Pro', 'Accessories', 149.99, 150, 'Mechanical keyboard');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('MOUSE-001', 'ErgoMouse', 'Accessories', 79.99, 200, 'Ergonomic wireless mouse');
INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('HEADSET-001', 'AudioPro 7', 'Accessories', 199.99, 80, 'Noise-canceling headset');

-- Orders table
CREATE TABLE orders (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id NUMBER REFERENCES customers(id),
    order_date DATE DEFAULT SYSDATE,
    status VARCHAR2(20) DEFAULT 'pending',
    total_amount NUMBER(10,2),
    shipping_address CLOB,
    notes CLOB
);

INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (1, DATE '2024-01-15', 'completed', 1449.98, '123 Tech St, San Francisco, CA', 'Express shipping requested');
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (2, DATE '2024-01-16', 'completed', 599.99, '456 Industrial Ave, Detroit, MI', NULL);
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (3, DATE '2024-01-17', 'shipped', 1299.98, 'Av. Reforma 100, Mexico City', 'International shipping');
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (4, DATE '2024-01-18', 'processing', 2099.97, '88 Innovation Rd, Shenzhen', 'Bulk order discount applied');
INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (5, DATE '2024-01-19', 'completed', 399.99, 'Hauptstrasse 1, Berlin', NULL);

-- Support tickets table
CREATE TABLE support_tickets (
    id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id NUMBER REFERENCES customers(id),
    subject VARCHAR2(200) NOT NULL,
    description CLOB,
    priority VARCHAR2(20) DEFAULT 'normal',
    status VARCHAR2(20) DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
    (1, 'Laptop screen flickering', 'My ProBook 15 screen flickers when running on battery.', 'high', 'open');
INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
    (2, 'Desk motor not working', 'The standing desk motor stopped responding.', 'normal', 'in_progress');
INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
    (3, 'Wrong item received', 'Ordered UltraSlim 13 but received ProBook 15 instead.', 'high', 'resolved');

COMMIT;
