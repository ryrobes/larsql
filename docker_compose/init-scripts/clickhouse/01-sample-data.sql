-- Sample data for LARS SQL connection testing
-- ClickHouse version

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id UInt32,
    name String,
    email String,
    company String,
    industry String,
    country String,
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY id;

INSERT INTO customers (id, name, email, company, industry, country) VALUES
    (1, 'Alice Johnson', 'alice@techcorp.com', 'TechCorp Inc', 'Technology', 'USA'),
    (2, 'Bob Smith', 'bob@acme.co', 'Acme Corporation', 'Manufacturing', 'USA'),
    (3, 'Carlos Garcia', 'carlos@globex.mx', 'Globex SA', 'Retail', 'Mexico'),
    (4, 'Diana Chen', 'diana@innovate.cn', 'Innovate Ltd', 'Technology', 'China'),
    (5, 'Erik Müller', 'erik@deutsche.de', 'Deutsche GmbH', 'Finance', 'Germany'),
    (6, 'Fatima Al-Hassan', 'fatima@gulf.ae', 'Gulf Trading', 'Trading', 'UAE'),
    (7, 'George Brown', 'george@aussie.au', 'Aussie Co', 'Mining', 'Australia'),
    (8, 'Hannah Lee', 'hannah@seoul.kr', 'Seoul Tech', 'Technology', 'South Korea'),
    (9, 'Ivan Petrov', 'ivan@moscow.ru', 'Moscow Corp', 'Energy', 'Russia'),
    (10, 'Julia Santos', 'julia@saopaulo.br', 'SP Industries', 'Manufacturing', 'Brazil');

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id UInt32,
    sku String,
    name String,
    category String,
    price Decimal(10,2),
    stock_quantity UInt32 DEFAULT 0,
    description String
) ENGINE = MergeTree()
ORDER BY id;

INSERT INTO products (id, sku, name, category, price, stock_quantity, description) VALUES
    (1, 'LAPTOP-001', 'ProBook 15', 'Electronics', 1299.99, 50, 'Professional laptop with 15" display'),
    (2, 'LAPTOP-002', 'UltraSlim 13', 'Electronics', 999.99, 75, 'Lightweight ultrabook'),
    (3, 'PHONE-001', 'SmartPhone X', 'Electronics', 799.99, 200, 'Latest flagship smartphone'),
    (4, 'TABLET-001', 'TabPro 10', 'Electronics', 499.99, 100, '10-inch tablet with stylus'),
    (5, 'CHAIR-001', 'ErgoChair Pro', 'Furniture', 399.99, 30, 'Ergonomic office chair'),
    (6, 'DESK-001', 'Standing Desk L', 'Furniture', 599.99, 20, 'Electric standing desk'),
    (7, 'MONITOR-001', '4K Display 27', 'Electronics', 449.99, 60, '27-inch 4K monitor'),
    (8, 'KEYBOARD-001', 'MechKey Pro', 'Accessories', 149.99, 150, 'Mechanical keyboard'),
    (9, 'MOUSE-001', 'ErgoMouse', 'Accessories', 79.99, 200, 'Ergonomic wireless mouse'),
    (10, 'HEADSET-001', 'AudioPro 7', 'Accessories', 199.99, 80, 'Noise-canceling headset');

-- Orders table (denormalized for analytics)
CREATE TABLE IF NOT EXISTS orders (
    id UInt32,
    customer_id UInt32,
    order_date Date,
    status String DEFAULT 'pending',
    total_amount Decimal(10,2),
    shipping_address String,
    notes String
) ENGINE = MergeTree()
ORDER BY (order_date, id);

INSERT INTO orders (id, customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (1, 1, '2024-01-15', 'completed', 1449.98, '123 Tech St, San Francisco, CA', 'Express shipping requested'),
    (2, 2, '2024-01-16', 'completed', 599.99, '456 Industrial Ave, Detroit, MI', ''),
    (3, 3, '2024-01-17', 'shipped', 1299.98, 'Av. Reforma 100, Mexico City', 'International shipping'),
    (4, 4, '2024-01-18', 'processing', 2099.97, '88 Innovation Rd, Shenzhen', 'Bulk order discount applied'),
    (5, 5, '2024-01-19', 'completed', 399.99, 'Hauptstraße 1, Berlin', ''),
    (6, 1, '2024-01-20', 'completed', 799.99, '123 Tech St, San Francisco, CA', 'Second order this month'),
    (7, 6, '2024-01-21', 'shipped', 949.98, 'Sheikh Zayed Rd, Dubai', 'Gift wrapping'),
    (8, 7, '2024-01-22', 'pending', 1599.98, '1 Mining Rd, Perth', 'Awaiting payment confirmation'),
    (9, 8, '2024-01-23', 'completed', 649.98, '555 Gangnam, Seoul', ''),
    (10, 9, '2024-01-24', 'cancelled', 499.99, 'Tverskaya 10, Moscow', 'Customer requested cancellation');

-- Order items table
CREATE TABLE IF NOT EXISTS order_items (
    id UInt32,
    order_id UInt32,
    product_id UInt32,
    quantity UInt32,
    unit_price Decimal(10,2)
) ENGINE = MergeTree()
ORDER BY (order_id, id);

INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 1, 1299.99), (2, 1, 8, 1, 149.99),
    (3, 2, 6, 1, 599.99),
    (4, 3, 2, 1, 999.99), (5, 3, 9, 1, 299.99),
    (6, 4, 1, 1, 1299.99), (7, 4, 3, 1, 799.99),
    (8, 5, 5, 1, 399.99),
    (9, 6, 3, 1, 799.99),
    (10, 7, 7, 2, 449.99), (11, 7, 9, 1, 49.99),
    (12, 8, 2, 1, 999.99), (13, 8, 6, 1, 599.99),
    (14, 9, 8, 1, 149.99), (15, 9, 4, 1, 499.99),
    (16, 10, 4, 1, 499.99);

-- Support tickets table
CREATE TABLE IF NOT EXISTS support_tickets (
    id UInt32,
    customer_id UInt32,
    subject String,
    description String,
    priority String DEFAULT 'normal',
    status String DEFAULT 'open',
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (created_at, id);

INSERT INTO support_tickets (id, customer_id, subject, description, priority, status) VALUES
    (1, 1, 'Laptop screen flickering', 'My ProBook 15 screen flickers when running on battery. Started after recent update.', 'high', 'open'),
    (2, 2, 'Desk motor not working', 'The standing desk motor stopped responding. Tried unplugging and replugging.', 'normal', 'in_progress'),
    (3, 3, 'Wrong item received', 'Ordered UltraSlim 13 but received ProBook 15 instead.', 'high', 'resolved'),
    (4, 4, 'Bulk order discount inquiry', 'We want to order 50 units. What bulk discount can you offer?', 'low', 'open'),
    (5, 5, 'Keyboard key stuck', 'The spacebar on my MechKey Pro is occasionally sticking.', 'normal', 'open'),
    (6, 1, 'Follow up on screen issue', 'Still experiencing the flickering issue. Tried the suggested fixes.', 'high', 'open'),
    (7, 6, 'International warranty', 'Does the warranty cover products shipped internationally?', 'low', 'resolved'),
    (8, 8, 'Monitor calibration help', 'Need help calibrating colors on my new 4K Display.', 'normal', 'resolved'),
    (9, 7, 'Payment failed', 'My credit card payment keeps getting declined even though funds are available.', 'high', 'in_progress'),
    (10, 10, 'Product suggestion', 'Would love to see a wireless version of the MechKey Pro!', 'low', 'closed');

-- Analytics view - daily sales
CREATE VIEW IF NOT EXISTS daily_sales AS
SELECT 
    order_date,
    count() AS order_count,
    sum(total_amount) AS total_revenue,
    avg(total_amount) AS avg_order_value
FROM orders
WHERE status != 'cancelled'
GROUP BY order_date
ORDER BY order_date;
