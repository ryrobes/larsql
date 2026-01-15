"""
Artifacts - Persistent rich UI outputs

Provides tools for LLMs to create persistent, browseable artifacts (dashboards,
reports, charts, tables) that survive cascade completion and can be viewed in
the Artifacts gallery.
"""
import os
import json
from datetime import datetime
from uuid import uuid4
from .extras import simple_eddy


@simple_eddy
def create_artifact(
    html: str,
    title: str,
    artifact_type: str = "dashboard",
    description: str | None = None,
    tags: list | None = None
) -> dict:
    """
    Create a persistent artifact (rich interactive UI) for this cascade run.

    Artifacts are saved to the database and browseable in the Artifacts view
    even after the cascade completes. Use this to publish final outputs, reports,
    dashboards, and interactive visualizations.

    **Workflow Pattern:**
    1. Use request_decision to iterate on visualizations
    2. Once approved/polished, use create_artifact to publish final version
    3. Artifact appears in gallery and is linked from session detail

    Available libraries: Plotly.js, Vega-Lite, HTMX, vanilla JavaScript
    Dark theme CSS variables automatically available

    **Fetching Live SQL Data:**

    IMPORTANT WORKFLOW - Always test queries before embedding them:

    Step 1: Discover and test your query first
      # Use sql_search() to find tables
      sql_search("bigfoot sightings data")

      # Test the query with sql_query() to see actual column names
      sql_query(sql="SELECT * FROM csv_files.bigfoot_sightings LIMIT 1", connection="csv_files")
      # Returns: {columns: ['state', 'class', 'county', ...], rows: [...], "error": null}

      # CHECK RESPONSE.ERROR! If not null, query failed - fix it!
      # Example error: {"error": "Column not found", "columns": [], "rows": []}

      # Once you have real columns, test your aggregation
      sql_query(sql="SELECT state, COUNT(*) as count FROM csv_files.bigfoot_sightings GROUP BY state", connection="csv_files")
      # Check error field again! Only proceed to HTML if error is null.

    Step 2: Write HTML using EXACT column names from SUCCESSFUL test (error=null)
      fetch('http://localhost:5001/api/sql/query', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          connection: 'csv_files',  // Connection name from sql_connections/
          sql: 'SELECT state, COUNT(*) as count FROM bigfoot_sightings GROUP BY state ORDER BY count DESC',
          limit: 1000
        })
      }).then(r => r.json()).then(result => {
        // ALWAYS check for errors first!
        if (result.error) {
          console.error('SQL error:', result.error);
          document.getElementById('chart').innerHTML =
            '<div style="color:#ef4444;padding:20px;">Error: ' + result.error + '</div>';
          return;
        }

        // result.columns = ['state', 'count']  // Matches your test!
        // result.rows = [['WA', 632], ['CA', 445], ...]

        // Use column indices OR find by name:
        const stateIdx = result.columns.indexOf('state');  // = 0
        const countIdx = result.columns.indexOf('count');  // = 1

        // Plotly example - use indices from your test:
        Plotly.newPlot('chart', [{
          x: result.rows.map(r => r[stateIdx]),  // state column
          y: result.rows.map(r => r[countIdx]),  // count column
          type: 'bar',
          marker: {color: '#a78bfa'}
        }], {
          paper_bgcolor: '#1a1a1a',
          plot_bgcolor: '#0a0a0a',
          font: {color: '#e5e7eb'}
        });
      }).catch(err => {
        console.error('Fetch error:', err);
        document.getElementById('chart').innerHTML =
          '<div style="color:#ef4444;padding:20px;">Network error</div>';
      });

    Transform to objects for Vega-Lite (needs {key: value} format):
      const data = result.rows.map(row =>
        Object.fromEntries(result.columns.map((col, i) => [col, row[i]]))
      );
      // [{state: 'WA', count: 632}, {state: 'CA', count: 445}, ...]

    Filters: Rebuild SQL query with WHERE clause and call fetch() again
      async function applyFilter(filterValue) {
        const sql = filterValue
          ? `SELECT state, COUNT(*) as count FROM bigfoot_sightings WHERE class = '${filterValue}' GROUP BY state`
          : `SELECT state, COUNT(*) as count FROM bigfoot_sightings GROUP BY state`;

        const result = await fetch('http://localhost:5001/api/sql/query', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({connection: 'csv_files', sql: sql})
        }).then(r => r.json());

        // Update chart with new data
        Plotly.react('chart', [{x: result.rows.map(r => r[0]), y: result.rows.map(r => r[1]), type: 'bar'}], layout);
      }

    Discovery tools: sql_search(), list_sql_connections(), sql_query()

    KEY POINT: Always sql_query() first to verify column names AND check for errors before writing fetch() code!

    Arguments:
        html: Full HTML content for the artifact. Can include inline JavaScript,
              Plotly charts, Vega-Lite specs, interactive tables, etc.
              This is a complete standalone page rendered in an iframe.
              NO SIZE LIMITS - Include all data, charts, and scripts inline.
        title: Artifact title (shown in gallery and viewer)
        artifact_type: Type classification for filtering:
                       - "dashboard" - Multi-chart dashboards
                       - "report" - Text reports with visualizations
                       - "chart" - Single chart/graph
                       - "table" - Interactive data tables
                       - "analysis" - Analytical outputs
                       - "custom" - Other
        description: Optional description/summary shown in gallery preview
        tags: Optional list of tags for organization (e.g., ["sales", "Q4", "plotly"])

    Returns:
        {"artifact_id": "art_abc123", "title": "...", "url": "/artifacts/art_abc123"}

    Example - Plotly Dashboard:
        create_artifact(
            html=\"\"\"
            <div style="padding:24px;">
              <h1>Q4 Sales Dashboard</h1>
              <div id="revenue-chart" style="height:400px;"></div>
              <div id="growth-chart" style="height:400px;"></div>
              <script>
                // Revenue chart
                Plotly.newPlot('revenue-chart', [{
                  x: ['Oct', 'Nov', 'Dec'],
                  y: [120000, 150000, 190000],
                  type: 'bar',
                  marker: {color: '#a78bfa'}
                }], {
                  title: 'Monthly Revenue',
                  paper_bgcolor: '#1a1a1a',
                  plot_bgcolor: '#0a0a0a',
                  font: {color: '#e5e7eb'}
                });

                // Growth chart
                Plotly.newPlot('growth-chart', [{
                  x: ['Oct', 'Nov', 'Dec'],
                  y: [5, 25, 27],
                  type: 'scatter',
                  mode: 'lines+markers'
                }], {
                  title: 'Growth Rate %',
                  paper_bgcolor: '#1a1a1a',
                  plot_bgcolor: '#0a0a0a'
                });
              </script>
            </div>
            \"\"\",
            title="Q4 Sales Dashboard",
            artifact_type="dashboard",
            description="Revenue and growth analysis for Q4 2024",
            tags=["sales", "Q4", "dashboard"]
        )

    Example - Interactive Table:
        create_artifact(
            html=\"\"\"
            <div style="padding:24px;">
              <h2>Top 50 Customers by Revenue</h2>
              <input type="text" id="filter" placeholder="Filter customers..."
                     oninput="filterTable(this.value)" style="width:100%;padding:8px;">
              <table id="customers" style="width:100%;margin-top:16px;">
                <thead><tr><th onclick="sortBy(0)">Name ▼</th><th onclick="sortBy(1)">Revenue ▼</th></tr></thead>
                <tbody><!-- rows here --></tbody>
              </table>
              <script>
                function filterTable(q) { /* filter logic */ }
                function sortBy(col) { /* sort logic */ }
              </script>
            </div>
            \"\"\",
            title="Top Customers 2024",
            artifact_type="table",
            tags=["customers", "revenue"]
        )

    Pro tips:
    - Make artifacts self-contained (include all data inline)
    - Use dark theme colors for consistency
    - Add interactivity (filters, sorts, hover tooltips)
    - Consider mobile responsiveness
    - Include data source/timestamp in description
    """
    from ..echo import get_echo
    from ..tracing import get_current_trace
    from .state_tools import get_current_session_id, get_current_cell_name, get_current_cascade_id

    session_id = get_current_session_id()
    cell_name = get_current_cell_name()
    cascade_id = get_current_cascade_id()

    if not session_id:
        return {"error": "No active session context", "created": False}

    echo = get_echo(session_id)
    trace = get_current_trace()

    # Generate artifact ID
    artifact_id = f"artifact_{uuid4().hex[:12]}"

    # Build artifact record
    now = datetime.utcnow()

    artifact = {
        "id": artifact_id,
        "session_id": session_id,
        "cascade_id": cascade_id or "unknown",
        "cell_name": cell_name or "unknown",
        "title": title,
        "artifact_type": artifact_type,
        "description": description or "",
        "html_content": html,
        "tags": json.dumps(tags) if tags else "[]",
        "created_at": now,  # datetime object for ClickHouse
        "updated_at": now   # datetime object for ClickHouse
    }

    # Save to database
    try:
        _save_artifact_to_db(artifact)
    except Exception as e:
        return {"error": f"Failed to save artifact: {str(e)}", "created": False}

    # Capture screenshot for gallery thumbnail (async, non-blocking)
    thumbnail_path = None
    try:
        from ..screenshot_service import get_screenshot_service
        from ..skills.human import _build_screenshot_html

        screenshot_service = get_screenshot_service()
        complete_html = _build_screenshot_html(html)

        thumbnail_path = screenshot_service.capture_artifact_sync(
            artifact_id=artifact_id,
            html=complete_html
        )
        print(f"[Artifacts] 📸 Thumbnail screenshot queued: {thumbnail_path}")
    except Exception as e:
        # Don't fail artifact creation if screenshot fails
        print(f"[Artifacts] ⚠ Thumbnail screenshot failed: {e}")

    # Add to echo history for visibility
    tag_str = f" • Tags: {', '.join(tags)}" if tags else ""
    echo.add_history(
        {
            "role": "assistant",
            "content": f"📦 **Created Artifact: {title}**\n\nType: {artifact_type}{tag_str}\n\n{description or 'Interactive UI artifact saved.'}\n\n[View in Artifacts](/artifacts/{artifact_id})",
            "artifact_id": artifact_id
        },
        trace_id=trace.id if trace else None,
        node_type="artifact_created"
    )

    return {
        "created": True,
        "artifact_id": artifact_id,
        "title": title,
        "url": f"/artifacts/{artifact_id}",
        "html_length": len(html)
    }


def _save_artifact_to_db(artifact: dict):
    """Save artifact to database using unified db_adapter."""
    from ..config import get_config
    from ..db_adapter import get_db

    cfg = get_config()
    db = get_db()

    # Table should already exist from migration
    # Just insert the artifact
    try:
        if cfg.use_clickhouse_server:
            # ClickHouse server - use insert_rows method
            db.insert_rows('artifacts', [artifact], columns=list(artifact.keys()))
            print(f"[Artifacts] Saved to ClickHouse table: {artifact['id']}")

        else:
            # chDB mode - save to Parquet
            _save_to_parquet(artifact, cfg)

    except Exception as e:
        print(f"[Artifacts] Save failed: {e}")
        import traceback
        traceback.print_exc()
        # Try Parquet fallback
        try:
            _save_to_parquet(artifact, cfg)
            print(f"[Artifacts] Fell back to Parquet successfully")
        except Exception as e2:
            print(f"[Artifacts] Parquet fallback also failed: {e2}")
            raise


def _save_to_parquet(artifact: dict, cfg):
    """Save artifact to Parquet file (chDB mode)."""
    # Ensure data directory exists
    data_dir = cfg.data_dir
    os.makedirs(data_dir, exist_ok=True)

    artifacts_file = os.path.join(data_dir, "artifacts.parquet")

    # If file exists, append; otherwise create
    if os.path.exists(artifacts_file):
        # Read existing, append new row
        try:
            import chdb
            existing_df = chdb.query(f"SELECT * FROM file('{artifacts_file}', Parquet)").to_df()
            import pandas as pd
            new_df = pd.concat([existing_df, pd.DataFrame([artifact])], ignore_index=True)
            new_df.to_parquet(artifacts_file, index=False)
        except Exception as e:
            print(f"[Artifacts] Failed to append to parquet: {e}")
            # Fallback: just write new file (will overwrite)
            import pandas as pd
            pd.DataFrame([artifact]).to_parquet(artifacts_file, index=False)
    else:
        # Create new file
        import pandas as pd
        pd.DataFrame([artifact]).to_parquet(artifacts_file, index=False)


@simple_eddy
def list_artifacts(
    cascade_id: str | None = None,
    artifact_type: str | None = None,
    tags: list | None = None,
    limit: int = 50
) -> dict:
    """
    List artifacts with optional filtering.

    Arguments:
        cascade_id: Filter by cascade (optional)
        artifact_type: Filter by type (optional)
        tags: Filter by tags (returns artifacts with ANY of these tags)
        limit: Maximum results (default 50)

    Returns:
        {"artifacts": [...], "count": N}
    """
    from ..config import get_config

    cfg = get_config()

    # Build query
    filters = []
    if cascade_id:
        filters.append(f"cascade_id = '{cascade_id}'")
    if artifact_type:
        filters.append(f"artifact_type = '{artifact_type}'")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    if cfg.use_clickhouse_server:
        import clickhouse_connect
        client = clickhouse_connect.get_client(host=cfg.clickhouse_host)

        result = client.query(f"""
            SELECT id, session_id, cascade_id, cell_name, title, artifact_type,
                   description, tags, created_at
            FROM artifacts
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit}
        """)

        artifacts = [dict(zip(result.column_names, row)) for row in result.result_rows]

    else:
        import chdb
        data_dir = cfg.data_dir
        artifacts_file = os.path.join(data_dir, "artifacts.parquet")

        if not os.path.exists(artifacts_file):
            return {"artifacts": [], "count": 0}

        result = chdb.query(f"""
            SELECT id, session_id, cascade_id, cell_name, title, artifact_type,
                   description, tags, created_at
            FROM file('{artifacts_file}', Parquet)
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit}
        """)

        artifacts = result.to_dict('records')

    return {
        "artifacts": artifacts,
        "count": len(artifacts)
    }


@simple_eddy
def get_artifact(artifact_id: str) -> dict:
    """
    Get a specific artifact by ID.

    Returns the full artifact including HTML content.
    """
    from ..config import get_config

    cfg = get_config()

    if cfg.use_clickhouse_server:
        import clickhouse_connect
        client = clickhouse_connect.get_client(host=cfg.clickhouse_host)

        result = client.query(f"""
            SELECT * FROM artifacts WHERE id = '{artifact_id}'
        """)

        if not result.result_rows:
            return {"error": "Artifact not found"}

        artifact = dict(zip(result.column_names, result.result_rows[0]))

    else:
        import chdb
        data_dir = cfg.data_dir
        artifacts_file = os.path.join(data_dir, "artifacts.parquet")

        if not os.path.exists(artifacts_file):
            return {"error": "No artifacts found"}

        result = chdb.query(f"""
            SELECT * FROM file('{artifacts_file}', Parquet)
            WHERE id = '{artifact_id}'
        """)

        artifacts = result.to_dict('records')
        if not artifacts:
            return {"error": "Artifact not found"}

        artifact = artifacts[0]

    return artifact
