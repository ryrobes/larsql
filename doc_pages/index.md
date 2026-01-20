LARS - AI that speaks SQL[

          

          
            
            Language-Augmented Relational SQL
            
              LarsqL
              LarsqL
            
          


        ](#)Getting Started

[One Line Change](#how-it-works)
          [Semantic Operators](#topics)
          [Data Stays Home](#federated)
          [Your SQL Client](#pgwire)
          [Vector Search](#vector)
          [Semantic Macros](#macros)
          [ASK_DATA](#askdata)
          [WATCH](#watch)
          [ANALYZE](#analyze)
          [Pipelines](#pipelines)

Production Ready

[Takes](#takes)
          [Champion Mode](#champion)
          [Self-* Properties](#self-properties)
          [Universal Training](#training)
          [Your Journey](#journey)

Deep Dive

[100+ Operators](#operators)
          [Surface or Deep](#depth)
          [Cost Tracking](#observability)
          [The Magic Trick](#cascade-reveal)
          [Custom Operators](#extensibility)

Beyond SQL

[Chain Languages](#polyglot)
          [The Rabbit Hole](#rabbit-hole)

Resources

[Documentation](docs.html)
          [GitHub](https://github.com/ryrobes/larsql)
          [@ryrobes](https://twitter.com/ryrobes)

[Get Started](#get-started)

LarsqL
            
            
              [How It Works](#how-it-works)
              [Takes](#takes)
              [Operators](#operators)
              [Observability](#observability)
              [Get Started](#get-started)
# Your team knows SQL.

              Why learn Python for AI?


Add AI operators to SQL
- from your own SQL client
- on your own database
- real syntax — not `ai_query('{json...}')`


No notebooks. No orchestration code.
Just
                  `WHERE description MEANS 'urgent'`
                
              
            

            
            
              
                
                  
                  SQL + Intent
                
                paused
                
                  
                    >
                    
                    
                  
                  
                    →

Express intent, not patterns — especially when you don't know what you're looking for.


Works with your existing databases, SQL clients & AI providers—including **Vertex AI**, **AWS Bedrock**, and **Azure OpenAI**
PostgreSQL
              
              
                
                MySQL
              
              
                
                SQLite
              
              
                
                Snowflake
              
              
                
                BigQuery
              
              
                
                MongoDB
              
              
                
                Redis
              
              
                
                Parquet
              
              
                
                Delta
              
              
                
                Iceberg
              
              
                
                Azure
              
              
                
                S3
              
              
              
                
                PostgreSQL
              
              
                
                MySQL
              
              
                
                SQLite
              
              
                
                Snowflake
              
              
                
                BigQuery
              
              
                
                MongoDB
              
              
                
                Redis
              
              
                
                Parquet
              
              
                
                Delta
              
              
                
                Iceberg
              
              
                
                Azure
              
              
                
                S3
              
            
          
        

        
        
          
            
              
              
                
                Excel
              
              
                
                JSON
              
              
                
                CSV
              
              
                
                MCP
              
              
                
                OpenRouter
              
              
                
                HF Spaces
              
              
                
                HF Transformers
              
              
                
                Ollama
              
              
                
                Pinecone
              
              
                
                Vertex AI
              
              
                
                Bedrock
              
              
                
                Azure OpenAI
              
              
                
                Cassandra
              
              
                
                GCS
              
              
              
                
                Excel
              
              
                
                JSON
              
              
                
                CSV
              
              
                
                MCP
              
              
                
                OpenRouter
              
              
                
                HF Spaces
              
              
                
                HF Transformers
              
              
                
                Ollama
              
              
                
                Pinecone
              
              
                
                Vertex AI
              
              
                
                Bedrock
              
              
                
                Azure OpenAI
              
              
                
                Cassandra
              
              
                
                GCS

Powered by `DuckDB` federated engine. If DuckDB can *read* it, LARS can *analyze* it. Connects via PostgreSQL wire protocol—use DataGrip, DBeaver, Tableau, or any SQL client.

## One line. That's all it takes.


Same query. Now it gets what you *mean*, not just what you *declared*.
Before
```
SELECT * FROM support_tickets
WHERE priority = 'high'
```
→

            
              
                After
                + AI
```
SELECT * FROM support_tickets
WHERE description MEANS 'urgent customer issue'
```


**That's it.** You just added AI to your query. No Python. No APIs. No orchestration code.

## Wait, it gets weirder.


You describe the dimensions. AI discovers what fits.
Your query
```
SELECT
    TOPICS(tweet, 4) AS topic,
    CLASSIFY(tweet, 'political', 'not-political')
        AS political,
    COUNT(*) AS tweets,
    AVG(likes) AS avg_likes
FROM twitter_archive
GROUP BY topic, political
```
→

            
              
                AI creates two dimensions
                4 topics
                × 2 classes
              
              
                
                  1
                  Tech Industry Commentary
                  political
                  1,847 rows
                
                
                  2
                  Tech Industry Commentary
                  not-political
                  494 rows
                
                
                  3
                  Hot Takes & Opinions
                  political
                  1,231 rows
                
                
                  4
                  Hot Takes & Opinions
                  not-political
                  423 rows
                
                
                  5
                  Personal Life Updates
                  not-political
                  1,892 rows
                
                
                  6
                  Link Sharing
                  political
                  312 rows
                
                
                  + 2 more rows...

**Semantic operators work just like regular SQL functions.**
TOPICS()
                Aggregate — discovers natural groupings across rows
              
              
                CLASSIFY()
                Dimensional — adds a column to each row

Mix them together. Nest them. Use them in WHERE, GROUP BY, ORDER BY. It's just SQL.

## Your data never moves. The intelligence comes to it.


Add AI to any database without copying a single row. LARS is a query layer, not a data store.
No data migration required
                
                
                  
                  Query multiple databases in one statement
                
                
                  
                  Results cached and costs tracked automatically
                
                
                  
                  Works with any SQL-compatible data source
                
              
            

            
              
                
                
                  ⌨
                  You
                  Write plain SQL
                

                
                
                  
                  ▶
                

                
                
                  LARS
                  Routes your query
                

                
                
                  
                    
                    ▶
                  
                  
                    
                    ▶
                  
                

                
                
                  
                    Your Databases
                    
                      Postgres
                      MySQL
                      BigQuery
                      Files
                    
                  
                  
                    AI Models
                    
                      Claude
                      GPT
                      Gemini
                      +300 more
                    
                    OpenRouter · Vertex AI · Bedrock · Azure OpenAI
## Use your existing SQL client. Seriously.


LARS speaks PostgreSQL wire protocol. That means your existing tools just work.
                No plugins. No extensions. No new software to learn.
DBeaver
                  Just connect
                
                
                  DataGrip
                  Just connect
                
                
                  Tableau
                  Just connect
                
                
                  psql
                  Just connect
                
                
                  psycopg2
                  Just connect

Your favorite SQL IDE. Your existing workflows. Now with AI operators.
Terminal
                Two commands
```
# Start LARS
$ lars serve sql --port 15432

# Connect with any PostgreSQL client
$ psql postgresql://localhost:15432/default

# Now you have AI operators
SELECT * FROM tickets
WHERE description MEANS 'urgent'
```

## Vector search in SQL. No extra infrastructure. Ad-hoc.


No ingestion pipelines. No upfront planning. Embed any column from any source DuckDB can reach—storage and indexing handled automatically.
1
                Generate embeddings
```
SELECT id, EMBED(description)
FROM products;
```


That's it. No schema changes. No separate setup.

                  Vectors are stored and indexed automatically.
2
                Search semantically
```
SELECT *
FROM VECTOR_SEARCH(
  'eco-friendly household items',
  'products', 20
)
```


Returns the 20 most similar products. Instant.

### The hybrid trick: 10,000x cost reduction


Vector search is fast but imprecise. LLM judgment is precise but expensive. Combine them.

```
WITH takes AS (
  SELECT * FROM VECTOR_SEARCH('affordable eco products', 'products', 100)
)
SELECT * FROM takes
WHERE description MEANS 'genuinely eco-friendly, not greenwashing'
LIMIT 10;
```
**Vector search:** 1M rows → 100 takes (fast, cheap)
              
              
                
                **LLM evaluation:** 100 → 10 winners (smart, still cheap)
## LLM once, SQL forever.


The LLM figures out the pattern once. Every row with the same *shape* after that? Pure SQL. Millions of rows, ~10 LLM calls.
String Fingerprinting
                parse
```
SELECT parse(phone, 'area code')
FROM contacts
```
"(555) 123-4567"
                    →
                    us_parens
                    LLM
                  
                  
                    "(800) 999-1234"
                    →
                    us_parens
                    cache
                  
                  
                    "555-123-4567"
                    →
                    us_dashes
                    LLM
                  
                  
                    "800-999-1234"
                    →
                    us_dashes
                    cache
                  
                
              
            

            
              
                JSON Schema
                smart_json
```
SELECT smart_json(data, 'customer name')
FROM orders
```
{customer: {name: "Alice"}, total: 99}
                    →
                    schema_a
                    LLM
                  
                  
                    {customer: {name: "Bob"}, total: 150}
                    →
                    schema_a
                    cache
                  
                  
                    {sku: "ABC", price: 29.99, customerName: "Jessica"}
                    →
                    schema_b
                    LLM
                  
                  
                    {sku: "XYZ", price: 49.99, customerName: "Angelina"}
                    →
                    schema_b
                    cache
### Code that writes code, cached by shape


The LLM generates a SQL expression (like a Lisp macro). That expression is cached by the data's structural fingerprint.
              Different values, same shape? The cached SQL runs directly. No LLM call needed.
~10
                phone formats in the wild
              
              
                ~10
                LLM calls to parse them all
              
              
                ∞
                rows processed instantly after
## The query you don't have to write.


You know what you want. Just not which tables. Ask in English—LARS already mapped your schema.
1
                  LARS discovers all connected databases, tables, and files
                
                
                  2
                  Your question goes to an agent that sees the full schema
                
                
                  3
                  Agent writes the SQL, executes it, returns results
                
                
                  4
                  Want to see the SQL? Use `ask_data_sql()` instead
                
              
            
            
              
                SQL
                Describe what you want
```
SELECT * FROM ask_data('metallica shows by country plus the most played song in each country');
-- or statement syntax:
ASK_DATA 'metallica shows by country plus the most played song in each country';
```
Results

| country        | shows | top_song          | times_played |
|----------------|-------|-------------------|--------------|
| United States  | 847   | Enter Sandman     | 831          |
| Germany        | 156   | Master of Puppets | 152          |
| United Kingdom | 134   | One               | 128          |
| ...            |       |                   |              |

Want to see (or edit) the SQL?
```
SELECT ask_data_sql('top 10 customers by revenue this quarter');
```
Returns: `SELECT c.name, SUM(o.total) as revenue FROM customers c JOIN orders o ON c.id = o.customer_id WHERE o.date >= '2024-10-01' GROUP BY c.name ORDER BY revenue DESC LIMIT 10`
                  
                
                
                  
                  `ask_data` is read-only—no accidental mutations. Need DDL or writes? `ask_data_sql` generates them (just won't execute).
## Alerts that understand meaning.


Traditional triggers fire on exact values. WATCH fires on *intent*.
                Subscribe to any query, trigger actions when results change—using the same semantic operators.
Traditional Alert
                  `WHERE error_count > 100
AND status = 'critical'`
                
                
                  Semantic Watch
                  `WHERE message SIMILAR_TO
'frustrated, want to cancel'`
                
              
              
                
                  
                  Queries any source LARS can reach—not just one table
                
                
                  
                  Triggers LLM workflows, signals, or plain SQL
                
                
                  
                  Smart change detection—fires on actual differences, not noise
                
              
            
            
              
                SQL
                Intelligent monitoring
```
CREATE WATCH churn_detector
POLL EVERY '5m'
AS SELECT customer_id, feedback
   FROM customer_feedback
   WHERE created_at > now() - INTERVAL '10 minutes'
     AND feedback SIMILAR_TO 'frustrated, want to cancel'
ON TRIGGER CASCADE 'retention_outreach.yaml';
```
When triggered
                    Automated
                  
                  
                    
                      
                      Query runs
                    
                    →
                    
                      
                      Results changed?
                    
                    →
                    
                      
                      Spawn LLM workflow
                    
                  
                
                
                  
                  **"I'm done with your service"** matches—even with zero keyword overlap. That's semantic alerting.
## The question after the query.


You ran a query. Now you want to know *why*.
                Pipe your results through `THEN ANALYZE`—an agent investigates, runs more SQL, writes Python, uses your tools—then saves findings. Fire and forget.
1
                  Query executes, results flow to pipeline
                
                
                  2
                  ANALYZE cascade receives data + question
                
                
                  3
                  Agent investigates (more SQL, Python, tools)
                
                
                  4
                  Analysis saved to `INTO` target table

ANALYZE is just a [pipeline cascade](#pipelines)—user-definable YAML that becomes SQL syntax. Build your own stages the same way.
SQL
                Pipeline syntax
```
SELECT month, churn_rate, segment
FROM metrics
WHERE year = 2024
THEN ANALYZE 'Why did churn spike in Q3?'
INTO churn_insights;
```
Results land in your table
                  
                    `SELECT * FROM churn_insights;`
                  
                
                
                  Bring your own cascade
```
SELECT * FROM metrics
THEN MY_CUSTOM_ANALYZER 'deep dive'
INTO custom_analysis;
```


Any cascade becomes a pipeline stage. Domain expert? Compliance bot? Define it in YAML, use it in SQL.

## Query first. Transform after.


Chain AI transformations on your results with `THEN`.
              Dedupe, filter, analyze, speak—pipe data through any stage.
              Save snapshots at each step with `INTO`.
SQL
                Chain transformations with THEN
```
SELECT * FROM customer_feedback
WHERE quarter = 'Q4'
THEN DEDUPE('email') INTO deduped
THEN FILTER('urgent issues') INTO urgent
THEN ANALYZE 'What are the patterns?'
INTO q4_analysis;
```
Cost optimization
                  
                    SQL runs first (free), filtering 10k rows to 50. Then LLM analyzes just 50 rows.
                    That's 200x less cost than per-row semantic operators.
                  
                
              
            
            
              
                
                  SELECT * FROM feedback
                  10,247 rows
                
                
                  ↓
                  THEN DEDUPE
                  3,891 rows
                
                
                  ↓
                  THEN FILTER('urgent')
                  47 rows
                
                
                  ↓
                  THEN ANALYZE INTO results
                  1 insight
### Semantic Routing with CHOOSE


AI classifies your data, routes to different workflows.

```
SELECT * FROM transactions
THEN CHOOSE BY FRAUD_DETECTOR (
    WHEN 'fraudulent' THEN BLOCK
    WHEN 'suspicious' THEN REVIEW
    ELSE ALLOW
);
```

## LLMs are unpredictable. So run them all. Bad outputs don't need handling - they just don't win.


Same prompt, wildly different results. Instead of hoping for the best, run 5 variations
              in parallel—different prompts, different models—and let an evaluator pick the winner.
              Bad outputs don't need handling. They just don't win.
**Input:** "Summarize this contract..."
              

              
                
                  Claude
                  
                  0.82
                
                
                  GPT-4
                  
                  err
                
                
                  Gemini
                  
                  0.94
                
                
                  Claude
                  
                  0.78
                
                
                  Llama
                  
                  err
                
              

              
                Evaluator
                LLM picks best
              

              
                Winner
                Take #3 (Gemini) → 0.94
#### Simpler error handling


Failures filter out naturally. Retries still exist when you need them—but takes handle most cases.

#### Multi-model racing


Run Claude, GPT-4, Gemini simultaneously. Discover which model works best for YOUR task.

#### Prompt exploration


Different prompt styles compete. Formal vs casual. Detailed vs concise. Best one emerges.

#### Cascade-level too


Run entire workflows in parallel. Only surface the winning execution. Wild.
CONFIG
              That's 3 lines
```
takes:
  factor: 5                              # Run 5 variations
  evaluator_instructions: "Pick the most accurate and complete summary"
```

### For ad-hoc queries? A SQL comment.


No config files. Just annotate your query.
3 variations, best wins
```
-- @ takes.factor: 3
SELECT description MEANS 'eco-friendly'
FROM products;
```
Multi-model ensemble
```
-- @ models: [claude-sonnet, gpt-4o, gemini-pro]
SELECT review SUMMARIZE 'key complaints'
FROM reviews;
```


Three frontier models. **One SQL comment.** Best answer wins.

#### LLM Evaluator


AI judge picks best output based on your criteria

#### Human Evaluator


Present options to humans for critical decisions

#### Pareto Frontier


Multi-objective: balance quality, cost, and speed

#### Weighted Random


Exploration mode for discovering new optima

## Your prompts compete. Winners breed.


Five prompt variations compete. Winner moves to production. 
                There, it runs 3x per request—random failures just don't win. 
                Production data feeds the next generation. Your prompts literally evolve.
10x
                  More reliable than single execution
                
                
                  60%
                  Cheaper than mutation mode
                
                
                  3x
                  Clone factor (configurable)
                
                
                  0
                  Lines of retry logic
#### Development: Mutation


5 different prompts compete. LLM evaluator picks winner. Genetic diversity.
↓
#### Production: Cloning


Champion prompt cloned 3x. Same prompt, different executions. Best one wins.
↓
#### Result: Filtered Errors


Random hallucinations? JSON parse failures? They just don't win. No retry logic.

## Code that writes code. Tests that write tests.


Five properties that make LARS fundamentally different.

#### Self-Orchestrating


Agent picks tools based on context—including MCP tool servers. No hardcoded tool lists.

#### Self-Testing


Tests write themselves from real executions. Freeze & replay.

#### Self-Optimizing


Prompts improve automatically through genetic selection.

#### Self-Healing


Failed cells debug and repair themselves with LLM assistance.

#### Self-Building


Cascades built through conversation. Chat to create workflows.

## Your queries are training data.


Every LLM call is logged. Every input. Every output. Every confidence score.
                Browse this history. Mark the good outputs. They become few-shot examples automatically.
Works on ANY model—GPT-4, Claude, Gemini, open source
                
                
                  
                  No training runs. No GPU costs. No waiting.
                
                
                  
                  Examples take effect immediately
                
                
                  
                  Easy to audit, edit, or remove
                
              
              
                You're not fine-tuning a model. You're curating a knowledge base that makes every model smarter at YOUR tasks.
              
            

            
              The Workflow
              
                
                  1
                  **Run queries normally**
                
                
                  2
                  System **auto-scores outputs** for quality (background worker, ~$0.0001/msg)
                
                
                  3
                  Browse high-confidence outputs in **Training UI**
                
                
                  4
                  Click **** to mark as trainable
                
                
                  5
                  Enable `use_training: true` on any cascade
                
                
                  6
                  **Done.** System improves from usage.
## Start simple. Go deep when ready.


Most teams are production-ready in a week. Here's the typical path.
Day 1
### Semantic filtering

WHERE text MEANS 'urgent'

Replace regex and LIKE patterns with natural language understanding. Instant win.
Day 3
### AI aggregations

SUMMARIZE(comments)

Group by category, let AI summarize each bucket. Still just SQL.
Week 1
### Takes enabled

takes: { factor: 3 }

Run 3 variations, best wins. Errors filter out. Production-grade reliability.
When ready
### Custom operators

name SOUNDS_LIKE 'Smith'

Drop a YAML cascade. Get a new SQL operator. Your team extends the language.

## 100+ AI operators. Still just SQL.


Semantic filtering. Logic checking. Text aggregation. Data quality scoring.
              Deduplication. PII removal. MDM. All as SQL functions.
SQL
              analyst_research.sql
```
SELECT
    outlook,
    COUNT(*) AS reports,
    CONSENSUS(recommendation) AS analyst_view,
    SUMMARIZE(analysis) AS key_themes
FROM analyst_reports
WHERE analysis CONTRADICTS 'management guidance'
GROUP BY NARRATIVE(analysis) AS outlook
ORDER BY reports DESC
```


Hover over a highlighted operator to see what it does

#### CONTRADICTS


"Does this contradict the management guidance?"


Semantic logic check. Finds conflicts between text and a reference claim. Unique to LARS.
analysis
                        
                          "Revenue declined 8% despite..."
                        
                        vs guidance
                        
                          "Strong growth trajectory"
                        
                      
                      →
                      
                        conflict?
                        
                          true (0.91)
#### NARRATIVE()


"What market outlook is the author conveying?"


Semantic GROUP BY on narrative framing. One LLM call categorizes all rows by the story they're telling.
in
                        
                          "Poised for breakout..."
                          "Warning signs mount..."
                          "Steady execution..."
                        
                      
                      →
                      
                        frames
                        
                          Bullish
                          Bearish
                          Neutral
#### CONSENSUS()


"What do these analysts agree on?"


Aggregate function that finds common ground across multiple texts. Synthesizes agreement, notes disagreement.
in (n rows)
                        
                          "Buy - strong moat"
                          "Hold - valuation risk"
                          "Buy - market leader"
                        
                      
                      →
                      
                        out (1 row)
                        
                          "Strong fundamentals, valuation concerns"
#### SUMMARIZE()


"Combine these analyses into key themes"


Aggregate function that condenses multiple text rows into a single coherent summary.
in (n rows)
                        
                          "Margin pressure from..."
                          "Supply chain issues..."
                          "Competition in core..."
                        
                      
                      →
                      
                        out (1 row)
                        
                          "Margin and supply chain headwinds amid rising competition"
                        
                      
                    
                  
                
              
            
          

          
            
            
              MEANS
              semantic filter
            
            
              SIMILAR_TO
              vector similarity
            
            
              CONTRADICTS
              finds conflicts
            
            
              IMPLIES
              logical inference
            

            
            
              SUMMARIZE
              text aggregation
            
            
              TOPICS()
              semantic GROUP BY
            
            
              SENTIMENT
              mood analysis
            
            
              CONSENSUS
              common ground
            

            
            
              NORMALIZE
              standardization
            
            
              DEDUPE
              semantic dedup
            
            
              QUALITY
              data quality score
            
            
              ANONYMIZE
              PII removal
            

            
            
              ASK
              any prompt
            
            
              EXTRACTS
              structured data
            
            
              TOXICITY
              content moderation
            
            
              GOLDEN_RECORD
              MDM merge
## What's happening under the hood?


Each operator is a portal to orchestrated AI workflows. Multi-model execution,
              caching, retries, validation—but you don't need to know that. Until you want to.
3x
#### Parallel execution


Run multiple models. Compare outputs. Pick the best.

#### Self-healing


Failures auto-retry with different models or prompts.
$
#### Cost tracking


Every token counted. Every cent attributed.


When you're ready to go deeper, [see the cascade architecture →](docs.html#cascade-dsl)

## Stay on the surface. Or go deep.


Some people just want queries that work. Others want to see every token.
              Both are valid. The UI is optional.
Query Results
            Dashboard
            Cascade Detail
            Context Inspector
            Cost Explorer
### Just the results


Write SQL. Get data. That's it. The AI is invisible.

### Cascades Dashboard


See all your workflows at a glance. Cost per cascade. Success rates. Recent runs.

### Cascade Execution


Watch workflows unfold. See takes race. Pick winners.

### Context Inspector


See exactly what the LLM saw. Every token. Every piece of context. Content-hashed for deduplication.

### Cost & Reliability Explorer


Drill down into costs. By cascade. By cell. By model. By hour.


*The UI is completely optional.* Everything works via SQL or command line.

## When finance asks where your LLM budget went...


Show them exactly which queries, which models, which users drove that OpenAI bill.
            Not buried in JSON trace files or separate dashboards—**it's all in SQL tables**.
            Query your costs the same way you query your data.
$
### Token-level cost attribution


See exactly what each piece of context cost. Which tokens were expensive. Where the money went.
91% context, 9% output — $0.000182
            
            
              ↓
### Query-level analytics


Track every query. Cache hit rates. Model distribution. Cost trends over time.
357 queries • $14.20 total • 78% cache hit
### Full context lineage


See exactly what went into every LLM call. Which items were reused. What's driving cost growth.
Top contributor: user_input (439 tok, 36%)
## The magic trick behind the operators.


You've been using cascades this whole time. That `MEANS` operator? It's a YAML file.
YAML
                cascades/semantic_sql/matches.cascade.yaml
```
cascade_id: semantic_matches

sql_function:
  operators:
    - "{{ text }} MEANS {{ criterion }}"

cells:
  - name: evaluate
    model: gemini-2.5-flash-lite
    instructions: |
      Does this text match the criterion?
      Text: {{ input.text }}
      Criterion: {{ input.criterion }}
```

#### Every operator is a file.


Want to change the model? Edit the file. Want stricter validation? Add a ward. Want three models to compete? Add takes.

#### The same system powers everything.


A simple MEANS check (1 cell) and a fraud detection workflow (7 cells, 3 models) are both cascades. Same primitives, different depths.

#### No abstraction gap.


Analysts use operators. Engineers customize cascades. Same system, different entry points.


**This is why LARS scales:** Start with one-liners. Evolve to workflows. Never switch tools.
MEANS
                →
                1 cell
              
              
                SUMMARIZE
                →
                1 cell
              
              
                IS_FRAUDULENT
                →
                7 cells
              
              
                Your operator
                →
                ?
## Need a custom operator? It's just YAML.


Drop a file. Restart. Your operator works. No code changes required.
YAML
                cascades/sounds_like.yaml
```
cascade_id: semantic_sounds_like

sql_function:
  name: sounds_like
  operators:
    - "{{ text }} SOUNDS_LIKE {{ ref }}"
  returns: BOOLEAN

cells:
  - name: evaluate
    model: gemini-2.5-flash-lite
    instructions: |
      Do these sound phonetically similar?
      Text: {{ input.text }}
      Reference: {{ input.ref }}
      Return only true or false.
```

### Instantly available in SQL

`SELECT * FROM customers
WHERE name SOUNDS_LIKE 'Smith'`
### Auto-discovered at startup

`Loaded 52 AI operators
• 18 infix: MEANS, CONTRADICTS, SIMILAR_TO...
• 34 functions: SUMMARIZE, DEDUPE, GOLDEN_RECORD...`
### Tools are cascades too. Call any of them from SQL.


> Every LARS tool—Python, JavaScript, Clojure, TTS, HuggingFace Spaces, even MCP tool servers—is
>               callable directly from SQL. Tools are auto-discovered and indexed, so agents can find what they need without hardcoded lists.
> Run Python
>                 `SELECT * FROM skill::python_data(
>   code := '[x**2 for x in range(10)]'
> );`
>               
>               
>                 Call HuggingFace Space
>                 `SELECT * FROM skill::huggingface(
>   space := 'stabilityai/sdxl',
>   prompt := 'data visualization rabbit'
> );`
>               
>               
>                 MCP (Filesystem)
>                 `SELECT * FROM skill::list_directory(
>   path := '/tmp'
> );`
>               
>               
>                 Text to Speech
>                 `SELECT * FROM skill::say(
>   text := 'Query complete. 47 anomalies found.'
> );`
>               
>               
>                 Browse Available Tools
>                 `SELECT * FROM skill('list_skills', '{}');`
## When SQL isn't enough? Chain languages.


> Each cell output becomes a queryable temp table. Chain SQL, Python, JavaScript,
>               Clojure, and LLM cells in one pipeline. Each language does what it's best at.
> SQL
>               Load data
>             
>             →
>             
>               Python
>               ML features
>             
>             →
>             
>               LLM
>               Classify
>             
>             →
>             
>               JS
>               Format
>             
>             →
>             
>               SQL
>               Aggregate
> **Auto-materializing temp tables.** Each cell's output becomes `_phase_name` that downstream SQL can query.
>               Python accesses prior cells via `data.previous_cell` dataframe.
>               No export/import. No glue code. It just flows.
> 
## "But it's just prompts, right?"


> Here's what a single operator *could* be doing underneath.
> What you write
```
SELECT * FROM insurance_claims
WHERE description IS_FRAUDULENT
```
Returns:
>               true
>               2.3s · $0.018
>             
>           
> 
>           
>             ↓ What actually happened ↓
>           
> 
>           
>             
>               is_fraudulent.cascade.yaml
>               7 cells · 3 models · 2 tools
>             
>             
>               
>                 Input
>                 "Claim for $50,000 water damage to basement. No photos available. Homeowner was traveling during incident."
>               
> 
>               
>                 
>                   brave_search
>                   Search: "water damage insurance fraud indicators 2024"
>                   0.4s
>                 
> 
>                 
>                   sql_data
>                   Query past claims from same address → 2 prior claims found
>                   0.1s
>                 
> 
>                 
>                   claude-sonnet
>                   
>                     Analyze claim with fraud research context
>                     "High risk: no documentation + absence during incident + prior claims"
>                   
>                   0.8s
>                 
> 
>                 
>                   gpt-4o
>                   
>                     Independent analysis, different prompt structure
>                     "Flag for review: 3 of 5 fraud indicators present"
>                   
>                   0.6s
>                 
> 
>                 
>                   gemini-pro
>                   
>                     Devil's advocate: argue against fraud
>                     "Cannot rule out legitimate claim, but pattern is concerning"
>                   
>                   0.5s
>                 
> 
>                 
>                   coordinator
>                   Weighs 3 opinions + evidence → consensus: fraudulent (confidence: 0.87)
>                   0.3s
>                 
> 
>                 
>                   ward:validate
>                   Check: confidence > 0.8 ✓ · reasoning present ✓ · no hallucination ✓
>                   0.02s
>                 
>               
> 
>               
>                 Final output:
>                 true
>                 $0.018 total · fully auditable
> Web search. Database lookups. Three models debating. Consensus building. Validation.
>               **All invisible. All logged. All from one SQL operator.**
>               You'll probably never need to know this. But when you do—it's all there.
> 
## Your SQL. Your databases.
> Now with AI.


> Start with one AI operator. Build from there.
>               Your analysts stay in SQL. Your engineers get full observability.
>               Your CFO gets the receipts.
> [View on GitHub](https://github.com/ryrobes/larsql)
>               [Read the Docs](docs.html)
> `pip install larsql`
> 
> LARS — AI that speaks SQL
> 
## AI for your data.
> Just SQL.


> No Python. No notebooks. No orchestration code.
> WHERE description MEANS 'urgent'
> Use your existing SQL client. Query your existing database. **Add intelligence.**
> 
## Same query.
> Now it understands meaning.

Before
```
SELECT * FROM tickets
WHERE priority = 'high'
```
→
>               
>                 
>                   After
>                   + AI
```
SELECT * FROM tickets
WHERE description MEANS 'urgent'
```

> One operator. Semantic understanding. **That's all it takes.**
> 
## Now it gets wild.
> AI discovers dimensions you didn't define.

Your Query
```
SELECT TOPICS(tweet, 4) AS topic,
       COUNT(*) AS tweets
FROM twitter_archive
GROUP BY topic
```
AI-Discovered Topics
>                 
>                 
>                   1
>                   Tech Industry Commentary
>                   2,341
>                 
>                 
>                   2
>                   Hot Takes & Opinions
>                   1,654
>                 
>                 
>                   3
>                   Personal Updates
>                   1,892
>                 
>                 
>                   4
>                   Link Sharing
>                   812
> You describe what you want. **AI figures out what fits.**
> 
## Run 3 attempts. Pick the best.
> Errors filter themselves out.

Parallel Execution
>                 
>                   
>                     1
>                     Comprehensive analysis with citations
>                     Best
>                   
>                   
>                     2
>                     Good response, less detail
>                     OK
>                   
>                   
>                     3
>                     JSON parse error
>                     Failed
>                   
>                 
>                 
>                   
>                 
>                 
>                   Evaluator Picks
>                   Attempt #1 — highest quality response
>                 
>               
>               
>                 
>                   Configuration
```
"takes": {
  "factor": 3,
  "evaluator": "Pick the most thorough"
}
```
**Faster** — parallel execution, not sequential retries
>                 
>                 
>                   
>                     
>                   
>                   **Higher quality** — best of N, not "first that worked"
>                 
>                 
>                   
>                     
>                   
>                   **Zero error handling** — failures become noise to filter
> LLMs fail randomly. **Plan for it.**
> 
## 100+ semantic operators


> Filter, classify, summarize, extract, dedupe — all in pure SQL
> MEANS
>                 SIMILAR_TO
>                 ABOUT
>                 CLASSIFY
>                 TOPICS
>                 SENTIMENT
>                 SUMMARIZE
>                 THEMES
>                 CONSENSUS
>                 ASK
>                 EXTRACTS
>                 PARSE
>                 CONTRADICTS
>                 IMPLIES
>                 DEDUPE
>                 OUTLIERS
>                 NORMALIZE
>                 EMBED
> Use them in **WHERE**, **SELECT**, **GROUP BY**, **ORDER BY** — they're just SQL functions.
> 
## Production ready.
> Start in seconds.


#### Any SQL Client


> PostgreSQL wire protocol. DataGrip, DBeaver, Tableau, psql — just connect.
> 
#### Cost Tracking


> Per-query observability. Know exactly what every AI operation costs.
> 
#### Self-Healing


> Failed queries auto-debug and repair themselves with LLM assistance.
> `pip install larsql && lars serve sql`
>                 
>                   
>                   Copy
>                 
>               
>               
>                 [Read the Docs](docs.html)
>                 [GitHub](https://github.com/ryrobes/larsql)
>               
>             
>           
>         
> 
>         
>         
>           
>             
>           
>           
>             
>             
>             
>             
>             
>             
>           
>           
>             
>           
>         
>       
>     
> 
>     
>     
>       
>       SLIDES
