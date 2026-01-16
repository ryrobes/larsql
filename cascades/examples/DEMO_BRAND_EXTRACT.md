# Brand Extraction Demo

A purpose-built demo cascade that showcases LARS's key features:

- **Deterministic cells** (Python + SQL alongside LLM)
- **Candidates** (best-of-3 extraction with evaluator)
- **Wards** (output validation with retry)
- **Context control** (the "leaky context" anti-pattern)
- **Receipts** (cost tracking to identify outliers)
- **Multi-turn tool use** (web search for low-confidence cases)
- **SQL integration** (lars_udf / lars_cascade_udf)

## The Demo Story

Three versions of the same cascade:

| Version | File | Feature |
|---------|------|---------|
| **v0** | `demo_brand_extract_v0.yaml` | "Leaky context" - lookup returns up to 50 rows |
| **v1** | `demo_brand_extract_v1.yaml` | Fixed - lookup limited to 5 rows |
| **v2** | `demo_brand_extract_v2.yaml` | Web search augmentation for low-confidence cases |

When you run v0 with a broad input like "USB-C Cable", the lookup returns 20+ brand matches, all of which get stuffed into the LLM prompt. This causes a **cost spike** visible in receipts.

The v1 fix is a **1-line change**: `LIMIT 50` → `LIMIT 5`

**v2 adds web search**: When the LLM isn't confident about a brand, it can call
`brave_web_search` for additional context. This creates **multi-turn sounding loops**
visible in the UI - you can see each candidate trying different search strategies.

## Quick Start

### Run from CLI

```bash
# Normal input (specific brand)
lars run examples/demo_brand_extract_v0.yaml \
  --input '{"product_name": "Sony WH-1000XM5 Headphones"}'

# Outlier input (broad query - triggers the leak in v0)
lars run examples/demo_brand_extract_v0.yaml \
  --input '{"product_name": "USB-C Cable 6ft Black"}'
```

### Compare v0 vs v1

```bash
# v0 with outlier - watch the cost spike
lars run examples/demo_brand_extract_v0.yaml \
  --input '{"product_name": "USB-C Cable 6ft Black"}' \
  --session demo_v0_outlier

# v1 with same input - cost back to normal
lars run examples/demo_brand_extract_v1.yaml \
  --input '{"product_name": "USB-C Cable 6ft Black"}' \
  --session demo_v1_outlier
```

Then check receipts:
```bash
lars sql query "SELECT session_id, SUM(cost) as total_cost FROM all_data WHERE session_id LIKE 'demo_%%' GROUP BY session_id"
```

## SQL Demo (The Mic Drop)

### Setup

```bash
# Start the PostgreSQL-compatible server
lars server --port 5432

# In another terminal, connect with any SQL client
psql postgresql://lars@localhost:5432/default

# Run the setup script
\i examples/demo_brand_setup.sql
```

### Run cascade on each row

```sql
-- Run v0 (leaky) on all products
SELECT
  id,
  product_name,
  lars_cascade_udf(
    'examples/demo_brand_extract_v0.yaml',
    json_object('product_name', product_name)
  ) as result
FROM demo_products
ORDER BY id;
```

Row 6 ("USB-C Cable") will spike in cost. Check receipts to see why.

### Simple scalar UDF

```sql
-- Quick one-shot extraction (no cascade, just LLM)
SELECT
  product_name,
  lars_udf('Extract the brand name. Return just the brand.', product_name) as brand
FROM demo_products;
```

## What to Show in the Demo Video

1. **Run list** - "Why did this one spike?"
2. **Receipts** - "Which cell caused it?"
3. **Cell anatomy** - "Tool calls + turns"
4. **Context inspector** - "97% was prompt payload, top chunk was..."
5. **Culprit** - "lookup_brands dumped 25 rows of JSON"
6. **Quick fix** - Switch to v1, "Now it's back to normal"
7. **SQL mic drop** - "And you can call it from any SQL client"

## Files

| File | Description |
|------|-------------|
| `demo_brand_extract_v0.yaml` | Leaky version (LIMIT 50) |
| `demo_brand_extract_v1.yaml` | Fixed version (LIMIT 5) |
| `demo_brand_extract_v2.yaml` | Web search augmented (multi-turn) |
| `demo_brand_setup.sql` | SQL to create demo_products table |

## Cell Overview

| Cell | Type | Purpose |
|------|------|---------|
| `setup_brands` | SQL (deterministic) | Create temp table with 30+ brands |
| `prep` | Python (deterministic) | Normalize input, extract query_key |
| `lookup_brands` | SQL (deterministic) | Search brands table (THE LEAK in v0) |
| `extract_brand` | LLM + Candidates | 3 parallel extractions, evaluator picks best |
| `extract_brand` (v2) | LLM + Candidates + Tools | Same, but with `brave_web_search` for uncertain cases |
| `validate` | LLM + Ward | Validate output, retry if invalid |

## v2: Web Search with Early Exit

v2 demonstrates **per-turn validation with early exit** inside soundings:

### The Pattern
```yaml
rules:
  max_turns: 3
  loop_until:
    python: |
      # Check if confidence >= 0.7
      if confidence >= 0.7:
        result = {"valid": True, "reason": "Confident"}
      else:
        result = {"valid": False, "reason": "Keep searching"}
  loop_until_silent: true  # Impartial - model doesn't know about this
```

### How It Works
1. Each sounding starts with up to 3 turns
2. After each turn, the validator checks confidence
3. If confidence >= 0.7, that sounding **exits early** (turns 2-3 skipped)
4. If confidence < 0.7, the sounding continues (likely calls web search)
5. `loop_until_silent: true` means the model doesn't game the validation

### The Demo Story
- **Clear brand** ("Sony WH-1000XM5"): Model is confident on turn 1, exits immediately
- **Ambiguous product** ("USB-C Cable"): Low confidence triggers more turns + web search
- **Unknown brand** ("JSAUX Steam Deck Dock"): May need web search to verify

**Requirements**: Set `BRAVE_SEARCH_API_KEY` environment variable.

```bash
# Try with an ambiguous product
lars run examples/demo_brand_extract_v2.yaml \
  --input '{"product_name": "JSAUX Steam Deck Dock"}'
```

In the Studio UI, you can see each sounding's turn count differs - some exit on turn 1,
others continue to turn 2 or 3 with web search calls visible in the conversation.
