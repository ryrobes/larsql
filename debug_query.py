from windlass.unified_logs import query_unified
import pandas as pd

# Get all records for the session
df = query_unified("session_id LIKE '%3057ef753f16%'")
print(f'Total records: {len(df)}')
print('\nUnique session IDs:')
for sid in df['session_id'].unique():
    print(f'  {sid}')
print('\nNode types:')
print(df['node_type'].value_counts())
print('\nParent session IDs:')
for psid in df['parent_session_id'].unique():
    print(f'  {psid}')
print('\nCascade IDs:')
print(df['cascade_id'].value_counts())
