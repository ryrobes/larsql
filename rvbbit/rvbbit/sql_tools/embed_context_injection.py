"""
Smart context injection for EMBED() operator.

When users write:
    SELECT id, EMBED(description) FROM products;

We rewrite to:
    SELECT id, semantic_embed_with_storage(description, 'products', CAST(id AS VARCHAR)) FROM products;

This allows the cascade to:
1. Generate the embedding (via Agent.embed)
2. Store it in rvbbit_embeddings with proper table/ID association
3. VECTOR_SEARCH can then find these embeddings

This is MUCH better than competitors (PostgresML, pgvector) which require:
- Manual schema changes (ALTER TABLE ADD COLUMN)
- Explicit UPDATE statements
- Offline batch scripts

With RVBBIT, it's pure SQL and automatic!

Architecture:
    SQL: SELECT id, EMBED(description) FROM products
        ↓
    Rewriter detects:
        - FROM clause: 'products' table
        - Primary key: 'id' column
        ↓
    Rewrites to: semantic_embed_with_storage(description, 'products', CAST(id AS VARCHAR))
        ↓
    Cascade: Generates embedding AND stores with table/ID
        ↓
    VECTOR_SEARCH: Finds embeddings in rvbbit_embeddings table
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def detect_table_and_id_column(query: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Detect table name and ID column from query.

    Strategies:
    1. FROM clause: Look for simple "FROM table_name"
    2. ID column: Look for columns named 'id', or first column in SELECT list

    Args:
        query: SQL query

    Returns:
        (table_name, id_column) tuple

    Examples:
        >>> detect_table_and_id_column("SELECT id, EMBED(text) FROM products")
        ('products', 'id')

        >>> detect_table_and_id_column("SELECT product_id, EMBED(desc) FROM catalog")
        ('catalog', 'product_id')
    """
    # Strategy 1: Extract FROM clause
    # Pattern: FROM table_name (with optional alias)
    from_match = re.search(r'\bFROM\s+(\w+)', query, re.IGNORECASE)
    if not from_match:
        return (None, None)

    table_name = from_match.group(1)

    # Strategy 2: Find ID column
    # Pattern 1: Look for column named 'id' or '*_id' in SELECT list
    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', query, re.IGNORECASE | re.DOTALL)
    if select_match:
        select_list = select_match.group(1)

        # Look for 'id' or '*_id' columns
        id_patterns = [
            r'\bid\b',           # Just 'id'
            r'\b(\w+_id)\b',     # product_id, customer_id, etc.
            r'\b(id_\w+)\b',     # id_product, id_customer, etc.
        ]

        for pattern in id_patterns:
            id_match = re.search(pattern, select_list, re.IGNORECASE)
            if id_match:
                id_col = id_match.group(0) if pattern == r'\bid\b' else id_match.group(1)
                return (table_name, id_col.strip())

        # Fallback: Use first column in SELECT list
        first_col = select_list.split(',')[0].strip()
        # Remove any AS alias
        first_col = re.sub(r'\s+AS\s+\w+', '', first_col, flags=re.IGNORECASE).strip()
        return (table_name, first_col)

    return (table_name, None)


def inject_embed_context(query: str) -> str:
    """
    Inject table and ID context into EMBED() calls.

    Transforms:
        SELECT id, EMBED(description) FROM products
    To:
        SELECT id, semantic_embed_with_storage(description, 'products', CAST(id AS VARCHAR)) FROM products

    This allows the cascade to store embeddings with proper table/ID association.

    Args:
        query: SQL query with EMBED() calls

    Returns:
        Query with context-injected EMBED() calls

    Note:
        Only injects if we can detect both table name AND ID column.
        Otherwise, falls back to regular EMBED() (generates but doesn't store).
    """
    if 'EMBED(' not in query.upper():
        return query

    # Detect table and ID column
    table_name, id_col = detect_table_and_id_column(query)

    if not table_name or not id_col:
        # Can't inject context - use regular EMBED
        logger.debug(f"Could not detect table/ID for EMBED context injection (table={table_name}, id={id_col})")
        return query

    logger.debug(f"Injecting EMBED context: table={table_name}, id_col={id_col}")

    # Pattern: EMBED(column) or EMBED(column, 'model')
    # Rewrite to: semantic_embed_with_storage(column, 'table', CAST(id AS VARCHAR))
    # or: semantic_embed_with_storage(column, 'model', 'table', CAST(id AS VARCHAR))

    def replace_embed(match):
        # Extract arguments from EMBED(...)
        args = match.group(1)

        # Count commas to determine if model is specified
        arg_parts = [a.strip() for a in args.split(',')]

        if len(arg_parts) == 1:
            # EMBED(column_name) → semantic_embed_with_storage(column, NULL, 'table', 'column', id)
            column_arg = arg_parts[0]
            # Extract bare column name (strip table prefix if present: p.description → description)
            column_name = column_arg.split('.')[-1] if '.' in column_arg else column_arg
            return f"semantic_embed_with_storage({column_arg}, NULL, '{table_name}', '{column_name}', CAST({id_col} AS VARCHAR))"
        elif len(arg_parts) == 2:
            # EMBED(column, 'model') → semantic_embed_with_storage(column, 'model', 'table', 'column', id)
            column_arg = arg_parts[0]
            model_arg = arg_parts[1]
            column_name = column_arg.split('.')[-1] if '.' in column_arg else column_arg
            return f"semantic_embed_with_storage({column_arg}, {model_arg}, '{table_name}', '{column_name}', CAST({id_col} AS VARCHAR))"
        else:
            # Unexpected - just keep original
            return match.group(0)

    # Replace all EMBED() calls
    result = re.sub(r'\bEMBED\s*\((.*?)\)', replace_embed, query, flags=re.IGNORECASE)

    if result != query:
        logger.debug(f"Injected context into EMBED() calls: table={table_name}, id={id_col}")

    return result
