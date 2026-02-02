-- Sample data for LARS SQL connection testing
-- PostgreSQL version

-- Customers table
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE,
    company VARCHAR(100),
    industry VARCHAR(50),
    country VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO customers (name, email, company, industry, country) VALUES
    ('Alice Johnson', 'alice@techcorp.com', 'TechCorp Inc', 'Technology', 'USA'),
    ('Bob Smith', 'bob@acme.co', 'Acme Corporation', 'Manufacturing', 'USA'),
    ('Carlos Garcia', 'carlos@globex.mx', 'Globex SA', 'Retail', 'Mexico'),
    ('Diana Chen', 'diana@innovate.cn', 'Innovate Ltd', 'Technology', 'China'),
    ('Erik Müller', 'erik@deutsche.de', 'Deutsche GmbH', 'Finance', 'Germany'),
    ('Fatima Al-Hassan', 'fatima@gulf.ae', 'Gulf Trading', 'Trading', 'UAE'),
    ('George Brown', 'george@aussie.au', 'Aussie Co', 'Mining', 'Australia'),
    ('Hannah Lee', 'hannah@seoul.kr', 'Seoul Tech', 'Technology', 'South Korea'),
    ('Ivan Petrov', 'ivan@moscow.ru', 'Moscow Corp', 'Energy', 'Russia'),
    ('Julia Santos', 'julia@saopaulo.br', 'SP Industries', 'Manufacturing', 'Brazil');

-- Products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10,2),
    stock_quantity INTEGER DEFAULT 0,
    description TEXT
);

INSERT INTO products (sku, name, category, price, stock_quantity, description) VALUES
    ('LAPTOP-001', 'ProBook 15', 'Electronics', 1299.99, 50, 'Professional laptop with 15" display'),
    ('LAPTOP-002', 'UltraSlim 13', 'Electronics', 999.99, 75, 'Lightweight ultrabook'),
    ('PHONE-001', 'SmartPhone X', 'Electronics', 799.99, 200, 'Latest flagship smartphone'),
    ('TABLET-001', 'TabPro 10', 'Electronics', 499.99, 100, '10-inch tablet with stylus'),
    ('CHAIR-001', 'ErgoChair Pro', 'Furniture', 399.99, 30, 'Ergonomic office chair'),
    ('DESK-001', 'Standing Desk L', 'Furniture', 599.99, 20, 'Electric standing desk'),
    ('MONITOR-001', '4K Display 27', 'Electronics', 449.99, 60, '27-inch 4K monitor'),
    ('KEYBOARD-001', 'MechKey Pro', 'Accessories', 149.99, 150, 'Mechanical keyboard'),
    ('MOUSE-001', 'ErgoMouse', 'Accessories', 79.99, 200, 'Ergonomic wireless mouse'),
    ('HEADSET-001', 'AudioPro 7', 'Accessories', 199.99, 80, 'Noise-canceling headset');

-- Orders table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    order_date DATE DEFAULT CURRENT_DATE,
    status VARCHAR(20) DEFAULT 'pending',
    total_amount DECIMAL(10,2),
    shipping_address TEXT,
    notes TEXT
);

INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
    (1, '2024-01-15', 'completed', 1449.98, '123 Tech St, San Francisco, CA', 'Express shipping requested'),
    (2, '2024-01-16', 'completed', 599.99, '456 Industrial Ave, Detroit, MI', NULL),
    (3, '2024-01-17', 'shipped', 1299.98, 'Av. Reforma 100, Mexico City', 'International shipping'),
    (4, '2024-01-18', 'processing', 2099.97, '88 Innovation Rd, Shenzhen', 'Bulk order discount applied'),
    (5, '2024-01-19', 'completed', 399.99, 'Hauptstraße 1, Berlin', NULL),
    (1, '2024-01-20', 'completed', 799.99, '123 Tech St, San Francisco, CA', 'Second order this month'),
    (6, '2024-01-21', 'shipped', 949.98, 'Sheikh Zayed Rd, Dubai', 'Gift wrapping'),
    (7, '2024-01-22', 'pending', 1599.98, '1 Mining Rd, Perth', 'Awaiting payment confirmation'),
    (8, '2024-01-23', 'completed', 649.98, '555 Gangnam, Seoul', NULL),
    (9, '2024-01-24', 'cancelled', 499.99, 'Tverskaya 10, Moscow', 'Customer requested cancellation');

-- Order items table
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL
);

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 1299.99), (1, 8, 1, 149.99),
    (2, 6, 1, 599.99),
    (3, 2, 1, 999.99), (3, 9, 1, 299.99),
    (4, 1, 1, 1299.99), (4, 3, 1, 799.99),
    (5, 5, 1, 399.99),
    (6, 3, 1, 799.99),
    (7, 7, 2, 449.99), (7, 9, 1, 49.99),
    (8, 2, 1, 999.99), (8, 6, 1, 599.99),
    (9, 8, 1, 149.99), (9, 4, 1, 499.99),
    (10, 4, 1, 499.99);

-- Support tickets table (good for semantic SQL testing)
CREATE TABLE support_tickets (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    subject VARCHAR(200) NOT NULL,
    description TEXT,
    priority VARCHAR(20) DEFAULT 'normal',
    status VARCHAR(20) DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
    (1, 'Laptop screen flickering', 'My ProBook 15 screen flickers when running on battery. Started after recent update.', 'high', 'open'),
    (2, 'Desk motor not working', 'The standing desk motor stopped responding. Tried unplugging and replugging.', 'normal', 'in_progress'),
    (3, 'Wrong item received', 'Ordered UltraSlim 13 but received ProBook 15 instead.', 'high', 'resolved'),
    (4, 'Bulk order discount inquiry', 'We want to order 50 units. What bulk discount can you offer?', 'low', 'open'),
    (5, 'Keyboard key stuck', 'The spacebar on my MechKey Pro is occasionally sticking.', 'normal', 'open'),
    (1, 'Follow up on screen issue', 'Still experiencing the flickering issue. Tried the suggested fixes.', 'high', 'open'),
    (6, 'International warranty', 'Does the warranty cover products shipped internationally?', 'low', 'resolved'),
    (8, 'Monitor calibration help', 'Need help calibrating colors on my new 4K Display.', 'normal', 'resolved'),
    (7, 'Payment failed', 'My credit card payment keeps getting declined even though funds are available.', 'high', 'in_progress'),
    (10, 'Product suggestion', 'Would love to see a wireless version of the MechKey Pro!', 'low', 'closed');

-- Create a view for customer order summary
CREATE VIEW customer_order_summary AS
SELECT 
    c.id AS customer_id,
    c.name AS customer_name,
    c.company,
    COUNT(o.id) AS total_orders,
    COALESCE(SUM(o.total_amount), 0) AS total_spent,
    MAX(o.order_date) AS last_order_date
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id
GROUP BY c.id, c.name, c.company;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO testuser;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO testuser;
