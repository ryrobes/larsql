from windlass.unified_logs import query_unified
import pandas as pd

test_session = "ui_run_803877a75417"

print(f"=== CHECKING CHILD CASCADE IDs ===\n")

# Get the 3 sub-cascade sessions
sub_sessions = [
    f"{test_session}_sub_0",
    f"{test_session}_sub_1",
    f"{test_session}_sub_2"
]

for sub_sid in sub_sessions:
    sub_df = query_unified(f"session_id = '{sub_sid}'")
    if len(sub_df) > 0:
        cascade_id = sub_df.iloc[0]['cascade_id']
        parent_sid = sub_df.iloc[0]['parent_session_id']
        print(f"{sub_sid}:")
        print(f"  cascade_id: {cascade_id}")
        print(f"  parent_session_id: {parent_sid}")
        print(f"  records: {len(sub_df)}")
        print()
