# LARS Dashboard Micro-App

A standalone dashboard built with LARS semantic SQL.

## Quick Start

1. **Install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
   pip install -r requirements.txt
   ```

2. **Configure LARS connection**
   ```bash
   cp .env.example .env
   # Edit .env with your LARS server URL
   ```

3. **Run the app**
   ```bash
   uvicorn app:app --reload --port 15400
   ```

4. **Open in browser**
   ```
   http://localhost:15400
   ```

## Project Structure

```
├── app.py                 # FastAPI backend - add your endpoints here
├── static/
│   ├── index.html         # HTML shell (imports, CDN links)
│   ├── app.jsx            # Main React app - modify this
│   ├── styles.css         # Custom styles (Tailwind + overrides)
│   └── components/
│       ├── Layout.jsx     # Page layout with header/sidebar
│       ├── Card.jsx       # Dashboard card container
│       ├── KPICard.jsx    # Single KPI display
│       ├── Chart.jsx      # Recharts wrapper (line/bar/area/pie)
│       ├── DataGrid.jsx   # AG Grid wrapper
│       └── Filters.jsx    # Filter components (dropdown, date, search)
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
└── README.md              # This file
```

## How It Works

1. **Backend (`app.py`)**: FastAPI endpoints that query LARS and return JSON
2. **Frontend (`app.jsx`)**: React components that fetch data and render charts/grids
3. **No build step**: Uses ESM imports from CDN - just edit and refresh

## Adding a New Chart

1. Add an endpoint in `app.py`:
   ```python
   @app.get("/api/data/my-chart")
   def my_chart_data():
       with get_connection() as conn:
           return query_to_dict(conn, "SELECT ... FROM ... WHERE ...")
   ```

2. Add the chart in `app.jsx`:
   ```jsx
   <Card title="My Chart">
       <Chart 
           endpoint="/api/data/my-chart"
           type="line"
           xKey="date"
           yKeys={[{ key: 'value', color: '#3b82f6', name: 'Value' }]}
       />
   </Card>
   ```

## Using LARS Semantic Operators

LARS queries work just like regular SQL, but with semantic operators:

```python
# Semantic filtering
"SELECT * FROM tickets WHERE description MEANS 'urgent customer issue'"

# Text-to-SQL
"SELECT * FROM ask_data('top customers by revenue this quarter')"

# Similarity search
"SELECT * FROM products WHERE name SIMILAR_TO 'eco-friendly'"

# Classification
"SELECT *, CLASSIFY(feedback, 'positive', 'negative', 'neutral') as sentiment FROM reviews"
```

## Customization

- **Colors**: Edit CSS custom properties in `styles.css`
- **Layout**: Modify `Layout.jsx` for different page structures
- **Charts**: See `Chart.jsx` for available options
- **Filters**: Compose filter components from `Filters.jsx`

## Deployment

This is a standard Python web app. Deploy however you like:

```bash
# Docker
docker build -t my-dashboard .
docker run -p 15400:15400 my-dashboard

# Railway, Fly.io, etc.
# Just push the repo - they'll detect the Python app

# Manual
uvicorn app:app --host 0.0.0.0 --port $PORT
```
