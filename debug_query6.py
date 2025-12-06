from windlass.unified_logs import query_unified
import pandas as pd

# Check the parent_session_id for child cascade records
child_session_id = "ui_run_3f2f23ead966_sounding_0"
print(f"=== CHECKING CHILD SESSION: {child_session_id} ===\n")

child_records = query_unified(f"session_id = '{child_session_id}'")
print(f"Total records: {len(child_records)}")
print(f"\nParent session IDs:")
print(child_records['parent_session_id'].value_counts())

print(f"\nNode types:")
print(child_records['node_type'].value_counts())

print(f"\nSample records:")
print(child_records[['session_id', 'parent_session_id', 'node_type', 'cascade_id', 'phase_name']].head(10).to_string())
