-- Sample data for LARS SQL connection testing
-- Microsoft SQL Server version
-- Note: Run after container is healthy with:
--   docker exec -it lars-test-mssql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P 'TestPass123!' -C -i /init.sql

-- Create database
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'testdb')
BEGIN
    CREATE DATABASE testdb;
END
GO

USE testdb;
GO

-- Customers table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'customers')
BEGIN
    CREATE TABLE customers (
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(100) NOT NULL,
        email NVARCHAR(100) UNIQUE,
        company NVARCHAR(100),
        industry NVARCHAR(50),
        country NVARCHAR(50),
        created_at DATETIME2 DEFAULT GETDATE()
    );

    INSERT INTO customers (name, email, company, industry, country) VALUES
        ('Alice Johnson', 'alice@techcorp.com', 'TechCorp Inc', 'Technology', 'USA'),
        ('Bob Smith', 'bob@acme.co', 'Acme Corporation', 'Manufacturing', 'USA'),
        ('Carlos Garcia', 'carlos@globex.mx', 'Globex SA', 'Retail', 'Mexico'),
        ('Diana Chen', 'diana@innovate.cn', 'Innovate Ltd', 'Technology', 'China'),
        ('Erik Mueller', 'erik@deutsche.de', 'Deutsche GmbH', 'Finance', 'Germany'),
        ('Fatima Al-Hassan', 'fatima@gulf.ae', 'Gulf Trading', 'Trading', 'UAE'),
        ('George Brown', 'george@aussie.au', 'Aussie Co', 'Mining', 'Australia'),
        ('Hannah Lee', 'hannah@seoul.kr', 'Seoul Tech', 'Technology', 'South Korea'),
        ('Ivan Petrov', 'ivan@moscow.ru', 'Moscow Corp', 'Energy', 'Russia'),
        ('Julia Santos', 'julia@saopaulo.br', 'SP Industries', 'Manufacturing', 'Brazil');
END
GO

-- Products table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'products')
BEGIN
    CREATE TABLE products (
        id INT IDENTITY(1,1) PRIMARY KEY,
        sku NVARCHAR(20) UNIQUE NOT NULL,
        name NVARCHAR(100) NOT NULL,
        category NVARCHAR(50),
        price DECIMAL(10,2),
        stock_quantity INT DEFAULT 0,
        description NVARCHAR(MAX)
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
END
GO

-- Orders table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'orders')
BEGIN
    CREATE TABLE orders (
        id INT IDENTITY(1,1) PRIMARY KEY,
        customer_id INT FOREIGN KEY REFERENCES customers(id),
        order_date DATE DEFAULT GETDATE(),
        status NVARCHAR(20) DEFAULT 'pending',
        total_amount DECIMAL(10,2),
        shipping_address NVARCHAR(MAX),
        notes NVARCHAR(MAX)
    );

    INSERT INTO orders (customer_id, order_date, status, total_amount, shipping_address, notes) VALUES
        (1, '2024-01-15', 'completed', 1449.98, '123 Tech St, San Francisco, CA', 'Express shipping requested'),
        (2, '2024-01-16', 'completed', 599.99, '456 Industrial Ave, Detroit, MI', NULL),
        (3, '2024-01-17', 'shipped', 1299.98, 'Av. Reforma 100, Mexico City', 'International shipping'),
        (4, '2024-01-18', 'processing', 2099.97, '88 Innovation Rd, Shenzhen', 'Bulk order discount applied'),
        (5, '2024-01-19', 'completed', 399.99, 'Hauptstrasse 1, Berlin', NULL);
END
GO

-- Support tickets table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'support_tickets')
BEGIN
    CREATE TABLE support_tickets (
        id INT IDENTITY(1,1) PRIMARY KEY,
        customer_id INT FOREIGN KEY REFERENCES customers(id),
        subject NVARCHAR(200) NOT NULL,
        description NVARCHAR(MAX),
        priority NVARCHAR(20) DEFAULT 'normal',
        status NVARCHAR(20) DEFAULT 'open',
        created_at DATETIME2 DEFAULT GETDATE()
    );

    INSERT INTO support_tickets (customer_id, subject, description, priority, status) VALUES
        (1, 'Laptop screen flickering', 'My ProBook 15 screen flickers when running on battery.', 'high', 'open'),
        (2, 'Desk motor not working', 'The standing desk motor stopped responding.', 'normal', 'in_progress'),
        (3, 'Wrong item received', 'Ordered UltraSlim 13 but received ProBook 15 instead.', 'high', 'resolved');
END
GO
