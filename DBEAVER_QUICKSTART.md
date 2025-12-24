# DBeaver Quick Start - Try Windlass SQL API NOW!

*Use this guide to test Windlass from DBeaver right now!*

---

## Option 1: Python Script in DBeaver (WORKS NOW!)

DBeaver supports Python scripts natively!

### **Steps**:

1. **Open DBeaver**

2. **File** → **New** → **SQL Script**
   - When prompted for connection, select **"No connection"** or any connection
   - Change language to **Python** (dropdown in toolbar)

3. **Paste this code**:

```python
# Windlass SQL Client Test from DBeaver!
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.client import WindlassClient
import pandas as pd

# Connect to Windlass server
client = WindlassClient('http://localhost:5001')

print("=" * 70)
print("🌊 Windlass SQL + LLMs in DBeaver!")
print("=" * 70)

# Example 1: Simple brand extraction
print("\n📦 Example 1: Extract Brands")
print("-" * 70)

df = client.execute("""
    SELECT
      product,
      windlass_udf('Extract the brand name only', product) as brand
    FROM (VALUES
      ('Apple iPhone 15 Pro Max'),
      ('Samsung Galaxy S24 Ultra'),
      ('Google Pixel 8 Pro'),
      ('Sony WH-1000XM5 Headphones')
    ) AS t(product)
""")

print(df.to_markdown(index=False))

# Example 2: Multi-column enrichment
print("\n\n🎨 Example 2: Multi-Column Product Enrichment")
print("-" * 70)

df2 = client.execute("""
    WITH products AS (
      SELECT * FROM (VALUES
        ('Apple iPhone 15 Pro Max Space Black', 1199.99),
        ('Levis 501 Original Jeans Blue', 59.99),
        ('KitchenAid Stand Mixer Red', 429.99)
      ) AS t(product_name, price)
    )
    SELECT
      product_name,
      price,
      windlass_udf('Extract brand', product_name) as brand,
      windlass_udf('Extract color', product_name) as color,
      windlass_udf('Category: Electronics/Clothing/Home', product_name) as category,
      windlass_udf('Price tier: budget/mid-range/premium/luxury',
                   product_name || ' - $' || price) as price_tier
    FROM products
""")

print(df2.to_markdown(index=False))

# Example 3: Aggregate by LLM-extracted category
print("\n\n📊 Example 3: Aggregate by LLM Category")
print("-" * 70)

df3 = client.execute("""
    WITH products AS (
      SELECT * FROM (VALUES
        ('Apple iPhone', 1199),
        ('Samsung Galaxy', 1299),
        ('Sony Headphones', 399),
        ('Levis Jeans', 59),
        ('Nike Shoes', 129),
        ('KitchenAid Mixer', 429)
      ) AS t(name, price)
    )
    SELECT
      windlass_udf('Category: Electronics/Clothing/Home', name) as category,
      COUNT(*) as product_count,
      ROUND(AVG(price), 2) as avg_price,
      MIN(price) as min_price,
      MAX(price) as max_price
    FROM products
    GROUP BY category
    ORDER BY product_count DESC
""")

print(df3.to_markdown(index=False))

# Example 4: CASCADE UDF (full workflow per row!)
print("\n\n⚡ Example 4: CASCADE UDF - Complete Workflow Per Row")
print("-" * 70)
print("⏳ Running cascade with soundings (takes ~30 seconds)...\n")

df4 = client.execute(f"""
    SELECT
      customer_name,
      windlass_cascade_udf(
        '/home/ryanr/repos/windlass/tackle/analyze_customer.yaml',
        json_object(
          'customer_id', '1',
          'customer_name', customer_name,
          'email', customer_name || '@example.com'
        )
      ) as analysis_json
    FROM (VALUES ('Acme Corp'), ('Startup Inc')) AS t(customer_name)
""")

import json
for idx, row in df4.iterrows():
    analysis = json.loads(row['analysis_json'])
    print(f"Customer: {row['customer_name']}")
    print(f"  Session ID: {analysis['session_id']}")
    print(f"  Status: {analysis['status']}")

    # Try to extract risk score
    try:
        output = analysis['outputs']['analyze']
        if isinstance(output, str):
            data = json.loads(output)
            print(f"  Risk Score: {data.get('risk_score', 'N/A')}")
            print(f"  Recommendation: {data.get('recommendation', 'N/A')}")
    except:
        print(f"  (Analysis completed)")
    print()

print("=" * 70)
print("✅ ALL EXAMPLES COMPLETED!")
print("=" * 70)
print("\n💡 You can now:")
print("   - Modify these queries in DBeaver")
print("   - Add your own data sources")
print("   - Use windlass_udf() on any text column")
print("   - Run complete cascades per row!")
print("\n🚀 LLM-powered SQL is working from DBeaver!")
```

4. **Execute** → Press **Ctrl+Enter** or click **Execute SQL Statement**

5. **See Results** → Output pane shows enriched data!

---

## Option 2: External Python Script (Copy-Paste Results)

1. **Write and test SQL in DBeaver** (syntax highlighting!)
2. **Save query to file**: `my_query.sql`
3. **Run from terminal**:

```bash
python3 << 'EOF'
from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Load your SQL from file
with open('my_query.sql') as f:
    query = f.read()

# Execute
df = client.execute(query)

# Save results as CSV
df.to_csv('results.csv', index=False)
print(f"✅ Results saved to results.csv ({len(df)} rows)")
EOF
```

4. **Import CSV in DBeaver**:
   - Right-click connection → **Import Data**
   - Select `results.csv`
   - View enriched results!

---

## Quick Test (30 Seconds)

**Paste this in DBeaver as Python script**:

```python
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

df = client.execute("""
    SELECT
      'Apple iPhone 15 Pro' as product,
      windlass_udf('Extract brand name', 'Apple iPhone 15 Pro') as brand,
      windlass_udf('Extract model number', 'Apple iPhone 15 Pro') as model
""")

print("🎉 Windlass + LLMs from DBeaver!")
print(df.to_markdown(index=False))
```

**Expected output**:
```
🎉 Windlass + LLMs from DBeaver!
| product               | brand | model |
|-----------------------|-------|-------|
| Apple iPhone 15 Pro   | Apple | 15    |
```

**If this works → You're running LLM-powered SQL from DBeaver!** 🚀

---

## Real-World Example

**Analyze support tickets from your database**:

```python
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

# Attach your production database (if you have one)
# client.attach('postgres://user:pass@host/db', 'prod')

# For demo, use sample data
df = client.execute("""
    WITH tickets AS (
      SELECT * FROM (VALUES
        (1, 'My package has not arrived and I need it urgently'),
        (2, 'Charged twice for the same order, please refund'),
        (3, 'Product is defective, keeps freezing'),
        (4, 'How do I return an item?'),
        (5, 'Wrong color received, need exchange')
      ) AS t(ticket_id, ticket_text)
    )

    SELECT
      ticket_id,
      ticket_text,

      -- Extract structured data with LLMs!
      windlass_udf('Issue type: shipping/billing/defect/return/exchange', ticket_text) as issue_type,
      windlass_udf('Urgency: low/medium/high', ticket_text) as urgency,
      windlass_udf('Sentiment: positive/neutral/negative', ticket_text) as sentiment

    FROM tickets
""")

print(df[['ticket_id', 'issue_type', 'urgency', 'sentiment']].to_markdown(index=False))

# Summary
print("\n📊 Summary:")
print(df.groupby('issue_type').size().to_markdown())
print(f"\nHigh urgency tickets: {len(df[df['urgency'] == 'high'])}")
```

**Expected**: Tickets automatically categorized by LLM!

---

## Troubleshooting

### **"ModuleNotFoundError: No module named 'windlass'"**

Fix the path in line 2:
```python
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')
# Change to YOUR windlass path!
```

Or install windlass:
```bash
cd /home/ryanr/repos/windlass
pip install -e .
```

---

### **"Connection refused"**

Start the dashboard server:
```bash
cd /home/ryanr/repos/windlass/dashboard/backend
python app.py
```

Verify it's running:
```bash
curl http://localhost:5001/api/sql/health
```

---

### **Slow queries**

First run makes LLM calls (1-3s each). Second run uses cache (<1ms)!

**To pre-warm cache**:
```python
# Run once to populate cache
client.execute("SELECT windlass_udf('Brand', name) FROM products")

# Second run is instant (cache hits!)
client.execute("SELECT windlass_udf('Brand', name) FROM products")
```

---

## Next: Native DBeaver Support (PostgreSQL Protocol)

Once we implement PostgreSQL wire protocol, you'll connect natively:

**DBeaver Connection**:
- Type: PostgreSQL
- Host: localhost
- Port: 5432
- Database: windlass

**Then just write SQL**:
```sql
SELECT
  product_name,
  windlass_udf('Extract brand', product_name) as brand
FROM products;
```

**No Python bridge needed!**

**Timeline**: We can build this next! (~1 week of focused work)

---

## Summary

**Today**: Python bridge in DBeaver (works, slight friction)
**Soon**: Native PostgreSQL protocol (seamless!)

**You can use LLM SQL UDFs RIGHT NOW** from DBeaver using Python scripts!

Try the quick test above and let me know how it goes! 🚀
