# Memory System


Understanding LARS's distinctive approach to agent memory: retrieval is an explicit tool call,
  not automatic context injection.


> **INFO: Core Philosophy**
>
> 
> **Write automatically, read explicitly.** Messages are auto-saved to configured memory banks,
>     but retrieval requires the agent to make an explicit tool call. This prevents context flooding
>     while giving agents control over when past knowledge is relevant.
> 

On This Page
- [Overview](#overview)
- [The Three Memory Tiers](#three-tiers)
- [Named Memory Banks](#memory-banks)
- [Research Database](#research-db)
- [Why Memory is a Tool](#why-tool)
- [Memory vs Context Cards](#comparison)
- [RAG System](#rag)


## Overview


LARS implements a distinctive approach to agent memory: **memory retrieval is an explicit tool call**,
  not automatic context injection. This philosophy provides control, transparency, and cost management while
  enabling agents to access persistent knowledge when needed.


Unlike frameworks that automatically inject "relevant" memories into every prompt (often flooding context
  with marginally useful information), LARS treats memory as a resource the agent can query when it
  determines memory would be helpful.

## The Three Memory Tiers


LARS provides three distinct memory systems, each serving different persistence and access patterns:


#### Named Memory Banks


Cross-session persistent memory with semantic search. Shared across cascades.
- RAG-backed vector search
- Auto-summarization every 50 messages
- Becomes a callable tool


**Scope:** Persistent / Multi-cascade


#### Research Database


Per-cascade DuckDB for structured data storage with SQL interface.
- Standard SQL queries
- CREATE/INSERT/SELECT/UPDATE
- Ideal for accumulating findings


**Scope:** Per-cascade / Structured


#### Context Cards


Session-scoped summaries and embeddings for auto-context selection.
- Auto-generated per message
- Powers inter-cell selection
- Session-scoped only


**Scope:** Session / Automatic

## Named Memory Banks


When you configure a `memory` field on a cascade, that memory bank name becomes a **callable tool**
  that the agent can invoke to search past conversations:

```memory bank configuration
cascade_id: sql_assistant
memory: sql_patterns_memory  # Creates tool named "sql_patterns_memory"

cells:
  - name: assist
    instructions: |
      Help the user write SQL queries.
      Search your memory for similar patterns if helpful.
    skills:
      - sql_data
      - sql_patterns_memory  # Agent can call this to search memories
```

### How It Works


| Operation     | Automatic/Explicit | Description                                                     |
|---------------|--------------------|-----------------------------------------------------------------|
| **Save**      | Automatic          | Every message is auto-saved to the memory bank during execution |
| **Retrieve**  | Explicit tool call | Agent must call the memory tool with a search query             |
| **Summarize** | Automatic          | LLM generates summary every 50 messages                         |


When the agent calls the memory tool, it performs semantic search using embeddings:

```memory tool call (agent perspective)
# Agent decides to search memory for SQL patterns
result = sql_patterns_memory(
    query="how to join tables with aggregation",
    limit=5
)
# Returns formatted results with relevant past conversations
```

### Storage Structure


```$lars_root/memories/
memories/
└── sql_patterns_memory/
    ├── metadata.json         # Stats, summary, cascade list
    └── messages/
        ├── session_123_1234567890_user.json
        ├── session_123_1234567891_assistant.json
        └── ...
```

### Cross-Cascade Sharing


Multiple cascades can share the same memory bank, building a collective knowledge base:

```shared memory bank
# cascade_a.yaml
cascade_id: sql_helper
memory: shared_sql_knowledge
cells: [...]

# cascade_b.yaml
cascade_id: data_analyst
memory: shared_sql_knowledge  # Same bank!
cells: [...]
```


Both cascades contribute to and can query the same memory bank, enabling knowledge transfer
  across different workflows.

## Research Database


For structured data that needs SQL-style querying, the Research Database provides
  per-cascade DuckDB storage:

```research database configuration
cascade_id: market_research
research_db: market_research  # Creates DuckDB file

cells:
  - name: gather_data
    instructions: |
      Research competitor pricing. Store findings in the database.
    skills:
      - brave_web_search
      - research_execute  # CREATE/INSERT/UPDATE
      - research_query    # SELECT queries
```


The agent can then create tables and store structured findings:

```research database usage (agent perspective)
# Create schema
research_execute("""
    CREATE TABLE IF NOT EXISTS competitors (
        name VARCHAR,
        pricing DECIMAL,
        features TEXT[]
    )
""")

# Store findings
research_execute("""
    INSERT INTO competitors VALUES
    ('Acme Corp', 99.99, ['feature1', 'feature2'])
""")

# Query later
research_query("SELECT * FROM competitors ORDER BY pricing")
```

### Research Tools


| Tool               | Purpose                    | SQL Operations                        |
|--------------------|----------------------------|---------------------------------------|
| `research_execute` | Schema & data modification | CREATE, INSERT, UPDATE, DELETE, ALTER |
| `research_query`   | Data retrieval             | SELECT only                           |


## Why Memory is a Tool


This design is intentional and provides several advantages over automatic memory injection:


| Aspect            | Auto-Injection (Other Frameworks) | Tool-Based (LARS)                            |
|-------------------|-----------------------------------|----------------------------------------------|
| **Context Size**  | Unpredictable, may flood          | Agent controls what to retrieve              |
| **Relevance**     | Algorithm guesses relevance       | Agent decides when memory helps              |
| **Cost**          | Embedding costs on every turn     | Only when agent queries                      |
| **Transparency**  | Hidden injection                  | Explicit tool call, fully logged             |
| **Composability** | One global memory                 | Multiple named banks, shared across cascades |


> **WARNING: Agent Instructions Matter**
>
> 
> Since memory retrieval is explicit, you should instruct agents when to search memory.
>     Include guidance like "Search your memory for similar patterns before attempting new solutions"
>     in cell instructions when memory lookup would be beneficial.
> 


## Memory vs Context Cards


Context cards (used by [auto-context](#auto-context)) and memory banks serve different purposes:


| Aspect      | Context Cards             | Memory Banks                |
|-------------|---------------------------|-----------------------------|
| **Scope**   | Single session            | Cross-session, persistent   |
| **Access**  | Automatic (inter-cell)    | Explicit tool call          |
| **Purpose** | Short-term working memory | Long-term knowledge base    |
| **Sharing** | Session-isolated          | Shared across cascades      |
| **Storage** | DuckDB (unified_logs)     | Files + DuckDB vector index |


> **TIP: Best Practices**
>
> 
> - **Use Memory Banks** for knowledge that should persist across sessions (SQL patterns, user preferences, domain knowledge)
> - **Use Research Database** for structured findings within a workflow (competitor data, scraped results)
> - **Use Context Cards** implicitly via auto-context for within-session intelligence
> - **Instruct agents** to search memory when relevant - they won't do it automatically
> 


## RAG System (Document Memory)


For static document collections, LARS provides cell-level RAG configuration:

```rag configuration
cells:
  - name: answer_questions
    rag:
      directory: "./docs"
      recursive: true
      include_patterns: ["*.md", "*.txt"]
    instructions: |
      Answer questions about our documentation.
      Search the docs first before responding.
    # Tools auto-injected: rag_search, rag_read_chunk, rag_list_sources
```


RAG tools are automatically injected when the `rag` block is present:


| Tool                       | Purpose                                |
|----------------------------|----------------------------------------|
| `rag_search(query, k=5)`   | Semantic search over indexed documents |
| `rag_read_chunk(chunk_id)` | Fetch full text of a specific chunk    |
| `rag_list_sources()`       | List available documents in the index  |


### RAG Configuration Options


```full rag configuration
rag:
  directory: "./docs"           # Root directory to index
  recursive: true                # Include subdirectories
  include_patterns:              # File patterns to include
    - "*.md"
    - "*.txt"
    - "*.pdf"
  exclude_patterns:              # Patterns to exclude
    - "**/node_modules/**"
    - "**/.git/**"
  chunk_size: 1000              # Characters per chunk
  chunk_overlap: 200            # Overlap between chunks
```

## Related Documentation
- [Auto-Context Deep Dive](#auto-context) - Intelligent context management including context cards
- [Context Management](#context) - Traditional explicit context configuration
- [Tools (Skills)](#tools) - Tool system overview
- [Vector Search & Embedding](#embedding) - Embedding system used by memory
