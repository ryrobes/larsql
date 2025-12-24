# Passing Multiple Fields to windlass_cascade_udf()

*DuckDB doesn't support function overloading, but we have better solutions!*

---

## TL;DR: You're Already Using the Best Pattern!

**Current Approach** (from your fraud example):
```sql
windlass_cascade_udf(
  'tackle/fraud_check.yaml',
  json_object(
    'customer_id', customer_id,
    'customer_name', customer_name,
    'transaction_amount', transaction_amount
  )
)
```

**This is perfect!** DuckDB's `json_object()` packs multiple fields into one JSON string.

---

## Solution 1: json_object() - THE RIGHT WAY ✅

### **How It Works**

```sql
SELECT
  customer_id,

  windlass_cascade_udf(
    'tackle/fraud_check.yaml',

    -- Pack ALL fields into JSON
    json_object(
      'customer_id', customer_id,
      'customer_name', customer_name,
      'email', email,
      'transaction_amount', amount,
      'transaction_date', created_at,
      'ip_address', ip_addr,
      'device_fingerprint', device_id
    )  -- Returns: '{"customer_id": 123, "customer_name": "Acme", ...}'

  ) as fraud_result

FROM transactions;
```

**Cascade receives**:
```json
{
  "customer_id": 123,
  "customer_name": "Acme Corp",
  "email": "acme@example.com",
  "transaction_amount": 150000,
  "transaction_date": "2024-12-24",
  "ip_address": "192.168.1.1",
  "device_fingerprint": "abc123"
}
```

**Then in cascade YAML**:
```yaml
phases:
  - name: analyze
    instructions: |
      Analyze this transaction:
      - Customer: {{ input.customer_name }} (ID: {{ input.customer_id }})
      - Amount: ${{ input.transaction_amount }}
      - Date: {{ input.transaction_date }}
      - Email: {{ input.email }}
      - IP: {{ input.ip_address }}
      - Device: {{ input.device_fingerprint }}

      Assess fraud risk...
```

**Pros**:
- ✅ Unlimited fields (pack as many as you want!)
- ✅ Strongly typed in cascade (inputs_schema validates)
- ✅ Clean, readable SQL
- ✅ Easy to add/remove fields (just modify json_object)
- ✅ Works TODAY (no code changes needed!)

**Cons**:
- ⚠️ Slightly verbose (but clear and explicit)

---

## Solution 2: JSON Nested Structures

For complex data, nest objects:

```sql
SELECT
  windlass_cascade_udf(
    'tackle/customer_360.yaml',

    -- Nested JSON for organization!
    json_object(
      'customer', json_object(
        'id', customer_id,
        'name', customer_name,
        'email', email,
        'tier', tier
      ),
      'transaction', json_object(
        'id', transaction_id,
        'amount', amount,
        'date', created_at,
        'description', description
      ),
      'context', json_object(
        'ip_address', ip_addr,
        'device_id', device_id,
        'location', location,
        'referrer', referrer
      )
    )

  ) as analysis

FROM transactions t
JOIN customers c ON t.customer_id = c.customer_id;
```

**Cascade receives**:
```json
{
  "customer": {
    "id": 123,
    "name": "Acme Corp",
    "email": "acme@example.com",
    "tier": "enterprise"
  },
  "transaction": {
    "id": "txn_456",
    "amount": 150000,
    "date": "2024-12-24",
    "description": "Equipment purchase"
  },
  "context": {
    "ip_address": "192.168.1.1",
    "device_id": "abc123",
    "location": "New York, NY",
    "referrer": "partner_site"
  }
}
```

**Access in cascade**:
```yaml
instructions: |
  Customer: {{ input.customer.name }} (Tier: {{ input.customer.tier }})
  Transaction: ${{ input.transaction.amount }} on {{ input.transaction.date }}
  Context: IP {{ input.context.ip_address }}, Device {{ input.context.device_id }}
```

**Pros**:
- ✅ Organized, hierarchical data
- ✅ Clear logical grouping
- ✅ Easy to understand

---

## Solution 3: SQL Struct → JSON (DuckDB Magic!)

DuckDB can convert STRUCT to JSON automatically:

```sql
-- Create struct, convert to JSON in one go
SELECT
  windlass_cascade_udf(
    'tackle/fraud_check.yaml',

    -- STRUCT is auto-converted to JSON!
    to_json({
      'customer_id': customer_id,
      'customer_name': customer_name,
      'amount': amount
    })

  ) as fraud_result

FROM transactions;
```

Even cleaner with row_to_json():

```sql
-- Pass ENTIRE row as JSON!
SELECT
  windlass_cascade_udf(
    'tackle/fraud_check.yaml',
    to_json(t.*)  -- Convert entire row to JSON!
  ) as result
FROM transactions t;
```

**Cascade gets ALL columns!**

---

## Solution 4: Concatenation (Simple, Limited)

For 2-3 simple strings, concatenate:

```sql
SELECT
  windlass_cascade_udf(
    'tackle/analyze.yaml',
    customer_name || '|' || email || '|' || CAST(amount AS VARCHAR)
  )
FROM customers;
```

Then parse in cascade:
```yaml
phases:
  - name: parse_and_analyze
    tool: python_data
    inputs:
      code: |
        parts = "{{ input }}".split('|')
        result = {
          'customer_name': parts[0],
          'email': parts[1],
          'amount': float(parts[2])
        }
```

**Pros**:
- ✅ Minimal SQL verbosity

**Cons**:
- ❌ Fragile (what if name contains `|`?)
- ❌ No type safety
- ❌ Ugly parsing logic

**Verdict**: Don't use this. json_object() is better!

---

## Solution 5: Optional Parameters (Enhancement)

**Future enhancement**: Make cascade UDF accept optional params:

```python
# In udf.py - enhanced signature
def windlass_cascade_udf_impl(
    cascade_path: str,
    inputs_json: str,
    param1: Optional[str] = None,
    param2: Optional[str] = None,
    param3: Optional[str] = None
) -> str:
    """Accept up to 3 optional positional params."""
    # Parse inputs
    inputs = json.loads(inputs_json) if isinstance(inputs_json, str) else inputs_json

    # Merge optional params
    if param1 is not None:
        inputs['param1'] = param1
    if param2 is not None:
        inputs['param2'] = param2
    if param3 is not None:
        inputs['param3'] = param3

    # Run cascade
    ...
```

Then in SQL:
```sql
-- 3-param version
SELECT windlass_cascade_udf(
  'tackle/fraud.yaml',
  json_object('customer_id', customer_id),  -- Primary input
  customer_name,  -- Optional param 1
  email,          -- Optional param 2
  CAST(amount AS VARCHAR)  -- Optional param 3
) FROM customers;
```

**Pros**:
- ✅ Less verbose for common cases

**Cons**:
- ❌ Limited to 3 params
- ❌ Positional (easy to mix up)
- ❌ Less clear than json_object

**Verdict**: json_object() is still better (unlimited fields, named, clear)

---

## Solution 6: Array of Values (Ugly)

```sql
SELECT
  windlass_cascade_udf(
    'tackle/analyze.yaml',
    to_json([customer_id, customer_name, amount])  -- Array
  )
FROM customers;
```

Cascade receives: `[123, "Acme Corp", 150000]`

**Cons**: Positional, no field names, type ambiguity
**Verdict**: DON'T DO THIS

---

## Recommendation: Stick with json_object()!

### **Best Pattern** (what you're already doing):

```sql
windlass_cascade_udf(
  'tackle/cascade.yaml',
  json_object(
    'field1', value1,
    'field2', value2,
    'field3', value3,
    -- Add as many as you want!
  )
)
```

### **Why It's Perfect**:
1. ✅ **Unlimited fields** - Pack 3, 10, 50 fields - doesn't matter
2. ✅ **Named parameters** - Self-documenting in SQL
3. ✅ **Type-safe** - Cascade's inputs_schema validates
4. ✅ **Nested objects** - Can structure hierarchically
5. ✅ **Works TODAY** - No code changes needed
6. ✅ **Composable** - Can build JSON programmatically

---

## Advanced Patterns with json_object()

### **Pattern 1: Computed Fields**

```sql
SELECT
  windlass_cascade_udf(
    'tackle/fraud.yaml',
    json_object(
      'customer_id', customer_id,
      'amount', amount,

      -- Computed fields!
      'amount_category', CASE
        WHEN amount < 1000 THEN 'low'
        WHEN amount < 50000 THEN 'medium'
        ELSE 'high'
      END,

      'time_category', CASE
        WHEN extract(hour from created_at) BETWEEN 9 AND 17 THEN 'business_hours'
        ELSE 'off_hours'
      END,

      'risk_signals', json_array(
        CASE WHEN new_customer THEN 'new_account' END,
        CASE WHEN vip_customer THEN 'vip' END
      )
    )
  ) as fraud_check

FROM transactions;
```

**The cascade gets enriched context!**

---

### **Pattern 2: Join Multiple Tables into Input**

```sql
SELECT
  t.transaction_id,

  windlass_cascade_udf(
    'tackle/comprehensive_fraud.yaml',

    -- Pack data from 4 different tables!
    json_object(
      'transaction', json_object(
        'id', t.transaction_id,
        'amount', t.amount,
        'description', t.description
      ),
      'customer', json_object(
        'id', c.customer_id,
        'name', c.company_name,
        'tier', c.tier,
        'created_at', c.created_at
      ),
      'account', json_object(
        'balance', a.balance,
        'overdraft_count', a.overdraft_count
      ),
      'history', json_object(
        'total_transactions', h.total_count,
        'avg_amount', h.avg_amount,
        'last_transaction_date', h.last_transaction
      )
    )

  ) as fraud_analysis

FROM transactions t
JOIN customers c ON t.customer_id = c.customer_id
JOIN accounts a ON t.account_id = a.account_id
JOIN (
  SELECT customer_id,
         COUNT(*) as total_count,
         AVG(amount) as avg_amount,
         MAX(created_at) as last_transaction
  FROM historical_transactions
  GROUP BY customer_id
) h ON c.customer_id = h.customer_id;
```

**The cascade sees the FULL customer context from multiple sources!**

---

### **Pattern 3: Pass Query Results as Arrays**

```sql
WITH customer_transactions AS (
  SELECT
    customer_id,
    json_agg(json_object(
      'amount', amount,
      'date', created_at,
      'merchant', merchant_name
    )) as transaction_history
  FROM historical_transactions
  WHERE created_at > CURRENT_DATE - INTERVAL '90 days'
  GROUP BY customer_id
)

SELECT
  c.customer_id,

  windlass_cascade_udf(
    'tackle/customer_behavior_analysis.yaml',
    json_object(
      'customer_id', c.customer_id,
      'name', c.company_name,

      -- Pass entire transaction history as array!
      'recent_transactions', ct.transaction_history
    )
  ) as behavior_analysis

FROM customers c
JOIN customer_transactions ct ON c.customer_id = ct.customer_id;
```

**Cascade receives**:
```json
{
  "customer_id": 123,
  "name": "Acme Corp",
  "recent_transactions": [
    {"amount": 5000, "date": "2024-12-01", "merchant": "Supplier A"},
    {"amount": 3000, "date": "2024-12-15", "merchant": "Supplier B"},
    {"amount": 7000, "date": "2024-12-20", "merchant": "Supplier C"}
  ]
}
```

**The cascade can analyze patterns across transactions!**

---

## Solution 7: Variadic UDF (Enhancement Idea)

We COULD add a variadic version that accepts any number of key-value pairs:

```python
# Future enhancement
def windlass_cascade_udf_variadic(*args):
    """
    Accept: cascade_path, key1, val1, key2, val2, ...
    Build JSON from alternating key/value pairs.
    """
    cascade_path = args[0]

    # Build inputs dict from remaining args (alternating key/value)
    inputs = {}
    for i in range(1, len(args), 2):
        if i + 1 < len(args):
            inputs[args[i]] = args[i + 1]

    return windlass_cascade_udf_impl(cascade_path, json.dumps(inputs))
```

**SQL**:
```sql
SELECT windlass_cascade_udf(
  'tackle/fraud.yaml',
  'customer_id', customer_id,  -- key, value
  'name', customer_name,        -- key, value
  'amount', amount              -- key, value
) FROM transactions;
```

**Pros**: Less verbose than json_object
**Cons**: Weird syntax, easy to mess up, loses DuckDB's type checking

**Verdict**: json_object() is still clearer!

---

## My Recommendation: Embrace json_object()

### **Why It's The Best**:

**1. Self-Documenting**
```sql
-- Clear what each field is!
json_object(
  'customer_id', c.id,
  'customer_name', c.name,
  'email', c.email
)

-- vs variadic (what's what?)
windlass_cascade_udf('tackle/x.yaml', c.id, c.name, c.email)  -- Which is which?
```

**2. Type-Safe**
```sql
json_object(
  'amount', CAST(amount AS DOUBLE),  -- Explicit casting
  'date', created_at::VARCHAR,       -- Control serialization
  'flag', is_vip::BOOLEAN            -- Type preserved
)
```

**3. Composable**
```sql
-- Build JSON programmatically!
WITH base_inputs AS (
  SELECT
    customer_id,
    json_object('id', customer_id, 'name', customer_name) as customer_json
  FROM customers
)

SELECT
  windlass_cascade_udf(
    'tackle/analyze.yaml',
    json_object(
      'customer', customer_json,  -- Reuse from CTE!
      'timestamp', CURRENT_TIMESTAMP
    )
  )
FROM base_inputs;
```

**4. Works with Complex Types**
```sql
json_object(
  'customer_id', customer_id,

  -- Pass arrays!
  'tags', json_array('vip', 'enterprise', 'verified'),

  -- Pass nested objects!
  'address', json_object('street', street, 'city', city, 'zip', zip),

  -- Pass aggregated data!
  'transaction_history', (
    SELECT json_agg(json_object('amount', amount, 'date', date))
    FROM transactions
    WHERE customer_id = c.customer_id
  )
)
```

---

## Helper Functions (Quality of Life)

If you find yourself repeating json_object() patterns, create SQL macros/views:

### **Macro 1: Standard Customer Input**
```sql
CREATE MACRO customer_input(cid, cname, cemail) AS
  json_object(
    'customer_id', cid,
    'customer_name', cname,
    'email', cemail
  );

-- Usage
SELECT windlass_cascade_udf(
  'tackle/analyze.yaml',
  customer_input(customer_id, customer_name, email)
) FROM customers;
```

### **Macro 2: Transaction Context**
```sql
CREATE MACRO transaction_context(tid, amt, cid, cname) AS
  json_object(
    'transaction_id', tid,
    'amount', amt,
    'customer', json_object('id', cid, 'name', cname)
  );

-- Usage
SELECT windlass_cascade_udf(
  'tackle/fraud.yaml',
  transaction_context(t.id, t.amount, c.id, c.name)
)
FROM transactions t
JOIN customers c ON t.customer_id = c.customer_id;
```

---

## Real-World Examples

### **Example 1: Medical Diagnosis** (10 fields)

```sql
SELECT
  patient_id,

  windlass_cascade_udf(
    'tackle/medical_diagnosis.yaml',
    json_object(
      'patient_id', patient_id,
      'age', age,
      'gender', gender,
      'symptoms', symptoms,
      'vital_signs', json_object(
        'temp', temperature,
        'bp_systolic', bp_sys,
        'bp_diastolic', bp_dia,
        'heart_rate', hr
      ),
      'medical_history', (
        SELECT json_agg(diagnosis)
        FROM patient_history
        WHERE patient_id = p.patient_id
      ),
      'medications', current_medications,
      'allergies', allergies,
      'visit_reason', chief_complaint,
      'duration_days', symptom_duration
    )
  ) as diagnosis

FROM patients p;
```

---

### **Example 2: Legal Document Analysis** (15+ fields)

```sql
SELECT
  document_id,

  windlass_cascade_udf(
    'tackle/legal_document_analysis.yaml',
    json_object(
      'document_id', doc_id,
      'document_type', doc_type,
      'filing_date', filed_at,
      'jurisdiction', jurisdiction,
      'parties', json_object(
        'plaintiff', plaintiff_name,
        'defendant', defendant_name,
        'judge', assigned_judge
      ),
      'claims', (
        SELECT json_agg(claim_text)
        FROM document_claims
        WHERE document_id = d.document_id
      ),
      'prior_rulings', (
        SELECT json_agg(json_object('case_id', case_id, 'outcome', outcome))
        FROM related_cases
        WHERE document_id = d.document_id
      ),
      'metadata', json_object(
        'page_count', page_count,
        'word_count', word_count,
        'attachments', attachment_count
      )
    )
  ) as legal_analysis

FROM documents d;
```

**The cascade can analyze complex legal context with full structure!**

---

## The Cognitive Trick: Think of json_object() as Function Arguments

In Python:
```python
analyze_fraud(
    customer_id=123,
    customer_name="Acme",
    amount=150000
)
```

In SQL with UDF:
```sql
windlass_cascade_udf(
  'tackle/fraud.yaml',
  json_object(
    'customer_id', 123,
    'customer_name', 'Acme',
    'amount', 150000
  )
)
```

**Same semantics, just different syntax!** json_object() is your **keyword argument** syntax.

---

## Bonus: Dynamic Field Selection

```sql
SELECT
  windlass_cascade_udf(
    'tackle/analyze.yaml',

    -- Conditionally include fields!
    json_object(
      'customer_id', customer_id,
      'name', customer_name,

      -- Only include email if not null
      'email', CASE WHEN email IS NOT NULL THEN email END,

      -- Only include amount for high-value
      'amount', CASE WHEN amount > 1000 THEN amount END,

      -- Computed metadata
      'is_high_value', amount > 50000,
      'is_new_customer', account_age_days < 30
    )

  ) as result

FROM customers;
```

---

## Summary: You're Already Using the Best Approach!

| Approach | Fields Supported | Clarity | Type Safety | Verdict |
|----------|------------------|---------|-------------|---------|
| **json_object()** | ∞ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ **USE THIS** |
| Nested json_object() | ∞ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ **USE THIS** |
| STRUCT → to_json() | ∞ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ Good alternative |
| Optional params | 3 | ⭐⭐⭐ | ⭐⭐⭐ | ⚠️ Limited |
| Concatenation | 3-5 | ⭐⭐ | ⭐ | ❌ Fragile |
| Array | ∞ | ⭐ | ⭐ | ❌ Ugly |

**Stick with json_object()!** It's:
- Flexible (unlimited fields)
- Clear (self-documenting)
- Safe (type-checked by cascade's inputs_schema)
- Standard (everyone knows JSON)
- Composable (nest objects, arrays, computed fields)

---

## Quick Reference

**Minimal** (2-3 fields):
```sql
json_object('field1', val1, 'field2', val2)
```

**Standard** (5-10 fields):
```sql
json_object(
  'field1', val1,
  'field2', val2,
  'field3', val3,
  'field4', val4
)
```

**Hierarchical** (organized):
```sql
json_object(
  'entity', json_object('id', id, 'name', name),
  'context', json_object('amount', amt, 'date', date),
  'metadata', json_object('source', src, 'flags', flags)
)
```

**Dynamic** (conditional fields):
```sql
json_object(
  'required_field', value,
  'optional_field', CASE WHEN condition THEN value END,
  'computed_field', CASE ... END
)
```

**Full Row** (lazy mode):
```sql
to_json(table_name.*)  -- All columns automatically!
```

---

**You're already doing it right!** No changes needed. 🎯
