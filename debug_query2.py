from windlass.unified_logs import query_unified
import pandas as pd
import json

# Get all records for the session
df = query_unified("session_id LIKE '%3057ef753f16%'")

print("=== SOUNDINGS-RELATED NODES ===")
soundings_df = df[df['node_type'].isin(['soundings', 'sounding_attempt', 'soundings_result', 'evaluator'])]
print(soundings_df[['timestamp_iso', 'node_type', 'session_id', 'parent_session_id', 'trace_id', 'parent_id', 'sounding_index']].to_string())

print("\n\n=== CASCADE NODES ===")
cascade_df = df[df['node_type'] == 'cascade']
print(cascade_df[['timestamp_iso', 'node_type', 'session_id', 'parent_session_id', 'trace_id', 'parent_id', 'cascade_id']].to_string())

print("\n\n=== ALL SESSION IDs in database (checking for child sessions) ===")
# Check if there are ANY sessions with this as parent
all_sessions = query_unified("parent_session_id = 'ui_run_3057ef753f16'")
print(f"Found {len(all_sessions)} records with parent_session_id = 'ui_run_3057ef753f16'")

print("\n\n=== Checking for _sounding_ pattern sessions ===")
sounding_sessions = query_unified("session_id LIKE '%3057ef753f16_sounding_%'")
print(f"Found {len(sounding_sessions)} records with _sounding_ pattern")
if len(sounding_sessions) > 0:
    print(sounding_sessions[['session_id', 'parent_session_id', 'node_type']].head(20).to_string())
