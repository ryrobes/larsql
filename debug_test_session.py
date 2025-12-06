from windlass.unified_logs import query_unified
import pandas as pd

test_session = "ui_run_803877a75417"

print(f"=== ANALYZING SESSION: {test_session} ===\n")

# Get all records for this session
df = query_unified(f"session_id = '{test_session}'")
print(f"Total records for parent: {len(df)}")

# Check sounding-related records
print("\n=== SOUNDING-RELATED RECORDS ===")
soundings = df[df['sounding_index'].notna()]
print(f"Records with sounding_index: {len(soundings)}")

if len(soundings) > 0:
    print("\nSounding index distribution:")
    print(soundings['sounding_index'].value_counts().sort_index())

    print("\nNode types with sounding_index:")
    print(soundings.groupby(['node_type', 'sounding_index']).size())

# Check for sub-cascades
print("\n=== SUB-CASCADE RECORDS ===")
sub_cascades = query_unified(f"session_id LIKE '{test_session}%_sub%'")
print(f"Sub-cascade records: {len(sub_cascades)}")

if len(sub_cascades) > 0:
    print("\nSub-cascade session IDs:")
    for sid in sorted(sub_cascades['session_id'].unique()):
        count = len(sub_cascades[sub_cascades['session_id'] == sid])
        sounding_idx = sub_cascades[sub_cascades['session_id'] == sid].iloc[0]['sounding_index']
        parent = sub_cascades[sub_cascades['session_id'] == sid].iloc[0]['parent_session_id']
        print(f"  {sid}: {count} records, sounding_index={sounding_idx}, parent={parent}")

# Check for duplicate entries
print("\n=== CHECKING FOR DUPLICATES ===")
node_counts = df.groupby('node_type').size().sort_values(ascending=False)
print("\nNode type counts:")
print(node_counts.head(10))

# Look at sounding_attempt nodes specifically
sounding_attempts = df[df['node_type'] == 'sounding_attempt']
print(f"\nSounding attempts: {len(sounding_attempts)}")
if len(sounding_attempts) > 0:
    print("\nSounding attempts details:")
    print(sounding_attempts[['sounding_index', 'is_winner', 'trace_id', 'cost']].to_string())
