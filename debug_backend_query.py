from windlass.unified_logs import query_unified
import pandas as pd

test_session = "ui_run_803877a75417"

print("=== SIMULATING BACKEND CASCADE-INSTANCES QUERY ===\n")

# Get all sessions for this cascade (parent + children)
cascade_id = "context_demo_parent"

# Query all sessions for this cascade
all_sessions_df = query_unified(f"cascade_id = '{cascade_id}'")
print(f"Total records for cascade '{cascade_id}': {len(all_sessions_df)}")

# Get unique session_ids
unique_sessions = all_sessions_df['session_id'].unique()
print(f"\nUnique session IDs: {len(unique_sessions)}")
for sid in sorted(unique_sessions):
    session_records = all_sessions_df[all_sessions_df['session_id'] == sid]
    parent_sid = session_records.iloc[0]['parent_session_id']
    depth = 1 if parent_sid and parent_sid != '' else 0
    print(f"  {sid}: depth={depth}, parent={parent_sid}, {len(session_records)} records")

# Simulate the backend's depth calculation
print("\n\n=== DEPTH CALCULATION (as backend would do) ===")
for sid in sorted(unique_sessions):
    session_records = all_sessions_df[all_sessions_df['session_id'] == sid]

    # Backend logic: find parent_session_id from ANY row
    parent_session_id = None
    for idx, r in session_records.iterrows():
        if r['parent_session_id'] and r['parent_session_id'] != '':
            parent_session_id = r['parent_session_id']
            break

    depth = 1 if parent_session_id else 0
    instance_type = "CHILD" if depth > 0 else "PARENT"
    print(f"  {sid}: {instance_type} (depth={depth})")

# Check if backend would create separate instances for each cascade node
print("\n\n=== CHECKING CASCADE NODES (potential duplicate triggers) ===")
cascade_nodes = all_sessions_df[all_sessions_df['node_type'] == 'cascade']
print(f"Cascade nodes: {len(cascade_nodes)}")
print("\nGrouped by session_id:")
grouped = cascade_nodes.groupby('session_id').size()
for sid, count in grouped.items():
    print(f"  {sid}: {count} cascade nodes")
