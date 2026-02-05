# Quickstart Guide


Get LARS running in minutes. This guide covers the essential setup — install, configure, and start querying.
**On This Page**
- [Install](#install)
- [Configure](#configure)
- [Bootstrap](#bootstrap)
- [Start SQL Server](#sql-server)
- [Launch Studio (Optional)](#studio)
- [Next Steps](#next-steps)
- [Elasticsearch (Optional)](#elasticsearch)
- [Troubleshooting](#troubleshooting)


## Install


```bash
pip install larsql
```


Optional installation variants:

```bash
# With browser automation (Playwright)
pip install larsql[browser]

# With local models (HuggingFace)
pip install larsql[local-models]

# Everything
pip install larsql[all]
```

## Configure


Set your LLM API key. [OpenRouter](https://openrouter.ai/keys) is recommended (see [AI Providers](#providers) for alternatives):

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

## Bootstrap


Run the bootstrap command to set up your LARS workspace in one step:

```bash
lars bootstrap
```


This single command handles everything:
- Creates workspace directories (cascades, skills, data, logs, etc.)
- Initializes the DuckDB database schema
- Downloads and registers built-in tools
- Sets up model configurations
- Runs initial SQL schema discovery


> **TIP: Bootstrap Options**
>
> 
> Skip specific steps if needed:
> 
```
lars bootstrap --skip-workspace  # Skip directory creation
lars bootstrap --skip-db         # Skip database initialization
lars bootstrap --skip-tools      # Skip tool downloads
lars bootstrap --skip-models     # Skip model setup
lars bootstrap --skip-sql-crawl  # Skip schema discovery
```


After bootstrap completes, you'll have this structure:

```
~/.lars/                  # Default LARS_ROOT location
├── .env                  # Environment config (auto-generated)
├── cascades/             # Workflow definitions
│   └── examples/         # Sample cascades
├── skills/               # Custom tools
├── sql_connections/      # Database connections
├── data/                 # Parquet data storage
│   └── system/           # Logs, sessions, analytics
├── session_dbs/          # Persistent session databases
└── logs/                 # Execution logs
```


> **NOTE: No External Database Required**
>
> 
> LARS uses **DuckDB + Parquet** for all storage. No need to install 
>     ClickHouse, PostgreSQL, or any other database. Everything is stored locally in 
>     the `~/.lars/data/` directory.
> 


## Start SQL Server


Start the PostgreSQL wire-protocol server. This lets any SQL client
  (DBeaver, DataGrip, psql, Tableau) connect and use LARS's semantic operators.

```bash
lars serve sql --port 15432
```


> **NOTE: Authentication Enabled**
>
> 
> LARS has authentication **enabled by default**. The default credentials are
>     `admin` / `admin`. See [Authentication](#authentication)
>     for user management and API keys.
> 


### Connect with psql


```bash
# Connect (default credentials: admin/admin)
psql postgresql://admin:admin@localhost:15432/default
```

### Connect with Any SQL Client


Use these connection settings in DBeaver, DataGrip, or any PostgreSQL client:


| Setting  | Value       |
|----------|-------------|
| Host     | `localhost` |
| Port     | `15432`     |
| Database | `default`   |
| Username | `admin`     |
| Password | `admin`     |


### Try a Semantic Query


```sql
-- Create a test table
CREATE TABLE products (
  id INTEGER,
  name VARCHAR,
  description TEXT
);

INSERT INTO products VALUES
  (1, 'EcoBottle', 'Reusable water bottle made from recycled ocean plastic'),
  (2, 'QuickCharge', 'Fast USB-C charger with 65W output'),
  (3, 'GreenPack', 'Backpack made from sustainable bamboo fiber');
-- Semantic search - find eco-friendly products
SELECT * FROM products
WHERE description MEANS 'eco-friendly';
```


That's it! You're running semantic queries from a standard SQL client.

## Launch Studio (Optional)


Start the LARS Studio web interface for a visual SQL IDE, cascade runner, and cost analytics:

```bash
lars serve studio
# Runs at http://localhost:5050
```


Open your browser to [http://localhost:5050](http://localhost:5050)


> **NOTE: Studio Login**
>
> 
> Studio uses the same authentication as the SQL server. Log in with 
>     `admin` / `admin` or any user you've created.
> 


### Studio Features


#### SQL Query IDE


Write and execute SQL with schema browser and semantic operators


#### Session Explorer


Browse execution history, costs, and "what the model saw"


#### Cascade Runner


Run and visualize multi-step workflows with takes evaluation

## Next Steps


You now have a working LARS installation. Here's what to explore next:
[
#### Semantic SQL


Query rewriting, caching, and all the semantic operators
](#semantic-sql)
  [
#### Built-in Operators


100+ operators for filtering, logic, aggregation, and more
](#operators)
  [
#### SQL Connections


Connect PostgreSQL, BigQuery, Snowflake, S3, and more
](#sql-connections)
  [
#### Cascade DSL


Build multi-step LLM workflows in YAML
](#cascade-dsl)
  [
#### AI Providers


Configure Ollama, Vertex AI, AWS Bedrock, or Azure
](#providers)
  [
#### Vector Search


Embed data and use SIMILAR_TO for similarity search
](#embedding)
## Elasticsearch (Optional)


<details>
<summary>Add Elasticsearch for Hybrid Search</summary>


**Elasticsearch is optional** but enables powerful additional features:
- **Hybrid Search**: Combine semantic (vector) search with keyword (BM25) matching
- **Better RAG**: More precise document retrieval for SQL schema and document search
- **KEYWORD_SEARCH**: Pure BM25 search for exact term matching (SKUs, model numbers, codes)
- **HYBRID_SEARCH**: Tunable blend of semantic understanding + exact keyword matches


> **TIP: When to Add Elasticsearch**
>
> 
> Skip this for now if you're just getting started. You can add Elasticsearch later when you need:
> 
> - Hybrid semantic + keyword search (e.g., finding products by concept AND model number)
> - Better RAG precision for document Q&A systems
> - SQL schema search across large databases
> 


### Start Elasticsearch with Docker


```bash
# Start Elasticsearch with single-node mode
docker run -d --name lars-elasticsearch \
  -p 9200:9200 \
  -p 9300:9300 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
  -e "cluster.routing.allocation.disk.threshold_enabled=false" \
  -v lars-es-data:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.11.3

# Wait for Elasticsearch to be ready (about 30 seconds)
echo "Waiting for Elasticsearch..."
until curl -s http://localhost:9200/_cluster/health > /dev/null 2>&1; do
  sleep 2
done
echo "Elasticsearch is ready!"
```

### Configure Environment Variable


Add this to your `.env` file to enable Elasticsearch:

```.env
LARS_ELASTICSEARCH_HOST=http://localhost:9200
```


> **NOTE: Automatic Detection**
>
> 
> When `LARS_ELASTICSEARCH_HOST` is set, LARS automatically:
> 
> - Registers `HYBRID_SEARCH`, `KEYWORD_SEARCH`, and `ELASTIC_SEARCH` functions
> - Enables the `backend='elastic'` option for `LARS EMBED` statements
> - Uses Elasticsearch for SQL schema search (better autocomplete and discovery)
> 
> If the environment variable is not set, these features simply won't be available,
>         and LARS will use DuckDB for all vector search operations.
> 


</details>

## Troubleshooting


### API Key Issues


> **WARNING: Error: API key not configured**
>
> 
> Ensure your environment variable is set:
> 
```
# Check if set
echo $OPENROUTER_API_KEY

# Or add to .env file
echo "OPENROUTER_API_KEY=sk-or-v1-your-key" >> ~/.lars/.env

# Verify setup
lars doctor
```


### Port Conflicts


> **WARNING: Error: Port already in use**
>
> 
> If ports are in use, specify different ports:
> 
```
# Find what's using the port
lsof -i :15432

# Use a different port for SQL server
lars serve sql --port 15433

# Use a different port for Studio
lars serve studio --port 5051
```


### Quick Reference


```bash
# Health check
lars doctor

# Database status
lars db status

# Run a cascade
lars run cascades/examples/hello_world.yaml

# View help
lars --help
```


> **TIP: Need More Help?**
>
> 
> Check the full documentation or open an issue on
>     [GitHub](https://github.com/ryrobes/larsql/issues).
>
