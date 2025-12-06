from windlass.unified_logs import query_unified
import pandas as pd
import json

# Get cascade_sounding_attempt nodes and check metadata
df = query_unified("session_id = 'ui_run_3f2f23ead966' AND node_type = 'cascade_sounding_attempt'")

print("=== CASCADE SOUNDING ATTEMPT METADATA ===")
for idx, row in df.iterrows():
    print(f"\nSounding {row['sounding_index']}:")
    print(f"  session_id: {row['session_id']}")
    print(f"  parent_session_id: {row['parent_session_id']}")

    if row['metadata_json']:
        try:
            metadata = json.loads(row['metadata_json'])
            print(f"  Metadata keys: {list(metadata.keys())}")
            if 'sub_session_id' in metadata:
                print(f"  sub_session_id: {metadata['sub_session_id']}")

                # Check if there are records for this sub_session_id
                sub_session_id = metadata['sub_session_id']
                child_records = query_unified(f"session_id = '{sub_session_id}'")
                print(f"  Records with session_id={sub_session_id}: {len(child_records)}")

                if len(child_records) > 0:
                    print(f"    Node types: {child_records['node_type'].value_counts().to_dict()}")
                else:
                    print(f"    NO RECORDS FOUND FOR {sub_session_id} - This is the bug!")
            else:
                print(f"  NO sub_session_id in metadata!")

            print(f"  Full metadata: {json.dumps(metadata, indent=4)}")
        except Exception as e:
            print(f"  Error parsing metadata: {e}")
