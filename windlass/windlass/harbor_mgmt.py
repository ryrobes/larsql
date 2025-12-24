"""
Harbor management for HuggingFace Spaces.

Handles fetching, caching, and querying of user's HF Spaces in ClickHouse.
"""

import json
from datetime import datetime, timezone
from typing import List, Dict, Optional
from rich.console import Console
from rich.table import Table

from .config import get_config
from .db_adapter import get_db
from .harbor import (
    list_all_user_spaces,
    get_spaces_summary,
    introspect_space,
    SpaceInfo
)


console = Console()


def refresh_spaces(author: Optional[str] = None):
    """
    Main refresh function: fetch user's Spaces from HuggingFace and populate ClickHouse.

    Args:
        author: HuggingFace username (defaults to inferring from HF_TOKEN)
    """
    config = get_config()
    db = get_db()

    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  HuggingFace Spaces Refresh         ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Step 1: Fetch spaces from HuggingFace
    try:
        console.print("[cyan]Fetching spaces from HuggingFace API...[/cyan]")

        # Use existing harbor.py function to get spaces
        spaces = list_all_user_spaces(author=author)

        console.print(f"[green]✓[/green] Fetched {len(spaces)} spaces")
    except Exception as e:
        console.print(f"\n[red]✗ Refresh failed: {e}[/red]")
        console.print("[yellow]Hint: Make sure HF_TOKEN environment variable is set[/yellow]")
        return

    # Step 2: Transform to table rows with introspection
    console.print("[cyan]Processing space metadata and introspecting APIs...[/cyan]")

    rows = []
    current_time = datetime.now(timezone.utc)

    for space in spaces:
        # Extract space components
        space_id = space.id
        author_name = space.author if hasattr(space, 'author') else space.id.split('/')[0]
        space_name = space.name if hasattr(space, 'name') else space.id.split('/')[-1]

        # Try to introspect if it's a Gradio space and RUNNING
        endpoints_json = None
        if space.sdk == 'gradio' and space.status == 'RUNNING':
            try:
                introspection = introspect_space(space_id)
                if introspection:
                    endpoints_json = json.dumps(introspection)
                    console.print(f"  [dim]Introspected {space_id}[/dim]")
            except Exception as e:
                console.print(f"  [dim yellow]Could not introspect {space_id}: {e}[/dim yellow]")

        row = {
            "space_id": space_id,
            "author": author_name,
            "space_name": space_name,
            "status": space.status,
            "hardware": space.hardware,
            "sdk": space.sdk,
            "hourly_cost": space.hourly_cost,
            "is_billable": space.is_billable,
            "is_callable": space.is_callable,
            "endpoints_json": endpoints_json,
            "private": space.private,
            "space_url": space.url or f"https://huggingface.co/spaces/{space_id}",
            "sleep_time": space.sleep_time,
            "requested_hardware": space.requested_hardware,
            "last_seen": current_time,
            "last_refreshed": current_time
        }

        rows.append(row)

    # Step 3: Insert into ClickHouse
    console.print(f"[cyan]Inserting {len(rows)} spaces into ClickHouse...[/cyan]")

    try:
        db.insert_rows("hf_spaces", rows)
        console.print(f"[green]✓[/green] Successfully inserted {len(rows)} spaces")
    except Exception as e:
        console.print(f"[red]✗ Failed to insert spaces: {e}[/red]")
        raise

    # Step 4: Show summary
    console.print("\n[bold green]✓ Refresh complete![/bold green]\n")
    show_stats()


def list_spaces(
    include_sleeping: bool = True,
    sdk_filter: Optional[str] = None,
    limit: int = 50
):
    """
    List spaces from database with Rich table formatting.

    Args:
        include_sleeping: If True, include SLEEPING spaces
        sdk_filter: Filter by SDK type (gradio, streamlit, etc.)
        limit: Max spaces to show
    """
    db = get_db()

    # Build query
    where_clauses = []
    if not include_sleeping:
        where_clauses.append("status != 'SLEEPING'")
    if sdk_filter:
        where_clauses.append(f"sdk = '{sdk_filter}'")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            space_id,
            author,
            space_name,
            status,
            hardware,
            sdk,
            hourly_cost,
            is_billable,
            is_callable,
            last_refreshed
        FROM hf_spaces FINAL
        WHERE {where_sql}
        ORDER BY is_billable DESC, status, space_id
        LIMIT {limit}
    """

    results = db.query(query)

    # Display with Rich table
    table = Table(title=f"HuggingFace Spaces (showing {len(results)})")
    table.add_column("Space ID", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("SDK", style="magenta")
    table.add_column("Hardware", style="yellow")
    table.add_column("Cost/Hr", justify="right", style="green")
    table.add_column("Callable", style="blue")

    for row in results:
        # Status emoji
        status_map = {
            'RUNNING': '🟢',
            'SLEEPING': '😴',
            'BUILDING': '🔨',
            'PAUSED': '⏸️',
            'STOPPED': '🛑',
            'RUNTIME_ERROR': '❌'
        }
        status_emoji = status_map.get(row["status"], '❓')

        # Hardware display
        hardware_display = row["hardware"] or "-"

        # Cost display
        if row["hourly_cost"] and row["hourly_cost"] > 0:
            cost_display = f"${row['hourly_cost']:.2f}"
        else:
            cost_display = "Free"

        table.add_row(
            row["space_id"],
            f"{status_emoji} {row['status']}",
            row["sdk"] or "-",
            hardware_display,
            cost_display,
            "✓" if row["is_callable"] else "✗"
        )

    console.print(table)


def show_stats():
    """Show HuggingFace Spaces statistics."""
    db = get_db()

    # Overall stats
    stats_query = """
        SELECT
            count() as total,
            countIf(status = 'RUNNING') as running,
            countIf(status = 'SLEEPING') as sleeping,
            countIf(is_billable) as billable,
            countIf(is_callable) as callable,
            SUM(CASE WHEN is_billable THEN hourly_cost ELSE 0 END) as total_hourly_cost
        FROM hf_spaces FINAL
    """

    stats = db.query(stats_query)

    if not stats or stats[0]['total'] == 0:
        console.print("[yellow]No spaces in database. Run 'windlass harbor refresh' first.[/yellow]")
        return

    stats = stats[0]

    # SDK breakdown
    sdk_query = """
        SELECT
            sdk,
            count() as total,
            countIf(status = 'RUNNING') as running
        FROM hf_spaces FINAL
        WHERE sdk IS NOT NULL
        GROUP BY sdk
        ORDER BY total DESC
    """

    sdks = db.query(sdk_query)

    # Hardware breakdown (for running spaces)
    hardware_query = """
        SELECT
            hardware,
            count() as count,
            SUM(hourly_cost) as total_cost
        FROM hf_spaces FINAL
        WHERE status = 'RUNNING' AND hardware IS NOT NULL
        GROUP BY hardware
        ORDER BY total_cost DESC
        LIMIT 5
    """

    hardware = db.query(hardware_query)

    # Display
    console.print("\n[bold]HuggingFace Spaces Statistics[/bold]\n")
    console.print(f"Total spaces:       {stats['total']:>5}")
    console.print(f"  Running:          {stats['running']:>5}")
    console.print(f"  Sleeping:         {stats['sleeping']:>5}")
    console.print(f"  Billable:         {stats['billable']:>5}")
    console.print(f"  Callable (tools): {stats['callable']:>5}")

    if stats['total_hourly_cost']:
        console.print(f"\nCurrent hourly cost: [green]${stats['total_hourly_cost']:.2f}/hr[/green]")
        console.print(f"Est. monthly cost:   [yellow]${stats['total_hourly_cost'] * 730:.2f}/mo[/yellow] (if always on)")

    if sdks:
        console.print(f"\nBy SDK:")
        for row in sdks:
            console.print(f"  {row['sdk']:12} {row['total']:>3} total ({row['running']} running)")

    if hardware:
        table = Table(title="\nRunning Hardware")
        table.add_column("Hardware", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Cost/Hr", justify="right", style="green")

        for row in hardware:
            table.add_row(
                row["hardware"],
                str(row["count"]),
                f"${row['total_cost']:.2f}"
            )

        console.print(table)

    console.print()


def update_usage_stats():
    """
    Update usage statistics from unified_logs.

    Counts how many times each space has been invoked as a tool.
    """
    db = get_db()

    console.print("[cyan]Updating usage statistics from logs...[/cyan]")

    # Query unified_logs for tool invocations
    # Tool names for Harbor follow pattern: hf_{author}_{spacename}_{endpoint}
    usage_query = """
        WITH tool_calls AS (
            SELECT
                tool_calls_json,
                timestamp
            FROM unified_logs
            WHERE node_type = 'tool_result'
              AND tool_calls_json IS NOT NULL
              AND tool_calls_json != ''
        )
        SELECT
            extractAll(tool_calls_json, '"name"\\s*:\\s*"hf_([^"]+)"')[1] as tool_names,
            COUNT(*) as invocations,
            MAX(timestamp) as last_call
        FROM tool_calls
        WHERE length(tool_names) > 0
        GROUP BY tool_names
    """

    try:
        results = db.query(usage_query)

        # Update each space's usage stats
        # This is a simplified version - ideally we'd parse tool names to match space_ids
        console.print(f"[green]✓[/green] Found {len(results)} harbor tool usage records")

    except Exception as e:
        console.print(f"[yellow]Could not update usage stats: {e}[/yellow]")


def pause_space_db(space_id: str):
    """
    Pause a space via HF API and update database.

    Args:
        space_id: Space ID to pause (e.g., "author/space-name")
    """
    from .harbor import pause_space

    console.print(f"[cyan]Pausing space {space_id}...[/cyan]")

    try:
        pause_space(space_id)

        # Update database
        db = get_db()
        current_time = datetime.now(timezone.utc)

        update_row = {
            "space_id": space_id,
            "status": "PAUSED",
            "is_billable": False,
            "is_callable": False,
            "last_refreshed": current_time
        }

        db.insert_rows("hf_spaces", [update_row])

        console.print(f"[green]✓[/green] Space paused and database updated")

    except Exception as e:
        console.print(f"[red]✗ Failed to pause space: {e}[/red]")


def wake_space_db(space_id: str):
    """
    Wake a sleeping space via HF API and update database.

    Args:
        space_id: Space ID to wake (e.g., "author/space-name")
    """
    from .harbor import wake_space

    console.print(f"[cyan]Waking space {space_id}...[/cyan]")
    console.print("[dim]This may take 30-60 seconds...[/dim]")

    try:
        wake_space(space_id)

        # Update database (note: status will be BUILDING until actually running)
        db = get_db()
        current_time = datetime.now(timezone.utc)

        update_row = {
            "space_id": space_id,
            "status": "BUILDING",  # Will become RUNNING after build completes
            "last_refreshed": current_time
        }

        db.insert_rows("hf_spaces", [update_row])

        console.print(f"[green]✓[/green] Space wake requested and database updated")
        console.print("[yellow]Run 'windlass harbor refresh' after ~1 minute to update final status[/yellow]")

    except Exception as e:
        console.print(f"[red]✗ Failed to wake space: {e}[/red]")
