# Semantic Macros with Structural Caching

**Code that writes code, cached by data shape.**

## What Are Semantic Macros?

A Semantic Macro is a function where:

1. **LLM generates SQL** based on data *shape* (structure/format), not content
2. **SQL is cached** by structural fingerprint
3. **Same shape + same task** = instant cache hit (no LLM call)
4. **Cached SQL executes** with actual values

This is analogous to Lisp macros: the LLM is the macro expander, producing code (SQL) that then runs. The key innovation is caching by *structure* rather than *content*.

```
┌─────────────────────────────────────────────────────────────────┐
│                     SEMANTIC MACRO FLOW                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Input: (data shape, intent)                                   │
│              ↓                                                  │
│   ┌─────────────────────┐                                       │
│   │  Structural Cache   │←── Cache key = hash(shape + intent)   │
│   └─────────────────────┘                                       │
│         ↓ miss    ↓ hit                                         │
│   ┌───────────┐  ┌───────────┐                                  │
│   │    LLM    │  │  Cached   │                                  │
│   │ generates │  │   SQL     │                                  │
│   │   SQL     │  │           │                                  │
│   └───────────┘  └───────────┘                                  │
│         ↓              ↓                                        │
│   ┌─────────────────────────┐                                   │
│   │   SQL executes with     │                                   │
│   │   actual values         │                                   │
│   └─────────────────────────┘                                   │
│              ↓                                                  │
│         Result                                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Why "Macro"?

In Lisp/Clojure, a macro is code that writes code:
- **Input:** Code (or in our case, structure + intent)
- **Output:** Code (SQL expression)
- **Expansion:** Happens once per unique input pattern
- **Execution:** The expanded code runs with actual values

Traditional "compilation" implies optimization and transformation to lower-level code. What we do is closer to macro expansion: generating code fragments that execute directly.

## Two Flavors of Structural Caching

### 1. JSON Schema Caching

For JSON data, the cache key is based on the **schema** (structure), not the values:

```sql
-- These two calls have the SAME schema:
SELECT smart_json('{"customer": {"name": "Alice"}, "total": 99}', 'customer name')
SELECT smart_json('{"customer": {"name": "Bob"}, "total": 150}', 'customer name')
--                  ↑ Different values, same structure = CACHE HIT

-- This has a DIFFERENT schema:
SELECT smart_json('{"sku": "ABC", "price": 29.99}', 'product code')
--                  ↑ Different structure = NEW SQL generated
```

**How it works:**
1. Extract JSON schema (field names and types, ignoring values)
2. Hash schema + task description
3. Cache SQL expression by this hash

### 2. String Fingerprint Caching

For patterned strings (phones, dates, IDs), the cache key is based on the **format fingerprint**:

```sql
-- These two calls have the SAME fingerprint:
SELECT parse_phone('(555) 123-4567', 'area code')  -- fingerprint: "known:phone:us_parens"
SELECT parse_phone('(800) 999-1234', 'area code')  -- fingerprint: "known:phone:us_parens"
--                  ↑ Different values, same format = CACHE HIT

-- This has a DIFFERENT fingerprint:
SELECT parse_phone('555-123-4567', 'area code')    -- fingerprint: "known:phone:us_dashes"
--                  ↑ Different format = NEW SQL generated
```

**Fingerprinting methods:**
- **Pattern Library:** Matches known formats (phone, date, email, currency, etc.)
- **Normalized:** Collapses character classes: `"(555) 123-4567"` → `"(D)_D-D"`
- **With Lengths:** Includes run lengths: `"(555) 123-4567"` → `"(D3)_D3-D4"`
- **Hybrid:** Pattern library first, falls back to normalized

## Available Semantic Macros

### `smart_json(data, path_description)`

Extract values from JSON using natural language.

```sql
SELECT smart_json(order_data, 'customer email') FROM orders;
SELECT smart_json(product_info, 'price in dollars') FROM products;

-- Operator syntax:
SELECT order_data -> 'customer name' FROM orders;
```

**Cache strategy:** JSON schema

### `parse_phone(phone_value, task)`

Parse phone numbers in any format.

```sql
SELECT parse_phone('(555) 123-4567', 'area code');      -- "555"
SELECT parse_phone('555.123.4567', 'last 4 digits');    -- "4567"
SELECT parse_phone('+1-555-123-4567', 'digits only');   -- "15551234567"
```

**Cache strategy:** String fingerprint (hybrid)

### `parse_date(date_value, task)`

Parse dates in any format.

```sql
SELECT parse_date('01/15/2024', 'year');           -- "2024"
SELECT parse_date('January 15, 2024', 'month');    -- "January" or "01"
SELECT parse_date('2024-01-15', 'iso format');     -- "2024-01-15"
```

**Cache strategy:** String fingerprint (pattern library)

### `parse_value(value, task)`

Universal parser for any patterned string.

```sql
SELECT parse_value(email, 'domain') FROM contacts;
SELECT parse_value(ssn, 'last 4 digits') FROM employees;
SELECT parse_value(price, 'numeric value') FROM products;

-- Operator syntax:
SELECT email PARSE 'domain' FROM contacts;
```

**Cache strategy:** String fingerprint (hybrid with lengths)

## Creating Your Own Semantic Macro

To create a semantic macro, define a cascade with:

1. **`output_mode: sql_execute`** - LLM returns SQL, not values
2. **`cache_key.strategy`** - Either `"structure"` or `"fingerprint"`
3. **Structure/fingerprint args** - Which args determine the cache key

### Example: JSON Schema Caching

```yaml
sql_function:
  name: my_json_extractor
  args:
    - name: data
      type: JSON
      structure_source: true  # Use schema for caching
    - name: task
      type: VARCHAR

  output_mode: sql_execute

  cache_key:
    strategy: structure
    structure_args: [data]

  cache: true
```

### Example: String Fingerprint Caching

```yaml
sql_function:
  name: my_string_parser
  args:
    - name: value
      type: VARCHAR
    - name: task
      type: VARCHAR

  output_mode: sql_execute

  cache_key:
    strategy: fingerprint
    fingerprint_args: [value]
    fingerprint_config:
      method: hybrid        # pattern_library, normalized, with_lengths, or hybrid
      include_lengths: false

  cache: true
```

## Performance Characteristics

| Scenario | LLM Calls | Latency |
|----------|-----------|---------|
| First call (new structure) | 1 | ~500-2000ms |
| Cache hit (same structure) | 0 | ~1-5ms |
| New structure | 1 | ~500-2000ms |
| Same structure, different task | 1 | ~500-2000ms |

The cache is **two-tier**:
- **L1:** In-memory dict (instant)
- **L2:** ClickHouse table (persistent across restarts)

## Design Philosophy

Semantic Macros embrace a key insight: **data shape is often more stable than data content**.

- Orders have the same structure across millions of rows
- Phone numbers follow a handful of standard formats
- Dates come in maybe a dozen common patterns

By caching at the structural level, we get:
- **Massive cost reduction:** One LLM call per structure, not per row
- **Consistent behavior:** Same structure always uses the same SQL
- **Self-healing:** New formats automatically generate new parsers
- **Transparency:** Users can inspect cached SQL expressions

This is the power of treating the LLM as a macro expander rather than a direct value generator.
