# Built-in Operators


LARS ships with 50+ semantic SQL operators out of the box. From semantic filtering
  to logic checking, text aggregation to data quality scoring - all callable as SQL functions.
On This Page
- [Semantic Filtering](#semantic-filtering)
- [Logic Operators](#logic-operators)
- [Text Transformation](#text-transformation)
- [Aggregation Functions](#aggregation)
- [Dimension Functions](#dimension-functions)
- [Data Quality](#data-quality)
- [Parsing Functions](#parsing)
- [MDM & Record Matching](#mdm)
- [Vector & Embedding](#vector)


> **TIP: Operator Shapes**
>
> 
> Operators come in three shapes: **SCALAR** (per-row),
>     **AGGREGATE** (per-group), and **DIMENSION**
>     (semantic GROUP BY). Dimension functions are unique to LARS - they process
>     all values in a single LLM call for efficient batch classification.
> 


## Semantic Filtering


Replace brittle regex and LIKE patterns with natural language understanding.

### MEANS / MATCHES


Semantic boolean filter. Returns true if the text semantically matches the criterion.

```means examples
-- Filter by semantic meaning
SELECT * FROM tickets
WHERE description MEANS 'urgent customer issue';
-- Alternative syntax
SELECT * FROM feedback
WHERE comment MATCHES 'positive experience';
-- Tilde shorthand
SELECT * FROM docs
WHERE title ~ 'financial report';
```


| Property | Value                               |
|----------|-------------------------------------|
| Shape    | SCALAR                              |
| Returns  | BOOLEAN                             |
| Args     | `(text VARCHAR, criterion VARCHAR)` |


### SCORE / ABOUT


Returns a relevance score from 0.0 to 1.0. Use for ranking or threshold filtering.

```score examples
-- Score relevance
SELECT title, SCORE(description, 'sustainability') AS relevance
FROM reports
ORDER BY relevance DESC;
-- Filter by threshold
SELECT * FROM articles
WHERE content ABOUT 'machine learning' > 0.7;
```


| Property | Value                               |
|----------|-------------------------------------|
| Shape    | SCALAR                              |
| Returns  | DOUBLE (0.0 - 1.0)                  |
| Args     | `(text VARCHAR, criterion VARCHAR)` |


### SIMILAR_TO


Vector similarity using embeddings. Fast cosine similarity without full LLM calls.

```similar_to examples
-- Find similar documents
SELECT * FROM docs
WHERE title SIMILAR_TO 'quarterly earnings report'
LIMIT 10;
-- Similarity score
SELECT title, SIMILAR_TO(abstract, 'climate change') AS sim
FROM papers
WHERE sim > 0.8;
```

## Logic Operators


Semantic logic checking - unique to LARS. Find contradictions, implications, and alignments.

### CONTRADICTS


Check if text contradicts a reference claim. Essential for fact-checking, compliance, and due diligence.

```contradicts examples
-- Find conflicting statements
SELECT * FROM analyst_reports
WHERE analysis CONTRADICTS 'company expects 20% growth';
-- Compliance checking
SELECT * FROM disclosures
WHERE statement CONTRADICTS 'no material changes';
```


| Property | Value                               |
|----------|-------------------------------------|
| Shape    | SCALAR                              |
| Returns  | BOOLEAN                             |
| Args     | `(text VARCHAR, reference VARCHAR)` |


### IMPLIES


Check if text logically implies a conclusion. Useful for reasoning chains and policy enforcement.

```implies examples
-- Check logical implication
SELECT * FROM policies
WHERE rule_text IMPLIES 'requires manager approval';
-- Reasoning validation
SELECT * FROM arguments
WHERE premise IMPLIES conclusion;
```

### ALIGNS


Check narrative/thematic alignment. Goes beyond topic matching to assess if texts support the same message.

```aligns examples
-- Check brand alignment
SELECT * FROM marketing_copy
WHERE message ALIGNS 'innovation and customer focus';
-- Alignment score
SELECT headline, ALIGNS(body, 'sustainability commitment') AS alignment
FROM press_releases;
```

## Text Transformation


Transform, extract, and rewrite text using natural language instructions.

### ASK


The swiss army knife. Apply any arbitrary prompt to text. Maximum flexibility.

```ask examples
-- Custom transformation
SELECT ASK(description, 'Extract the main product features as a bullet list')
FROM products;
-- Complex analysis
SELECT ASK(review, 'What specific improvements does the customer suggest?')
FROM feedback;
```

### EXTRACTS


Extract specific information from text. Like grep with understanding.

```extracts examples
-- Extract specific data
SELECT EXTRACTS(email_body, 'deadline date') AS deadline
FROM emails;
-- Extract multiple fields
SELECT
  EXTRACTS(contract, 'payment terms') AS terms,
  EXTRACTS(contract, 'termination clause') AS termination
FROM contracts;
```

### CONDENSE / TLDR


Per-row text summarization. Condense long text to key points.

```condense examples
-- Summarize each row
SELECT title, CONDENSE(body) AS summary
FROM articles;
-- TLDR alias
SELECT TLDR(meeting_notes) AS summary
FROM meetings;
```

### NORMALIZE


Standardize entities to canonical forms. Handles company names, addresses, phones, and more.

```normalize examples
-- Normalize company names
SELECT NORMALIZE(company_name, 'company') AS canonical_name
FROM vendors;
-- "IBM Corp.", "I.B.M.", "International Business Machines" → "IBM"
-- Normalize addresses
SELECT NORMALIZE(address, 'address') AS std_address
FROM customers;
```

## Aggregation Functions


LLM-powered aggregates that work with GROUP BY, just like SUM or AVG.

### SUMMARIZE


Aggregate text summarization. Combines multiple rows into a coherent summary.

```summarize examples
-- Summarize reviews per product
SELECT
  product_id,
  COUNT(*) AS review_count,
  SUMMARIZE(review_text) AS summary
FROM reviews
GROUP BY product_id;
-- Summarize with focus
SELECT SUMMARIZE(feedback, 'complaints only')
FROM customer_feedback;
```

### THEMES / TOPICS


Extract N topics from a collection. Returns JSON array of discovered themes.

```themes examples
-- Extract top 5 themes
SELECT THEMES(comment, 5) AS top_themes
FROM feedback;
-- Themes per category
SELECT
  category,
  THEMES(description, 3) AS main_topics
FROM articles
GROUP BY category;
```

### CONSENSUS


Find common ground across multiple texts. What do they agree on?

```consensus examples
-- Find analyst consensus
SELECT
  ticker,
  CONSENSUS(recommendation) AS consensus_view
FROM analyst_reports
GROUP BY ticker;
-- What do reviewers agree on?
SELECT CONSENSUS(review_text) AS common_feedback
FROM reviews
WHERE product_id = 123;
```

### OUTLIERS


Find semantically unusual items in a collection. Anomaly detection for text.

```outliers examples
-- Find unusual responses
SELECT OUTLIERS(survey_response, 5) AS unusual_responses
FROM survey_data;
-- Detect anomalies per category
SELECT
  category,
  OUTLIERS(description, 3) AS anomalies
FROM logs
GROUP BY category;
```

### DEDUPE


Semantic deduplication. Identifies and returns representatives for duplicate clusters.

```dedupe examples
-- Deduplicate records
SELECT DEDUPE(company_name) AS unique_companies
FROM leads;
-- With similarity threshold
SELECT DEDUPE(description, 0.85) AS unique_items
FROM products;
```

## Dimension Functions


**Unique to LARS.** Semantic GROUP BY - one LLM call processes all values and assigns
  each to a bucket. Much more efficient than per-row classification.


> **NOTE: How Dimension Functions Work**
>
> 
> Instead of calling the LLM once per row, dimension functions collect all unique values,
>     send them to the LLM in a single batch, and receive back a mapping. This enables
>     semantic grouping at scale with minimal API costs.
> 


### TOPICS()


Group by auto-discovered topics. LLM determines meaningful categories.

```topics() dimension
-- Semantic GROUP BY on topics
SELECT
  TOPICS(title, 8) AS topic,
  COUNT(*) AS count,
  SUMMARIZE(description) AS summary
FROM articles
GROUP BY topic
ORDER BY count DESC;
```

### SENTIMENT()


Group by sentiment level. Configurable focus (general, fear, excitement, etc.).

```sentiment() dimension
-- Group by sentiment
SELECT
  SENTIMENT(comment) AS sentiment_level,
  COUNT(*) AS count
FROM reviews
GROUP BY sentiment_level;
-- Focus on specific emotion
SELECT
  SENTIMENT(feedback, 'frustration') AS frustration_level,
  COUNT(*)
FROM support_tickets
GROUP BY frustration_level;
```

### NARRATIVE()


Group by narrative framing. Identifies the story angle: Bullish/Bearish, David vs Goliath,
  Crisis, Progress, etc.

```narrative() dimension
-- Group by narrative frame
SELECT
  NARRATIVE(analysis) AS frame,
  COUNT(*) AS reports,
  SUMMARIZE(analysis) AS key_points
FROM media_coverage
GROUP BY frame;
```

### Other Dimension Functions


| Function        | Description               | Example Buckets                          |
|-----------------|---------------------------|------------------------------------------|
| `TOXICITY()`    | Content moderation levels | Clean, Mild, Moderate, Severe            |
| `INTENT()`      | Communicative intent      | Question, Statement, Complaint, Request  |
| `CREDIBILITY()` | Source reliability        | Very Low, Low, Moderate, High, Very High |
| `COMPLEXITY()`  | Task/content complexity   | Trivial, Low, Medium, High, Very High    |
| `CATEGORY()`    | Auto or custom categories | User-defined or auto-detected            |
| `AUDIENCE()`    | Target audience           | Technical, Executive, Consumer, etc.     |
| `FORMALITY()`   | Formality level           | Casual, Neutral, Formal, Legal           |
| `STANCE()`      | Position on topic         | Supportive, Neutral, Opposed             |


## Data Quality


Assess, validate, and clean data quality issues.

### QUALITY


Data quality score from 0.0 to 1.0. Assesses completeness, validity, and consistency.

```quality examples
-- Score data quality
SELECT
  id,
  QUALITY(address) AS address_quality,
  QUALITY(phone) AS phone_quality
FROM contacts
WHERE QUALITY(address) < 0.5;
```

### VALID


Format validation. Returns boolean for email, phone, URL, date, SSN, zip, etc.

```valid examples
-- Validate email format
SELECT * FROM contacts
WHERE NOT VALID(email, 'email');
-- Multiple validations
SELECT
  id,
  VALID(phone, 'phone') AS phone_ok,
  VALID(zip, 'zip') AS zip_ok
FROM leads;
-- Supported types: email, phone, url, date, ssn, zip, uuid, ip, credit_card, iban
```

### ANONYMIZE


Remove or mask PII. Essential for GDPR/HIPAA compliance.

```anonymize examples
-- Anonymize text
SELECT ANONYMIZE(notes) AS safe_notes
FROM medical_records;
-- Specify what to remove
SELECT ANONYMIZE(transcript, 'names, phone numbers, addresses')
FROM call_logs;
```

## Parsing Functions


Parse unstructured text into structured data. All parsing functions use
  **structural caching** for massive efficiency gains.


> **NOTE: Structural Caching: Code That Writes Code**
>
> 
> Parsing functions don't call the LLM for every row. Instead, they work like macros:
> 
> 1. The LLM analyzes the **shape** of the input (not the content)
> 2. It generates a SQL expression to parse that shape
> 3. The SQL expression is **cached by shape fingerprint**
> 4. Future rows with the same shape use the cached SQL instantly
> 
> For example, phone numbers `(555) 123-4567` and `(800) 999-1234`
>     have the same shape `(DDD) DDD-DDDD`. The first call generates a regex,
>     all subsequent calls with that format execute instantly with zero LLM cost.
> 
> This means you only pay for **new shapes**, not new values. Parse a million
>     phone numbers in 3 formats? That's 3 LLM calls, not a million.
> 


### PARSE


The universal parser. Extract anything from text using plain English instructions.
  Unlike specialized parsers, this handles any extraction task.

```parse examples
-- Extract dates
SELECT PARSE(email_body, 'the deadline date') AS deadline
FROM emails;
-- Extract specific facts
SELECT PARSE(notes, 'reason for rejection') AS reason
FROM applications;
-- Extract lists (returns JSON array)
SELECT PARSE(meeting_notes, 'action items') AS todos
FROM meetings;
-- Extract amounts
SELECT PARSE(contract, 'total contract value') AS value
FROM agreements;
-- Infix syntax
SELECT bio PARSE 'years of experience' AS experience
FROM takes;
```


| Property | Value                                            |
|----------|--------------------------------------------------|
| Shape    | SCALAR                                           |
| Returns  | VARCHAR (single value or JSON for lists/objects) |
| Args     | `(text VARCHAR, instruction VARCHAR)`            |


> **TIP: When to Use PARSE vs Specialized Parsers**
>
> 
> Use `PARSE()` for ad-hoc extraction or when you need flexibility.
>     Use specialized parsers (`PARSE_NAME`, `PARSE_ADDRESS`)
>     when you need consistent structured output schemas.
> 


### PARSE_NAME


Parse person names into components: prefix, first, middle, last, suffix.

```parse_name examples
-- Parse names with ->> operator
SELECT
  PARSE_NAME(full_name) ->> 'first' AS first_name,
  PARSE_NAME(full_name) ->> 'last' AS last_name
FROM contacts;
-- Returns JSON: {"prefix": "Dr.", "first": "John", "middle": "Q", "last": "Smith", "suffix": "Jr."}
-- Available fields: prefix, first, middle, last, suffix, nickname, formatted
```


| Property | Value            |
|----------|------------------|
| Shape    | SCALAR           |
| Returns  | JSON             |
| Args     | `(name VARCHAR)` |


### PARSE_ADDRESS


Parse addresses into street, city, state, zip, country components.

```parse_address examples
-- Parse addresses with ->> operator
SELECT
  PARSE_ADDRESS(addr) ->> 'city' AS city,
  PARSE_ADDRESS(addr) ->> 'state' AS state,
  PARSE_ADDRESS(addr) ->> 'zip' AS zip
FROM customers;
-- Available fields: street_number, street_name, unit_number, city, state, zip, country, formatted
```


| Property | Value               |
|----------|---------------------|
| Shape    | SCALAR              |
| Returns  | JSON                |
| Args     | `(address VARCHAR)` |


### PARSE_PHONE


Parse phone numbers into structured components and normalized formats.

```parse_phone examples
-- Parse phone numbers with ->> operator
SELECT
  PARSE_PHONE(phone) ->> 'e164' AS e164_format,
  PARSE_PHONE(phone) ->> 'national' AS national_format,
  PARSE_PHONE(phone) ->> 'is_valid' AS valid
FROM contacts;
-- Specify default country for numbers without country code
SELECT PARSE_PHONE(phone, 'GB') ->> 'international'
FROM uk_customers;
-- Available fields: country_code, area_code, exchange, subscriber, extension,
--   e164, national, international, is_valid, type
```


| Property | Value                                             |
|----------|---------------------------------------------------|
| Shape    | SCALAR                                            |
| Returns  | JSON                                              |
| Args     | `(phone VARCHAR, default_country VARCHAR = 'US')` |


### PARSE_DATE


Parse any date format. Handles "January 15, 2024", "01/15/24", "2024-01-15", "March 2024", "Q1 2024", etc.

```parse_date examples
-- Parse dates with ->> operator
SELECT
  PARSE_DATE(date_text) ->> 'iso' AS iso_date,
  PARSE_DATE(date_text) ->> 'year' AS year,
  PARSE_DATE(date_text) ->> 'day_of_week' AS day
FROM events;
-- Handle ambiguous formats (US vs EU)
SELECT PARSE_DATE(date_text, 'dmy') ->> 'iso'
FROM eu_records;
-- Available fields: year, month, day, hour, minute, second, timezone,
--   iso, iso_datetime, formatted, day_of_week, quarter, is_approximate, is_valid
```


| Property | Value                                                |
|----------|------------------------------------------------------|
| Shape    | SCALAR                                               |
| Returns  | JSON                                                 |
| Args     | `(date_text VARCHAR, prefer_format VARCHAR = 'mdy')` |


### SMART_JSON / ->


Natural language JSON extraction. Uses **schema-based caching** - the LLM
  sees the JSON structure (field names and types), not the values. Same schema = cached SQL.

```smart_json examples
-- Extract with natural language
SELECT SMART_JSON(payload, 'customer email')
FROM orders;
-- Arrow syntax
SELECT metadata -> 'order total'
FROM transactions;
-- All orders have the same JSON schema, so this is 1 LLM call
-- for the first row, then cached SQL for the rest
```

## MDM & Record Matching


Master Data Management primitives. Merge duplicates, match records, create golden records.

### GOLDEN_RECORD


Create best composite record from duplicate takes. Picks the best value for each field.

```golden_record examples
-- Merge duplicate customer records
SELECT
  customer_cluster_id,
  GOLDEN_RECORD(name, email, phone, address) AS master_record
FROM customer_matches
GROUP BY customer_cluster_id;
```

### MATCH_PAIR / SAME_AS


Check if two values represent the same entity. For fuzzy JOINs and deduplication.

```match_pair examples
-- Fuzzy join
SELECT * FROM vendors a, leads b
WHERE MATCH_PAIR(a.company_name, b.company_name);
-- With relationship context
SELECT * FROM records
WHERE MATCH_PAIR(name1, name2, 'same person');
```

### COALESCE_SMART


Smart COALESCE - picks the best non-null value, not just the first. Quality-aware.

```coalesce_smart examples
-- Pick best email (not just first non-null)
SELECT COALESCE_SMART(email1, email2, email3) AS best_email
FROM contact_sources;
-- With preference
SELECT COALESCE_SMART(phone1, phone2, phone3, 'prefer mobile')
FROM contacts;
```

## Vector & Embedding


Create embeddings and perform vector search.

### EMBED


Generate embedding vector for text. Used to power SIMILAR_TO and VECTOR_SEARCH.

```embed examples
-- Generate embedding
SELECT EMBED(description) AS embedding
FROM products;
-- Index a column for vector search
LARS EMBED articles.content
FROM articles;
```

### VECTOR_SEARCH


Semantic search using pre-computed embeddings.

```vector_search examples
-- Search by semantic similarity
SELECT * FROM VECTOR_SEARCH(
  'machine learning applications',
  docs.content,
  20,    -- limit
  0.7   -- min_score
);
```

## Creating Custom Operators


Any cascade with `sql_function` configuration becomes a SQL operator automatically.
  See [Semantic SQL](#semantic-sql) for details on creating your own.

```cascades/my_operator.cascade.yaml
cascade_id: my_custom_operator

sql_function:
  name: MY_OP
  operators:
    - "{{ text }} MY_OP {{ criterion }}"
    - "MY_OP({{ text }}, {{ criterion }})"
  args:
    - name: text
      type: VARCHAR
    - name: criterion
      type: VARCHAR
  returns: BOOLEAN
  shape: SCALAR

cells:
  - name: evaluate
    instructions: |
      Your prompt here using {{ input.text }} and {{ input.criterion }}
```

## Next Steps
- [Semantic SQL](#semantic-sql) - Architecture and custom operators
- [Tools Reference](#tools) - Built-in tools for cascades
- [Vector Search](#embedding) - Embedding and search details
