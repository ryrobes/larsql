from windlass.unified_logs import query_unified
import pandas as pd

# Use the test session you're looking at
test_session = "ui_run_803877a75417"

print(f"=== ANALYZING SUB-CASCADES FOR: {test_session} ===\n")

# Get parent records
parent_df = query_unified(f"session_id = '{test_session}'")
print(f"Parent session records: {len(parent_df)}")

# Get all sub-cascade records
sub_df = query_unified(f"session_id LIKE '{test_session}_sub%'")
print(f"\nTotal sub-cascade records: {len(sub_df)}")

# Get unique sub-cascade session IDs
unique_subs = sub_df['session_id'].unique()
print(f"Unique sub-cascade session IDs: {len(unique_subs)}")

for sid in sorted(unique_subs):
    sub_records = sub_df[sub_df['session_id'] == sid]
    sounding_idx = sub_records.iloc[0]['sounding_index']
    parent_sid = sub_records.iloc[0]['parent_session_id']
    print(f"  {sid}: {len(sub_records)} records, sounding_index={sounding_idx}, parent={parent_sid}")

# Check backend query - see what API returns
print("\n\n=== SIMULATING BACKEND QUERY ===")
print("Querying for sub_cascade_start events...")
sub_start_events = parent_df[parent_df['role'] == 'sub_cascade_start']
print(f"sub_cascade_start events in parent: {len(sub_start_events)}")

if len(sub_start_events) > 0:
    print("\nDetails:")
    for idx, row in sub_start_events.iterrows():
        print(f"  Phase: {row['phase_name']}, Sounding: {row['sounding_index']}, Content: {row['content_json'][:50] if row['content_json'] else 'None'}")

# Check if there are duplicate cascade nodes
print("\n\n=== CHECKING FOR DUPLICATE CASCADE NODES ===")
cascade_nodes = sub_df[sub_df['node_type'] == 'cascade']
print(f"Cascade nodes in sub-sessions: {len(cascade_nodes)}")
if len(cascade_nodes) > 0:
    print("\nGrouped by session_id:")
    print(cascade_nodes.groupby('session_id').size())
