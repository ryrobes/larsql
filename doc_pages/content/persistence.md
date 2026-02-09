# Persistence & Materialization


Save query results as durable tables with `INTO`. Materialized tables persist as Parquet files,
  survive across sessions and connections, and are automatically discoverable via the `into_*` naming convention.


> **INFO: Why INTO instead of CREATE TABLE AS?**
>
> LARS uses DuckDB with ephemeral, per-connection databases. Each SQL connection gets its own
> isolated DuckDB instance — there's no shared catalog like PostgreSQL or MySQL. `CREATE TABLE AS`
> only exists for the lifetime of your connection. `INTO` solves this by writing results to Parquet
> files on disk, making them accessible from any connection, any session, at any time.


On This Page
- [Overview](#overview)
- [Basic INTO Syntax](#basic-syntax)
- [THEN PASS INTO](#then-pass-into)
- [Per-Stage Materialization](#per-stage-into)
- [INTO in Hyper Dashboards](#hyper-dashboards)
- [Discovering Materialized Tables](#discovery)
- [Lifecycle & Storage](#lifecycle)
- [Arrow Alias Syntax](#arrow-alias)
- [Examples](#examples)


## Overview


INTO is LARS's answer to the ephemeral nature of DuckDB connections. When you run a query
  through LARS's PostgreSQL wire protocol, your DuckDB instance is created fresh for each connection.
  Traditional `CREATE TABLE AS` statements would lose their results the moment you disconnect.


#### Parquet-Backed


Results are written as Parquet files to disk — fast columnar storage that
      any connection can read.


#### Cross-Session


INTO tables survive disconnections, server restarts, and can be queried
      from any client connected to the same LARS instance.


#### Auto-Discoverable


All materialized tables follow the `into_*` naming convention. Query them
      directly — LARS rewrites references to read from the underlying Parquet files.


#### Pipeline-Native


INTO integrates naturally with LARS's `THEN` pipeline syntax, enabling
      intermediate snapshots at every stage.


## Basic INTO Syntax {#basic-syntax}


Append `INTO table_name` to any query to materialize the results:

```sql
SELECT *
FROM products
WHERE category = 'Electronics'
INTO electronics;
```

This creates a table accessible as `into_electronics`. Query it from any connection:

```sql
SELECT * FROM into_electronics;
```

The original name (without prefix) also works within the same session:

```sql
SELECT * FROM electronics;
```


> **TIP: Naming Convention**
>
> When you write `INTO my_table`, LARS stores it as `into_my_table`. This prefix makes
> materialized tables instantly recognizable and avoids collisions with source tables.


## THEN PASS INTO {#then-pass-into}


`THEN PASS INTO` is a pipeline stage that materializes results without any transformation.
  It's the simplest way to save data for downstream use:

```sql
SELECT customer_id, name, total_spend
FROM customers
WHERE total_spend > 1000
THEN PASS INTO high_value_customers;
```

`PASS` is a no-op stage — it passes data through unchanged. Combined with `INTO`, it becomes
  a materialization command. This is especially useful in two contexts:

1. **Saving query results** for later analysis without modifying them
2. **Sharing data between Hyper dashboard panels** (see [INTO in Hyper Dashboards](#hyper-dashboards))

### PASS INTO with MUTE

If you only want to save data and don't need to see the results, add `THEN MUTE`:

```sql
SELECT * FROM raw_events
WHERE event_date = CURRENT_DATE
THEN PASS INTO todays_events
THEN MUTE;
```

`MUTE` suppresses the result set and returns a single status row confirming how many rows were saved.


## Per-Stage Materialization {#per-stage-into}


Every stage in a pipeline can have its own `INTO`, creating snapshots at each step:

```sql
SELECT * FROM raw_data INTO step0_raw
THEN DEDUPE('email') INTO step1_deduped
THEN FILTER('active customers only') INTO step2_active
THEN ANALYZE 'segment by purchasing behavior' INTO step3_segments;
```

After execution, you have four queryable tables:
- `into_step0_raw` — the original data
- `into_step1_deduped` — after deduplication
- `into_step2_active` — after filtering
- `into_step3_segments` — the final analysis

This is invaluable for:
- **Debugging** — inspect intermediate results to find where things went wrong
- **Audit trails** — keep a record of each transformation step
- **Incremental pipelines** — reuse intermediate results in other queries


> **TIP: Compliance & Debugging**
>
> Use per-stage INTO for compliance and debugging. Each intermediate table is a
> permanent record of exactly what data flowed through each transformation.


## INTO in Hyper Dashboards {#hyper-dashboards}


Hyper dashboards use `THEN PASS INTO` as a shared data layer. Dashboard panels execute in
  parallel — they can't depend on each other's results. Instead, setup SQL materializes shared
  data that all panels reference:

```sql
--- HYPER 'Sales Dashboard'

SELECT * FROM sales_data
WHERE year = 2024
THEN PASS INTO shared_sales;

--- PANEL 'Revenue by Region' (1, 1, 1, 1)
SELECT region, SUM(revenue) as total
FROM into_shared_sales GROUP BY region;

--- PANEL 'Revenue by Month' (2, 1, 1, 1)
SELECT month, SUM(revenue) as total
FROM into_shared_sales GROUP BY month;

--- PANEL 'Top Products' (1, 2, 2, 1)
SELECT product, SUM(units_sold) as units
FROM into_shared_sales GROUP BY product
ORDER BY units DESC LIMIT 10;
```

The setup SQL runs once, materializing `into_shared_sales`. Then each panel query runs in
  parallel against the materialized result — fast and consistent.

> **See also:** [Hyper SQL Client](hyper.html#dashboard-panels) for full dashboard documentation.


## Discovering Materialized Tables {#discovery}


All INTO tables follow the `into_*` naming convention, making them easy to find:

```sql
-- Query any INTO table directly
SELECT * FROM into_electronics;
SELECT COUNT(*) FROM into_step1_deduped;

-- Join INTO tables with source data
SELECT e.*, p.supplier
FROM into_electronics e
JOIN product_suppliers p ON e.product_id = p.product_id;
```

### How It Works

Behind the scenes, LARS's `into_table_rewriter` detects `into_*` references in your SQL and
  rewrites them to `read_parquet()` calls pointing at the stored Parquet files. This happens
  transparently — you just write normal SQL.

```
-- What you write:
SELECT * FROM into_electronics;

-- What LARS executes:
SELECT * FROM read_parquet('/path/to/data/user/lars_results/into_electronics/data.parquet') AS into_electronics;
```


## Lifecycle & Storage {#lifecycle}


### Storage Location

INTO tables are stored as Parquet files under LARS's data directory:

```
$LARS_ROOT/data/user/<results_db>/into_<name>/data.parquet
```

Where `<results_db>` is derived from the database name in your connection string (e.g., `lars_results_myproject`).

### Persistence

- **Across sessions:** INTO tables persist on disk. Reconnect and they're still there.
- **Across server restarts:** Parquet files survive server restarts — no data loss.
- **Re-execution:** Running `INTO` with the same name replaces the previous data (atomic overwrite).

### Namespace Scoping

The `<results_db>` namespace is derived from the database name you connect with. Different
  database names create isolated namespaces:

```
psql -d myproject    →  $LARS_ROOT/data/user/lars_results_myproject/
psql -d analytics    →  $LARS_ROOT/data/user/lars_results_analytics/
```

### Cleanup

INTO tables are not automatically cleaned up. To remove materialized data, delete the
  corresponding directory under `$LARS_ROOT/data/user/`.


## Arrow Alias Syntax {#arrow-alias}


LARS also supports an arrow syntax (`->`) as a shorthand for saving query results:

```sql
SELECT * FROM products WHERE active = true -> active_products;
```

This is equivalent to saving results with the arrow alias. The `SHADOW AS` keyword provides
  a more SQL-like alternative:

```sql
SELECT * FROM products WHERE active = true SHADOW AS active_products;
```

> **NOTE:** Arrow aliases and `INTO` serve similar purposes but work through different mechanisms.
> `INTO` is the recommended approach for pipeline materialization and cross-session persistence.


## Examples


### Staging for Multi-Step Analysis

```sql
-- Step 1: Materialize the base dataset
SELECT * FROM transactions
WHERE amount > 100 AND date >= '2024-01-01'
THEN PASS INTO large_transactions;

-- Step 2: Analyze in a separate query
SELECT category, COUNT(*) as cnt, AVG(amount) as avg_amount
FROM into_large_transactions
GROUP BY category
ORDER BY avg_amount DESC;
```

### Pipeline with Intermediate Snapshots

```sql
SELECT * FROM customer_feedback INTO raw_feedback
THEN FILTER('English language only') INTO english_only
THEN ANALYZE 'classify sentiment and extract key themes' INTO analyzed
THEN FILTER('negative sentiment') INTO negative_feedback;
```

### Dashboard Data Sharing

```sql
--- HYPER 'Customer Health'

SELECT c.*, o.total_orders, o.last_order_date
FROM customers c
JOIN (SELECT customer_id, COUNT(*) as total_orders, MAX(order_date) as last_order_date
      FROM orders GROUP BY customer_id) o
ON c.id = o.customer_id
THEN PASS INTO customer_health;

--- PANEL 'At Risk' (1, 1)
SELECT * FROM into_customer_health
WHERE last_order_date < CURRENT_DATE - INTERVAL '90 days'
ORDER BY total_orders DESC;

--- PANEL 'Champions' (2, 1)
SELECT * FROM into_customer_health
WHERE total_orders > 50
ORDER BY last_order_date DESC;
```

### Silent Background Materialization

```sql
-- Save data without displaying results
SELECT * FROM daily_metrics
WHERE metric_date = CURRENT_DATE
THEN PASS INTO todays_metrics
THEN MUTE;
```
