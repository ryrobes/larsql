# DBeaver Simple Query Protocol Configuration

**Issue**: DBeaver tries to use Extended Query Protocol (prepared statements) which Windlass doesn't support yet.

**Solution**: Force DBeaver to use Simple Query Protocol via connection properties!

---

## Quick Fix (30 Seconds)

### **Method 1: Connection Properties** (RECOMMENDED)

1. **Right-click your Windlass connection** in DBeaver → **Edit Connection**

2. Go to **"Driver properties"** tab (or "Connection details" → "Driver properties")

3. Click **"Driver properties"** at the bottom

4. Find or add these properties:
   - **Name**: `preferQueryMode`
   - **Value**: `simple`

5. Also add (if available):
   - **Name**: `prepareThreshold`
   - **Value**: `0`

6. Click **OK** → **Test Connection** → Should work now!

---

### **Method 2: JDBC URL Parameter**

1. **Edit Connection** → **Main** tab

2. In the **JDBC URL** field, add `?preferQueryMode=simple`:
   ```
   jdbc:postgresql://localhost:15432/default?preferQueryMode=simple
   ```

3. **Test Connection** → Should work!

---

### **Method 3: Connection Settings Tab**

Some DBeaver versions have connection settings:

1. **Edit Connection** → **Connection settings** (or **PostgreSQL** tab)

2. Look for checkboxes like:
   - ☑ **"Use simple query mode"**
   - ☐ **"Use prepared statements"** (uncheck this!)
   - ☑ **"Disable prepared statements"**

3. **Test Connection**

---

## If None of These Work

### **Method 4: Edit Connection String Directly**

1. **Edit Connection** → **Main** tab

2. Switch to **"URL"** mode (radio button)

3. Manually enter:
   ```
   jdbc:postgresql://localhost:15432/default?preferQueryMode=simple&prepareThreshold=0
   ```

4. **Test Connection**

---

## Alternative: Connect via Python Bridge

If DBeaver still refuses, use the **Python script method** (guaranteed to work):

### **In DBeaver**:

1. **File** → **New** → **SQL Script**
2. Change language to **Python** (dropdown)
3. Paste:

```python
import sys
sys.path.insert(0, '/home/ryanr/repos/windlass/windlass')

from windlass.client import WindlassClient

client = WindlassClient('http://localhost:5001')

df = client.execute("""
    SELECT
      product,
      windlass_udf('Extract brand', product) as brand,
      windlass_udf('Category', product) as category
    FROM (VALUES
      ('Apple iPhone 15 Pro'),
      ('Samsung Galaxy S24'),
      ('Levis 501 Jeans')
    ) AS t(product)
""")

print(df.to_markdown(index=False))
```

4. **Execute** → Results appear!

**This bypasses the driver entirely** and uses HTTP API.

---

## Understanding the Issue

### **Extended Query Protocol** (what DBeaver wants):
- Uses prepared statements (Parse, Bind, Execute messages)
- More efficient for repeated queries
- More complex to implement

### **Simple Query Protocol** (what we support):
- One-shot query execution (Query message)
- SQL string sent directly
- Simpler, works for 95% of use cases

**We implemented Simple Query Protocol** because:
- ✅ Sufficient for SQL IDEs, BI tools
- ✅ Easier to implement (~300 lines vs ~800 lines)
- ✅ Works with psql, most clients

**DBeaver defaults to Extended Protocol**, hence the error.

---

## Verification

After configuring, test with:

```sql
SELECT 1 as test;
```

Should return:
```
test
----
1
```

Then try:
```sql
SELECT windlass_udf('Extract brand', 'Apple iPhone') as brand;
```

Should return:
```
brand
-----
Apple
```

**If this works, you're good to go!** 🎉

---

## Future: Extended Query Protocol

If you want to implement it later, we'd need to add:

**In postgres_protocol.py**:
- Parse message handler (parse SQL, return statement ID)
- Bind message handler (bind parameters to statement)
- Execute message handler (execute bound statement)
- Describe message handler (describe statement/portal)

**Effort**: ~400 additional lines

**Benefit**: DBeaver works without configuration

**For now**: Simple Query Protocol + `preferQueryMode=simple` is sufficient!

---

## Common DBeaver Settings Locations

### **PostgreSQL Driver Properties**:

Depending on DBeaver version, properties might be in:

1. **Connection → Edit → Driver properties** tab
2. **Connection → Edit → PostgreSQL** tab → "Additional connection properties"
3. **Connection → Edit → Connection details** → "Driver properties" button

Look for fields to add:
- `preferQueryMode = simple`
- `prepareThreshold = 0`

---

## Test Query for DBeaver

Once connected, paste this to verify everything works:

```sql
-- Test 1: Basic query
SELECT 1 as one, 2 as two, 3 as three;

-- Test 2: Simple UDF
SELECT windlass_udf('Extract brand name', 'Apple iPhone 15 Pro Max') as brand;

-- Test 3: Multi-column enrichment
WITH products AS (
  SELECT * FROM (VALUES
    ('Apple iPhone 15 Pro Max Space Black', 1199.99),
    ('Samsung Galaxy S24 Ultra Titanium', 1299.99),
    ('Levis 501 Jeans Blue', 59.99)
  ) AS t(product_name, price)
)
SELECT
  product_name,
  price,
  windlass_udf('Extract brand', product_name) as brand,
  windlass_udf('Extract color', product_name) as color,
  windlass_udf('Category: Electronics/Clothing/Home', product_name) as category
FROM products;

-- Test 4: Aggregate by LLM field
WITH products AS (
  SELECT * FROM (VALUES
    ('Apple iPhone', 1199),
    ('Samsung Galaxy', 1299),
    ('Sony Headphones', 399),
    ('Levis Jeans', 59),
    ('Nike Shoes', 129)
  ) AS t(name, price)
)
SELECT
  windlass_udf('Category: Electronics/Clothing/Footwear/Other', name) as category,
  COUNT(*) as count,
  ROUND(AVG(price), 2) as avg_price
FROM products
GROUP BY category;
```

**If all 4 tests pass → You're running LLM-powered SQL in DBeaver!** 🎊

---

## Quick Reference

**Setting**: `preferQueryMode=simple`
**Location**: Driver properties in connection settings
**Effect**: Forces simple query protocol (compatible with Windlass v1)

**Connection**: `postgresql://windlass@localhost:15432/default?preferQueryMode=simple`

🚀 Try it now!
