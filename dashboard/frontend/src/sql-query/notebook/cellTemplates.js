/**
 * Cell Templates - Pre-filled code patterns for common operations
 */

export const SQL_TEMPLATES = [
  {
    id: 'blank',
    name: 'Blank',
    description: 'Empty SQL cell',
    code: '-- Enter SQL here\nSELECT 1'
  },
  {
    id: 'select',
    name: 'SELECT Query',
    description: 'Basic select with filtering',
    code: `-- Select data from a table
SELECT *
FROM table_name
WHERE condition = 'value'
LIMIT 100`
  },
  {
    id: 'join',
    name: 'JOIN',
    description: 'Join two tables',
    code: `-- Join tables
SELECT
    a.*,
    b.column_name
FROM table_a a
LEFT JOIN table_b b
    ON a.id = b.a_id
WHERE a.status = 'active'`
  },
  {
    id: 'aggregate',
    name: 'Aggregate',
    description: 'Group by with aggregations',
    code: `-- Aggregate data
SELECT
    category,
    COUNT(*) as count,
    SUM(amount) as total,
    AVG(amount) as average,
    MIN(amount) as min_val,
    MAX(amount) as max_val
FROM table_name
GROUP BY category
ORDER BY total DESC`
  },
  {
    id: 'cte',
    name: 'CTE (WITH)',
    description: 'Common Table Expression',
    code: `-- Use CTEs for complex queries
WITH filtered_data AS (
    SELECT *
    FROM source_table
    WHERE status = 'active'
),
aggregated AS (
    SELECT
        category,
        COUNT(*) as cnt
    FROM filtered_data
    GROUP BY category
)
SELECT *
FROM aggregated
ORDER BY cnt DESC`
  },
  {
    id: 'window',
    name: 'Window Functions',
    description: 'ROW_NUMBER, RANK, LAG/LEAD',
    code: `-- Window functions example
SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY category ORDER BY date DESC) as rn,
    SUM(amount) OVER (PARTITION BY category) as category_total,
    LAG(amount) OVER (ORDER BY date) as prev_amount
FROM table_name`
  },
  {
    id: 'pivot',
    name: 'Pivot',
    description: 'Pivot rows to columns',
    code: `-- Pivot using CASE statements
SELECT
    date,
    SUM(CASE WHEN category = 'A' THEN amount ELSE 0 END) as category_a,
    SUM(CASE WHEN category = 'B' THEN amount ELSE 0 END) as category_b,
    SUM(CASE WHEN category = 'C' THEN amount ELSE 0 END) as category_c
FROM table_name
GROUP BY date
ORDER BY date`
  },
  {
    id: 'ref_prior',
    name: 'Reference Prior Cell',
    description: 'Query output from a previous cell',
    code: `-- Reference prior cell output as temp table
-- Use _cell_name to access materialized results
SELECT *
FROM _previous_cell
WHERE column > 100`
  }
];

export const PYTHON_TEMPLATES = [
  {
    id: 'blank',
    name: 'Blank',
    description: 'Empty Python cell',
    code: `# Access prior cell outputs as DataFrames:
# df = data.cell_name
#
# Set result to a DataFrame or dict:
result = {"message": "Hello"}`
  },
  {
    id: 'transform',
    name: 'DataFrame Transform',
    description: 'Filter, select, add columns',
    code: `# Transform DataFrame
import pandas as pd

# Get data from prior cell
df = data.previous_cell

# Filter rows
df = df[df['status'] == 'active']

# Select columns
df = df[['id', 'name', 'value']]

# Add computed column
df['doubled'] = df['value'] * 2

result = df`
  },
  {
    id: 'aggregate',
    name: 'Aggregate',
    description: 'GroupBy and aggregations',
    code: `# Aggregate data
import pandas as pd

df = data.previous_cell

# Group and aggregate
result = df.groupby('category').agg({
    'amount': ['sum', 'mean', 'count'],
    'date': 'max'
}).reset_index()

# Flatten column names
result.columns = ['_'.join(col).strip('_') for col in result.columns]`
  },
  {
    id: 'pivot',
    name: 'Pivot Table',
    description: 'Create pivot table',
    code: `# Create pivot table
import pandas as pd

df = data.previous_cell

result = pd.pivot_table(
    df,
    values='amount',
    index='date',
    columns='category',
    aggfunc='sum',
    fill_value=0
).reset_index()`
  },
  {
    id: 'merge',
    name: 'Merge DataFrames',
    description: 'Join two cell outputs',
    code: `# Merge DataFrames from prior cells
import pandas as pd

df1 = data.cell_one
df2 = data.cell_two

result = pd.merge(
    df1,
    df2,
    on='id',
    how='left'
)`
  },
  {
    id: 'chart',
    name: 'Create Chart',
    description: 'Generate Plotly chart',
    code: `# Create a chart (returns chart JSON)
import pandas as pd

df = data.previous_cell

# Build chart specification
result = {
    "type": "bar",
    "title": "Chart Title",
    "data": {
        "x": df['category'].tolist(),
        "y": df['value'].tolist()
    }
}`
  },
  {
    id: 'clean',
    name: 'Clean Data',
    description: 'Handle nulls, types, duplicates',
    code: `# Clean and prepare data
import pandas as pd

df = data.previous_cell

# Remove duplicates
df = df.drop_duplicates()

# Handle nulls
df = df.fillna({
    'string_col': 'Unknown',
    'numeric_col': 0
})

# Convert types
df['date'] = pd.to_datetime(df['date_string'])
df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

result = df`
  },
  {
    id: 'summary',
    name: 'Summary Stats',
    description: 'Descriptive statistics',
    code: `# Generate summary statistics
import pandas as pd

df = data.previous_cell

# Get summary
summary = {
    "row_count": len(df),
    "columns": list(df.columns),
    "dtypes": df.dtypes.astype(str).to_dict(),
    "null_counts": df.isnull().sum().to_dict(),
    "numeric_stats": df.describe().to_dict()
}

result = summary`
  }
];

// Combined for easy access
export const TEMPLATES = {
  sql_data: SQL_TEMPLATES,
  python_data: PYTHON_TEMPLATES
};

export default TEMPLATES;
