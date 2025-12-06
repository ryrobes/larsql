from windlass.unified_logs import query_unified
import pandas as pd
import json

test_session = "ui_run_3f2f23ead966"

print(f"=== ANALYZING PARENT SESSION: {test_session} ===\n")

# Get parent session records
parent_records = query_unified(f"session_id = '{test_session}'")
print(f"Parent session records: {len(parent_records)}")
print(f"Parent session's parent_session_id values: {parent_records['parent_session_id'].unique()}")

# Get cascade_sounding_attempt metadata
cascade_sounding_attempts = query_unified(f"session_id = '{test_session}' AND node_type = 'cascade_sounding_attempt'")
print(f"\nCascade sounding attempts: {len(cascade_sounding_attempts)}")

# Check each child session
for idx, row in cascade_sounding_attempts.iterrows():
    metadata = json.loads(row['metadata_json'])
    sub_session_id = metadata.get('sub_session_id')

    print(f"\n--- Sounding {row['sounding_index']} ---")
    print(f"  Parent metadata says sub_session_id: {sub_session_id}")

    # Get child session records
    child_records = query_unified(f"session_id = '{sub_session_id}'")
    print(f"  Child session records: {len(child_records)}")

    if len(child_records) > 0:
        # Check what parent_session_id values exist
        parent_session_ids = child_records['parent_session_id'].unique()
        print(f"  Child's parent_session_id values: {parent_session_ids}")

        # Check a few specific node types
        cascade_nodes = child_records[child_records['node_type'] == 'cascade']
        if len(cascade_nodes) > 0:
            print(f"  Cascade nodes parent_session_id: {cascade_nodes['parent_session_id'].unique()}")

        phase_nodes = child_records[child_records['node_type'] == 'phase']
        if len(phase_nodes) > 0:
            print(f"  Phase nodes parent_session_id: {phase_nodes['parent_session_id'].unique()}")

print("\n\n=== CHECKING HOW VALIDATORS WORK (for comparison) ===")
# Find sessions with validators to see how they properly set parent_session_id
validator_sessions = query_unified("cascade_id LIKE '%validator%' OR cascade_id LIKE '%ward%' LIMIT 10")
if len(validator_sessions) > 0:
    print(f"\nFound {len(validator_sessions)} validator-related records")
    print("Sample validator sessions with parent relationships:")
    validator_with_parent = validator_sessions[validator_sessions['parent_session_id'].notna()]
    if len(validator_with_parent) > 0:
        print(validator_with_parent[['session_id', 'parent_session_id', 'cascade_id', 'node_type']].head(5).to_string())
    else:
        print("No validator records with parent_session_id found")
