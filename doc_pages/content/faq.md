# Frequently Asked Questions


Real answers to real questions. No marketing fluff.
**On This Page**
- [The Hard Questions](#hard-questions)
- [Data & Privacy](#privacy)
- [Cost & Performance](#cost)
- [Technical Deep Dives](#technical)
- [The Secret Sauce](#secret-sauce)
- [The Skeptic's Corner](#skeptics)
- [Comparisons](#comparisons)


## The Hard Questions


### "LLMs are non-deterministic. How can this possibly work with SQL?"


You're right—they are. And here's the thing: **your data isn't deterministic either.**


Think about it. The same SQL query returns different results every time your data changes. The same analyst interprets data differently on different days. Business logic evolves. "Urgent" meant something different last quarter.


LARS doesn't pretend LLMs are deterministic. Instead, we:
1. **Cache aggressively** — Same input = same output (until you invalidate)
2. **Use Takes** — Run 3-5 attempts in parallel, pick the best one. Random failures just don't win.
3. **Log everything** — Every LLM call is recorded. You can audit exactly what happened.
4. **Let you tune consistency** — Temperature, model choice, and prompt engineering are all exposed.


The real question isn't "is it deterministic?" It's "is it *reliable enough* for my use case?" For most semantic queries, the answer is yes—and you can verify it.

### "Isn't this just expensive regex with extra steps?"


No. Regex matches patterns. LARS understands meaning.

```sql
-- Regex: catches "urgent", misses everything else
WHERE description ~ 'urgent|critical|asap'
-- LARS: catches intent regardless of wording
WHERE description MEANS 'urgent customer issue'
```


The second query catches:
- "This is blocking our launch"
- "Customer threatening to cancel"
- "Need this fixed yesterday"
- "P0 incident"


None of those match your regex. All of them are urgent.


**But yes, it costs more than regex.** A semantic query might cost $0.001-0.01 depending on data volume. Regex costs nothing. The question is: what's the cost of *missing* those urgent tickets?

### "What happens when the LLM hallucinates?"


Short answer: **Takes catch most of it, wards catch the rest.**


Longer answer:
1. **Takes** — Run the same query multiple times with slight variations. An evaluator picks the best result. Hallucinations rarely win against correct answers.
2. **Wards** — Validation rules that check outputs. "Must be valid JSON." "Must reference only existing columns." "Confidence must be > 0.8."
3. **Structured outputs** — When you ask for TRUE/FALSE, you get TRUE or FALSE. Not a paragraph explaining why it might be true.
4. **The hybrid pattern** — Vector search narrows to 100 candidates (no hallucination possible—they're real rows). LLM evaluates just those 100. Worst case: it picks a wrong row. It can't invent one.


Hallucinations aren't eliminated. They're mitigated to the point where they're rarer than human analyst errors.

### "Why not just use Python/pandas?"


You absolutely can. LARS isn't replacing Python—it's replacing the *glue code* between your SQL and your LLM.
Without LARS
    
      `47 lines of: query DB, loop rows, call API, handle errors, parse JSON, retry failures, cache results, track costs, rejoin to SQL...`
    
  
  
    With LARS
    
      `SELECT * FROM tickets WHERE description MEANS 'urgent'`

**Use Python when:**
- You need custom ML models
- Complex data transformations
- Notebook-style exploration
- One-off analysis


**Use LARS when:**
- Your team knows SQL better than Python
- You want results in your existing BI tools
- You need production-grade reliability
- You want cost tracking and audit logs built-in


### "Is this production-ready or a demo?"


Production-ready. Here's what that means:
- **Auth** — Username/password and connection-level security
- **Cost tracking** — Per-query, per-user, per-model attribution
- **Caching** — Content-addressed cache with configurable TTL
- **Observability** — Every LLM call logged with full context
- **Error handling** — Retries, fallbacks, graceful degradation
- **Rate limiting** — Per-connection query limits


What we *don't* have (yet):
- SOC2 certification (in progress)
- Enterprise SSO (roadmap)
- Multi-tenant SaaS (it's self-hosted)


## Data & Privacy


### "Where does my data go?"


**Your data stays in your infrastructure.** LARS is a query layer, not a data store.


When you run a semantic query:
1. LARS pulls data from *your* database
2. Sends *only the relevant columns* to the LLM
3. LLM returns a result
4. Result is cached locally


The LLM sees the data you query. It doesn't see your whole database. You control exactly what gets sent via column selection and WHERE clauses.

### "Does my data train anyone's models?"


**No.**
- OpenRouter: No training on API data
- Anthropic (Claude): No training on API data
- OpenAI: No training on API data (with data retention disabled)
- Vertex AI / Bedrock / Azure: Enterprise data policies apply


You can also run fully local models via Ollama. Zero data leaves your machine.

### "Can I use this with air-gapped infrastructure?"


Yes. Two options:
1. **Local models** — Run Ollama, vLLM, or any OpenAI-compatible server. LARS points to `localhost`.
2. **Private cloud** — Deploy in your VPC with Vertex AI, Bedrock, or Azure OpenAI. Data never leaves your cloud.


The PostgreSQL wire protocol means your SQL clients connect to LARS exactly like they connect to any other database.

### "What about PII in queries?"


LARS has an `ANONYMIZE` operator that strips PII before processing:

```sql
SELECT ANONYMIZE(customer_feedback) AS safe_text,
       SENTIMENT(ANONYMIZE(customer_feedback)) AS sentiment
FROM feedback
```


You can also:
- Configure column-level redaction rules
- Use views to pre-filter sensitive data
- Run local models for PII-sensitive workloads


## Cost & Performance


### "How much does this actually cost per query?"


It depends on:
- **Model** — GPT-4o vs Claude Sonnet vs Gemini Flash (10x price difference)
- **Data volume** — 100 rows vs 10,000 rows
- **Operator type** — Simple filter vs complex aggregation
- **Cache hit rate** — Repeated queries are free


**Typical costs:**


| Query Type            | Rows   | Model         | Cost    |
|-----------------------|--------|---------------|---------|
| `WHERE x MEANS 'y'`   | 100    | Gemini Flash  | ~$0.001 |
| `WHERE x MEANS 'y'`   | 10,000 | Gemini Flash  | ~$0.05  |
| `SUMMARIZE(comments)` | 50     | Claude Sonnet | ~$0.02  |
| `TOPICS(text, 5)`     | 1,000  | GPT-4o        | ~$0.15  |


**The hybrid trick** — Vector search first, then semantic:

```sql
WITH candidates AS (
  SELECT * FROM VECTOR_SEARCH('eco friendly', 'products', 100)
)
SELECT * FROM candidates WHERE description MEANS 'genuinely sustainable'
```


This queries 1M rows but only sends 100 to the LLM. Cost: ~$0.002.

### "What if an LLM call fails mid-query?"


LARS handles this automatically:
1. **Retries** — Transient failures retry with exponential backoff
2. **Fallback models** — Configure backup models if primary fails
3. **Takes** — If 1 of 3 attempts fails, the other 2 still compete
4. **Graceful degradation** — Return partial results with error flags


You never get a stack trace in your BI tool. You get a result (possibly partial) with metadata about what happened.

### "How does caching work?"


LARS uses **content-addressed caching**:

```cache key
cache_key = hash(operator + input_text + model + prompt_version)
```


Same input = same cache key = same result. The cache doesn't care about:
- Query structure (SELECT vs CTE)
- Column order
- Whitespace


**Cache TTL** is configurable per-operator. Sentiment on tweets? Cache forever. Fraud detection? Cache for 1 hour.


**Cache hit rates** in practice: 60-90% for analytical workloads. Your second run of a dashboard is nearly free.

### "Can I set spending limits?"


Yes. Multiple levels:

```yaml
# Per-query limit
-- @ max_cost: 0.50
SELECT ...

# Per-session limit (connection level)
max_cost_per_session: 10.00

# Per-day limit (global)
daily_cost_limit: 100.00
```


Queries that would exceed limits fail with a clear error before any LLM calls.

## Technical Deep Dives


### "What's the difference between MEANS and SIMILAR_TO?"


| Operator     | How it works             | Best for                               |
|--------------|--------------------------|----------------------------------------|
| `MEANS`      | LLM evaluates each row   | Nuanced interpretation, small datasets |
| `SIMILAR_TO` | Vector cosine similarity | Large datasets, fuzzy matching         |


```sql
-- MEANS: "Does this text convey urgency?" (LLM judges)
WHERE description MEANS 'urgent issue'
-- SIMILAR_TO: "Is this text close to 'urgent issue' in vector space?"
WHERE description SIMILAR_TO 'urgent issue'
```


**SIMILAR_TO** is faster and cheaper but less precise. **MEANS** understands context and nuance but costs more.


> **TIP: Pro tip: Use both**
>
> 
```
WITH candidates AS (
  SELECT * FROM tickets WHERE description SIMILAR_TO 'urgent issue' LIMIT 100
)
SELECT * FROM candidates WHERE description MEANS 'truly urgent, not just flagged urgent'
```


### "When should I use vector search vs semantic operators?"


**Vector search (`VECTOR_SEARCH`, `SIMILAR_TO`):**
- Finding "more like this"
- Large datasets (millions of rows)
- Fuzzy matching where precision isn't critical
- Building candidate sets for further filtering


**Semantic operators (`MEANS`, `CLASSIFY`, `SUMMARIZE`):**
- Nuanced judgment calls
- Small-to-medium datasets (< 10K rows per query)
- When you need to explain *why* something matched
- Aggregations that require understanding


### "Can I chain multiple AI operators in one query?"


Yes. They compose like regular SQL functions:

```sql
SELECT 
  customer_id,
  SENTIMENT(feedback) AS mood,
  CLASSIFY(feedback, 'product', 'service', 'pricing') AS category,
  SUMMARIZE(feedback) AS summary
FROM customer_feedback
WHERE feedback MEANS 'frustrated but still engaged'
GROUP BY customer_id
```


Each operator runs independently. Results are joined back to your query.

### "What happens with GROUP BY and AI functions?"


AI aggregate functions work like `SUM()` or `COUNT()`:

```sql
SELECT 
  product_category,
  COUNT(*) AS reviews,
  SUMMARIZE(review_text) AS summary,    -- Aggregates all reviews in group
  CONSENSUS(review_text) AS agreement   -- Finds common ground
FROM reviews
GROUP BY product_category
```


The LLM sees all rows in each group and produces one output per group.


**Row-level functions** in GROUP BY work differently:

```sql
SELECT 
  TOPICS(description, 3) AS topic,  -- AI determines the grouping
  COUNT(*) AS count
FROM tickets
GROUP BY topic
```


Here, LARS first clusters all rows into topics, then groups by those clusters.

## The Secret Sauce


*What actually makes this different.*

### It's not the LLM call. Everyone can call an LLM.


The trick is making semantic operations **feel like SQL**.

```sql
SELECT * FROM tickets 
WHERE description MEANS 'urgent' 
  AND status = 'open'
ORDER BY created_at DESC
```


That's not "SQL + AI bolted on." That's just SQL. The AI operator composes with `AND`, respects `ORDER BY`, works in subqueries, joins, CTEs—everything.


This matters because:
- **No context switching** — Stay in SQL, stay in your mental model
- **Declarative** — Say *what* you want, not *how* to get it
- **Composable** — Chain operators like any other SQL function
- **Tool-agnostic** — Works in DBeaver, DataGrip, Tableau, psql, any SQL client


### Fully declarative, fully auditable


Every other LLM integration we've seen:

```python
results = []
for row in query_results:
    response = llm.call(f"Is this urgent? {row['description']}")
    if response == "yes":
        results.append(row)
```


That's imperative. It's a black box. Good luck explaining to your CFO why your LLM bill spiked.


LARS:

```sql
-- @ takes.factor: 3
SELECT * FROM tickets WHERE description MEANS 'urgent'
```


Declarative. Auditable. You can see exactly:
- What the LLM saw (input context)
- What it returned (raw output)
- Why it made that decision (reasoning, if enabled)
- What it cost (per-query, per-operator)
- How long it took (latency breakdown)


All queryable. All in SQL tables. `SELECT * FROM lars_system.costs WHERE query_id = '...'`

### Federation is the force multiplier


Your data lives in PostgreSQL (transactions), Snowflake (warehouse), S3 parquet files (logs), MongoDB (user profiles), and a random CSV your analyst emailed you.
Without LARS
    
      ETL everything into one place. Wait 6 hours. Query. Repeat when data changes.
    
  
  
    With LARS
```
SELECT 
    p.customer_id,
    m.profile->>'tier' AS tier,
    SUMMARIZE(s.support_tickets) AS issues
FROM postgres.customers p
JOIN mongo.profiles m ON p.id = m.customer_id  
JOIN snowflake.tickets s ON p.id = s.customer_id
GROUP BY p.customer_id, tier
```


Query across sources. No ETL. No data movement. DuckDB handles the federation, LARS handles the semantics.

### The operators aren't magic—they're tiny debuggable machines


Every LARS operator is a YAML file:

```cascades/semantic_sql/matches.cascade.yaml
cascade_id: semantic_matches
sql_function:
  operators: ["{{ text }} MEANS {{ criterion }}"]
cells:
  - name: evaluate
    model: gemini-2.5-flash-lite
    instructions: |
      Does this text match the criterion?
      Text: {{ input.text }}
      Criterion: {{ input.criterion }}
```


That's it. No hidden complexity. Want to know how `MEANS` works? Read the file.


Want to customize it? Copy, edit, restart. Your operator now exists.


Want to debug a weird result? The cascade execution is fully logged—every prompt, every response, every decision.


**The abstraction is thin and inspectable.** That's the point.

## The Skeptic's Corner


*For the Reddit thread you're about to post in.*

### "This is just a wrapper around the ChatGPT API"


Yes. Also:
- PostgreSQL is just a wrapper around disk I/O
- React is just a wrapper around DOM manipulation
- Kubernetes is just a wrapper around containers


The value isn't in the API call. It's in:
- SQL-native syntax that composes with your existing queries
- Caching that makes repeated queries free
- Takes that handle LLM unreliability
- Cost tracking so you don't get a surprise $10K bill
- Observability so you can debug production issues


You *could* write all this yourself. You could also write your own database.

### "You're just adding latency to every query"


Only to queries that use semantic operators. Regular SQL passes through unchanged.


And yes, an LLM call adds 200-2000ms. That's the trade-off for understanding *meaning* instead of just matching patterns.


If sub-100ms latency is critical, LARS isn't for that query. Use it for analytics, batch processing, and dashboards—not your hot path.

### "This will never work at scale"


Define "scale."
- **1M rows?** Vector search first, semantic filter on top 100. Works fine.
- **10K queries/day?** Caching handles 70%+, actual LLM load is manageable.
- **1000 concurrent users?** Connection pooling, query queuing, rate limiting.


"Scale" concerns usually assume every query hits an LLM. They don't. The hybrid approach means LLMs see a tiny fraction of your data.


That said—if you're processing 100M events/second in real-time, this isn't your tool. But neither is any LLM-based approach.

### "Real engineers write their own LLM pipelines"


Real engineers also write their own web frameworks, databases, and operating systems.


Or—hear me out—they use tools so they can focus on their actual problem.


You *can* build: prompt management, caching, retry logic, cost tracking, observability, error handling, connection pooling, query parsing, result stitching...


Or you can write:

```sql
WHERE description MEANS 'urgent'
```


Your call.

### "What happens when OpenAI/Anthropic goes down?"


Your queries wait, retry, or fail—same as when your database goes down.


Mitigations:
- **Fallback models** — Primary fails, secondary takes over
- **Caching** — Recent queries still work
- **Local models** — Ollama doesn't depend on anyone's uptime


If five-nines availability is required, run local models or multi-provider with automatic failover.

### "The LLM could return anything. This is dangerous."


The LLM returns *filtered rows* or *computed values*. It doesn't execute arbitrary code or modify your database.


Worst case scenarios:
- **Filter returns wrong rows** — You see irrelevant data. Annoying, not dangerous.
- **Aggregation hallucinates** — Summary is wrong. Same risk as a human analyst misreading data.
- **Classification is incorrect** — Row gets wrong label. Validate with spot checks.


LARS is read-only by default. The most damage a hallucination can do is show you wrong information—which is already a risk with dashboards, reports, and analysts.

### "I could build this in a weekend"


Try it. Seriously.


Build:
- ☐ SQL parser that handles CTEs, subqueries, and window functions
- ☐ Semantic operator extraction and replacement
- ☐ Parallel execution with result stitching
- ☐ Content-addressed caching with TTL
- ☐ Multi-model support with fallback
- ☐ Takes system with evaluator
- ☐ pgwire protocol server
- ☐ Cost tracking per query/user/model
- ☐ Observability UI
- ☐ Connection pooling for external data sources


Then maintain it while also doing your actual job.


The "weekend project" version works for demos. Production needs the other 90%.

### "This is AI hype / vaporware"


It's an open-source SQL server. You can:
1. `pip install larsql`
2. `lars bootstrap`
3. `lars serve sql`
4. Connect with psql
5. Run a query


That's not hype. That's software you can run right now.


Whether it's *useful for your use case* is a legitimate question. Whether it *exists and works* is not.

### "Why would I trust an LLM with my data analysis?"


You already trust:
- Analysts who make mistakes
- Dashboards with wrong formulas
- Reports with bad assumptions
- Data pipelines with silent failures


The question isn't "is it perfect?" It's "is it better than the alternative?"


For many tasks—semantic search, fuzzy matching, text classification—LLMs outperform keyword search and manual rules. Not because they're magic, but because they've seen more patterns than any human.


Trust, but verify. That's what the observability layer is for.

### "Just use [other tool]"


Maybe! Here's an honest comparison:


| If you need...             | Consider              |
|----------------------------|-----------------------|
| Python-first LLM framework | LangChain, LlamaIndex |
| Managed text-to-SQL        | AI2SQL, Vanna         |
| Vector database            | Pinecone, Weaviate    |
| Data transformation        | dbt                   |
| Pure SQL analytics         | Just... SQL           |


LARS is for: **SQL users who want semantic operators without leaving SQL.**


If that's not you, use what fits. No tool is universal.

## Comparisons


### "How is this different from text-to-SQL tools?"


Text-to-SQL (like AI2SQL, SQLCoder) converts English → SQL.


LARS extends SQL with semantic operators. You still write SQL—you just have superpowers.


|               | Text-to-SQL                 | LARS                        |
|---------------|-----------------------------|-----------------------------|
| Input         | "Show me urgent tickets"    | `WHERE desc MEANS 'urgent'` |
| Output        | SQL query                   | Query results               |
| Control       | Hope it generates right SQL | You write the SQL           |
| Debugging     | Black box                   | Full observability          |
| Composability | Limited                     | Full SQL semantics          |


### "How does this compare to LangChain/LlamaIndex?"


LangChain/LlamaIndex are Python frameworks for building LLM apps.


LARS is a SQL interface that happens to use LLMs internally.


**Use LangChain when:**
- Building custom AI applications
- Need fine-grained control over prompts/chains
- Python is your primary language


**Use LARS when:**
- Your users know SQL, not Python
- You want AI in your existing BI stack
- You need production observability out of the box


### "What about dbt + LLM integrations?"


dbt transforms data. LARS queries it.


They're complementary:

```sql
-- dbt model: clean and structure data
-- LARS query: add semantic understanding at read time

SELECT * FROM {{ ref('stg_tickets') }}
WHERE description MEANS 'customer churn risk'
```


You don't need LARS to use dbt. You don't need dbt to use LARS. They work great together.

## Still Have Questions?
- **Discord:** [Join the community](https://discord.gg/lars)
- **GitHub:** [Open an issue](https://github.com/ryrobes/larsql/issues)
- **Twitter:** [@ryrobes](https://twitter.com/ryrobes)
