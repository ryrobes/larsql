-- DB2 Sample Data for LARS SQL Connections Testing
-- This script creates tables matching the schema used in other test databases

CONNECT TO testdb;

-- Customers table
CREATE TABLE customers (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    country VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Products table
CREATE TABLE products (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(100),
    price DECIMAL(10, 2) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE orders (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'pending',
    total_amount DECIMAL(12, 2),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- Order items table
CREATE TABLE order_items (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Support tickets table
CREATE TABLE support_tickets (
    id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    subject VARCHAR(255) NOT NULL,
    description CLOB,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(50) DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    CONSTRAINT fk_tickets_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- Insert sample customers
INSERT INTO customers (name, email, city, country) VALUES
    ('Alice Johnson', 'alice@example.com', 'New York', 'USA'),
    ('Bob Smith', 'bob@example.com', 'Los Angeles', 'USA'),
    ('Carol Williams', 'carol@example.com', 'Chicago', 'USA'),
    ('David Brown', 'david@example.com', 'Houston', 'USA'),
    ('Eva Martinez', 'eva@example.com', 'Phoenix', 'USA'),
    ('Frank Garcia', 'frank@example.com', 'Toronto', 'Canada'),
    ('Grace Lee', 'grace@example.com', 'Vancouver', 'Canada'),
    ('Henry Wilson', 'henry@example.com', 'London', 'UK'),
    ('Ivy Taylor', 'ivy@example.com', 'Manchester', 'UK'),
    ('Jack Anderson', 'jack@example.com', 'Sydney', 'Australia');

-- Insert sample products
INSERT INTO products (name, category, price, stock_quantity) VALUES
    ('Laptop Pro 15', 'Electronics', 1299.99, 50),
    ('Wireless Mouse', 'Electronics', 29.99, 200),
    ('USB-C Hub', 'Electronics', 49.99, 150),
    ('Mechanical Keyboard', 'Electronics', 149.99, 75),
    ('Monitor 27 inch', 'Electronics', 399.99, 30),
    ('Office Chair', 'Furniture', 299.99, 25),
    ('Standing Desk', 'Furniture', 599.99, 15),
    ('Desk Lamp', 'Furniture', 39.99, 100),
    ('Notebook Set', 'Office Supplies', 12.99, 500),
    ('Pen Pack', 'Office Supplies', 8.99, 1000);

-- Insert sample orders
INSERT INTO orders (customer_id, status, total_amount) VALUES
    (1, 'completed', 1349.98),
    (2, 'completed', 449.98),
    (3, 'pending', 599.99),
    (1, 'shipped', 179.98),
    (4, 'completed', 1299.99),
    (5, 'pending', 339.98),
    (6, 'completed', 49.99),
    (7, 'shipped', 899.98),
    (8, 'completed', 21.98),
    (9, 'pending', 149.99);

-- Insert sample order items
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 1299.99),
    (1, 2, 1, 29.99),
    (1, 3, 1, 49.99),
    (2, 5, 1, 399.99),
    (2, 3, 1, 49.99),
    (3, 7, 1, 599.99),
    (4, 4, 1, 149.99),
    (4, 2, 1, 29.99),
    (5, 1, 1, 1299.99),
    (6, 6, 1, 299.99),
    (6, 8, 1, 39.99),
    (7, 3, 1, 49.99),
    (8, 7, 1, 599.99),
    (8, 6, 1, 299.99),
    (9, 9, 1, 12.99),
    (9, 10, 1, 8.99),
    (10, 4, 1, 149.99);

-- Insert sample support tickets
INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
    (1, 'Laptop not charging', 'My new laptop stopped charging after 2 weeks of use.', 'high', 'open'),
    (2, 'Wrong item received', 'I ordered a keyboard but received a mouse instead.', 'medium', 'resolved'),
    (3, 'Shipping delay inquiry', 'My order has been pending for 5 days. When will it ship?', 'low', 'open'),
    (4, 'Return request', 'I would like to return the monitor as it has dead pixels.', 'high', 'in_progress'),
    (5, 'Product question', 'Does the standing desk come with assembly instructions?', 'low', 'resolved');

COMMIT;

CONNECT RESET;
