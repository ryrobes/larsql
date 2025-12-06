from windlass.unified_logs import query_unified
import pandas as pd

# Search for cascade-level soundings (should have cascade_soundings node type)
print("=== SEARCHING FOR CASCADE-LEVEL SOUNDINGS ===")
cascade_soundings = query_unified("node_type = 'cascade_soundings' OR node_type = 'cascade_sounding_attempt'")
print(f"Found {len(cascade_soundings)} cascade_soundings records")

if len(cascade_soundings) > 0:
    print("\nCascade soundings sessions:")
    print(cascade_soundings[['session_id', 'parent_session_id', 'node_type', 'sounding_index']].to_string())

    # Pick one session to analyze
    if len(cascade_soundings) > 0:
        test_session = cascade_soundings.iloc[0]['session_id']
        print(f"\n\n=== ANALYZING SESSION: {test_session} ===")

        # Check for child sessions
        print("\nLooking for child sessions with parent_session_id =", test_session)
        children = query_unified(f"parent_session_id = '{test_session}'")
        print(f"Found {len(children)} child records")

        if len(children) > 0:
            print("\nChild session IDs:")
            print(children['session_id'].unique())
        else:
            print("NO CHILD SESSIONS FOUND - This is the bug!")
else:
    print("\nNo cascade_soundings found in database. Let me search for recent sessions:")
    recent = query_unified("cascade_id = 'multi_approach_problem_solver' LIMIT 5")
    print(f"Found {len(recent)} records with cascade_id = 'multi_approach_problem_solver'")
    if len(recent) > 0:
        print("\nSession IDs:")
        print(recent['session_id'].unique())
