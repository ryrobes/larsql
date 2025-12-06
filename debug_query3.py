from windlass.unified_logs import query_unified
import pandas as pd
import json

# Get sounding_attempt nodes to see if they have sub_session_id metadata
df = query_unified("session_id LIKE '%3057ef753f16%' AND node_type = 'sounding_attempt'")

print("=== SOUNDING ATTEMPT NODES ===")
print(df[['session_id', 'parent_session_id', 'sounding_index', 'node_type', 'metadata_json']].to_string())

print("\n\n=== METADATA DETAILS ===")
for idx, row in df.iterrows():
    print(f"\nSounding {row['sounding_index']}:")
    if row['metadata_json']:
        try:
            metadata = json.loads(row['metadata_json'])
            print(f"  Metadata keys: {metadata.keys()}")
            if 'sub_session_id' in metadata:
                print(f"  sub_session_id: {metadata['sub_session_id']}")
            print(f"  Full metadata: {json.dumps(metadata, indent=2)}")
        except:
            print(f"  Raw metadata: {row['metadata_json']}")

# Check if there are ANY records at all with those session IDs
print("\n\n=== CHECKING FOR CHILD SESSION RECORDS ===")
for i in range(3):
    child_session = f"ui_run_3057ef753f16_sounding_{i}"
    child_records = query_unified(f"session_id = '{child_session}'")
    print(f"\nRecords for {child_session}: {len(child_records)}")
    if len(child_records) > 0:
        print(child_records[['session_id', 'parent_session_id', 'node_type', 'phase_name']].head().to_string())
