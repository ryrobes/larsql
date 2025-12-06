from windlass.unified_logs import query_unified
import pandas as pd

test_session = "ui_run_24c50fa853bd"

print(f"=== ANALYZING SESSION: {test_session} ===\n")

# Get all records for this session
df = query_unified(f"session_id = '{test_session}'")
print(f"Total records for parent: {len(df)}")

# Find soundings
soundings = df[df['node_type'] == 'sounding_attempt']
print(f"\nSoundings found: {len(soundings)}")
print(f"Sounding indices: {sorted(soundings['sounding_index'].dropna().unique())}")

# Find sub_cascade_start nodes
sub_cascades = df[df['role'] == 'sub_cascade_start']
print(f"\nSub-cascade starts found: {len(sub_cascades)}")

# Check for child sessions
print(f"\n=== CHECKING FOR CHILD SESSIONS ===")
all_sessions = query_unified("1=1")  # Get all sessions
child_sessions = all_sessions[all_sessions['parent_session_id'] == test_session]
print(f"Child sessions with parent_session_id='{test_session}': {len(child_sessions)}")

if len(child_sessions) > 0:
    print(f"\nChild session IDs:")
    for sid in child_sessions['session_id'].unique():
        count = len(child_sessions[child_sessions['session_id'] == sid])
        print(f"  {sid}: {count} records")
else:
    print("  NO CHILD SESSIONS FOUND!")

# Check for _sub pattern
print(f"\n=== CHECKING FOR '_sub' PATTERN SESSIONS ===")
sub_pattern_sessions = query_unified(f"session_id LIKE '{test_session}%_sub%'")
print(f"Sessions matching '{test_session}%_sub%': {len(sub_pattern_sessions)}")

if len(sub_pattern_sessions) > 0:
    print(f"\nFound session IDs:")
    for sid in sub_pattern_sessions['session_id'].unique():
        count = len(sub_pattern_sessions[sub_pattern_sessions['session_id'] == sid])
        parent = sub_pattern_sessions[sub_pattern_sessions['session_id'] == sid].iloc[0]['parent_session_id']
        print(f"  {sid}: {count} records, parent_session_id={parent}")
