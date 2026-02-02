# SQL Connections


Connect LARS to 18+ data sources through DuckDB's federation capabilities. Query PostgreSQL,
  BigQuery, Snowflake, S3, MongoDB, and more with a unified SQL interface.


> **INFO: Federation, Not ETL**
>
> 
> LARS federates queries across data sources using DuckDB's ATTACH capability. For most sources,
>     data stays where it is—queries are pushed down. For document databases (MongoDB, Cassandra),
>     data is materialized into DuckDB for SQL compatibility.
> 


> **TIP: Tested Databases**
>
> 
> LARS has been tested with PostgreSQL, MySQL, Oracle, MSSQL, IBM DB2, and SAP HANA
>     via Docker test infrastructure. See the `docker/` directory for example configurations.
> 

On This Page
- [Quick Start](#quick-start)
- [Connection Types](#connection-types)
- [Traditional Databases](#databases)
- [Cloud Data Warehouses](#cloud-warehouses)
- [Object Storage](#object-storage)
- [Lakehouse Formats](#lakehouse)
- [Document Databases](#document-dbs)
- [Spreadsheets & Files](#files)
- [Schema Discovery](#schema-discovery)
- [Troubleshooting](#troubleshooting)


## Quick Start


Connections are configured via YAML files in the `sql_connections/` directory.

### Step 1: Create Connection File


```sql_connections/my_postgres.yaml
connection_name: my_postgres
type: postgres
host: localhost
port: 5432
database: mydb
user: myuser
password_env: POSTGRES_PASSWORD
enabled: true
```

### Step 2: Set Environment Variables


```environment setup
export POSTGRES_PASSWORD="secret"
```

### Step 3: Run Schema Discovery


```cli
lars sql crawl
```

### Step 4: Query Your Data


```cli
lars sql query "SELECT * FROM my_postgres.public.users LIMIT 10"
```

## Connection Types Overview


| Category                  | Types                                             | Federation                              |
|---------------------------|---------------------------------------------------|-----------------------------------------|
| **Traditional Databases** | `postgres`, `mysql`, `sqlite`, `clickhouse`       | Native ATTACH (ClickHouse materializes) |
| **Cloud Warehouses**      | `bigquery`, `snowflake`, `motherduck`             | Native ATTACH via extensions            |
| **Object Storage**        | `s3`, `gcs`, `azure`, `http`                      | Direct file reads (Parquet, CSV, JSON)  |
| **Lakehouse**             | `delta`, `iceberg`                                | Native format support                   |
| **Document DBs**          | `mongodb`, `cassandra`                            | Materializes to DuckDB                  |
| **Files**                 | `excel`, `gsheets`, `csv_folder`, `duckdb_folder` | Direct reads / materialization          |
| **Generic**               | `odbc`                                            | Via ODBC drivers                        |


### Common Configuration Options


All connection types support these optional fields:


| Field                      | Default | Description                                          |
|----------------------------|---------|------------------------------------------------------|
| `enabled`                  | `true`  | Whether the connection is active                     |
| `read_only`                | `true`  | Prevent write operations                             |
| `sample_row_limit`         | `50`    | Max rows for schema discovery samples                |
| `distinct_value_threshold` | `100`   | Show value distribution if distinct count below this |


## Traditional Databases


#### PostgreSQL


Native DuckDB ATTACH using the `postgres` extension.


Default port: 5432


#### MySQL


Native DuckDB ATTACH using the `mysql` extension.


Default port: 3306


#### SQLite


Direct file attachment for SQLite databases.


Local files only


#### ClickHouse


HTTP API connection, tables materialized into DuckDB.


Default port: 8123 (HTTP)

### PostgreSQL


| Field          | Required | Default | Description                              |
|----------------|----------|---------|------------------------------------------|
| `host`         | Yes      | —       | PostgreSQL server hostname               |
| `database`     | Yes      | —       | Database name                            |
| `port`         | No       | 5432    | PostgreSQL port                          |
| `user`         | No       | —       | Username                                 |
| `password_env` | No       | —       | Environment variable containing password |


```sql_connections/production_db.yaml
connection_name: production_db
type: postgres
host: db.example.com
port: 5432
database: production
user: readonly_user
password_env: PROD_DB_PASSWORD
enabled: true
read_only: true
```

```query syntax
SELECT * FROM production_db.public.users;
SELECT * FROM production_db.analytics.events;
```

### MySQL


```sql_connections/mysql_analytics.yaml
connection_name: mysql_analytics
type: mysql
host: mysql.example.com
port: 3306
database: analytics
user: analyst
password_env: MYSQL_PASSWORD
enabled: true
```

### SQLite


```sql_connections/local_cache.yaml
connection_name: local_cache
type: sqlite
database: /path/to/cache.db
enabled: true
```

### ClickHouse


> **WARNING: Materialization**
>
> 
> ClickHouse tables are **materialized** (copied) into DuckDB. Use `sample_row_limit`
>     to control how many rows are copied per table. This is different from PostgreSQL/MySQL which use
>     native federation.
> 


```sql_connections/clickhouse_logs.yaml
connection_name: clickhouse_logs
type: clickhouse
host: clickhouse.example.com
port: 8123  # HTTP port, not 9000
database: logs
user: reader
password_env: CLICKHOUSE_PASSWORD
enabled: true
sample_row_limit: 1000
```

```dependency
pip install clickhouse-connect
```

## Cloud Data Warehouses


#### BigQuery


Native DuckDB extension from community repository.


GCP service account auth


#### Snowflake


Native DuckDB `snowflake` extension.


Account + user + warehouse


#### Motherduck


Cloud-hosted DuckDB with native ATTACH.


Token-based auth

### BigQuery


| Field             | Required | Default                          | Description                      |
|-------------------|----------|----------------------------------|----------------------------------|
| `project_id`      | Yes      | —                                | GCP project ID to query          |
| `credentials_env` | No       | `GOOGLE_APPLICATION_CREDENTIALS` | Env var for service account JSON |


```sql_connections/bigquery_analytics.yaml
connection_name: bigquery_analytics
type: bigquery
project_id: my-gcp-project
enabled: true
read_only: true
```

```environment setup
# Option 1: Path to service account JSON file
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"

# Option 2: JSON content directly (useful in containers)
export GOOGLE_APPLICATION_CREDENTIALS='{"type":"service_account","project_id":"..."}'
```


**Required GCP Permissions:**
- `bigquery.jobs.create` - To run queries
- `bigquery.tables.getData` - To read table data
- `bigquery.readsessions.create` (optional) - For Storage Read API (faster reads)


### Snowflake


| Field          | Required | Description                                    |
|----------------|----------|------------------------------------------------|
| `account`      | Yes      | Account identifier (e.g., `xy12345.us-east-1`) |
| `user`         | Yes      | Snowflake username                             |
| `database`     | No       | Default database                               |
| `warehouse`    | No       | Compute warehouse                              |
| `role`         | No       | Snowflake role                                 |
| `password_env` | No       | Env var for password                           |


```sql_connections/snowflake_warehouse.yaml
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

### Motherduck


```sql_connections/motherduck_analytics.yaml
connection_name: motherduck_analytics
type: motherduck
database: my_analytics
motherduck_token_env: MOTHERDUCK_TOKEN
enabled: true
```

## Object Storage


Read Parquet, CSV, and JSON files directly from cloud object storage.


#### Amazon S3


Also supports MinIO, Cloudflare R2, DigitalOcean Spaces via `endpoint_url`.


#### Google Cloud Storage


Read from GCS buckets with service account auth.


#### Azure Blob Storage


Read from Azure containers via connection string.


#### HTTP/HTTPS


Read files directly from URLs.

### Amazon S3


| Field            | Required | Default   | Description                        |
|------------------|----------|-----------|------------------------------------|
| `bucket`         | Yes      | —         | S3 bucket name                     |
| `prefix`         | No       | —         | Path prefix within bucket          |
| `region`         | No       | us-east-1 | AWS region                         |
| `access_key_env` | No       | —         | Env var for AWS access key         |
| `secret_key_env` | No       | —         | Env var for AWS secret key         |
| `file_pattern`   | No       | *.parquet | Glob pattern for files             |
| `endpoint_url`   | No       | —         | S3-compatible endpoint (MinIO, R2) |


```sql_connections/s3_data_lake.yaml
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

#### S3-Compatible Storage (MinIO, R2)


```minio example
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

```cloudflare r2 example
connection_name: r2_storage
type: s3
bucket: my-bucket
endpoint_url: https://account-id.r2.cloudflarestorage.com
access_key_env: R2_ACCESS_KEY
secret_key_env: R2_SECRET_KEY
file_pattern: "**/*.parquet"
enabled: true
```

### Google Cloud Storage


```sql_connections/gcs_warehouse.yaml
connection_name: gcs_warehouse
type: gcs
bucket: my-data-warehouse
prefix: processed/2024
credentials_env: GOOGLE_APPLICATION_CREDENTIALS
file_pattern: "*.parquet"
enabled: true
```

### Azure Blob Storage


```sql_connections/azure_data.yaml
connection_name: azure_data
type: azure
bucket: analytics-container
prefix: exports
connection_string_env: AZURE_STORAGE_CONNECTION_STRING
file_pattern: "*.parquet"
enabled: true
```

### HTTP/HTTPS Files


```sql_connections/public_dataset.yaml
connection_name: public_dataset
type: http
folder_path: https://example.com/data/events.parquet
enabled: true
```

## Lakehouse Formats


#### Delta Lake


Read Delta tables from local paths or cloud storage (s3://, azure://).


#### Apache Iceberg


Read Iceberg tables with optional catalog support (REST, Glue, Hive).

### Delta Lake


```local delta table
connection_name: delta_events
type: delta
table_path: /data/delta/events
enabled: true
```

```delta on s3
connection_name: delta_s3
type: delta
table_path: s3://my-bucket/delta/customers
access_key_env: AWS_ACCESS_KEY_ID
secret_key_env: AWS_SECRET_ACCESS_KEY
region: us-east-1
enabled: true
```

### Apache Iceberg


```sql_connections/iceberg_warehouse.yaml
connection_name: iceberg_warehouse
type: iceberg
table_path: s3://my-bucket/iceberg/sales
access_key_env: AWS_ACCESS_KEY_ID
secret_key_env: AWS_SECRET_ACCESS_KEY
enabled: true
```

## Document Databases


> **WARNING: Materialization Required**
>
> 
> Document databases (MongoDB, Cassandra) are **materialized** into DuckDB tables.
>     Use `sample_row_limit` to control data volume. Nested documents are flattened with
>     underscores (e.g., `address.city` becomes `address_city`).
> 


### MongoDB


| Field             | Required | Description                               |
|-------------------|----------|-------------------------------------------|
| `mongodb_uri_env` | Yes      | Env var containing MongoDB connection URI |
| `database`        | Yes      | MongoDB database name                     |


```sql_connections/mongo_users.yaml
connection_name: mongo_users
type: mongodb
mongodb_uri_env: MONGODB_URI
database: production
enabled: true
sample_row_limit: 10000
```

```environment & dependencies
export MONGODB_URI="mongodb://user:password@localhost:27017"
pip install pymongo pandas
```

### Cassandra


```sql_connections/cassandra_events.yaml
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

```dependency
pip install cassandra-driver pandas
```

## Spreadsheets & Files


#### Google Sheets


Read sheets via service account. Sheet must be shared.


#### Excel Files


Read local .xlsx/.xls files. Each sheet becomes a table.


#### CSV Folder


Auto-load all CSV files from a directory.


#### DuckDB Folder


Attach multiple .duckdb files from a directory.

### Google Sheets


```sql_connections/sales_tracker.yaml
connection_name: sales_tracker
type: gsheets
spreadsheet_id: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
sheet_name: Q4_Sales  # Optional: specific sheet
credentials_env: GOOGLE_APPLICATION_CREDENTIALS
enabled: true
```


**Note:** The spreadsheet must be shared with the service account email.

### Excel Files


```sql_connections/budget_2024.yaml
connection_name: budget_2024
type: excel
file_path: /data/reports/budget_2024.xlsx
enabled: true
```

```query syntax
SELECT * FROM budget_2024.Sheet1;
SELECT * FROM budget_2024.Summary;
```

```dependency
pip install openpyxl
```

### CSV Folder


```sql_connections/csv_data.yaml
connection_name: csv_data
type: csv_folder
folder_path: /data/csv_exports
enabled: true
```

```query syntax
-- For file: customers.csv
SELECT * FROM csv_data.customers;
-- For file: 2024-sales-report.csv
SELECT * FROM csv_data._2024_sales_report;
```

### DuckDB Folder


```sql_connections/research_dbs.yaml
connection_name: research_dbs
type: duckdb_folder
folder_path: /data/research
enabled: true
```

### ODBC (Generic)


Connect to any ODBC-compatible database.

```sql_connections/legacy_db.yaml
connection_name: legacy_db
type: odbc
odbc_dsn: LegacyOracleDB
enabled: true
```

## Schema Discovery


After configuring connections, run schema discovery to index tables for search and populate
  the RAG index for natural language queries.

```discovery commands
# Basic discovery
lars sql crawl

# With custom session ID
lars sql crawl --session my_discovery

# With all environment variables
MONGODB_URI="mongodb://..." \
AWS_ACCESS_KEY_ID="..." \
AWS_SECRET_ACCESS_KEY="..." \
lars sql crawl
```

### What Discovery Does
1. Connects to each enabled data source
2. Lists all tables/views
3. Extracts schema information (columns, types)
4. Samples data for value distributions
5. Builds a RAG index for natural language queries


## Troubleshooting


### BigQuery: "Error while creating read session"


> **TIP: Solution**
>
> 
> Missing BigQuery Storage Read API permissions. Either grant `bigquery.readsessions.create`
>     and `bigquery.readsessions.getData`, or accept that schema info will be available but
>     row counts/samples won't.
> 


### S3/MinIO: "HTTP 403" errors


> **TIP: Solution**
>
> 
> S3 credentials not set or expired. Ensure environment variables are set:
> 
```
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```


### MongoDB: "missing mongodb_uri_env or env var not set"


> **TIP: Solution**
>
> 
> The `MONGODB_URI` environment variable isn't set:
> 
```
export MONGODB_URI="mongodb://user:password@host:27017"
```


### ClickHouse: "Authentication failed"


> **TIP: Solution**
>
> 
> Wrong credentials or using native port instead of HTTP. Use port **8123** (HTTP),
>     not 9000 (native).
> 


### General: "Unsupported database type"


> **TIP: Solution**
>
> 
> Typo in `type` field. Check it matches one of the supported types exactly.
> 


## Dependencies Reference


| Type                                  | Required Packages                        |
|---------------------------------------|------------------------------------------|
| `postgres`, `mysql`, `sqlite`         | Built into DuckDB                        |
| `bigquery`, `snowflake`, `motherduck` | DuckDB extensions (auto-installed)       |
| `s3`, `gcs`, `azure`, `http`          | DuckDB httpfs extension (auto-installed) |
| `delta`, `iceberg`                    | DuckDB extensions                        |
| `mongodb`                             | `pip install pymongo pandas`             |
| `cassandra`                           | `pip install cassandra-driver pandas`    |
| `clickhouse`                          | `pip install clickhouse-connect`         |
| `excel`                               | `pip install openpyxl`                   |
| `gsheets`                             | DuckDB extension + service account       |
| `odbc`                                | System ODBC drivers                      |


```install all optional connectors
pip install pymongo cassandra-driver clickhouse-connect openpyxl pandas
```

## Next Steps
- [Semantic SQL](#semantic-sql) - Run AI-powered queries on connected data
- [Vector Search](#embedding) - Create embeddings from your data
- [AI Providers](#providers) - Configure LLM providers for semantic operations
