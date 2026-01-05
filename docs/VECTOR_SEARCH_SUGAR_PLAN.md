# Vector Search SQL Sugar - Implementation Plan

## Problem Statement

Current embedding and vector search SQL is **functional but clunky**:

```sql
-- Embedding: verbose JSON construction
SELECT embed_batch(
  'bird_line',
  'text',
  (SELECT to_json(list({'id': CAST(id AS VARCHAR), 'text': text})) FROM bird_line LIMIT 10)
);

-- Vector search: wrapped in read_json_auto, positional args
SELECT * FROM read_json_auto(
  vector_search_json_3('Venezuela', 'bird_line', 10)
);

-- Elastic: unclear multi-arity support
SELECT * FROM vector_search_elastic('Venezuela', 'bird_line', 10, 0.5, 0.8, 0.2);
```

**Pain Points:**
1. Manual JSON construction for embedding
2. `read_json_auto()` wrapper boilerplate
3. Positional string arguments (`'bird_line'` instead of `bird_line.text`)
4. Unclear which arguments are supported
5. No autocomplete/IDE support for table.column syntax

---

## Goal: Elegant SQL Sugar

### A. RVBBIT EMBED Statement (Side-Effectful Indexing)

Follows RVBBIT MAP/RUN pattern for consistency:

```sql
-- ClickHouse backend:
RVBBIT EMBED bird_line.text
USING (SELECT CAST(id AS VARCHAR) AS id, text AS text FROM bird_line)
WITH (backend='clickhouse', batch_size=50);

-- Elastic backend:
RVBBIT EMBED bird_line.text
USING (SELECT CAST(id AS VARCHAR) AS id, text AS text FROM bird_line)
WITH (backend='elastic', batch_size=50, index='rvbbit_embeddings');

-- File-based (from CSV, parquet, etc.):
RVBBIT EMBED documents.content
USING (SELECT id, content AS text FROM read_csv('docs.csv'))
WITH (backend='clickhouse');
```

**Benefits:**
- Consistent with RVBBIT MAP/RUN syntax
- Explicit id + text columns (no inference bugs)
- Supports arbitrary queries (not just tables)
- Clear backend selection

### B. Field-Aware Search Sugar (Pure Queries)

Table-valued functions with table.column syntax:

```sql
-- Basic vector search:
SELECT * FROM VECTOR_SEARCH('Venezuela', bird_line.text, 10);

-- With score threshold:
SELECT * FROM VECTOR_SEARCH('Venezuela', bird_line.text, 10, 0.5);

-- Hybrid search (semantic + keyword):
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10);

-- Hybrid with weights:
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10, 0.5, 0.8, 0.2);
--                                                            ^^^^  ^^^  ^^^
--                                                            min   sem  key

-- Join with other tables:
SELECT p.*, vs.score, vs.chunk_text
FROM products p
JOIN VECTOR_SEARCH('eco-friendly', products.description, 5) vs
  ON vs.id = p.id::VARCHAR
WHERE vs.score > 0.7;
```

**Rewrites to:**
```sql
-- VECTOR_SEARCH rewrites to:
SELECT * FROM read_json_auto(
  vector_search_json_3('Venezuela', 'bird_line.text', 10)
) WHERE metadata.column_name = 'text';  -- Auto-filter by column!

-- HYBRID_SEARCH rewrites to:
SELECT * FROM vector_search_elastic_6(
  'Venezuela', 'bird_line', 'text', 10, 0.5, 0.8, 0.2
);
```

**Benefits:**
- Natural table.column syntax (IDE autocomplete)
- Automatic metadata.column_name filtering
- Clear argument names (not positional strings)
- read_json_auto wrapper handled automatically

---

## Design Decisions

### 1. Field Reference Syntax

Use SQL standard dotted identifiers:

```sql
table.column        -- Standard SQL identifier
table_name.col_name -- Natural, autocomplete-friendly
```

**Not:**
```sql
'table.column'      -- String (no autocomplete)
'table:column'      -- Non-standard
```

### 2. Backend Selection

Explicit WITH options (no magic detection):

```sql
WITH (backend='clickhouse')  -- Explicit
WITH (backend='elastic')     -- Clear
```

**Not:**
```sql
-- Magic detection based on table name or previous queries
```

### 3. USING Query Pattern

Reuse RVBBIT MAP/RUN pattern for consistency:

```sql
RVBBIT EMBED table.column
USING (
  SELECT id_column AS id,    -- Must alias to 'id'
         text_column AS text  -- Must alias to 'text'
  FROM source
)
```

**Required columns:**
- `id`: Primary key (cast to VARCHAR)
- `text`: Text content to embed

**Optional columns:**
- `metadata`: JSON object with extra fields
- `chunk_id`: For document chunking

### 4. Metadata Column Filtering

Auto-filter search results by column_name:

```sql
-- User writes:
VECTOR_SEARCH('query', bird_line.text, 10)

-- System extracts: column = 'text'
-- Rewrites to:
read_json_auto(vector_search_json_3('query', 'bird_line.text', 10))
-- Plus adds: WHERE metadata.column_name = 'text'
```

**Why:** Tables may have multiple embedded columns (title, description, content). Auto-filter ensures you only search the requested column.

---

## Implementation Phases

### Phase 1: RVBBIT EMBED Statement Parser

**Goal:** Parse and rewrite RVBBIT EMBED syntax

**Files to Create/Modify:**

1. **`sql_rewriter.py`** - Add EMBED to detection and parsing

```python
@dataclass
class RVBBITEmbedStatement:
    """Parsed RVBBIT EMBED statement."""
    field_ref: str              # "bird_line.text"
    table_name: str             # "bird_line" (extracted)
    column_name: str            # "text" (extracted)
    using_query: str            # SELECT ... query
    with_options: Dict[str, Any]  # backend, batch_size, etc.

def _is_embed_statement(query: str) -> bool:
    """Check if query is RVBBIT EMBED."""
    clean = query.strip().upper()
    return 'RVBBIT EMBED' in clean

def _parse_rvbbit_embed(query: str) -> RVBBITEmbedStatement:
    """
    Parse RVBBIT EMBED statement.

    Syntax:
        RVBBIT EMBED table.column
        USING (SELECT id, text FROM ...)
        WITH (backend='clickhouse', batch_size=50)
    """
    # Extract field reference (table.column)
    # Extract USING clause
    # Extract WITH options
    # Validate id + text columns in USING query

def _rewrite_embed(stmt: RVBBITEmbedStatement) -> str:
    """
    Rewrite EMBED statement to embed_batch() call.

    Returns SQL that executes the embedding operation.
    """
    backend = stmt.with_options.get('backend', 'clickhouse')
    batch_size = stmt.with_options.get('batch_size', 100)

    if backend == 'clickhouse':
        return f"""
        SELECT embed_batch(
            '{stmt.table_name}',
            '{stmt.column_name}',
            ({stmt.using_query}),
            {batch_size}
        )
        """
    elif backend == 'elastic':
        index = stmt.with_options.get('index', 'rvbbit_embeddings')
        return f"""
        SELECT embed_batch_elastic(
            '{stmt.table_name}',
            '{stmt.column_name}',
            ({stmt.using_query}),
            '{index}',
            {batch_size}
        )
        """
    else:
        raise RVBBITSyntaxError(f"Unknown backend: {backend}")
```

**Integration:**

```python
# In rewrite_rvbbit_syntax():
if _is_embed_statement(normalized):
    stmt = _parse_rvbbit_embed(normalized)
    return _rewrite_embed(stmt)
```

---

### Phase 2: Field Reference Parser

**Goal:** Extract table.column from SQL identifiers

**File to Create:** `sql_tools/field_reference.py`

```python
"""
Field Reference Parser - Extract table.column identifiers.

Handles dotted identifiers in SQL for field-aware operations.
"""

import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class FieldReference:
    """A parsed table.column reference."""
    table: str       # "bird_line"
    column: str      # "text"
    full_ref: str    # "bird_line.text"

    @property
    def metadata_key(self) -> str:
        """Key for metadata.column_name filtering."""
        return f"{self.table}.{self.column}"

def parse_field_reference(identifier: str) -> Optional[FieldReference]:
    """
    Parse a dotted identifier into table and column.

    Args:
        identifier: String like "bird_line.text" or "users.email"

    Returns:
        FieldReference if valid dotted identifier, None otherwise

    Examples:
        >>> parse_field_reference("bird_line.text")
        FieldReference(table='bird_line', column='text', ...)

        >>> parse_field_reference("text")  # No dot
        None

        >>> parse_field_reference("db.schema.table.col")  # Too many parts
        None
    """
    # Simple pattern: word.word
    if '.' not in identifier:
        return None

    parts = identifier.split('.')
    if len(parts) != 2:
        return None  # Only support table.column (not schema.table.column)

    table, column = parts

    # Validate SQL identifier format (no quotes, special chars)
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
        return None
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column):
        return None

    return FieldReference(
        table=table,
        column=column,
        full_ref=identifier
    )

def extract_field_from_function_call(sql: str, func_name: str, arg_index: int = 1) -> Optional[FieldReference]:
    """
    Extract field reference from function call argument.

    Args:
        sql: SQL query
        func_name: Function name to find (e.g., "VECTOR_SEARCH")
        arg_index: Which argument to extract (0-based, default 1 for 2nd arg)

    Returns:
        FieldReference if found, None otherwise

    Example:
        >>> extract_field_from_function_call(
        ...     "SELECT * FROM VECTOR_SEARCH('query', bird_line.text, 10)",
        ...     "VECTOR_SEARCH",
        ...     1
        ... )
        FieldReference(table='bird_line', column='text', ...)
    """
    # Use token-based parsing to find function call
    # Extract argument at arg_index
    # Parse as field reference
    # Return
```

---

### Phase 3: VECTOR_SEARCH Rewriter

**Goal:** Rewrite table-valued VECTOR_SEARCH calls

**File to Create:** `sql_tools/vector_search_rewriter.py`

```python
"""
Vector Search Rewriter - Sugar for vector search table functions.

Rewrites:
    SELECT * FROM VECTOR_SEARCH('query', table.column, limit)

To:
    SELECT * FROM read_json_auto(
        vector_search_json_3('query', 'table.column', limit)
    )
    WHERE metadata.column_name = 'column'  -- Auto-filter by column
"""

from typing import Optional, Tuple
import logging

log = logging.getLogger(__name__)


def has_vector_search_calls(sql: str) -> bool:
    """Check if SQL contains VECTOR_SEARCH or HYBRID_SEARCH table functions."""
    sql_upper = sql.upper()
    return (
        'VECTOR_SEARCH(' in sql_upper or
        'HYBRID_SEARCH(' in sql_upper
    )


def rewrite_vector_search(sql: str) -> str:
    """
    Rewrite VECTOR_SEARCH and HYBRID_SEARCH table functions.

    Handles:
    - VECTOR_SEARCH('query', table.column, limit) → ClickHouse
    - VECTOR_SEARCH('query', table.column, limit, min_score) → ClickHouse with threshold
    - HYBRID_SEARCH('query', table.column, ...) → Elastic

    Returns:
        Rewritten SQL with read_json_auto wrappers and metadata filters
    """
    from .semantic_rewriter_v2 import _tokenize
    from .field_reference import extract_field_from_function_call, parse_field_reference

    if not has_vector_search_calls(sql):
        return sql

    try:
        tokens = _tokenize(sql)
    except Exception as e:
        log.warning(f"[vector_search_rewriter] Tokenization failed: {e}")
        return sql

    result = sql

    # Find VECTOR_SEARCH calls
    result = _rewrite_vector_search_calls(result, tokens)

    # Find HYBRID_SEARCH calls
    result = _rewrite_hybrid_search_calls(result, tokens)

    return result


def _rewrite_vector_search_calls(sql: str, tokens) -> str:
    """
    Rewrite VECTOR_SEARCH table function calls.

    VECTOR_SEARCH('query', table.column, limit)
    → read_json_auto(vector_search_json_3('query', 'table.column', limit))
      WHERE metadata.column_name = 'column'

    VECTOR_SEARCH('query', table.column, limit, min_score)
    → read_json_auto(vector_search_json_4('query', 'table.column', limit, min_score))
      WHERE metadata.column_name = 'column'
    """
    # Token-based matching for: FROM VECTOR_SEARCH(...)
    # Extract arguments
    # Parse field reference from 2nd arg
    # Generate read_json_auto wrapper
    # Add metadata.column_name filter
    pass  # TODO: Implement


def _rewrite_hybrid_search_calls(sql: str, tokens) -> str:
    """
    Rewrite HYBRID_SEARCH table function calls.

    HYBRID_SEARCH('query', table.column, limit)
    → vector_search_elastic_3('query', 'table', 'column', limit)

    HYBRID_SEARCH('query', table.column, limit, min_score, sem_weight, kw_weight)
    → vector_search_elastic_6('query', 'table', 'column', limit, min_score, sem_weight, kw_weight)
    """
    # Token-based matching for: FROM HYBRID_SEARCH(...)
    # Extract arguments
    # Parse field reference from 2nd arg
    # Split table.column into separate args
    # Generate numbered function call
    pass  # TODO: Implement
```

---

### Phase 4: Integration with Unified Rewriter

**Goal:** Add vector search rewriting to the unified pipeline

**Modify:** `sql_tools/unified_operator_rewriter.py`

```python
def rewrite_all_operators(sql: str) -> str:
    """Unified entry point for ALL SQL extensions."""

    # ... existing directive stripping ...

    # Phase 0.5: Vector search table functions
    # Must run BEFORE semantic operators (field.ref syntax conflicts)
    result = _rewrite_vector_search_functions(inner_sql)

    # ... existing block/dimension/inline operators ...

    return result


def _rewrite_vector_search_functions(sql: str) -> str:
    """Rewrite VECTOR_SEARCH and HYBRID_SEARCH table functions."""
    try:
        from .vector_search_rewriter import rewrite_vector_search
        return rewrite_vector_search(sql)
    except Exception as e:
        log.warning(f"[unified_rewriter] Vector search rewrite failed: {e}")
        return sql
```

---

## Detailed Syntax Specification

### RVBBIT EMBED Statement

**Full Syntax:**
```sql
RVBBIT EMBED <table>.<column>
USING (<select_query>)
[WITH (<options>)]
```

**Required:**
- `<table>.<column>`: Field reference (table.column identifier)
- `USING (<select_query>)`: Query that returns `id` and `text` columns

**Optional WITH Options:**
- `backend`: `'clickhouse'` (default) or `'elastic'`
- `batch_size`: Integer (default: 100)
- `index`: String for Elastic index name (default: `'rvbbit_embeddings'`)
- `model`: Embedding model override (default from config)

**USING Query Requirements:**
- Must return at least 2 columns
- Must have column aliased as `id` (VARCHAR)
- Must have column aliased as `text` (VARCHAR)
- Optional: `metadata` (JSON) for additional fields

**Examples:**

```sql
-- Minimal (ClickHouse):
RVBBIT EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)

-- With options:
RVBBIT EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
WITH (backend='elastic', batch_size=200, index='articles_idx')

-- With metadata:
RVBBIT EMBED articles.content
USING (
  SELECT
    id::VARCHAR AS id,
    content AS text,
    to_json({'title': title, 'author': author}) AS metadata
  FROM articles
)

-- From file:
RVBBIT EMBED docs.text
USING (SELECT row_number AS id, content AS text FROM read_csv('docs.csv'))
WITH (backend='clickhouse')
```

---

### VECTOR_SEARCH Function

**Signature:**
```sql
VECTOR_SEARCH(
  query: VARCHAR,           -- Search query
  field: table.column,      -- Field reference (NOT string)
  limit: INTEGER,           -- Max results
  min_score: DOUBLE = 0.0   -- Optional score threshold
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  chunk_text VARCHAR,
  metadata JSON
)
```

**Backend:** ClickHouse vector index

**Examples:**

```sql
-- Basic search:
SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10);

-- With score threshold:
SELECT * FROM VECTOR_SEARCH('renewable energy', articles.content, 20, 0.6);

-- Select specific columns:
SELECT id, score, chunk_text
FROM VECTOR_SEARCH('AI ethics', papers.abstract, 5);

-- Join with source table:
SELECT a.title, vs.score, vs.chunk_text
FROM articles a
JOIN VECTOR_SEARCH('machine learning', articles.content, 10) vs
  ON vs.id = a.id::VARCHAR;
```

**Rewrite Logic:**

```python
# Input:
VECTOR_SEARCH('query', bird_line.text, 10)

# Detect field reference: bird_line.text
# Extract: table='bird_line', column='text'

# Rewrite to:
read_json_auto(
  vector_search_json_3('query', 'bird_line.text', 10)
)
WHERE metadata.column_name = 'text'  -- Auto-added filter
```

---

### HYBRID_SEARCH Function

**Signature:**
```sql
HYBRID_SEARCH(
  query: VARCHAR,              -- Search query
  field: table.column,         -- Field reference
  limit: INTEGER,              -- Max results
  min_score: DOUBLE = 0.0,     -- Optional score threshold
  semantic_weight: DOUBLE = 0.7,  -- Semantic score weight
  keyword_weight: DOUBLE = 0.3    -- Keyword score weight
)
RETURNS TABLE (
  id VARCHAR,
  score DOUBLE,
  semantic_score DOUBLE,
  keyword_score DOUBLE,
  chunk_text VARCHAR,
  metadata JSON
)
```

**Backend:** Elasticsearch with hybrid scoring

**Examples:**

```sql
-- Basic hybrid search:
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10);

-- With custom weights (80% semantic, 20% keyword):
SELECT * FROM HYBRID_SEARCH('climate action', articles.content, 20, 0.5, 0.8, 0.2);

-- Full control:
SELECT id, score, semantic_score, keyword_score
FROM HYBRID_SEARCH('sustainability', products.description, 50, 0.6, 0.7, 0.3)
ORDER BY score DESC;
```

**Rewrite Logic:**

```python
# Input:
HYBRID_SEARCH('query', bird_line.text, 10, 0.5, 0.8, 0.2)

# Extract field: table='bird_line', column='text'
# Count args: 6 total

# Rewrite to:
vector_search_elastic_6(
  'query',        -- query
  'bird_line',    -- table (split from field ref)
  'text',         -- column (split from field ref)
  10,             -- limit
  0.5,            -- min_score
  0.8,            -- semantic_weight
  0.2             -- keyword_weight
)
```

---

## Token-Based Parsing Strategy

### Detecting Table Functions in FROM Clause

```python
def _find_table_function_calls(tokens, func_name: str):
    """
    Find table function calls in FROM clause using token matching.

    Detects:
        FROM VECTOR_SEARCH(...)
        JOIN HYBRID_SEARCH(...) ON ...

    Returns:
        List of (token_start, token_end, args) tuples
    """
    matches = []

    for i, tok in enumerate(tokens):
        if tok.typ != 'ident':
            continue

        # Check for FROM or JOIN before function
        if tok.text.upper() in ('FROM', 'JOIN'):
            # Look ahead for function name
            j = i + 1
            while j < len(tokens) and tokens[j].typ == 'ws':
                j += 1

            if j < len(tokens) and tokens[j].typ == 'ident':
                if tokens[j].text.upper() == func_name:
                    # Found it! Now extract arguments
                    args_start = j + 1
                    # Find balanced parens...
                    args = _extract_function_args(tokens, args_start)
                    matches.append((i, args_end, args))

    return matches
```

### Parsing Field References in Arguments

```python
def _parse_arg_as_field_ref(tokens, start, end) -> Optional[FieldReference]:
    """
    Parse a function argument as a field reference.

    Handles:
        bird_line.text         → FieldReference(...)
        'bird_line.text'       → None (it's a string, not identifier)
        bird_line.text::VARCHAR → FieldReference(...) (ignore cast)
    """
    # Skip whitespace
    i = start
    while i < end and tokens[i].typ == 'ws':
        i += 1

    # Expect identifier
    if i >= end or tokens[i].typ != 'ident':
        return None

    # Check for dotted identifier: ident.ident
    if i + 2 < end:
        if tokens[i + 1].typ == 'punct' and tokens[i + 1].text == '.':
            if tokens[i + 2].typ == 'ident':
                # Got table.column!
                table = tokens[i].text
                column = tokens[i + 2].text
                return FieldReference(table, column, f"{table}.{column}")

    return None
```

---

## Rewrite Examples

### Example 1: Basic VECTOR_SEARCH

**Input:**
```sql
SELECT * FROM VECTOR_SEARCH('climate change', articles.content, 10)
```

**Token Analysis:**
```
[FROM] [VECTOR_SEARCH] [(] ['climate change'] [,] [articles] [.] [content] [,] [10] [)]
                                                   ^^^^^^^^   ^   ^^^^^^^
                                                   Field reference detected!
```

**Rewrite Steps:**
1. Detect `FROM VECTOR_SEARCH(...)`
2. Extract args: `['climate change', 'articles.content', '10']`
3. Parse arg[1] as field ref: `FieldReference(table='articles', column='content')`
4. Generate wrapper:

**Output:**
```sql
SELECT * FROM read_json_auto(
  vector_search_json_3('climate change', 'articles.content', 10)
)
WHERE metadata.column_name = 'content'
```

### Example 2: HYBRID_SEARCH with Weights

**Input:**
```sql
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 10, 0.5, 0.8, 0.2)
```

**Rewrite Steps:**
1. Detect `FROM HYBRID_SEARCH(...)`
2. Extract args: `['Venezuela', 'bird_line.text', '10', '0.5', '0.8', '0.2']`
3. Parse arg[1]: `FieldReference(table='bird_line', column='text')`
4. Count args: 6 → use `vector_search_elastic_6`
5. Split field ref into table + column args

**Output:**
```sql
SELECT * FROM vector_search_elastic_6(
  'Venezuela',   -- query
  'bird_line',   -- table
  'text',        -- column
  10,            -- limit
  0.5,           -- min_score
  0.8,           -- semantic_weight
  0.2            -- keyword_weight
)
```

### Example 3: RVBBIT EMBED

**Input:**
```sql
RVBBIT EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text AS text FROM bird_line LIMIT 100)
WITH (backend='elastic', batch_size=50)
```

**Parse Steps:**
1. Detect `RVBBIT EMBED`
2. Extract field ref: `bird_line.text` → table='bird_line', column='text'
3. Extract USING query: `SELECT id::VARCHAR AS id, text AS text FROM bird_line LIMIT 100`
4. Extract WITH options: `{backend: 'elastic', batch_size: 50}`
5. Validate USING query has `id` and `text` columns

**Output:**
```sql
SELECT embed_batch_elastic(
  'bird_line',
  'text',
  (SELECT id::VARCHAR AS id, text AS text FROM bird_line LIMIT 100),
  'rvbbit_embeddings',
  50
)
```

---

## Edge Cases & Validation

### 1. Ambiguous Field References

**Problem:**
```sql
-- Which table does 'text' belong to?
SELECT * FROM VECTOR_SEARCH('query', text, 10)
```

**Solution:** Require dotted identifier:
```sql
SELECT * FROM VECTOR_SEARCH('query', articles.text, 10)  -- Clear!
```

Single identifiers are treated as strings (backwards compat).

### 2. Missing id/text Columns in USING

**Problem:**
```sql
RVBBIT EMBED articles.content
USING (SELECT content FROM articles)  -- Missing 'id'!
```

**Solution:** Validation error:
```
RVBBIT EMBED requires USING query to return:
  - id: VARCHAR (primary key)
  - text: VARCHAR (content to embed)

Your query returns: ['content']
Missing: ['id', 'text']
```

### 3. Multiple Embedded Columns

**Problem:** Table has multiple embedded columns (title, description, content)

**Solution:** metadata.column_name filter:
```sql
-- Only search 'content' column:
VECTOR_SEARCH('query', articles.content, 10)
→ WHERE metadata.column_name = 'content'

-- Search different column:
VECTOR_SEARCH('query', articles.title, 10)
→ WHERE metadata.column_name = 'title'
```

### 4. Schema-Qualified Names

**Problem:**
```sql
VECTOR_SEARCH('query', myschema.articles.content, 10)
```

**Solution (v1):** Only support table.column (2 parts):
```
Error: Field reference must be table.column, got 3 parts
```

**Solution (v2 - future):** Support schema.table.column

---

## Implementation Order

### Sprint 1: RVBBIT EMBED Statement (3-4 hours)

1. ✅ Add detection to `sql_rewriter.py` (`_is_embed_statement()`)
2. ✅ Implement parser (`_parse_rvbbit_embed()`)
3. ✅ Implement rewriter (`_rewrite_embed()`)
4. ✅ Add field reference parser (`field_reference.py`)
5. ✅ Integration tests
6. ✅ Validate USING query (has id/text columns)

**Deliverable:**
```sql
RVBBIT EMBED bird_line.text
USING (SELECT id::VARCHAR AS id, text FROM bird_line)
WITH (backend='clickhouse')
```

### Sprint 2: VECTOR_SEARCH Rewriter (4-5 hours)

1. ✅ Create `vector_search_rewriter.py`
2. ✅ Token-based detection of table functions
3. ✅ Argument extraction (with field ref parsing)
4. ✅ Generate read_json_auto wrapper
5. ✅ Add metadata.column_name filter
6. ✅ Integration with unified rewriter
7. ✅ Tests for various argument combinations

**Deliverable:**
```sql
SELECT * FROM VECTOR_SEARCH('query', bird_line.text, 10)
```

### Sprint 3: HYBRID_SEARCH Support (2-3 hours)

1. ✅ Add HYBRID_SEARCH detection
2. ✅ Parse field reference
3. ✅ Generate vector_search_elastic_N calls
4. ✅ Handle multi-arity (3, 4, 6 arg versions)
5. ✅ Tests for weight configurations

**Deliverable:**
```sql
SELECT * FROM HYBRID_SEARCH('query', bird_line.text, 10, 0.5, 0.8, 0.2)
```

### Sprint 4: Documentation & Polish (1-2 hours)

1. ✅ User documentation (`docs/VECTOR_SEARCH_SUGAR.md`)
2. ✅ Update `docs/SQL_FEATURES_REFERENCE.md`
3. ✅ Add examples to `examples/` directory
4. ✅ Error message improvements
5. ✅ Performance testing

---

## Testing Strategy

### Unit Tests

```python
# test_field_reference.py
def test_parse_field_reference():
    assert parse_field_reference("table.col").table == "table"
    assert parse_field_reference("text") is None  # No dot
    assert parse_field_reference("a.b.c") is None  # Too many parts

# test_embed_parser.py
def test_parse_rvbbit_embed():
    sql = "RVBBIT EMBED t.c USING (SELECT id, text FROM t)"
    stmt = _parse_rvbbit_embed(sql)
    assert stmt.table_name == "t"
    assert stmt.column_name == "c"

# test_vector_search_rewriter.py
def test_rewrite_vector_search():
    sql = "SELECT * FROM VECTOR_SEARCH('q', t.c, 10)"
    result = rewrite_vector_search(sql)
    assert "read_json_auto" in result
    assert "vector_search_json_3" in result
```

### Integration Tests

```python
# test_vector_search_integration.py
def test_embed_and_search_clickhouse():
    # 1. Embed documents
    embed_sql = """
        RVBBIT EMBED docs.content
        USING (SELECT id::VARCHAR AS id, content AS text FROM docs)
    """
    execute(embed_sql)

    # 2. Search
    search_sql = "SELECT * FROM VECTOR_SEARCH('test', docs.content, 5)"
    results = execute(search_sql)
    assert len(results) > 0
    assert 'score' in results.columns
```

### Real-World Tests

```sql
-- Test 1: Embed from CSV
RVBBIT EMBED documents.text
USING (SELECT row_number AS id, content AS text FROM read_csv('docs.csv'))
WITH (backend='clickhouse');

-- Test 2: Search with join
SELECT p.*, vs.score
FROM products p
JOIN VECTOR_SEARCH('eco-friendly', products.description, 10) vs
  ON vs.id = p.id::VARCHAR
WHERE vs.score > 0.7;

-- Test 3: Hybrid search with custom weights
SELECT * FROM HYBRID_SEARCH('Venezuela', bird_line.text, 20, 0.6, 0.9, 0.1)
ORDER BY score DESC;
```

---

## Error Handling

### 1. Missing Required Columns

```sql
RVBBIT EMBED t.c
USING (SELECT content FROM t)  -- Missing 'id'!
```

**Error:**
```
RVBBIT EMBED Error: USING query must return columns:
  - id: VARCHAR (primary key)
  - text: VARCHAR (content to embed)

Your query returns: ['content']
Missing: ['id', 'text']

Hint: Use aliases: SELECT my_id AS id, my_text AS text
```

### 2. Invalid Field Reference

```sql
VECTOR_SEARCH('query', 'not.a.field.ref', 10)
```

**Error:**
```
VECTOR_SEARCH Error: Expected field reference (table.column), got string

Received: 'not.a.field.ref' (string literal)
Expected: table.column (identifier)

Hint: Remove quotes to use field reference syntax
```

### 3. Backend Not Available

```sql
RVBBIT EMBED t.c USING (...) WITH (backend='elastic')
```

**If Elastic not configured:**
```
RVBBIT EMBED Error: Elastic backend not available

Required environment: ELASTICSEARCH_URL
Current: Not set

Available backends: ['clickhouse']
```

---

## Backwards Compatibility

### Existing Calls Still Work

```sql
-- Old syntax (still supported):
SELECT embed_batch('bird_line', 'text', ...)

-- Old vector search (still supported):
SELECT * FROM read_json_auto(vector_search_json_3(...))

-- New sugar (also works):
RVBBIT EMBED bird_line.text USING (...)
SELECT * FROM VECTOR_SEARCH('query', bird_line.text, 10)
```

**No breaking changes!** New syntax is additive.

---

## Future Enhancements

### 1. Automatic id Column Detection

```sql
-- Future: Infer primary key from table metadata
RVBBIT EMBED articles.content
USING (SELECT * FROM articles)  -- Auto-detect 'id' column

-- Current: Must be explicit
RVBBIT EMBED articles.content
USING (SELECT id::VARCHAR AS id, content AS text FROM articles)
```

### 2. Multi-Column Embedding

```sql
-- Embed multiple columns from same table:
RVBBIT EMBED articles.(title, content, summary)
USING (SELECT id::VARCHAR AS id, title, content, summary FROM articles)
```

### 3. Semantic JOIN Sugar

```sql
-- Join tables by semantic similarity:
SELECT a.*, b.*
FROM articles a
SEMANTIC JOIN products b ON a.content ~ b.description
WITH (threshold=0.7)
```

### 4. Streaming Embeddings

```sql
-- Incremental embedding (only new rows):
RVBBIT EMBED articles.content INCREMENTAL
USING (SELECT id::VARCHAR AS id, content AS text FROM articles WHERE embedded_at IS NULL)
```

---

## Summary

**Goal:** Add elegant SQL sugar for embedding and vector search operations

**Approach:**
1. **RVBBIT EMBED** - Follows existing RVBBIT MAP/RUN pattern
2. **VECTOR_SEARCH/HYBRID_SEARCH** - Table functions with field reference syntax
3. **Token-based parsing** - Consistent with unified operator system
4. **Field references** - Natural table.column syntax (IDE-friendly)

**Benefits:**
- Cleaner, more intuitive SQL
- Consistent with RVBBIT syntax patterns
- Token-based (robust)
- Backwards compatible (additive)
- IDE autocomplete for table.column

**Implementation:** 3 sprints (~10-12 hours total)

**Ready to start when you are!** 🚀
