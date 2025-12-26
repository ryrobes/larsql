"""
Tool registry management for RVBBIT.

Handles syncing tools from in-memory registry to ClickHouse and analytics.
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from .config import get_config
from .db_adapter import get_db
from .traits_manifest import get_trait_manifest


console = Console()


def normalize_tool_type(tool_type_str: str) -> str:
    """
    Normalize tool type to match DB enum values.

    Maps various type strings to: 'function', 'cascade', 'memory', 'validator'
    """
    if 'cascade' in tool_type_str:
        return 'cascade'
    elif 'memory' in tool_type_str:
        return 'memory'
    elif 'validator' in tool_type_str:
        return 'validator'
    else:
        return 'function'


def compute_manifest_hash(manifest: Dict) -> str:
    """
    Compute a stable hash of the tool manifest.

    Uses tool names and descriptions to detect changes.
    Returns a hash string that changes only when tools are added/removed/modified.
    """
    # Create a sorted, deterministic representation
    tool_items = []
    for tool_name in sorted(manifest.keys()):
        tool_info = manifest[tool_name]
        description = tool_info.get('description', '')
        tool_type = normalize_tool_type(tool_info.get('type', 'function'))
        # Include name, normalized type, and description in hash
        tool_items.append(f"{tool_name}|{tool_type}|{description}")

    # Join and hash
    manifest_str = '\n'.join(tool_items)
    return hashlib.sha256(manifest_str.encode('utf-8')).hexdigest()


def tools_have_changed(manifest: Dict) -> Tuple[bool, Optional[str]]:
    """
    Check if the current tool manifest differs from what's in the database.

    Returns:
        (changed: bool, reason: Optional[str])
        - changed: True if tools need to be synced
        - reason: Description of what changed (or None if unchanged)
    """
    db = get_db()

    try:
        # Get current tools from database
        db_tools_query = """
            SELECT
                tool_name,
                tool_type,
                tool_description
            FROM tool_manifest_vectors FINAL
            ORDER BY tool_name
        """

        db_tools = db.query(db_tools_query)

        # If database is empty, we need to sync
        if not db_tools:
            return (True, "Database is empty - initial sync required")

        # Build a comparable representation of DB tools
        db_manifest = {}
        for row in db_tools:
            db_manifest[row['tool_name']] = {
                'type': row['tool_type'],
                'description': row['tool_description']
            }

        # Compare counts first (quick check)
        if len(manifest) != len(db_manifest):
            added = set(manifest.keys()) - set(db_manifest.keys())
            removed = set(db_manifest.keys()) - set(manifest.keys())

            changes = []
            if added:
                changes.append(f"{len(added)} added")
            if removed:
                changes.append(f"{len(removed)} removed")

            return (True, f"Tool count changed: {', '.join(changes)}")

        # Compute hashes for deep comparison
        current_hash = compute_manifest_hash(manifest)

        # Build comparable manifest from DB
        db_comparable = {}
        for tool_name, tool_data in db_manifest.items():
            db_comparable[tool_name] = {
                'type': tool_data['type'],
                'description': tool_data['description']
            }

        db_hash = compute_manifest_hash(db_comparable)

        # Compare hashes
        if current_hash != db_hash:
            # Find what actually changed
            modified = []
            for tool_name in manifest.keys():
                if tool_name in db_manifest:
                    current_desc = manifest[tool_name].get('description', '')
                    db_desc = db_manifest[tool_name]['description']
                    if current_desc != db_desc:
                        modified.append(tool_name)

            if modified:
                return (True, f"{len(modified)} tool(s) modified: {', '.join(modified[:5])}")
            else:
                return (True, "Tool metadata changed")

        # No changes detected
        return (False, None)

    except Exception as e:
        # If we can't check, assume tools have changed (safe default)
        console.print(f"[yellow]⚠ Could not check for changes: {e}[/yellow]")
        return (True, f"Unable to verify (will sync): {e}")


def sync_tools_to_db(force: bool = False):
    """
    Sync current tool manifest to ClickHouse tool_manifest_vectors table.

    This enables:
    - Cross-instance tool visibility
    - Tool usage analytics
    - Semantic tool search
    - Historical tracking

    Args:
        force: If True, always sync even if tools haven't changed.
               If False (default), skip sync if tools are unchanged.
    """
    config = get_config()
    db = get_db()

    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Tool Registry Sync to Database     ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Step 1: Get current manifest
    console.print("[cyan]Discovering tools from manifest...[/cyan]")

    try:
        manifest = get_trait_manifest(refresh=True)
        console.print(f"[green]✓[/green] Discovered {len(manifest)} tools")
    except Exception as e:
        console.print(f"[red]✗ Failed to get manifest: {e}[/red]")
        return

    # Step 1.5: Check if tools have changed (unless forced)
    if not force:
        console.print("[cyan]Checking for changes...[/cyan]")
        changed, reason = tools_have_changed(manifest)

        if not changed:
            console.print("[green]✓[/green] Tools unchanged - skipping sync")
            console.print("[dim]  (Use --force or force=True to sync anyway)[/dim]\n")
            return
        else:
            console.print(f"[yellow]⚡[/yellow] Changes detected: {reason}")
    else:
        console.print("[yellow]⚡[/yellow] Force mode - syncing all tools")

    # Step 2: Generate embeddings for all tool descriptions
    console.print("[cyan]Generating embeddings for tool descriptions...[/cyan]")

    try:
        from .rag.indexer import embed_texts

        # Collect all descriptions
        tool_names_ordered = list(manifest.keys())
        descriptions = []
        for tool_name in tool_names_ordered:
            tool_info = manifest[tool_name]
            description = tool_info.get('description', '')
            if not description:
                description = f"{tool_info.get('type', 'tool')}: {tool_name}"
            descriptions.append(description)

        # Batch embed all at once (more efficient)
        embed_result = embed_texts(
            texts=descriptions,
            model=config.default_embed_model,
            session_id="tool_sync",
            cascade_id="tool_registry_sync",
            cell_name="embed_tools"
        )

        embeddings = embed_result['embeddings']
        embedding_model = embed_result['model']
        embedding_dim = embed_result['dim']

        console.print(f"[green]✓[/green] Generated {len(embeddings)} embeddings using {embedding_model}")

    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Could not generate embeddings: {e}")
        console.print("[dim]Continuing without embeddings (text search only)...[/dim]")
        embeddings = [[] for _ in manifest]
        embedding_model = ""
        embedding_dim = 0

    # Step 3: Transform to table rows
    console.print("[cyan]Transforming tool metadata...[/cyan]")

    rows = []
    current_time = datetime.now(timezone.utc)

    for i, tool_name in enumerate(tool_names_ordered):
        tool_info = manifest[tool_name]
        # Determine tool type from manifest
        tool_type_str = tool_info.get('type', 'function')

        # Map to enum string values for ClickHouse Enum8
        if 'cascade' in tool_type_str:
            tool_type = 'cascade'
        elif 'memory' in tool_type_str:
            tool_type = 'memory'
        elif 'validator' in tool_type_str:
            tool_type = 'validator'
        else:
            tool_type = 'function'  # default

        # Extract description
        description = tool_info.get('description', '')
        if not description:
            description = f"{tool_type_str.capitalize()} tool: {tool_name}"

        # Build schema JSON
        schema_json = None
        if 'schema' in tool_info:
            schema_json = json.dumps(tool_info['schema'])
        elif 'inputs' in tool_info:
            schema_json = json.dumps({'inputs': tool_info['inputs']})

        # Get source path
        source_path = tool_info.get('path', '')

        row = {
            "tool_name": tool_name,
            "tool_type": tool_type,
            "tool_description": description,
            "schema_json": schema_json,
            "source_path": source_path,
            "embedding": embeddings[i] if i < len(embeddings) else [],
            "embedding_model": embedding_model,
            "embedding_dim": embedding_dim,
            "last_updated": current_time
        }

        rows.append(row)

    # Step 4: Insert into ClickHouse
    console.print(f"[cyan]Inserting {len(rows)} tools into ClickHouse...[/cyan]")

    try:
        db.insert_rows("tool_manifest_vectors", rows)
        console.print(f"[green]✓[/green] Successfully synced {len(rows)} tools")
    except Exception as e:
        console.print(f"[red]✗ Failed to insert tools: {e}[/red]")
        raise

    # Step 5: Show summary
    console.print("\n[bold green]✓ Sync complete![/bold green]\n")
    show_tool_summary()


def show_tool_summary():
    """Show summary of tools in database."""
    db = get_db()

    # Count by type
    type_query = """
        SELECT
            tool_type,
            count() as total
        FROM tool_manifest_vectors FINAL
        GROUP BY tool_type
        ORDER BY total DESC
    """

    type_counts = db.query(type_query)

    console.print("[bold]Tools by Type[/bold]\n")
    for row in type_counts:
        type_name = row['tool_type']  # Enum8 returns string directly
        console.print(f"  {type_name:12} {row['total']:>4} tools")

    console.print()


def list_tools(
    tool_type: Optional[str] = None,
    limit: int = 50
):
    """
    List tools from database.

    Args:
        tool_type: Filter by type (function, cascade, memory, validator)
        limit: Max tools to show
    """
    db = get_db()

    # Build query
    where_clauses = []

    if tool_type:
        type_map = {
            'function': 0,
            'cascade': 1,
            'memory': 2,
            'validator': 3
        }
        if tool_type in type_map:
            where_clauses.append(f"tool_type = {type_map[tool_type]}")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    query = f"""
        SELECT
            tool_name,
            tool_type,
            tool_description,
            source_path,
            last_updated
        FROM tool_manifest_vectors FINAL
        WHERE {where_sql}
        ORDER BY tool_name
        LIMIT {limit}
    """

    results = db.query(query)

    # Display with Rich table
    table = Table(title=f"Tools in Database (showing {len(results)})")
    table.add_column("Tool Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Description", style="white")
    table.add_column("Source", style="dim")

    for row in results:
        type_name = row["tool_type"]  # Enum8 returns string directly

        # Truncate description
        desc = row["tool_description"][:60]
        if len(row["tool_description"]) > 60:
            desc += "..."

        # Truncate source path
        source = row["source_path"] or "-"
        if len(source) > 40:
            source = "..." + source[-37:]

        table.add_row(
            row["tool_name"],
            type_name,
            desc,
            source
        )

    console.print(table)


def show_usage_stats(days: int = 7):
    """
    Show tool usage statistics from unified_logs.

    Args:
        days: Number of days to look back (default: 7)
    """
    db = get_db()

    console.print(f"\n[bold cyan]Tool Usage Statistics (Last {days} Days)[/bold cyan]\n")

    # Most used tools
    console.print("[bold]Most Used Tools[/bold]\n")

    usage_query = f"""
        WITH tool_calls AS (
            SELECT
                JSONExtractString(tool_calls_json, 'function', 'name') as tool_name,
                timestamp,
                session_id,
                cost
            FROM unified_logs
            WHERE timestamp > now() - INTERVAL {days} DAY
              AND tool_calls_json != ''
              AND tool_calls_json IS NOT NULL
              AND node_type = 'tool_result'
        )
        SELECT
            tool_name,
            COUNT(*) as invocations,
            COUNT(DISTINCT session_id) as unique_sessions,
            MAX(timestamp) as last_used,
            SUM(cost) as total_cost
        FROM tool_calls
        WHERE tool_name != ''
        GROUP BY tool_name
        ORDER BY invocations DESC
        LIMIT 20
    """

    try:
        usage_results = db.query(usage_query)

        if usage_results:
            table = Table()
            table.add_column("Tool", style="cyan")
            table.add_column("Uses", justify="right", style="green")
            table.add_column("Sessions", justify="right")
            table.add_column("Cost", justify="right", style="yellow")
            table.add_column("Last Used", style="dim")

            for row in usage_results:
                cost_str = f"${row['total_cost']:.4f}" if row['total_cost'] else "-"
                last_used = str(row['last_used'])[:19] if row['last_used'] else "-"

                table.add_row(
                    row["tool_name"],
                    str(row["invocations"]),
                    str(row["unique_sessions"]),
                    cost_str,
                    last_used
                )

            console.print(table)
        else:
            console.print("[yellow]No tool usage found in logs[/yellow]")

    except Exception as e:
        console.print(f"[red]Error querying usage stats: {e}[/red]")

    # Unused tools
    console.print("\n[bold]Unused Tools (Never Invoked)[/bold]\n")

    unused_query = f"""
        SELECT
            tm.tool_name,
            tm.tool_type,
            tm.tool_description
        FROM (SELECT * FROM tool_manifest_vectors FINAL) AS tm
        LEFT JOIN (
            SELECT DISTINCT JSONExtractString(tool_calls_json, 'function', 'name') as tool_name
            FROM unified_logs
            WHERE timestamp > now() - INTERVAL {days} DAY
              AND tool_calls_json != ''
              AND tool_calls_json IS NOT NULL
        ) AS used ON tm.tool_name = used.tool_name
        WHERE used.tool_name IS NULL
           OR used.tool_name = ''
        ORDER BY tm.tool_name
        LIMIT 20
    """

    try:
        unused_results = db.query(unused_query)

        if unused_results:
            console.print(f"Found {len(unused_results)} unused tools:\n")

            for row in unused_results:
                type_name = row['tool_type']  # Enum8 returns string directly
                console.print(f"  • [cyan]{row['tool_name']}[/cyan] ({type_name})")

            if len(unused_results) == 20:
                console.print("\n  [dim](Showing first 20 unused tools)[/dim]")
        else:
            console.print("[green]All tools have been used![/green]")

    except Exception as e:
        console.print(f"[red]Error querying unused tools: {e}[/red]")

    console.print()


def show_tool_stats():
    """Show overall tool statistics."""
    db = get_db()

    # Overall counts
    total_query = """
        SELECT
            count() as total_tools
        FROM tool_manifest_vectors FINAL
    """

    total = db.query(total_query)[0]['total_tools']

    # Usage stats (last 7 days)
    usage_query = """
        SELECT
            COUNT(DISTINCT JSONExtractString(tool_calls_json, 'function', 'name')) as tools_used,
            COUNT(*) as total_invocations
        FROM unified_logs
        WHERE timestamp > now() - INTERVAL 7 DAY
          AND tool_calls_json != ''
          AND tool_calls_json IS NOT NULL
          AND node_type = 'tool_result'
    """

    usage = db.query(usage_query)[0]

    # Display
    console.print("\n[bold]Tool Registry Statistics[/bold]\n")
    console.print(f"Total registered tools: {total:>5}")
    console.print(f"Tools used (7 days):    {usage['tools_used']:>5}")
    console.print(f"Total invocations:      {usage['total_invocations']:>5}")

    if total > 0 and usage['tools_used'] > 0:
        usage_pct = (usage['tools_used'] / total) * 100
        console.print(f"Usage rate:             {usage_pct:>5.1f}%")

    console.print()


def find_tool_by_description(search_query: str, limit: int = 10):
    """
    Find tools by searching descriptions (simple text search).

    Args:
        search_query: Text to search for in tool descriptions
        limit: Max results to return
    """
    db = get_db()

    console.print(f"\n[bold]Searching for tools matching: [cyan]{search_query}[/cyan][/bold]\n")

    search_query_escaped = search_query.replace("'", "''")

    # Use double %% to escape % in ILIKE patterns for Python string formatting
    query = f"""
        SELECT
            tool_name,
            tool_type,
            tool_description,
            source_path
        FROM tool_manifest_vectors FINAL
        WHERE tool_description ILIKE '%%{search_query_escaped}%%'
           OR tool_name ILIKE '%%{search_query_escaped}%%'
        ORDER BY tool_name
        LIMIT {limit}
    """

    results = db.query(query)

    if not results:
        console.print("[yellow]No tools found matching your search[/yellow]\n")
        return

    table = Table()
    table.add_column("Tool Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Description", style="white")

    for row in results:
        type_name = row["tool_type"]  # Enum8 returns string directly

        # Truncate description
        desc = row["tool_description"][:80]
        if len(row["tool_description"]) > 80:
            desc += "..."

        table.add_row(
            row["tool_name"],
            type_name,
            desc
        )

    console.print(table)
    console.print()


def semantic_find_tools(query: str, limit: int = 10):
    """
    Find tools using semantic search (vector similarity).

    Args:
        query: Natural language query (e.g., "parse PDF documents")
        limit: Max results to return
    """
    config = get_config()
    db = get_db()

    console.print(f"\n[bold]Semantic search for: [cyan]{query}[/cyan][/bold]\n")

    try:
        from .rag.indexer import embed_texts

        # Embed the query
        console.print("[dim]Embedding query...[/dim]")
        embed_result = embed_texts(
            texts=[query],
            model=config.default_embed_model,
            session_id="tool_search",
            cascade_id="tool_search",
            cell_name="search"
        )

        query_embedding = embed_result['embeddings'][0]

        # Vector search in ClickHouse
        # Note: ClickHouse cosineDistance returns 0 for identical vectors, higher for dissimilar
        search_query = f"""
            SELECT
                tool_name,
                tool_type,
                tool_description,
                source_path,
                cosineDistance(embedding, {query_embedding}) as distance
            FROM tool_manifest_vectors FINAL
            WHERE length(embedding) > 0
            ORDER BY distance ASC
            LIMIT {limit}
        """

        results = db.query(search_query)

        if not results:
            console.print("[yellow]No tools with embeddings found[/yellow]")
            console.print("[dim]Run 'rvbbit tools sync' to generate embeddings[/dim]\n")
            return

        # Display results
        table = Table()
        table.add_column("Tool Name", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Similarity", justify="right", style="green")
        table.add_column("Description", style="white")

        for row in results:
            type_name = row["tool_type"]

            # Convert distance to similarity score (0-1, higher is better)
            similarity = 1.0 - min(row["distance"], 1.0)
            similarity_pct = f"{similarity * 100:.1f}%"

            # Truncate description
            desc = row["tool_description"][:70]
            if len(row["tool_description"]) > 70:
                desc += "..."

            table.add_row(
                row["tool_name"],
                type_name,
                similarity_pct,
                desc
            )

        console.print(table)
        console.print()

    except Exception as e:
        console.print(f"[red]Error during semantic search: {e}[/red]")
        import traceback
        traceback.print_exc()
