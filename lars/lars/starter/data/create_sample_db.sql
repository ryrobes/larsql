-- =============================================================================
-- RVBBIT Sample Database
-- =============================================================================
-- Run this script to create sample data for testing RVBBIT features.
--
-- Usage with DuckDB CLI:
--   duckdb data/sample.duckdb < data/create_sample_db.sql
--
-- Usage with Python:
--   import duckdb
--   conn = duckdb.connect('data/sample.duckdb')
--   conn.execute(open('data/create_sample_db.sql').read())
--
-- After creation, crawl the schema:
--   rvbbit sql crawl
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Customers Table
-- Represents a B2B SaaS customer base
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    email VARCHAR NOT NULL UNIQUE,
    company VARCHAR NOT NULL,
    industry VARCHAR,
    company_size VARCHAR,
    country VARCHAR DEFAULT 'USA',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP
);

INSERT INTO customers VALUES
    (1, 'Alice Chen', 'alice@acme.com', 'Acme Corp', 'Technology', 'Enterprise', 'USA', '2024-01-15 09:30:00', '2025-01-10 14:22:00'),
    (2, 'Bob Smith', 'bob@globaltech.io', 'GlobalTech', 'Technology', 'Mid-Market', 'USA', '2024-01-20 11:45:00', '2025-01-12 16:45:00'),
    (3, 'Carol Davis', 'carol@greenco.org', 'GreenCo', 'Sustainability', 'SMB', 'Canada', '2024-02-01 14:00:00', '2025-01-08 10:30:00'),
    (4, 'David Lee', 'david@finserv.com', 'FinServ Inc', 'Finance', 'Enterprise', 'USA', '2024-02-10 08:15:00', '2025-01-11 09:15:00'),
    (5, 'Eva Martinez', 'eva@healthplus.net', 'HealthPlus', 'Healthcare', 'Mid-Market', 'Mexico', '2024-02-15 10:30:00', '2025-01-09 11:00:00'),
    (6, 'Frank Johnson', 'frank@retailmax.com', 'RetailMax', 'Retail', 'Enterprise', 'USA', '2024-03-01 13:00:00', '2025-01-07 15:30:00'),
    (7, 'Grace Kim', 'grace@edulearn.edu', 'EduLearn', 'Education', 'Mid-Market', 'South Korea', '2024-03-05 07:45:00', '2025-01-13 08:00:00'),
    (8, 'Henry Wilson', 'henry@mfgpro.com', 'MfgPro', 'Manufacturing', 'Enterprise', 'Germany', '2024-03-10 16:20:00', '2025-01-06 12:45:00'),
    (9, 'Iris Thompson', 'iris@mediawave.co', 'MediaWave', 'Media', 'SMB', 'UK', '2024-03-15 09:00:00', '2025-01-05 17:20:00'),
    (10, 'Jack Brown', 'jack@logipro.com', 'LogiPro', 'Logistics', 'Mid-Market', 'Australia', '2024-03-20 12:30:00', '2025-01-04 13:10:00'),
    (11, 'Karen White', 'karen@biotech.io', 'BioTech Innovations', 'Biotechnology', 'Enterprise', 'USA', '2024-04-01 10:00:00', '2025-01-14 10:45:00'),
    (12, 'Leo Garcia', 'leo@solarworks.com', 'SolarWorks', 'Energy', 'Mid-Market', 'Spain', '2024-04-10 15:45:00', '2025-01-03 14:30:00');

-- -----------------------------------------------------------------------------
-- Products Table
-- Product catalog with descriptions for semantic search testing
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    sku VARCHAR UNIQUE NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR NOT NULL,
    features TEXT,
    target_audience VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO products VALUES
    (1, 'Enterprise License', 'LIC-ENT-001',
     'Full-featured enterprise solution with unlimited users, advanced analytics, SSO integration, and dedicated support. Ideal for large organizations requiring robust security and compliance features.',
     5000.00, 'License', 'Unlimited users, SSO, SAML, audit logs, 99.9% SLA', 'Large enterprises', '2024-01-01'),

    (2, 'Team License', 'LIC-TEAM-001',
     'Collaborative team plan designed for growing teams up to 50 users. Includes shared workspaces, real-time collaboration, and standard integrations.',
     2500.00, 'License', '50 users, collaboration tools, integrations, email support', 'Growing teams', '2024-01-01'),

    (3, 'Starter Plan', 'LIC-START-001',
     'Basic plan perfect for small teams just getting started. Supports up to 10 users with essential features for productivity.',
     500.00, 'License', '10 users, basic features, community support', 'Small teams and startups', '2024-01-01'),

    (4, 'Education License', 'LIC-EDU-001',
     'Special discounted license for educational institutions. Includes all Team features plus educational resources and student management.',
     1000.00, 'License', 'Unlimited students, teacher dashboard, LMS integration', 'Schools and universities', '2024-01-01'),

    (5, 'Premium Support Package', 'SVC-SUP-001',
     'Premium 24/7 support with dedicated account manager, priority ticket handling, and quarterly business reviews.',
     1200.00, 'Service', '24/7 support, dedicated AM, priority queue, QBRs', 'Enterprise customers', '2024-01-01'),

    (6, 'Training Workshop', 'SVC-TRN-001',
     'Comprehensive on-site or virtual training workshop for your team. Covers all platform features, best practices, and custom workflow setup.',
     3000.00, 'Service', '2-day workshop, custom curriculum, hands-on labs', 'All customers', '2024-01-01'),

    (7, 'Consulting Hours', 'SVC-CON-001',
     'Expert consulting services at hourly rate. Our specialists help with implementation, optimization, and custom development.',
     250.00, 'Service', 'Per-hour billing, flexible scheduling, expert consultants', 'All customers', '2024-01-01'),

    (8, 'API Access Add-on', 'ADD-API-001',
     'Enable full API access for custom integrations and automation. Includes detailed documentation and sandbox environment.',
     800.00, 'Add-on', 'REST API, webhooks, sandbox, rate limits: 10k/day', 'Developers', '2024-02-01'),

    (9, 'Advanced Analytics Module', 'ADD-ANA-001',
     'Unlock advanced analytics capabilities including predictive insights, custom dashboards, and data export features.',
     1500.00, 'Add-on', 'Predictive analytics, custom dashboards, data export', 'Data-driven teams', '2024-02-01'),

    (10, 'Security & Compliance Pack', 'ADD-SEC-001',
     'Enhanced security features including advanced encryption, compliance reporting (SOC2, HIPAA, GDPR), and security audit tools.',
     2000.00, 'Add-on', 'Advanced encryption, SOC2, HIPAA, GDPR compliance', 'Regulated industries', '2024-02-01');

-- -----------------------------------------------------------------------------
-- Orders Table
-- Transaction history for customers
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    product_id INTEGER REFERENCES products(id),
    product_name VARCHAR NOT NULL,
    quantity INTEGER DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    status VARCHAR DEFAULT 'pending',
    payment_method VARCHAR,
    order_date DATE NOT NULL,
    completed_date DATE
);

INSERT INTO orders VALUES
    (1, 1, 1, 'Enterprise License', 1, 5000.00, 5000.00, 'completed', 'wire_transfer', '2024-02-01', '2024-02-03'),
    (2, 1, 5, 'Premium Support Package', 1, 1200.00, 1200.00, 'completed', 'wire_transfer', '2024-02-15', '2024-02-15'),
    (3, 2, 2, 'Team License', 1, 2500.00, 2500.00, 'completed', 'credit_card', '2024-02-20', '2024-02-20'),
    (4, 3, 3, 'Starter Plan', 1, 500.00, 500.00, 'completed', 'credit_card', '2024-03-01', '2024-03-01'),
    (5, 4, 1, 'Enterprise License', 1, 5000.00, 5000.00, 'pending', 'wire_transfer', '2024-03-05', NULL),
    (6, 5, 2, 'Team License', 1, 2500.00, 2500.00, 'completed', 'credit_card', '2024-03-10', '2024-03-10'),
    (7, 6, 3, 'Starter Plan', 1, 500.00, 500.00, 'cancelled', 'credit_card', '2024-03-12', NULL),
    (8, 7, 4, 'Education License', 1, 1000.00, 1000.00, 'completed', 'invoice', '2024-03-15', '2024-03-20'),
    (9, 2, 5, 'Premium Support Package', 1, 1200.00, 1200.00, 'completed', 'credit_card', '2024-03-20', '2024-03-20'),
    (10, 8, 1, 'Enterprise License', 1, 5000.00, 5000.00, 'pending', 'wire_transfer', '2024-03-25', NULL),
    (11, 1, 8, 'API Access Add-on', 1, 800.00, 800.00, 'completed', 'credit_card', '2024-04-01', '2024-04-01'),
    (12, 4, 10, 'Security & Compliance Pack', 1, 2000.00, 2000.00, 'completed', 'wire_transfer', '2024-04-05', '2024-04-07'),
    (13, 11, 1, 'Enterprise License', 1, 5000.00, 5000.00, 'completed', 'wire_transfer', '2024-04-10', '2024-04-12'),
    (14, 11, 5, 'Premium Support Package', 1, 1200.00, 1200.00, 'completed', 'wire_transfer', '2024-04-10', '2024-04-10'),
    (15, 12, 2, 'Team License', 1, 2500.00, 2500.00, 'completed', 'credit_card', '2024-04-15', '2024-04-15'),
    (16, 9, 3, 'Starter Plan', 1, 500.00, 500.00, 'completed', 'credit_card', '2024-04-20', '2024-04-20'),
    (17, 10, 2, 'Team License', 1, 2500.00, 2500.00, 'completed', 'credit_card', '2024-04-25', '2024-04-25'),
    (18, 3, 9, 'Advanced Analytics Module', 1, 1500.00, 1500.00, 'completed', 'credit_card', '2024-05-01', '2024-05-01'),
    (19, 6, 1, 'Enterprise License', 1, 5000.00, 5000.00, 'completed', 'wire_transfer', '2024-05-05', '2024-05-08'),
    (20, 6, 5, 'Premium Support Package', 1, 1200.00, 1200.00, 'completed', 'wire_transfer', '2024-05-05', '2024-05-05');

-- -----------------------------------------------------------------------------
-- Support Tickets Table
-- Customer support interactions with text for semantic analysis
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    subject VARCHAR NOT NULL,
    description TEXT NOT NULL,
    priority VARCHAR DEFAULT 'medium',
    status VARCHAR DEFAULT 'open',
    category VARCHAR,
    assigned_to VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    satisfaction_score INTEGER
);

INSERT INTO support_tickets VALUES
    (1, 1, 'SSO Integration Issue',
     'We are having trouble configuring SAML SSO with our Okta identity provider. The authentication flow completes but users are not being assigned the correct roles. Need assistance with attribute mapping.',
     'high', 'resolved', 'Integration', 'Sarah Tech', '2024-03-01 10:00:00', '2024-03-02 14:30:00', 5),

    (2, 2, 'API Rate Limiting Questions',
     'Our development team is hitting rate limits when syncing data. We need clarification on the rate limiting policy and whether we can request higher limits for our integration.',
     'medium', 'resolved', 'Technical', 'Mike Support', '2024-03-05 09:30:00', '2024-03-05 16:00:00', 4),

    (3, 3, 'Billing Inquiry',
     'I noticed our invoice shows charges for 12 users but we only have 8 active users. Can you please review our account and adjust the billing accordingly?',
     'low', 'resolved', 'Billing', 'Lisa Billing', '2024-03-10 11:00:00', '2024-03-11 09:00:00', 5),

    (4, 4, 'Data Export Feature Request',
     'We need the ability to export compliance reports in PDF format for our auditors. Currently we can only export CSV. Is this feature on the roadmap?',
     'medium', 'open', 'Feature Request', NULL, '2024-03-15 14:00:00', NULL, NULL),

    (5, 5, 'Performance Issues with Dashboard',
     'Our analytics dashboard is loading very slowly, sometimes taking over 30 seconds to display data. This started about a week ago. We have approximately 50k records.',
     'high', 'in_progress', 'Performance', 'John DevOps', '2024-03-18 08:45:00', NULL, NULL),

    (6, 6, 'User Permission Configuration',
     'We need help setting up custom roles for our retail managers. They should have access to view reports but not modify settings. The current role templates do not match our needs.',
     'medium', 'resolved', 'Configuration', 'Sarah Tech', '2024-03-20 10:30:00', '2024-03-21 11:00:00', 4),

    (7, 7, 'LMS Integration Setup',
     'We are trying to integrate with our Canvas LMS but the connection keeps failing with a timeout error. We have verified the API credentials are correct.',
     'high', 'resolved', 'Integration', 'Mike Support', '2024-03-22 13:00:00', '2024-03-23 09:30:00', 5),

    (8, 8, 'Scheduled Report Not Sending',
     'Our weekly manufacturing report that was scheduled to send every Monday at 8am has not been delivered for the past 3 weeks. No errors shown in the interface.',
     'medium', 'resolved', 'Technical', 'John DevOps', '2024-03-25 07:00:00', '2024-03-25 15:00:00', 4),

    (9, 1, 'New Team Member Onboarding',
     'We have 5 new team members joining next week. Can you help us understand the best practices for onboarding and setting up their workspaces efficiently?',
     'low', 'resolved', 'Onboarding', 'Lisa Training', '2024-03-28 09:00:00', '2024-03-29 10:00:00', 5),

    (10, 11, 'HIPAA Compliance Documentation',
     'Our compliance team is requesting documentation about HIPAA compliance features. Specifically, we need details on data encryption, access logging, and BAA availability.',
     'high', 'open', 'Compliance', NULL, '2024-04-01 11:00:00', NULL, NULL);

-- -----------------------------------------------------------------------------
-- Activities Table
-- User activity log for behavioral analysis
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    user_email VARCHAR NOT NULL,
    activity_type VARCHAR NOT NULL,
    details TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO activities VALUES
    (1, 1, 'alice@acme.com', 'login', 'Logged in from IP 192.168.1.100', '2025-01-10 09:00:00'),
    (2, 1, 'alice@acme.com', 'report_viewed', 'Viewed Q4 Analytics Dashboard', '2025-01-10 09:15:00'),
    (3, 1, 'alice@acme.com', 'export', 'Exported user list to CSV', '2025-01-10 10:30:00'),
    (4, 2, 'bob@globaltech.io', 'login', 'Logged in from IP 10.0.0.50', '2025-01-12 14:00:00'),
    (5, 2, 'bob@globaltech.io', 'api_call', 'Called /api/v1/users endpoint', '2025-01-12 14:05:00'),
    (6, 2, 'bob@globaltech.io', 'api_call', 'Called /api/v1/reports endpoint', '2025-01-12 14:10:00'),
    (7, 3, 'carol@greenco.org', 'login', 'Logged in from mobile app', '2025-01-08 08:00:00'),
    (8, 3, 'carol@greenco.org', 'settings_changed', 'Updated notification preferences', '2025-01-08 08:30:00'),
    (9, 4, 'david@finserv.com', 'login', 'Logged in from IP 172.16.0.1', '2025-01-11 07:00:00'),
    (10, 4, 'david@finserv.com', 'compliance_report', 'Generated SOC2 compliance report', '2025-01-11 07:30:00'),
    (11, 5, 'eva@healthplus.net', 'login', 'Logged in from IP 192.168.50.25', '2025-01-09 10:00:00'),
    (12, 5, 'eva@healthplus.net', 'user_created', 'Created new user: nurse1@healthplus.net', '2025-01-09 10:15:00'),
    (13, 7, 'grace@edulearn.edu', 'login', 'Logged in from campus network', '2025-01-13 06:00:00'),
    (14, 7, 'grace@edulearn.edu', 'course_created', 'Created new course: Data Science 101', '2025-01-13 06:30:00'),
    (15, 11, 'karen@biotech.io', 'login', 'Logged in from IP 10.10.10.1', '2025-01-14 09:00:00'),
    (16, 11, 'karen@biotech.io', 'audit_log_viewed', 'Viewed system audit logs', '2025-01-14 09:30:00'),
    (17, 11, 'karen@biotech.io', 'export', 'Exported audit logs for review', '2025-01-14 10:00:00');

-- -----------------------------------------------------------------------------
-- Useful Views
-- Pre-built queries for common analytics
-- -----------------------------------------------------------------------------

-- Revenue by customer
CREATE VIEW IF NOT EXISTS customer_revenue AS
SELECT
    c.id as customer_id,
    c.name as customer_name,
    c.company,
    c.industry,
    COUNT(o.id) as total_orders,
    SUM(o.total_amount) as total_revenue,
    AVG(o.total_amount) as avg_order_value
FROM customers c
LEFT JOIN orders o ON c.id = o.customer_id AND o.status = 'completed'
GROUP BY c.id, c.name, c.company, c.industry;

-- Monthly revenue trend
CREATE VIEW IF NOT EXISTS monthly_revenue AS
SELECT
    strftime('%Y-%m', order_date) as month,
    COUNT(*) as order_count,
    SUM(total_amount) as revenue,
    COUNT(DISTINCT customer_id) as unique_customers
FROM orders
WHERE status = 'completed'
GROUP BY strftime('%Y-%m', order_date)
ORDER BY month;

-- Product performance
CREATE VIEW IF NOT EXISTS product_performance AS
SELECT
    p.id as product_id,
    p.name as product_name,
    p.category,
    COUNT(o.id) as times_ordered,
    SUM(o.quantity) as units_sold,
    SUM(o.total_amount) as total_revenue
FROM products p
LEFT JOIN orders o ON p.id = o.product_id AND o.status = 'completed'
GROUP BY p.id, p.name, p.category;

-- Support ticket summary
CREATE VIEW IF NOT EXISTS ticket_summary AS
SELECT
    category,
    status,
    priority,
    COUNT(*) as ticket_count,
    AVG(satisfaction_score) as avg_satisfaction
FROM support_tickets
GROUP BY category, status, priority;

-- =============================================================================
-- Sample database created successfully!
--
-- Tables: customers, products, orders, support_tickets, activities
-- Views: customer_revenue, monthly_revenue, product_performance, ticket_summary
--
-- Query examples:
--   SELECT * FROM customers WHERE industry = 'Technology';
--   SELECT * FROM customer_revenue ORDER BY total_revenue DESC;
--   SELECT * FROM monthly_revenue;
-- =============================================================================
