"""
Display Tools - Rich UI rendering without blocking execution

Provides tools for LLMs to display charts, dashboards, and interactive content
inline with their message output. Unlike request_decision, these tools return
immediately and don't wait for user input.
"""
from .extras import simple_eddy


@simple_eddy
def show_ui(
    html: str,
    title: str = None,
    description: str = None,
    collapsible: bool = False
) -> dict:
    """
    Display rich HTML/HTMX content inline with your message (non-blocking).

    This tool renders HTML content with full visualization support inline wherever
    your message appears in the dashboard. Execution continues immediately - it does
    NOT wait for user interaction.

    Use this to show:
    - Interactive charts (Plotly, Vega-Lite)
    - Data tables with filtering/sorting
    - Custom dashboards
    - Rich formatted content
    - Anything you can build with HTML/CSS/JS

    Available libraries in the rendered HTML:
    - Basecoat UI - shadcn-style components (btn, card, input, badge, table, etc.)
    - Tailwind CSS - Utility classes for layout
    - Plotly.js - Interactive charts (Plotly.newPlot)
    - Vega-Lite - Grammar of graphics (vegaEmbed)
    - Vanilla JavaScript - Full DOM access
    - RVBBIT dark theme CSS variables

    Basecoat component examples:
    - <button class="btn btn-primary">Action</button>
    - <div class="card"><div class="card-content">...</div></div>
    - <input class="input" placeholder="...">
    - <span class="badge">Status</span>
    - <table class="table">...</table>

    Arguments:
        html: HTML content to display. Can include <script> tags for visualizations.
              No template variables needed (not a checkpoint).
              NO SIZE LIMITS - Include full charts and data inline.
        title: Optional title shown above the UI (rendered as h3)
        description: Optional description/context shown below title
        collapsible: If true, UI starts collapsed with expand button

    Returns immediately with:
        {"displayed": true, "title": "..."}

    Example - Plotly chart:
        show_ui(
            html=\"\"\"
            <div id="sales-chart" style="height:400px;"></div>
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
              Plotly.newPlot('sales-chart', data, layout, {responsive: true});
            </script>
            \"\"\",
            title="Sales Trend Analysis",
            description="Based on Q1-Q4 data from 2024"
        )

    Example - Vega-Lite:
        show_ui(
            html=\"\"\"
            <div id="scatter"></div>
            <script>
              var spec = {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "data": {"values": [
                  {"x": 1, "y": 28}, {"x": 2, "y": 55}, {"x": 3, "y": 43}
                ]},
                "mark": "point",
                "encoding": {
                  "x": {"field": "x", "type": "quantitative"},
                  "y": {"field": "y", "type": "quantitative"}
                },
                "background": "#1a1a1a"
              };
              vegaEmbed('#scatter', spec, {theme: 'dark'});
            </script>
            \"\"\",
            title="Data Distribution"
        )

    Example - Interactive table:
        show_ui(
            html=\"\"\"
            <input type="text" id="filter" placeholder="Filter..." oninput="filterRows(this.value)">
            <table id="data-table" style="width:100%; margin-top:12px;">
              <thead><tr><th>Name</th><th>Value</th><th>Status</th></tr></thead>
              <tbody id="table-body">
                <tr><td>Item 1</td><td>42</td><td>✓</td></tr>
                <tr><td>Item 2</td><td>37</td><td>✗</td></tr>
              </tbody>
            </table>
            <script>
              function filterRows(query) {
                var rows = document.querySelectorAll('#table-body tr');
                rows.forEach(row => {
                  var text = row.textContent.toLowerCase();
                  row.style.display = text.includes(query.toLowerCase()) ? '' : 'none';
                });
              }
            </script>
            \"\"\",
            title="Filtered Results"
        )

    Pro tip: Call show_ui multiple times in a cell to build progressive visual narratives!
    """
    from ..echo import get_echo
    from ..tracing import get_current_trace
    from .state_tools import get_current_session_id

    session_id = get_current_session_id()
    if not session_id:
        return {"error": "No active session context", "displayed": False}

    echo = get_echo(session_id)
    trace = get_current_trace()

    # Build ui_spec (same format as request_decision HTML sections)
    ui_spec = {
        "type": "html_display",
        "content": html,
        "title": title,
        "description": description,
        "collapsible": collapsible
    }

    # Build message content for markdown rendering
    message_parts = []
    if title:
        message_parts.append(f"### {title}")
    if description:
        message_parts.append(description)
    message_parts.append("[Interactive UI displayed below]")

    message_content = "\n\n".join(message_parts)

    # Capture screenshot of display UI (async, non-blocking, overwrites iterations)
    try:
        from ..screenshot_service import get_screenshot_service
        from ..traits.human import _build_screenshot_html
        from .state_tools import get_current_candidate_index

        screenshot_service = get_screenshot_service()
        complete_html = _build_screenshot_html(html)
        sounding_idx = get_current_candidate_index()

        screenshot_service.capture_htmx_render(
            html=complete_html,
            session_id=session_id,
            cell_name=cell_name or "show_ui",
            candidate_index=sounding_idx,
            render_type="display"
        )
        print(f"[Screenshots] 📸 show_ui screenshot queued (overwrites)")
    except Exception as e:
        # Don't fail if screenshot fails
        print(f"[Screenshots] ⚠ Screenshot failed: {e}")

    # Add to echo history with ui_spec in metadata
    # The frontend will detect ui_spec in metadata and render HTMLSection inline
    echo.add_history(
        {
            "role": "assistant",
            "content": message_content,
            "node_type": "ui_display"
        },
        trace_id=trace.id if trace else None,
        node_type="ui_display",
        metadata={
            "ui_spec": ui_spec  # Critical: This tells frontend to render HTML
        }
    )

    return {
        "displayed": True,
        "title": title or "UI displayed",
        "html_length": len(html)
    }
