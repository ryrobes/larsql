#!/usr/bin/env python3
"""
Backfill tool call content_type with proper sub-types.

Finds rows that contain tool calls in content_json and updates their
content_type to 'tool_call:<tool_name>'.

Usage:
    python scripts/backfill_tool_calls.py [--dry-run]
"""

import argparse
import sys
import os

# Add lars to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lars.db_adapter import get_db
from lars.content_classifier import _extract_tool_call_from_text


def backfill_tool_calls(dry_run: bool = False):
    """Find and update tool call content types."""
    db = get_db()

    # Find all rows that likely contain tool calls
    # (have "tool" and "arguments" in content_json)
    # Note: content_json stores escaped JSON, so we search for \\"tool\\"
    query = """
        SELECT message_id, content_json, content_type
        FROM unified_logs
        WHERE position(content_json, 'tool') > 0
          AND position(content_json, 'arguments') > 0
          AND role = 'assistant'
    """

    rows = db.query(query)
    print(f"Found {len(rows)} potential tool call rows")

    updates = []
    for row in rows:
        message_id = row['message_id']
        content_json = row.get('content_json', '')
        current_type = row.get('content_type', 'text')

        # Parse the JSON string to get actual content
        if content_json:
            import json
            try:
                content = json.loads(content_json) if isinstance(content_json, str) else content_json
                if isinstance(content, str):
                    # Content is a string, check for embedded tool call
                    tool_call = _extract_tool_call_from_text(content)
                    if tool_call:
                        tool_name = tool_call.get('tool', 'unknown')
                        new_type = f'tool_call:{tool_name}'
                        if new_type != current_type:
                            updates.append((message_id, new_type, current_type))
            except json.JSONDecodeError:
                # Try direct extraction from the JSON string itself
                tool_call = _extract_tool_call_from_text(content_json)
                if tool_call:
                    tool_name = tool_call.get('tool', 'unknown')
                    new_type = f'tool_call:{tool_name}'
                    if new_type != current_type:
                        updates.append((message_id, new_type, current_type))

    print(f"Found {len(updates)} rows to update")

    # Group by new content_type for summary
    type_counts = {}
    for _, new_type, old_type in updates:
        key = f"{old_type} -> {new_type}"
        type_counts[key] = type_counts.get(key, 0) + 1

    print("\nUpdates by type:")
    for key, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {key}: {count}")

    if dry_run:
        print("\n[DRY RUN] No changes made")
        return

    # Apply updates
    print(f"\nApplying {len(updates)} updates...")
    for message_id, new_type, _ in updates:
        update_query = f"""
            ALTER TABLE unified_logs
            UPDATE content_type = '{new_type}'
            WHERE message_id = '{message_id}'
        """
        try:
            db.execute(update_query)
        except Exception as e:
            print(f"  Error updating {message_id}: {e}")

    print("Done!")

    # Verify
    verify_query = """
        SELECT content_type, count(*) as cnt
        FROM unified_logs
        WHERE role = 'assistant' AND cost > 0
        GROUP BY content_type
        ORDER BY cnt DESC
    """
    result = db.query(verify_query)
    print("\nFinal content type distribution:")
    for row in result:
        print(f"  {row['content_type']}: {row['cnt']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill tool call content types')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    args = parser.parse_args()

    backfill_tool_calls(dry_run=args.dry_run)
