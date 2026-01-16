# SQL Connectors Reference

LARS supports connecting to 18+ data sources through DuckDB's federation capabilities. All connections are configured via YAML files in the `sql_connections/` directory.

## Table of Contents

- [Quick Start](#quick-start)
- [Connection Types](#connection-types)
  - [Traditional Databases](#traditional-databases)
    - [PostgreSQL](#postgresql)
    - [MySQL](#mysql)
    - [SQLite](#sqlite)
    - [ClickHouse](#clickhouse)
  - [Cloud Data Warehouses](#cloud-data-warehouses)
    - [BigQuery](#bigquery)
    - [Snowflake](#snowflake)
    - [Motherduck](#motherduck)
  - [Object Storage](#object-storage)
    - [Amazon S3](#amazon-s3)
    - [S3-Compatible (MinIO, R2)](#s3-compatible-minio-r2)
    - [Google Cloud Storage](#google-cloud-storage)
    - [Azure Blob Storage](#azure-blob-storage)
    - [HTTP/HTTPS Files](#httphttps-files)
  - [Lakehouse Formats](#lakehouse-formats)
    - [Delta Lake](#delta-lake)
    - [Apache Iceberg](#apache-iceberg)
  - [Document Databases](#document-databases)
    - [MongoDB](#mongodb)
    - [Cassandra](#cassandra)
  - [Spreadsheets & Files](#spreadsheets--files)
    - [Google Sheets](#google-sheets)
    - [Excel Files](#excel-files)
    - [CSV Folder](#csv-folder)
    - [DuckDB Folder](#duckdb-folder)
  - [Generic Connectors](#generic-connectors)
    - [ODBC](#odbc)
- [Common Configuration Options](#common-configuration-options)
- [Running Schema Discovery](#running-schema-discovery)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

1. Create a YAML file in `sql_connections/`:

```yaml
# sql_connections/my_postgres.yaml
connection_name: my_postgres
type: postgres
host: localhost
port: 5432
database: mydb
user: myuser
password_env: POSTGRES_PASSWORD
enabled: true
```

2. Set required environment variables:

```bash
export POSTGRES_PASSWORD="secret"
```

3. Run schema discovery:

```bash
lars sql crawl
```

4. Query your data:

```bash
lars sql query "SELECT * FROM my_postgres.public.users LIMIT 10"
```

---

## Connection Types

### Traditional Databases

#### PostgreSQL

Native DuckDB ATTACH using the `postgres` extension.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `host` | PostgreSQL server hostname |
| `database` | Database name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `port` | 5432 | PostgreSQL port |
| `user` | - | Username |
| `password_env` | - | Environment variable containing password |

**Example:**

```yaml
# sql_connections/production_db.yaml
connection_name: production_db
type: postgres
host: db.example.com
port: 5432
database: production
user: readonly_user
password_env: PROD_DB_PASSWORD
enabled: true
read_only: true
sample_row_limit: 100
```

**Environment Variables:**
```bash
export PROD_DB_PASSWORD="your_password"
```

**Query Syntax:**
```sql
SELECT * FROM production_db.public.users;
SELECT * FROM production_db.analytics.events;
```

---

#### MySQL

Native DuckDB ATTACH using the `mysql` extension.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `host` | MySQL server hostname |
| `database` | Database name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `port` | 3306 | MySQL port |
| `user` | - | Username |
| `password_env` | - | Environment variable containing password |

**Example:**

```yaml
connection_name: mysql_analytics
type: mysql
host: mysql.example.com
port: 3306
database: analytics
user: analyst
password_env: MYSQL_PASSWORD
enabled: true
```

**Query Syntax:**
```sql
SELECT * FROM mysql_analytics.analytics.pageviews;
```

---

#### SQLite

Direct file attachment for SQLite databases.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `database` | Path to SQLite file |

**Example:**

```yaml
connection_name: local_cache
type: sqlite
database: /path/to/cache.db
enabled: true
```

**Query Syntax:**
```sql
SELECT * FROM local_cache.main.cache_entries;
```

---

#### ClickHouse

Connects via HTTP API and materializes tables into DuckDB.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `host` | ClickHouse server hostname |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `port` | 8123 | HTTP port (not native 9000) |
| `database` | default | Database name |
| `user` | default | Username |
| `password_env` | - | Environment variable containing password |

**Example:**

```yaml
connection_name: clickhouse_logs
type: clickhouse
host: clickhouse.example.com
port: 8123
database: logs
user: reader
password_env: CLICKHOUSE_PASSWORD
enabled: true
sample_row_limit: 1000
```

**Dependencies:**
```bash
pip install clickhouse-connect
```

**Note:** ClickHouse tables are materialized (copied) into DuckDB. The `sample_row_limit` controls how many rows are copied per table.

**Query Syntax:**
```sql
SELECT * FROM clickhouse_logs.access_logs;
```

---

### Cloud Data Warehouses

#### BigQuery

Native DuckDB ATTACH using the `bigquery` extension from the community repository.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `project_id` | GCP project ID to query |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `credentials_env` | GOOGLE_APPLICATION_CREDENTIALS | Env var for service account JSON |

**Example:**

```yaml
connection_name: bigquery_analytics
type: bigquery
project_id: my-gcp-project
enabled: true
read_only: true
sample_row_limit: 100
```

**Environment Variables:**

```bash
# Option 1: Path to service account JSON file
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# Option 2: JSON content directly (useful in containers)
export GOOGLE_APPLICATION_CREDENTIALS='{"type":"service_account","project_id":"..."}'
```

**Required GCP Permissions:**
- `bigquery.jobs.create` - To run queries
- `bigquery.tables.getData` - To read table data
- `bigquery.readsessions.create` (optional) - For Storage Read API (faster reads)

**Note:** If you don't have Storage Read API permissions, schema discovery will still work but row counts and sample data may not be available.

**Query Syntax:**
```sql
SELECT * FROM bigquery_analytics.my_dataset.my_table;
```

---

#### Snowflake

Native DuckDB ATTACH using the `snowflake` extension.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `account` | Snowflake account identifier (e.g., `xy12345.us-east-1`) |
| `user` | Snowflake username |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `database` | - | Default database |
| `warehouse` | - | Compute warehouse |
| `role` | - | Snowflake role |
| `password_env` | - | Env var for password |

**Example:**

```yaml
connection_name: snowflake_warehouse
type: snowflake
account: xy12345.us-east-1
user: analyst
database: ANALYTICS
warehouse: COMPUTE_WH
role: ANALYST_ROLE
password_env: SNOWFLAKE_PASSWORD
enabled: true
```

**Query Syntax:**
```sql
SELECT * FROM snowflake_warehouse.ANALYTICS.PUBLIC.CUSTOMERS;
```

---

#### Motherduck

Cloud-hosted DuckDB with native ATTACH.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `database` | Motherduck database name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `motherduck_token_env` | MOTHERDUCK_TOKEN | Env var for authentication token |

**Example:**

```yaml
connection_name: motherduck_analytics
type: motherduck
database: my_analytics
motherduck_token_env: MOTHERDUCK_TOKEN
enabled: true
```

**Environment Variables:**
```bash
export MOTHERDUCK_TOKEN="your_motherduck_token"
```

**Query Syntax:**
```sql
SELECT * FROM motherduck_analytics.main.events;
```

---

### Object Storage

#### Amazon S3

Read Parquet, CSV, and JSON files directly from S3 buckets.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `bucket` | S3 bucket name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `prefix` | - | Path prefix within bucket |
| `region` | us-east-1 | AWS region |
| `access_key_env` | - | Env var for AWS access key |
| `secret_key_env` | - | Env var for AWS secret key |
| `file_pattern` | *.parquet | Glob pattern for files |

**Example:**

```yaml
connection_name: s3_data_lake
type: s3
bucket: my-data-lake
prefix: bronze/events
region: us-west-2
access_key_env: AWS_ACCESS_KEY_ID
secret_key_env: AWS_SECRET_ACCESS_KEY
file_pattern: "*.parquet"
enabled: true
```

**Environment Variables:**
```bash
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
```

**Supported File Formats:**
- `.parquet` - Apache Parquet
- `.csv` - CSV files
- `.json` / `.jsonl` - JSON/JSONL files

**Query Syntax:**
```sql
SELECT * FROM s3_data_lake.events;  -- Queries events.parquet
```

---

#### S3-Compatible (MinIO, R2)

Works with any S3-compatible storage including MinIO, Cloudflare R2, DigitalOcean Spaces.

**Additional Fields:**
| Field | Description |
|-------|-------------|
| `endpoint_url` | S3-compatible endpoint URL |

**Example (MinIO):**

```yaml
connection_name: minio_data
type: s3
bucket: analytics
prefix: raw
endpoint_url: http://localhost:9000
access_key_env: MINIO_ACCESS_KEY
secret_key_env: MINIO_SECRET_KEY
file_pattern: "*.parquet"
enabled: true
```

**Example (Cloudflare R2):**

```yaml
connection_name: r2_storage
type: s3
bucket: my-bucket
endpoint_url: https://account-id.r2.cloudflarestorage.com
access_key_env: R2_ACCESS_KEY
secret_key_env: R2_SECRET_KEY
file_pattern: "**/*.parquet"
enabled: true
```

---

#### Google Cloud Storage

Read files from GCS buckets.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `bucket` | GCS bucket name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `prefix` | - | Path prefix within bucket |
| `credentials_env` | GOOGLE_APPLICATION_CREDENTIALS | Env var for service account |
| `file_pattern` | *.parquet | Glob pattern for files |

**Example:**

```yaml
connection_name: gcs_warehouse
type: gcs
bucket: my-data-warehouse
prefix: processed/2024
credentials_env: GOOGLE_APPLICATION_CREDENTIALS
file_pattern: "*.parquet"
enabled: true
```

**Query Syntax:**
```sql
SELECT * FROM gcs_warehouse.sales_2024;
```

---

#### Azure Blob Storage

Read files from Azure Blob containers.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `bucket` | Azure container name |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `prefix` | - | Path prefix within container |
| `connection_string_env` | - | Env var for Azure connection string |
| `file_pattern` | *.parquet | Glob pattern for files |

**Example:**

```yaml
connection_name: azure_data
type: azure
bucket: analytics-container
prefix: exports
connection_string_env: AZURE_STORAGE_CONNECTION_STRING
file_pattern: "*.parquet"
enabled: true
```

**Environment Variables:**
```bash
export AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
```

---

#### HTTP/HTTPS Files

Read files directly from HTTP/HTTPS URLs.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `folder_path` | Full URL to the file |

**Example:**

```yaml
connection_name: public_dataset
type: http
folder_path: https://example.com/data/events.parquet
enabled: true
```

**Note:** Best for single files or known URLs. For multiple files, use S3/GCS/Azure.

---

### Lakehouse Formats

#### Delta Lake

Read Delta Lake tables from local paths or cloud storage.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `table_path` | Path to Delta table (local, s3://, azure://) |

**Optional Fields (for cloud paths):**
| Field | Description |
|-------|-------------|
| `access_key_env` | AWS access key env var |
| `secret_key_env` | AWS secret key env var |
| `region` | AWS region |

**Example (Local):**

```yaml
connection_name: delta_events
type: delta
table_path: /data/delta/events
enabled: true
```

**Example (S3):**

```yaml
connection_name: delta_s3
type: delta
table_path: s3://my-bucket/delta/customers
access_key_env: AWS_ACCESS_KEY_ID
secret_key_env: AWS_SECRET_ACCESS_KEY
region: us-east-1
enabled: true
```

**Query Syntax:**
```sql
SELECT * FROM delta_events.events;
```

---

#### Apache Iceberg

Read Iceberg tables with catalog support.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `table_path` | Path to Iceberg table, OR |
| `catalog_uri` | URI to Iceberg catalog |

**Optional Fields:**
| Field | Description |
|-------|-------------|
| `catalog_type` | Catalog type: `rest`, `glue`, `hive` |

**Example:**

```yaml
connection_name: iceberg_warehouse
type: iceberg
table_path: s3://my-bucket/iceberg/sales
access_key_env: AWS_ACCESS_KEY_ID
secret_key_env: AWS_SECRET_ACCESS_KEY
enabled: true
```

---

### Document Databases

#### MongoDB

Materializes MongoDB collections into DuckDB tables.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `mongodb_uri_env` | Env var containing MongoDB connection URI |
| `database` | MongoDB database name |

**Example:**

```yaml
connection_name: mongo_users
type: mongodb
mongodb_uri_env: MONGODB_URI
database: production
enabled: true
sample_row_limit: 10000
```

**Environment Variables:**
```bash
export MONGODB_URI="mongodb://user:password@localhost:27017"
# Or with replica set:
export MONGODB_URI="mongodb://user:password@host1:27017,host2:27017/admin?replicaSet=rs0"
```

**Dependencies:**
```bash
pip install pymongo pandas
```

**Note:**
- Collections are materialized (copied) into DuckDB
- Nested documents are flattened with underscores
- `_id` fields are converted to strings
- `sample_row_limit` controls how many documents are copied per collection

**Query Syntax:**
```sql
SELECT * FROM mongo_users.customers;
SELECT * FROM mongo_users.orders;
```

---

#### Cassandra

Materializes Cassandra tables into DuckDB.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `cassandra_hosts` | List of Cassandra host addresses |
| `cassandra_keyspace` | Keyspace name |

**Optional Fields:**
| Field | Description |
|-------|-------------|
| `user` | Username |
| `password_env` | Env var for password |

**Example:**

```yaml
connection_name: cassandra_events
type: cassandra
cassandra_hosts:
  - cassandra1.example.com
  - cassandra2.example.com
cassandra_keyspace: events
user: reader
password_env: CASSANDRA_PASSWORD
enabled: true
sample_row_limit: 5000
```

**Dependencies:**
```bash
pip install cassandra-driver pandas
```

---

### Spreadsheets & Files

#### Google Sheets

Read Google Sheets as tables.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `spreadsheet_id` | Google Sheets ID (from URL) |

**Optional Fields:**
| Field | Default | Description |
|-------|---------|-------------|
| `sheet_name` | - | Specific sheet (default: all sheets) |
| `credentials_env` | GOOGLE_APPLICATION_CREDENTIALS | Service account credentials |

**Example:**

```yaml
connection_name: sales_tracker
type: gsheets
spreadsheet_id: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
sheet_name: Q4_Sales
credentials_env: GOOGLE_APPLICATION_CREDENTIALS
enabled: true
```

**Note:** The spreadsheet must be shared with the service account email.

---

#### Excel Files

Read local Excel files (.xlsx, .xls).

**Required Fields:**
| Field | Description |
|-------|-------------|
| `file_path` | Path to Excel file |

**Example:**

```yaml
connection_name: budget_2024
type: excel
file_path: /data/reports/budget_2024.xlsx
enabled: true
```

**Dependencies:**
```bash
pip install openpyxl
```

**Query Syntax:**
```sql
SELECT * FROM budget_2024.Sheet1;
SELECT * FROM budget_2024.Summary;
```

---

#### CSV Folder

Automatically load all CSV files from a directory.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `folder_path` | Path to directory containing CSV files |

**Example:**

```yaml
connection_name: csv_data
type: csv_folder
folder_path: /data/csv_exports
enabled: true
sample_row_limit: 100
```

**Behavior:**
- Each CSV file becomes a table
- Table names are derived from filenames (sanitized)
- Files are materialized into DuckDB on first access

**Query Syntax:**
```sql
-- For file: customers.csv
SELECT * FROM csv_data.customers;

-- For file: 2024-sales-report.csv
SELECT * FROM csv_data._2024_sales_report;
```

---

#### DuckDB Folder

Attach multiple DuckDB database files from a directory.

**Required Fields:**
| Field | Description |
|-------|-------------|
| `folder_path` | Path to directory containing .duckdb files |

**Example:**

```yaml
connection_name: research_dbs
type: duckdb_folder
folder_path: /data/research
enabled: true
```

**Behavior:**
- Each .duckdb file is attached as a separate database
- Database names are derived from filenames

**Query Syntax:**
```sql
-- For file: market_research.duckdb with table "companies"
SELECT * FROM market_research.companies;
```

---

### Generic Connectors

#### ODBC

Connect to any ODBC-compatible database.

**Required Fields (one of):**
| Field | Description |
|-------|-------------|
| `odbc_dsn` | ODBC Data Source Name |
| `odbc_connection_string_env` | Env var containing ODBC connection string |

**Example:**

```yaml
connection_name: legacy_db
type: odbc
odbc_dsn: LegacyOracleDB
enabled: true
```

**Note:** Requires ODBC drivers to be installed on the system.

---

## Common Configuration Options

All connection types support these optional fields:

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | true | Whether the connection is active |
| `read_only` | true | Prevent write operations |
| `sample_row_limit` | 50 | Max rows for schema discovery samples |
| `distinct_value_threshold` | 100 | Show value distribution if distinct count < this |

---

## Running Schema Discovery

After configuring connections, run schema discovery to index tables for search:

```bash
# Basic discovery
lars sql crawl

# With custom session ID
lars sql crawl --session my_discovery

# With environment variables for all connections
MONGODB_URI="mongodb://..." \
AWS_ACCESS_KEY_ID="..." \
AWS_SECRET_ACCESS_KEY="..." \
lars sql crawl
```

Discovery will:
1. Connect to each enabled data source
2. List all tables/views
3. Extract schema information (columns, types)
4. Sample data for value distributions
5. Build a RAG index for natural language queries

---

## Troubleshooting

### BigQuery: "Error while creating read session"

**Cause:** Missing BigQuery Storage Read API permissions.

**Solution:** Either:
1. Grant `bigquery.readsessions.create` and `bigquery.readsessions.getData` permissions
2. Or accept that schema info will be available but row counts/samples won't

### S3/MinIO: "HTTP 403" errors

**Cause:** S3 credentials not set or expired.

**Solution:** Ensure environment variables are set:
```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
# Or for MinIO:
export MINIO_ACCESS_KEY="..."
export MINIO_SECRET_KEY="..."
```

### MongoDB: "missing mongodb_uri_env or env var not set"

**Cause:** The `MONGODB_URI` environment variable isn't set.

**Solution:**
```bash
export MONGODB_URI="mongodb://user:password@host:27017"
```

### ClickHouse: "Authentication failed"

**Cause:** Wrong credentials or using native port instead of HTTP.

**Solution:**
- Use port 8123 (HTTP), not 9000 (native)
- Verify username and password

### General: "Unsupported database type"

**Cause:** Typo in `type` field or unsupported type.

**Solution:** Check the `type` field matches one of the supported types exactly.

---

## Dependencies by Connector Type

| Type | Required Packages |
|------|-------------------|
| postgres | (built into DuckDB) |
| mysql | (built into DuckDB) |
| sqlite | (built into DuckDB) |
| bigquery | (DuckDB extension, auto-installed) |
| snowflake | (DuckDB extension) |
| motherduck | (DuckDB extension) |
| s3, gcs, azure, http | (DuckDB httpfs extension, auto-installed) |
| delta | (DuckDB delta extension) |
| iceberg | (DuckDB iceberg extension) |
| mongodb | `pip install pymongo pandas` |
| cassandra | `pip install cassandra-driver pandas` |
| clickhouse | `pip install clickhouse-connect` |
| excel | `pip install openpyxl` |
| gsheets | (DuckDB extension + service account) |
| odbc | System ODBC drivers |

Install all optional connectors:
```bash
pip install pymongo cassandra-driver clickhouse-connect openpyxl pandas
```
