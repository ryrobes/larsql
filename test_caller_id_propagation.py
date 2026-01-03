#!/usr/bin/env python3
"""
Test script to verify caller_id propagation to meta cascades.

Tests that assess_training_confidence and analyze_context_relevance inherit
caller_id from their parent sessions.

Usage:
    python test_caller_id_propagation.py
"""

import os
os.environ['RVBBIT_ROOT'] = '/home/ryanr/repos/rvbbit'

def test_current_state():
    """Check current state of meta cascades in database."""
    from rvbbit.db_adapter import get_db

    db = get_db()

    print("="*70)
    print("CURRENT STATE: Meta Cascades in Database")
    print("="*70)

    query = """
        SELECT
            session_id,
            cascade_id,
            parent_session_id,
            caller_id,
            created_at
        FROM cascade_sessions
        WHERE cascade_id IN ('assess_training_confidence', 'analyze_context_relevance')
        ORDER BY created_at DESC
        LIMIT 10
    """

    results = db.query(query)

    if not results:
        print("\n  ℹ️  No meta cascades found in database yet")
        return

    print(f"\n  Found {len(results)} meta cascade sessions:\n")

    has_caller_id_count = 0
    has_parent_session_count = 0

    for i, row in enumerate(results, 1):
        has_caller = bool(row.get('caller_id'))
        has_parent = bool(row.get('parent_session_id'))

        if has_caller:
            has_caller_id_count += 1
        if has_parent:
            has_parent_session_count += 1

        status = "✅" if (has_caller and has_parent) else "❌"

        print(f"  {i}. {status} {row['session_id'][:30]}")
        print(f"     Cascade: {row['cascade_id']}")
        print(f"     Parent Session: {row['parent_session_id'] or '(empty)'}")
        print(f"     Caller ID: {row['caller_id'] or '(empty)'}")
        print()

    print(f"  Summary:")
    print(f"    Sessions with caller_id:        {has_caller_id_count}/{len(results)}")
    print(f"    Sessions with parent_session:   {has_parent_session_count}/{len(results)}")

    if has_caller_id_count == 0:
        print(f"\n  ❌ PROBLEM: No meta cascades have caller_id!")
        print(f"     Cost rollup to SQL queries will be incomplete.")
    elif has_caller_id_count < len(results):
        print(f"\n  ⚠️  PARTIAL: Some meta cascades missing caller_id")
    else:
        print(f"\n  ✅ SUCCESS: All meta cascades have caller_id!")


def test_parent_lookup():
    """Test that we can lookup caller_id from parent sessions."""
    from rvbbit.db_adapter import get_db

    db = get_db()

    print("\n" + "="*70)
    print("TEST: Can We Trace caller_id via parent_session_id?")
    print("="*70)

    # Find a session with caller_id
    query_with_caller = """
        SELECT session_id, cascade_id, caller_id
        FROM cascade_sessions
        WHERE caller_id != ''
        ORDER BY created_at DESC
        LIMIT 5
    """

    sessions_with_caller = db.query(query_with_caller)

    if not sessions_with_caller:
        print("\n  ℹ️  No sessions with caller_id found (SQL queries not run yet)")
        return

    print(f"\n  Found {len(sessions_with_caller)} sessions with caller_id:\n")

    for row in sessions_with_caller[:3]:
        print(f"  Session: {row['session_id']}")
        print(f"    Cascade: {row['cascade_id']}")
        print(f"    Caller ID: {row['caller_id']}")

        # Check if this session has child sessions
        child_query = f"""
            SELECT session_id, cascade_id, caller_id
            FROM cascade_sessions
            WHERE parent_session_id = '{row['session_id']}'
        """

        children = db.query(child_query)

        if children:
            print(f"    Children: {len(children)}")
            for child in children:
                has_caller = bool(child.get('caller_id'))
                status = "✅" if has_caller else "❌"
                print(f"      {status} {child['cascade_id']}: caller_id={'inherited' if has_caller else 'MISSING'}")
        else:
            print(f"    Children: None")
        print()


def test_cost_rollup_query():
    """Test the SQL query for cost rollup by caller_id."""
    from rvbbit.db_adapter import get_db

    db = get_db()

    print("\n" + "="*70)
    print("TEST: Cost Rollup Query (by caller_id)")
    print("="*70)

    query = """
        SELECT
            caller_id,
            cascade_id,
            COUNT(DISTINCT session_id) as sessions,
            SUM(cost) as total_cost,
            SUM(tokens_in + tokens_out) as total_tokens
        FROM unified_logs
        WHERE caller_id != ''
        GROUP BY caller_id, cascade_id
        ORDER BY caller_id, total_cost DESC
        LIMIT 20
    """

    results = db.query(query)

    if not results:
        print("\n  ℹ️  No logged data with caller_id yet")
        return

    print(f"\n  Found {len(results)} caller_id + cascade combinations:\n")

    # Group by caller_id
    by_caller = {}
    for row in results:
        caller = row['caller_id']
        if caller not in by_caller:
            by_caller[caller] = []
        by_caller[caller].append(row)

    for caller_id, cascades in list(by_caller.items())[:3]:
        print(f"  Caller: {caller_id}")
        total_cost = sum(c['total_cost'] or 0 for c in cascades)
        print(f"  Total Cost: ${total_cost:.6f}")
        print(f"  Cascades:")

        # Check for meta cascades
        has_meta = False
        for cascade in cascades:
            is_meta = cascade['cascade_id'] in ['assess_training_confidence', 'analyze_context_relevance']
            if is_meta:
                has_meta = True

            marker = "  [META]" if is_meta else ""
            cost_val = cascade.get('total_cost') or 0
            print(f"    - {cascade['cascade_id']:40} ${float(cost_val):.6f}{marker}")

        if not has_meta:
            print(f"    ⚠️  No meta cascades found - they may be missing caller_id!")
        else:
            print(f"    ✅ Meta cascades included in rollup!")
        print()


if __name__ == "__main__":
    print("\n")
    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print("║              Caller ID Propagation Test - Meta Cascades                     ║")
    print("╚══════════════════════════════════════════════════════════════════════════════╝")
    print()

    test_current_state()
    test_parent_lookup()
    test_cost_rollup_query()

    print("\n" + "="*70)
    print("VERIFICATION COMPLETE")
    print("="*70)
    print()
    print("Next steps:")
    print("  1. If meta cascades have caller_id ✅ - Fix worked!")
    print("  2. If meta cascades missing caller_id ❌ - Need to run a cascade to test")
    print()
    print("To generate test data:")
    print("  1. rvbbit serve sql --port 15432")
    print("  2. psql postgresql://localhost:15432/default")
    print("  3. Run: SELECT * FROM test WHERE col MEANS 'something' LIMIT 5")
    print("  4. Wait 10 seconds for analytics worker")
    print("  5. Re-run: python test_caller_id_propagation.py")
    print()
