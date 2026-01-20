# Quickstart Guide


Get LARS running in minutes. This guide covers the essential setup — install, configure, and start querying.
**On This Page**
- [Install](#install)
- [Configure](#configure)
- [Start ClickHouse](#clickhouse)
- [Initialize Project](#initialize)
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

## Start ClickHouse


LARS requires **ClickHouse** for logging, analytics, and vector search.
  Run it with Docker:

```bash
docker run -d \
  --name lars-clickhouse \
  --ulimit nofile=262144:262144 \
  -p 8123:8123 \
  -p 9000:9000 \
  -p 9009:9009 \
  -v clickhouse-data:/var/lib/clickhouse \
  -v clickhouse-logs:/var/log/clickhouse-server \
  -e CLICKHOUSE_USER=lars \
  -e CLICKHOUSE_PASSWORD=lars \
  clickhouse/clickhouse-server:25.11
```


> **NOTE: ClickHouse Ports**
>
> 
> - **9000**: Native protocol (used by LARS)
> - **8123**: HTTP interface (useful for debugging)
> 


## Initialize Project


Create a project directory with starter files and initialize the database:

```bash
# Create and enter project directory
lars init my_lars_project ; cd my_lars_project

# Initialize the database schema
lars db init
```


This creates the following structure:

```
my_lars_project/
├── .env                  # Environment config (auto-generated)
├── cascades/             # Workflow definitions
│   └── examples/         # Sample cascades
├── skills/               # Custom tools
├── sql_connections/      # Database connections
├── data/                 # Local data files
├── session_dbs/          # Persistent session databases
└── logs/                 # Execution logs
```


> **TIP: Auto-Configuration**
>
> 
> `lars init` automatically creates a `.env` file with
>     `LARS_ROOT` set to your project's absolute path. Just add your API key
>     if you haven't already exported it.
> 


## Start SQL Server


Start the PostgreSQL wire-protocol server. This lets any SQL client
  (DBeaver, DataGrip, psql, Tableau) connect and use LARS's semantic operators.

```bash
lars serve sql --port 15432
```

### Connect with psql


```bash
# Connect (default credentials: lars/lars)
psql postgresql://localhost:15432/default
```

### Connect with Any SQL Client


Use these connection settings in DBeaver, DataGrip, or any PostgreSQL client:


| Setting  | Value       |
|----------|-------------|
| Host     | `localhost` |
| Port     | `15432`     |
| Database | `default`   |
| Username | `lars`      |
| Password | `lars`      |


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

### Studio Features


#### SQL Query IDE


Write and execute SQL with schema browser and semantic operators

#### Session Explorer


Browse execution history, costs, and "what the model saw"

#### Cascade Runner


Run and visualize multi-step workflows with takes evaluation

## Next Steps


You now have a working LARS installation. Here's what to explore next:


#### [Semantic SQL](#semantic-sql)


Query rewriting, caching, and all the semantic operators

#### [Built-in Operators](#operators)


100+ operators for filtering, logic, aggregation, and more

#### [SQL Connections](#sql-connections)


Connect PostgreSQL, BigQuery, Snowflake, S3, and more

#### [Cascade DSL](#cascade-dsl)


Build multi-step LLM workflows in YAML

#### [AI Providers](#providers)


Configure Ollama, Vertex AI, AWS Bedrock, or Azure

#### [Vector Search](#embedding)


Embed data and use SIMILAR_TO for similarity search

## Elasticsearch (Optional)


<details>
<summary>Optional Setup
    Add Elasticsearch for Hybrid Search</summary>


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

### Docker Compose (With Kibana UI)


For a complete setup including Kibana for monitoring:

```docker-compose.elastic.yml
version: '3.8'

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.3
    container_name: lars-elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
      - cluster.routing.allocation.disk.threshold_enabled=false
    ports:
      - "9200:9200"   # HTTP API
      - "9300:9300"   # Transport protocol
    volumes:
      - lars-es-data:/usr/share/elasticsearch/data
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9200/_cluster/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5

  kibana:
    image: docker.elastic.co/kibana/kibana:8.11.3
    container_name: lars-kibana
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
      - xpack.security.enabled=false
    ports:
      - "5601:5601"   # Kibana UI
    depends_on:
      elasticsearch:
        condition: service_healthy

volumes:
  lars-es-data:
```

```bash
# Start with Docker Compose
docker compose -f docker-compose.elastic.yml up -d
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
>     and LARS will use ClickHouse for all vector search operations.
> 


### Verify Elasticsearch


```bash
# Check cluster health
curl http://localhost:9200/_cluster/health | jq
```


> **NOTE: Elasticsearch Ports**
>
> 
> - **9200**: HTTP API (used by LARS)
> - **9300**: Transport protocol (internal cluster communication)
> - **5601**: Kibana UI (if using docker-compose)
> 


</details>

## Troubleshooting


### ClickHouse Connection Errors


> **WARNING: Error: Connection refused**
>
> 
```
# Check if ClickHouse is running
docker ps | grep clickhouse

# Check logs
docker logs lars-clickhouse

# Restart if needed
docker restart lars-clickhouse
```


> **WARNING: Error: Table doesn't exist**
>
> 
> Run database initialization:
> 
```
lars db init
```


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
echo "OPENROUTER_API_KEY=sk-or-v1-your-key" >> .env

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
