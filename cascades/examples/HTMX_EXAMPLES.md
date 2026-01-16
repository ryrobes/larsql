# HTMX Checkpoint Examples

Advanced examples demonstrating LLM-generated interactive UIs with HTMX, visualizations, and rich interactions.

## Available Libraries in HTMX Iframes

All HTMX checkpoints have access to:
- **HTMX** - Hypermedia interactions
- **Plotly.js** - Interactive charts and graphs
- **Vega & Vega-Lite** - Grammar of graphics visualizations
- **Vanilla JavaScript** - Full DOM manipulation

## Examples

### 1. Basic Approval Form
**File:** `htmx_demo.yaml`

**What it shows:**
- Simple approve/reject pattern
- Markdown-rendered message context
- Form submission with JSON encoding
- Template variable replacement

**Run:**
```bash
lars examples/htmx_demo.yaml --input '{"task": "quantum computing"}' --session basic_test
```

**Use cases:** Simple yes/no decisions, document approval, workflow gates

---

### 2. Plotly Interactive Charts
**File:** `htmx_plotly_demo.yaml`

**What it shows:**
- LLM generates synthetic data
- Creates Plotly charts with inline data
- Dark theme styling for charts
- Chart + approval form together

**Run:**
```bash
lars examples/htmx_plotly_demo.yaml --input '{"analysis_topic": "sales trends"}' --session plotly_test
```

**Charts LLMs can create:**
- Bar charts, line charts, scatter plots
- 3D visualizations
- Heatmaps, box plots, violin plots
- Statistical charts (histograms, distribution plots)
- Financial charts (candlestick, OHLC)

**Example Plotly code:**
```html
<div id="chart" style="height:400px;"></div>
<script>
var data = [{
  x: ['Q1', 'Q2', 'Q3', 'Q4'],
  y: [120, 150, 170, 190],
  type: 'bar',
  marker: {color: '#a78bfa'}
}];

var layout = {
  title: 'Quarterly Sales',
  paper_bgcolor: '#1a1a1a',
  plot_bgcolor: '#0a0a0a',
  font: {color: '#e5e7eb'}
};

Plotly.newPlot('chart', data, layout, {responsive: true});
</script>
```

---

### 3. Vega-Lite Dashboards
**File:** `htmx_vegalite_demo.yaml`

**What it shows:**
- Declarative visualization specs
- Multiple charts in one UI
- Grammar of graphics approach
- JSON-based chart definitions

**Run:**
```bash
lars examples/htmx_vegalite_demo.yaml --input '{"dataset_topic": "climate data"}' --session vega_test
```

**Vega-Lite advantages:**
- More concise than Plotly for standard charts
- Declarative JSON specs
- Automatic axis labels and legends
- Layered visualizations

**Example Vega-Lite code:**
```html
<div id="vis"></div>
<script>
var spec = {
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "data": {
    "values": [
      {"month": "Jan", "temp": 45},
      {"month": "Feb", "temp": 48},
      {"month": "Mar", "temp": 55}
    ]
  },
  "mark": "line",
  "encoding": {
    "x": {"field": "month", "type": "ordinal"},
    "y": {"field": "temp", "type": "quantitative"}
  },
  "background": "#1a1a1a",
  "config": {
    "axis": {"labelColor": "#e5e7eb", "titleColor": "#a78bfa"},
    "legend": {"labelColor": "#e5e7eb"}
  }
};

vegaEmbed('#vis', spec, {theme: 'dark', actions: false});
</script>
```

---

### 4. Multi-Step Wizards
**File:** `htmx_wizard_demo.yaml`

**What it shows:**
- Progressive form disclosure
- State carried across steps
- Client-side step navigation
- Review before final submit

**Run:**
```bash
lars examples/htmx_wizard_demo.yaml --input '{"workflow_type": "ETL pipeline"}' --session wizard_test
```

**Pattern:**
- Step 1: Basic info → stores in hidden inputs
- Step 2: Advanced config → adds to hidden inputs
- Step 3: Review all → shows summary
- Final: Submit to checkpoint endpoint

**Use cases:** Complex configuration, onboarding flows, multi-part forms

---

### 5. Interactive Data Tables
**File:** `htmx_interactive_table.yaml`

**What it shows:**
- Client-side filtering
- Column sorting
- Row selection with checkboxes
- Bulk operations

**Run:**
```bash
lars examples/htmx_interactive_table.yaml --input '{"data_topic": "customer orders"}' --session table_test
```

**Features LLMs can add:**
- Search/filter
- Multi-column sort
- Pagination
- Row selection
- Inline editing
- Export to CSV

---

### 6. Real-Time Status Polling
**File:** `htmx_realtime_status.yaml`

**What it shows:**
- Auto-refreshing content (hx-trigger="every 2s")
- Progress bars
- Live activity logs
- Simulated async operations

**Run:**
```bash
lars examples/htmx_realtime_status.yaml --input '{"task_description": "model training"}' --session status_test
```

**Polling patterns:**
```html
<!-- Auto-update every 2 seconds -->
<div hx-get="/api/status/{{ session_id }}"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  Loading...
</div>

<!-- Poll until complete -->
<div hx-get="/api/task/status"
     hx-trigger="every 1s [progress < 100]">
</div>
```

---

## Advanced Techniques

### Combining Visualizations with Forms

```yaml
instructions: |
  Create a data analysis workflow:
  1. Show Plotly chart with current data
  2. Let user adjust parameters via form inputs
  3. Update chart on input change (hx-trigger="change")
  4. Submit final parameters for approval
```

### Multi-Chart Dashboards

```yaml
instructions: |
  Create a dashboard with:
  - Plotly line chart (time series)
  - Vega-Lite bar chart (categories)
  - Summary statistics table
  - Approve/reject buttons

  All with inline data, dark theme, responsive layout.
```

### Interactive Exploration

```yaml
instructions: |
  Build an explorer UI:
  - Plotly 3D scatter plot (rotate, zoom)
  - Dropdown to filter by category (hx-get on change)
  - Table showing selected points
  - Export selected data button
```

## Tips for LLMs

### Dark Theme Styling

Always use Lars colors:
```javascript
// Plotly
{
  paper_bgcolor: '#1a1a1a',
  plot_bgcolor: '#0a0a0a',
  font: {color: '#e5e7eb'},
  xaxis: {gridcolor: '#333'},
  yaxis: {gridcolor: '#333'}
}

// Vega-Lite
{
  "background": "#1a1a1a",
  "config": {
    "axis": {"labelColor": "#e5e7eb", "titleColor": "#a78bfa", "gridColor": "#333"},
    "legend": {"labelColor": "#e5e7eb"}
  }
}
```

### Responsive Charts

```javascript
// Plotly
Plotly.newPlot('chart', data, layout, {responsive: true});

// Vega-Lite
vegaEmbed('#chart', spec, {
  theme: 'dark',
  actions: false,  // Hide embed actions
  renderer: 'svg'   // Better for responsiveness
});
```

### Inline Data Patterns

```javascript
// Small datasets: Embed directly
var data = [{x: [1,2,3], y: [4,5,6]}];

// Medium datasets: Generate programmatically
var data = Array.from({length: 50}, (_, i) => ({
  x: i,
  y: Math.sin(i / 5) * 100
}));

// Large datasets: Consider aggregation first
```

## Testing Checklist

When testing these examples:

- [ ] Charts render without errors
- [ ] Dark theme applied correctly
- [ ] Charts are interactive (hover, zoom, pan)
- [ ] Forms submit successfully
- [ ] Layout looks clean (no overflow, proper spacing)
- [ ] Responsive on window resize
- [ ] Console shows no errors
- [ ] Cascade continues after approval

## Performance Notes

**Chart Libraries:**
- Plotly: ~3MB (first load cached by CDN)
- Vega-Lite: ~1MB
- Load time: ~500ms on first checkpoint

**Optimization:**
- Libraries load once per iframe
- Cached by browser across checkpoints
- Minimal impact on cascade performance

## Troubleshooting

**Chart doesn't appear:**
```javascript
// Check console for:
console.log('Plotly loaded:', typeof Plotly !== 'undefined');
console.log('vegaEmbed loaded:', typeof vegaEmbed !== 'undefined');

// Verify div exists:
console.log('Chart div:', document.getElementById('myChart'));
```

**Data not showing:**
```javascript
// Log your data before plotting
console.log('Chart data:', JSON.stringify(data, null, 2));

// Check for NaN, Infinity, null values
data.y.forEach((val, i) => {
  if (!isFinite(val)) console.warn('Invalid data at index', i, ':', val);
});
```

**Theme not applied:**
```javascript
// Ensure you set both backgrounds
{
  paper_bgcolor: '#1a1a1a',  // Outer area
  plot_bgcolor: '#0a0a0a',    // Chart area
  font: {color: '#e5e7eb'}     // Text color
}
```

---

## Future Ideas

- **D3.js integration** - Custom SVG visualizations
- **Chart.js** - Lightweight alternative to Plotly
- **ag-Grid** - Enterprise data tables
- **Monaco Editor** - Inline code editing
- **Mermaid** - Diagrams and flowcharts (already in main app)
- **Three.js** - 3D visualizations

These can all be added to the iframe template as needed!
