# Hyper SQL Client


Hyper is LARS's built-in SQL client, integrated directly into Studio. While LARS exposes a standard
  PostgreSQL wire protocol — letting you use any SQL client like DBeaver, DataGrip, or psql — Hyper
  provides a zero-install, tightly integrated experience with features purpose-built for semantic SQL.
On This Page
- [Overview](#overview)
- [Getting Started](#getting-started)
- [SQL Editor](#sql-editor)
- [Dashboard Panels](#dashboard-panels)
- [Interactive Parameters](#interactive-parameters)
- [Chart Visualization](#chart-visualization)
- [Explain Plans & Cost Tracking](#explain-plans)
- [AI Dashboard Builder](#ai-dashboard-builder)
- [Tabs & File Management](#tabs-files)
- [Capture & Annotate](#capture-annotate)
- [Panel Types Reference](#panel-types)
- [Keyboard Shortcuts](#keyboard-shortcuts)


## Overview


Hyper is not a replacement for your favorite SQL client — it's a complement. Use DBeaver or DataGrip
  for schema browsing, migrations, and traditional database work. Use Hyper when you want to:

- **Build interactive dashboards** with pure SQL — no JavaScript, no React, no build step
- **Visualize explain plans** with cost estimates before running queries
- **Track actual LLM costs** per query in real time
- **Use AI to generate dashboards** from screenshots and voice descriptions
- **Iterate quickly** on semantic SQL with live panel previews

Hyper runs inside Studio's sidebar as the **ℓ** view (accessible from the left navigation).


## Getting Started


1. Launch Studio (`lars studio`)
2. Click the **ℓ** icon in the left sidebar
3. Start writing SQL in the Monaco-powered editor
4. Press **Ctrl+Enter** (or **⌘+Enter** on Mac) to execute

The editor comes pre-loaded with a sample interactive dashboard demonstrating panels, charts,
and parameter binding.


## SQL Editor


Hyper uses [Monaco Editor](https://microsoft.github.io/monaco-editor/) — the same editor that
powers VS Code — with LARS-specific enhancements:

- **Syntax highlighting** for SQL with semantic operator awareness
- **Auto-explain** — as you type, Hyper estimates cost and shows explain plans inline
- **Gutter icons** — color-coded cost tier indicators appear next to each query block
- **Ghost text** — estimated and actual costs appear as inline decorations
- **Multi-query support** — write multiple queries separated by semicolons; each gets its own panel
- **Database selector** — switch between connected databases from the toolbar


## Dashboard Panels


Hyper's signature feature is **SQL-native dashboards**. Instead of writing JavaScript to create charts,
you embed layout and visualization metadata directly in your SQL using special comment directives.

### Panel Syntax

```sql
--- PANEL 'Panel Title' (col, row, colspan, rowspan) [OPTIONS]
SELECT ... ;
```

- **Title** — displayed as the panel header
- **Position** — `(col, row)` places the panel on a grid; `(col, row, colspan, rowspan)` controls size
- **Options** — `HIDE_TITLE`, `HIDE_BORDER`, `ON_SELECT ...`

### Setup SQL with PASS INTO

Use `THEN PASS INTO` to materialize intermediate results that multiple panels can reference:

```sql
SELECT * FROM sales_data
WHERE year = 2024
 THEN PASS INTO shared_data;

--- PANEL 'By Region' (1, 1, 1, 1)
SELECT region, SUM(revenue) as total
FROM into_shared_data GROUP BY region;

--- PANEL 'By Month' (2, 1, 1, 1)
SELECT month, SUM(revenue) as total
FROM into_shared_data GROUP BY month;
```

The setup SQL runs once, then each panel query runs in parallel against the materialized result.

> For full documentation on `INTO` — including per-stage materialization, lifecycle, storage details,
> and the `into_*` naming convention — see [Persistence & Materialization](persistence.html).

### Dashboard Naming

Name your dashboard with the `--- HYPER` directive:

```sql
--- HYPER 'Sales Dashboard'
-- Your queries here...
```

This name appears as the tab title.


## Interactive Parameters


Panels can be interactive — clicking a chart element sets a parameter that filters other panels.

### Single Select (ON_SELECT)

```sql
--- PANEL 'Categories' (1, 1) ON_SELECT @param_set('cat', category)
SELECT category, COUNT(*) as count
FROM products GROUP BY category;

--- PANEL 'Filtered Products' (2, 1)
SELECT name, price FROM products
WHERE (CASE WHEN @param_get('cat') IS NULL
  THEN true ELSE category = @param_get('cat') END);
```

Click a row in "Categories" to filter "Filtered Products". Click again to deselect.

### Multi Select (ON_SELECT[])

```sql
--- PANEL 'Departments' (1, 1) ON_SELECT[] @params_set('depts', dept)
SELECT dept, COUNT(*) FROM employees GROUP BY dept;
```

The `[]` suffix enables checkbox-style multi-select.

### Parameter Functions

| Function | Description |
|----------|-------------|
| `@param_set('key', field)` | Set a single-value parameter from the clicked row |
| `@params_set('key', field)` | Append/remove from a multi-value parameter |
| `@param_get('key')` | Retrieve the current parameter value in a query |
| `@param_clear('key')` | Clear a parameter value |


## Chart Visualization


Hyper supports multiple chart libraries through SQL-native configuration. Return `format` and `config`
columns to control visualization:

### Vega-Lite Charts

```sql
--- PANEL 'Revenue Trend' (1, 1)
SELECT
  'vega-lite' as format,
  {mark: 'line', x: 'month', y: 'revenue', title: 'Monthly Revenue'} as config,
  month, SUM(revenue) as revenue
FROM sales GROUP BY month;
```

### Plotly Charts

```sql
--- PANEL 'Market Share' (1, 1)
SELECT
  'plotly' as format,
  {type: 'pie', values: 'total', labels: 'category'} as config,
  category, SUM(revenue) as total
FROM sales GROUP BY category;
```

### Supported Format Types

| Format | Description |
|--------|-------------|
| `vega-lite` | Declarative charts (bar, line, area, scatter, etc.) |
| `plotly` | Interactive charts (pie, scatter, 3D, etc.) |
| `metric` | Single-value KPI display |
| `sparkline` | Inline mini-charts |
| `markdown` | Rendered Markdown content |
| `mermaid` | Mermaid diagram rendering |
| `image` | Image display from URLs |
| `text` | Plain text display |

If no `format` column is returned, the panel defaults to a **data grid** — a sortable, filterable table.


## Explain Plans & Cost Tracking


Hyper provides rich explain plan visualization that goes beyond traditional `EXPLAIN`:

### Auto-Explain

As you type, Hyper automatically runs an explain plan in the background (debounced at 300ms).
The results appear as:

- **Gutter icons** — color-coded by cost tier (green = cheap, red = expensive)
- **Ghost text** — estimated cost appears inline after each query
- **Hover tooltips** — hover gutter icons for detailed operation breakdown

### Cost Tiers

| Tier | Cost Range | Icon |
|------|-----------|------|
| Zero | $0 | No LLM calls |
| Free | < $0.001 | Negligible cost |
| Low | < $0.01 | Basic operations |
| Moderate | < $0.10 | Multi-step pipelines |
| High | < $1.00 | Complex operations |
| Very High | > $1.00 | Use with caution |

### Actual Cost Tracking

After execution, Hyper polls for actual costs from the unified log and updates the display:

```
Estimated: $0.0023  →  Actual: $0.0019
```

The **Cost Analysis Dashboard** (available as a system tab) provides a detailed breakdown of
costs across all executed queries.

### Explain Preview Panel

Before execution, each panel shows a skeleton preview with:

- Estimated cost and cost tier
- Number of LLM calls required
- Operation breakdown with row count estimates
- Cache hit rates
- Model information


## AI Dashboard Builder


Hyper includes an AI-powered dashboard generator that creates SQL dashboards from natural language.

### How It Works

1. **Hold Spacebar** to enter capture mode
2. **Speak** your description (audio is transcribed)
3. **Draw** annotations on screen to highlight areas of interest
4. **Release Spacebar** — a screenshot with your annotations is captured
5. **Review** the screenshot and transcript in the Intent Review modal
6. **Submit** — LARS generates a complete SQL dashboard

The generated SQL uses Hyper's panel syntax with charts, parameters, and layout — ready to execute.

### Intent Review Modal

Before generating, you can:

- Edit the transcribed text
- Add additional drawing annotations
- Include current panel data for context
- Review the full screenshot


## Tabs & File Management


### Tabs

Hyper supports multiple concurrent workspaces via tabs:

- Each tab maintains its own SQL, results, panel state, and database selection
- Tab names are automatically derived from `--- HYPER 'Name'` directives
- Create new tabs with the **+** button
- Reorder tabs by dragging

### Saving & Loading Files

The SQL File Manager lets you persist queries:

- **Save** — store the current SQL with a name and optional description
- **Browse** — search and load saved files
- **Favorites** — star frequently used queries
- **Database context** — files remember which database they target

Files are stored in LARS's internal database and available across sessions.


## Capture & Annotate


The capture system lets you visually communicate with the AI dashboard builder:

- **Spacebar hold** — activates the full-screen drawing overlay
- **Drawing tools** — multiple brush colors and sizes
- **Audio recording** — captures voice description while you draw
- **Audio level visualization** — real-time feedback during recording
- **Screenshot** — captures the entire view with your annotations overlaid

This multimodal input (voice + drawing + screenshot) gives the AI rich context for
generating relevant dashboards.


## Panel Types Reference


Hyper includes a rich set of panel types, each automatically selected based on
your query's `format` column or data shape:

| Panel Type | Trigger | Description |
|-----------|---------|-------------|
| **DataGrid** | Default (no format) | Sortable, filterable data table |
| **VegaLite** | `format = 'vega-lite'` | Declarative charting (bar, line, area, scatter, etc.) |
| **Plotly** | `format = 'plotly'` | Interactive charts (pie, 3D, animations) |
| **Metric** | `format = 'metric'` | Single-value KPI cards |
| **Sparkline** | `format = 'sparkline'` | Inline trend visualization |
| **Markdown** | `format = 'markdown'` | Rendered Markdown content |
| **Mermaid** | `format = 'mermaid'` | Mermaid diagrams (flowcharts, sequence, etc.) |
| **Image** | `format = 'image'` | Image display from URL |
| **Text** | `format = 'text'` | Plain text display |
| **Dropdown** | Panel parameter | Dropdown filter controls |
| **Slider** | Panel parameter | Range slider controls |
| **DateRange** | Panel parameter | Date range picker |
| **Toggle** | Panel parameter | Boolean toggle switch |


## Keyboard Shortcuts


| Shortcut | Action |
|----------|--------|
| **Ctrl+Enter** / **⌘+Enter** | Execute all queries |
| **Spacebar (hold)** | Enter capture mode (draw + voice) |
| **Ctrl+S** / **⌘+S** | Save current file |
| **Ctrl+N** / **⌘+N** | New tab |
| **Ctrl+W** / **⌘+W** | Close current tab |
| **Escape** | Exit capture mode / close modals |
