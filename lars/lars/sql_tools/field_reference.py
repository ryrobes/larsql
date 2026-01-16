"""
Field Reference Parser - Extract table.column identifiers from SQL.

Handles dotted SQL identifiers for field-aware operations like:
- LARS EMBED bird_line.text
- VECTOR_SEARCH('query', articles.content, 10)
- HYBRID_SEARCH('query', products.description, 20)

This provides natural SQL syntax with IDE autocomplete support.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional, List

log = logging.getLogger(__name__)


@dataclass
class FieldReference:
    """A parsed table.column reference."""
    table: str       # "bird_line"
    column: str      # "text"
    full_ref: str    # "bird_line.text"

    @property
    def metadata_key(self) -> str:
        """
        Key for metadata.column_name filtering in vector search.

        When a table has multiple embedded columns (title, description, content),
        we filter by column_name to ensure we only search the requested column.
        """
        return self.column

    def __str__(self):
        return self.full_ref


def parse_field_reference(identifier: str) -> Optional[FieldReference]:
    """
    Parse a dotted identifier into table and column components.

    Args:
        identifier: String like "bird_line.text" or "users.email"

    Returns:
        FieldReference if valid dotted identifier, None otherwise

    Examples:
        >>> ref = parse_field_reference("bird_line.text")
        >>> ref.table
        'bird_line'
        >>> ref.column
        'text'

        >>> parse_field_reference("text")  # No dot - not a field ref
        None

        >>> parse_field_reference("db.schema.table.col")  # Too many parts
        None
    """
    identifier = identifier.strip()

    # Must contain exactly one dot
    if '.' not in identifier:
        return None

    parts = identifier.split('.')
    if len(parts) != 2:
        # Future: could support schema.table.column (3 parts)
        log.debug(f"Field reference has {len(parts)} parts, expected 2: {identifier}")
        return None

    table, column = parts

    # Validate SQL identifier format (letters, numbers, underscores only)
    # Must start with letter or underscore
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
        log.debug(f"Invalid table name in field reference: {table}")
        return None

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column):
        log.debug(f"Invalid column name in field reference: {column}")
        return None

    return FieldReference(
        table=table,
        column=column,
        full_ref=identifier
    )


def is_field_reference(identifier: str) -> bool:
    """
    Quick check if identifier looks like a field reference.

    Args:
        identifier: String to check

    Returns:
        True if it's a valid table.column reference
    """
    return parse_field_reference(identifier) is not None


def extract_field_refs_from_sql(sql: str) -> List[FieldReference]:
    """
    Extract all field references from SQL query.

    Finds all table.column patterns that look like field references.

    Args:
        sql: SQL query

    Returns:
        List of FieldReference objects found

    Example:
        >>> sql = "SELECT * FROM VECTOR_SEARCH('q', bird_line.text, 10)"
        >>> refs = extract_field_refs_from_sql(sql)
        >>> refs[0].table
        'bird_line'
    """
    # Pattern: word.word (valid SQL identifiers)
    pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b'

    refs = []
    for match in re.finditer(pattern, sql):
        table = match.group(1)
        column = match.group(2)
        full_ref = f"{table}.{column}"

        ref = FieldReference(
            table=table,
            column=column,
            full_ref=full_ref
        )
        refs.append(ref)

    return refs


def validate_field_reference(field_ref: str, context: str = "field reference") -> FieldReference:
    """
    Validate and parse a field reference, raising error if invalid.

    Args:
        field_ref: Field reference string
        context: Context for error message (e.g., "LARS EMBED")

    Returns:
        FieldReference if valid

    Raises:
        ValueError: If field reference is invalid

    Example:
        >>> ref = validate_field_reference("bird_line.text", "LARS EMBED")
        >>> ref.table
        'bird_line'
    """
    ref = parse_field_reference(field_ref)

    if ref is None:
        raise ValueError(
            f"{context} Error: Invalid field reference: '{field_ref}'\n"
            f"\n"
            f"Expected format: table.column (e.g., bird_line.text)\n"
            f"Got: '{field_ref}'\n"
            f"\n"
            f"Valid examples:\n"
            f"  - articles.content\n"
            f"  - products.description\n"
            f"  - users.email\n"
        )

    return ref


# ============================================================================
# Testing & Examples
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("FIELD REFERENCE PARSER TEST")
    print("=" * 80)

    test_cases = [
        ("bird_line.text", True),
        ("articles.content", True),
        ("users.email", True),
        ("text", False),  # No dot
        ("table", False),  # No dot
        ("db.schema.table.col", False),  # Too many parts
        ("table.column.extra", False),  # Too many parts
        ("123table.col", False),  # Invalid table name (starts with number)
        ("table.123col", False),  # Invalid column name (starts with number)
        ("valid_table.valid_col_123", True),  # Valid with underscores/numbers
    ]

    passed = 0
    failed = 0

    for identifier, should_parse in test_cases:
        ref = parse_field_reference(identifier)
        success = (ref is not None)

        if success == should_parse:
            status = "[OK] PASS"
            passed += 1
        else:
            status = "[ERR] FAIL"
            failed += 1

        print(f"\n{status} - {identifier}")
        if ref:
            print(f"  Table: {ref.table}, Column: {ref.column}")

    print("\n" + "=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)

    # Test extraction from SQL
    print("\n[TEST: Extract from SQL]")
    sql = "SELECT * FROM VECTOR_SEARCH('query', bird_line.text, 10) WHERE articles.title MEANS 'x'"
    refs = extract_field_refs_from_sql(sql)
    print(f"SQL: {sql}")
    print(f"Found {len(refs)} field references:")
    for ref in refs:
        print(f"  - {ref.full_ref} (table={ref.table}, column={ref.column})")
