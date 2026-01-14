// MongoDB initialization script for integration tests
// This runs when the container starts for the first time

// Switch to testdb (created by MONGO_INITDB_DATABASE env var)
db = db.getSiblingDB('testdb');

// Create test user with readWrite permissions
db.createUser({
    user: 'testuser',
    pwd: 'testpassword',
    roles: [
        { role: 'readWrite', db: 'testdb' }
    ]
});

// Create sample collections with test data

// Customers collection
db.customers.insertMany([
    {
        _id: ObjectId(),
        name: "Alice Johnson",
        email: "alice@example.com",
        age: 32,
        city: "New York",
        tier: "gold",
        created_at: new Date("2024-01-15"),
        tags: ["active", "premium"]
    },
    {
        _id: ObjectId(),
        name: "Bob Smith",
        email: "bob@example.com",
        age: 45,
        city: "Los Angeles",
        tier: "silver",
        created_at: new Date("2024-02-20"),
        tags: ["active"]
    },
    {
        _id: ObjectId(),
        name: "Carol White",
        email: "carol@example.com",
        age: 28,
        city: "Chicago",
        tier: "bronze",
        created_at: new Date("2024-03-10"),
        tags: ["new"]
    },
    {
        _id: ObjectId(),
        name: "David Brown",
        email: "david@example.com",
        age: 51,
        city: "Houston",
        tier: "gold",
        created_at: new Date("2024-01-05"),
        tags: ["active", "premium", "vip"]
    },
    {
        _id: ObjectId(),
        name: "Eva Martinez",
        email: "eva@example.com",
        age: 36,
        city: "Phoenix",
        tier: "silver",
        created_at: new Date("2024-04-01"),
        tags: ["active"]
    }
]);

// Orders collection with nested documents
db.orders.insertMany([
    {
        _id: ObjectId(),
        customer_email: "alice@example.com",
        order_date: new Date("2024-06-01"),
        status: "delivered",
        total: 150.00,
        items: [
            { sku: "WIDGET-001", name: "Blue Widget", qty: 2, price: 50.00 },
            { sku: "GADGET-002", name: "Red Gadget", qty: 1, price: 50.00 }
        ],
        shipping: {
            method: "express",
            address: "123 Main St, New York, NY"
        }
    },
    {
        _id: ObjectId(),
        customer_email: "bob@example.com",
        order_date: new Date("2024-06-15"),
        status: "processing",
        total: 75.00,
        items: [
            { sku: "WIDGET-001", name: "Blue Widget", qty: 1, price: 50.00 },
            { sku: "TOOL-003", name: "Mini Tool", qty: 1, price: 25.00 }
        ],
        shipping: {
            method: "standard",
            address: "456 Oak Ave, Los Angeles, CA"
        }
    },
    {
        _id: ObjectId(),
        customer_email: "david@example.com",
        order_date: new Date("2024-06-20"),
        status: "delivered",
        total: 500.00,
        items: [
            { sku: "PREMIUM-001", name: "Premium Package", qty: 1, price: 500.00 }
        ],
        shipping: {
            method: "express",
            address: "789 Pine Rd, Houston, TX"
        }
    }
]);

// Products collection
db.products.insertMany([
    {
        _id: ObjectId(),
        sku: "WIDGET-001",
        name: "Blue Widget",
        description: "A high-quality blue widget",
        price: 50.00,
        category: "widgets",
        in_stock: true,
        quantity: 150,
        specs: {
            color: "blue",
            weight_kg: 0.5,
            dimensions: { width: 10, height: 5, depth: 3 }
        }
    },
    {
        _id: ObjectId(),
        sku: "GADGET-002",
        name: "Red Gadget",
        description: "A versatile red gadget",
        price: 50.00,
        category: "gadgets",
        in_stock: true,
        quantity: 75,
        specs: {
            color: "red",
            weight_kg: 0.3,
            dimensions: { width: 8, height: 4, depth: 2 }
        }
    },
    {
        _id: ObjectId(),
        sku: "TOOL-003",
        name: "Mini Tool",
        description: "A compact multi-purpose tool",
        price: 25.00,
        category: "tools",
        in_stock: true,
        quantity: 200,
        specs: {
            color: "silver",
            weight_kg: 0.1,
            dimensions: { width: 5, height: 2, depth: 1 }
        }
    },
    {
        _id: ObjectId(),
        sku: "PREMIUM-001",
        name: "Premium Package",
        description: "All-inclusive premium package",
        price: 500.00,
        category: "premium",
        in_stock: true,
        quantity: 10,
        specs: {
            contents: ["widget", "gadget", "tool", "accessories"],
            weight_kg: 2.5
        }
    }
]);

// Create indexes for better query performance
db.customers.createIndex({ email: 1 }, { unique: true });
db.customers.createIndex({ tier: 1 });
db.orders.createIndex({ customer_email: 1 });
db.orders.createIndex({ order_date: -1 });
db.products.createIndex({ sku: 1 }, { unique: true });
db.products.createIndex({ category: 1 });

print("MongoDB initialization complete: testdb created with customers, orders, and products collections");
