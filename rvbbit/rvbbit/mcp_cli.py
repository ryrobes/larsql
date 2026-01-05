"""
MCP CLI Commands

Command implementations for rvbbit mcp subcommands.
"""

import json
import sys
import os
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box


# =============================================================================
# Configuration File Helpers
# =============================================================================

def _get_config_file_path():
    """Get path to MCP config file (create directory if needed)."""
    from rvbbit.config import RVBBIT_ROOT
    config_dir = os.path.join(RVBBIT_ROOT, "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "mcp_servers.yaml")


def _load_config_file():
    """Load existing MCP config file (or return empty list)."""
    import yaml
    config_file = _get_config_file_path()

    if os.path.exists(config_file):
        with open(config_file, 'r') as f:
            servers = yaml.safe_load(f)
            return servers if servers else []

    return []


def _save_config_file(servers):
    """Save MCP servers to config file."""
    import yaml
    config_file = _get_config_file_path()

    with open(config_file, 'w') as f:
        yaml.dump(servers, f, default_flow_style=False, sort_keys=False)


# =============================================================================
# MCP Commands
# =============================================================================

def cmd_mcp_add(args):
    """Add a new MCP server to configuration."""
    console = Console()

    # Validate transport-specific args
    if args.transport == 'http' and not args.url:
        console.print("[red]Error: HTTP transport requires --url[/red]")
        console.print("[dim]Example: rvbbit mcp add github http --url http://localhost:3000/mcp[/dim]")
        sys.exit(1)

    if args.transport == 'stdio' and not args.command:
        console.print("[red]Error: stdio transport requires a command[/red]")
        console.print("[dim]Example: rvbbit mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /tmp[/dim]")
        sys.exit(1)

    # Load existing config
    servers = _load_config_file()

    # Check if server already exists
    for server in servers:
        if server.get('name') == args.name:
            console.print(f"[yellow]Warning: Server '{args.name}' already exists[/yellow]")
            console.print("Use 'rvbbit mcp remove' first, or choose a different name")
            sys.exit(1)

    # Build server config
    server_config = {
        'name': args.name,
        'transport': args.transport,
        'enabled': not args.disabled
    }

    if args.transport == 'stdio':
        # Parse command into command + args
        import shlex
        try:
            parts = shlex.split(args.command) if args.command else []
        except ValueError:
            # Fallback for unquoted commands - just split on spaces
            parts = args.command.split() if args.command else []

        if not parts:
            console.print("[red]Error: Command cannot be empty for stdio transport[/red]")
            sys.exit(1)

        server_config['command'] = parts[0]
        if len(parts) > 1:
            server_config['args'] = parts[1:]
    elif args.transport == 'http':
        server_config['url'] = args.url

    # Add environment variables
    if args.env:
        env_dict = {}
        for env_var in args.env:
            if '=' not in env_var:
                console.print(f"[red]Error: Invalid env format '{env_var}' (expected KEY=VALUE)[/red]")
                sys.exit(1)
            key, value = env_var.split('=', 1)
            env_dict[key] = value
        server_config['env'] = env_dict

    # Add to servers list
    servers.append(server_config)

    # Save config
    try:
        _save_config_file(servers)
        config_file = _get_config_file_path()

        console.print(f"[green]✓ Added MCP server '{args.name}'[/green]")
        console.print(f"[dim]Config file: {config_file}[/dim]")

        # Show what was added
        console.print("\n[cyan]Server configuration:[/cyan]")

        # Build display string
        if args.transport == 'stdio':
            cmd_display = f"{server_config['command']}"
            if server_config.get('args'):
                cmd_display += " " + " ".join(server_config['args'])
            config_text = (
                f"Name: [bold]{args.name}[/bold]\n"
                f"Transport: {args.transport}\n"
                f"Command: {cmd_display}\n"
                + (f"Environment: {', '.join(args.env)}\n" if args.env else "")
                + f"Enabled: {not args.disabled}"
            )
        else:
            config_text = (
                f"Name: [bold]{args.name}[/bold]\n"
                f"Transport: {args.transport}\n"
                f"URL: {args.url}\n"
                + (f"Environment: {', '.join(args.env)}\n" if args.env else "")
                + f"Enabled: {not args.disabled}"
            )

        console.print(Panel(config_text, box=box.ROUNDED))

        console.print("\n[dim]Next steps:[/dim]")
        console.print("  1. Test connection: [cyan]rvbbit mcp status " + args.name + "[/cyan]")
        console.print("  2. List tools: [cyan]rvbbit mcp introspect " + args.name + "[/cyan]")

    except Exception as e:
        console.print(f"[red]Failed to save config: {e}[/red]")
        sys.exit(1)


def cmd_mcp_remove(args):
    """Remove an MCP server from configuration."""
    console = Console()

    # Load existing config
    servers = _load_config_file()

    if not servers:
        console.print("[yellow]No servers configured[/yellow]")
        return

    # Find and remove server
    original_count = len(servers)
    servers = [s for s in servers if s.get('name') != args.name]

    if len(servers) == original_count:
        console.print(f"[yellow]Server '{args.name}' not found[/yellow]")
        console.print("\nConfigured servers:")
        for server in servers:
            console.print(f"  - {server.get('name')}")
        sys.exit(1)

    # Save updated config
    try:
        _save_config_file(servers)
        console.print(f"[green]✓ Removed MCP server '{args.name}'[/green]")
    except Exception as e:
        console.print(f"[red]Failed to save config: {e}[/red]")
        sys.exit(1)


def cmd_mcp_enable(args):
    """Enable a disabled MCP server."""
    console = Console()

    # Load existing config
    servers = _load_config_file()

    if not servers:
        console.print("[yellow]No servers configured[/yellow]")
        return

    # Find and enable server
    found = False
    for server in servers:
        if server.get('name') == args.name:
            server['enabled'] = True
            found = True
            break

    if not found:
        console.print(f"[yellow]Server '{args.name}' not found[/yellow]")
        sys.exit(1)

    # Save updated config
    try:
        _save_config_file(servers)
        console.print(f"[green]✓ Enabled MCP server '{args.name}'[/green]")
        console.print(f"[dim]Test it: rvbbit mcp status {args.name}[/dim]")
    except Exception as e:
        console.print(f"[red]Failed to save config: {e}[/red]")
        sys.exit(1)


def cmd_mcp_disable(args):
    """Disable an MCP server."""
    console = Console()

    # Load existing config
    servers = _load_config_file()

    if not servers:
        console.print("[yellow]No servers configured[/yellow]")
        return

    # Find and disable server
    found = False
    for server in servers:
        if server.get('name') == args.name:
            server['enabled'] = False
            found = True
            break

    if not found:
        console.print(f"[yellow]Server '{args.name}' not found[/yellow]")
        sys.exit(1)

    # Save updated config
    try:
        _save_config_file(servers)
        console.print(f"[green]✓ Disabled MCP server '{args.name}'[/green]")
    except Exception as e:
        console.print(f"[red]Failed to save config: {e}[/red]")
        sys.exit(1)


def cmd_mcp_list(args):
    """List configured MCP servers."""
    from rvbbit.config import get_config

    console = Console()
    config = get_config()

    if not config.mcp_enabled:
        console.print("[yellow]MCP integration is disabled (RVBBIT_MCP_ENABLED=false)[/yellow]")
        return

    servers = config.mcp_servers

    if not servers:
        console.print("[yellow]No MCP servers configured[/yellow]")
        console.print("\nAdd servers to:")
        console.print("  1. config/mcp_servers.yaml")
        console.print("  2. RVBBIT_MCP_SERVERS_YAML environment variable")
        return

    # Filter if needed
    if args.enabled_only:
        servers = [s for s in servers if s.enabled]

    table = Table(
        title=f"[bold cyan]MCP Servers[/bold cyan] ({len(servers)} configured)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )

    table.add_column("Name", style="cyan")
    table.add_column("Transport", style="blue")
    table.add_column("Command/URL", style="white")
    table.add_column("Enabled", justify="center")

    for server in servers:
        if server.transport.value == "stdio":
            cmd_str = f"{server.command} {' '.join(server.args or [])}"
            if len(cmd_str) > 60:
                cmd_str = cmd_str[:57] + "..."
        else:  # http
            cmd_str = server.url or "Unknown"

        enabled_str = "[green]✓[/green]" if server.enabled else "[red]✗[/red]"

        table.add_row(
            server.name,
            server.transport.value,
            cmd_str,
            enabled_str
        )

    console.print(table)

    # Show environment variable info
    if not args.enabled_only:
        console.print("\n[dim]Tip: Use --enabled-only to show only enabled servers[/dim]")


def cmd_mcp_status(args):
    """Show MCP server status and health."""
    from rvbbit.config import get_config
    from rvbbit.mcp_client import get_mcp_client, MCPClient

    console = Console()
    config = get_config()

    if not config.mcp_enabled:
        console.print("[yellow]MCP integration is disabled[/yellow]")
        return

    servers = config.mcp_servers
    if not servers:
        console.print("[yellow]No MCP servers configured[/yellow]")
        return

    # Filter by server name if specified
    if args.server:
        servers = [s for s in servers if s.name == args.server]
        if not servers:
            console.print(f"[red]Server '{args.server}' not found in configuration[/red]")
            return

    # Only check enabled servers
    servers = [s for s in servers if s.enabled]

    table = Table(
        title="[bold cyan]MCP Server Status[/bold cyan]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta"
    )

    table.add_column("Server", style="cyan")
    table.add_column("Transport", style="blue")
    table.add_column("Status", justify="center")
    table.add_column("Tools", justify="right")
    table.add_column("Resources", justify="right")
    table.add_column("Prompts", justify="right")

    for server in servers:
        try:
            # Try to connect and introspect
            client = get_mcp_client(server)

            # Get tool count
            tools = client.list_tools()
            tool_count = len(tools)

            # Try resources
            try:
                resources = client.list_resources()
                resource_count = len(resources)
            except:
                resource_count = 0

            # Try prompts
            try:
                prompts = client.list_prompts()
                prompt_count = len(prompts)
            except:
                prompt_count = 0

            status = "[green]✓ Running[/green]"

        except Exception as e:
            status = f"[red]✗ Error[/red]"
            tool_count = resource_count = prompt_count = "-"

        table.add_row(
            server.name,
            server.transport.value,
            status,
            str(tool_count),
            str(resource_count),
            str(prompt_count)
        )

    console.print(table)


def cmd_mcp_introspect(args):
    """List tools/resources/prompts from a specific MCP server."""
    from rvbbit.config import get_config
    from rvbbit.mcp_client import get_mcp_client

    console = Console()
    config = get_config()

    if not config.mcp_enabled:
        console.print("[yellow]MCP integration is disabled[/yellow]")
        return

    # Find server
    server = None
    for s in config.mcp_servers:
        if s.name == args.server:
            server = s
            break

    if not server:
        console.print(f"[red]Server '{args.server}' not found in configuration[/red]")
        sys.exit(1)

    if not server.enabled:
        console.print(f"[yellow]Server '{args.server}' is disabled[/yellow]")
        console.print("Enable it in config/mcp_servers.yaml")
        sys.exit(1)

    try:
        client = get_mcp_client(server)

        # Show resources
        if args.resources:
            try:
                resources = client.list_resources()

                table = Table(
                    title=f"[bold cyan]Resources from '{args.server}'[/bold cyan]",
                    box=box.ROUNDED
                )
                table.add_column("URI", style="cyan")
                table.add_column("Name", style="white")
                table.add_column("Type", style="blue")
                table.add_column("Description", style="dim")

                for res in resources:
                    table.add_row(
                        res.uri,
                        res.name,
                        res.mime_type or "unknown",
                        res.description or ""
                    )

                console.print(table)
            except Exception as e:
                console.print(f"[red]Failed to list resources: {e}[/red]")

        # Show prompts
        elif args.prompts:
            try:
                prompts = client.list_prompts()

                table = Table(
                    title=f"[bold cyan]Prompts from '{args.server}'[/bold cyan]",
                    box=box.ROUNDED
                )
                table.add_column("Name", style="cyan")
                table.add_column("Description", style="white")
                table.add_column("Arguments", style="dim")

                for prompt in prompts:
                    args_str = ", ".join([arg["name"] for arg in prompt.arguments]) if prompt.arguments else "none"
                    table.add_row(
                        prompt.name,
                        prompt.description or "",
                        args_str
                    )

                console.print(table)
            except Exception as e:
                console.print(f"[red]Failed to list prompts: {e}[/red]")

        # Show tools (default)
        else:
            tools = client.list_tools()

            table = Table(
                title=f"[bold cyan]Tools from '{args.server}'[/bold cyan] ({len(tools)} available)",
                box=box.ROUNDED
            )
            table.add_column("Tool Name", style="cyan")
            table.add_column("Description", style="white")
            table.add_column("Parameters", style="dim")

            for tool in tools:
                # Extract parameter names from input schema
                props = tool.input_schema.get("properties", {})
                required = tool.input_schema.get("required", [])
                params = []
                for param_name in props.keys():
                    if param_name in required:
                        params.append(f"{param_name}*")
                    else:
                        params.append(param_name)

                params_str = ", ".join(params) if params else "none"

                table.add_row(
                    tool.name,
                    tool.description or "",
                    params_str
                )

            console.print(table)

    except Exception as e:
        console.print(f"[red]Failed to introspect server '{args.server}': {e}[/red]")
        sys.exit(1)


def cmd_mcp_manifest(args):
    """Show all MCP tools in the trait manifest."""
    from rvbbit.mcp_discovery import get_mcp_manifest
    from rich.syntax import Syntax

    console = Console()

    try:
        manifest = get_mcp_manifest()

        if not manifest:
            console.print("[yellow]No MCP tools in manifest[/yellow]")
            console.print("\nMCP tools are discovered automatically when:")
            console.print("  1. First cascade execution")
            console.print("  2. Quartermaster invoked")
            console.print("  3. Manual refresh (rvbbit mcp refresh)")
            return

        # JSON output
        if args.json:
            json_str = json.dumps(manifest, indent=2, default=str)
            syntax = Syntax(json_str, "json", theme="monokai", line_numbers=True)
            console.print(syntax)
            return

        # Table output
        table = Table(
            title=f"[bold cyan]MCP Tools in Manifest[/bold cyan] ({len(manifest)} tools)",
            box=box.ROUNDED
        )
        table.add_column("Tool Name", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Server", style="magenta")
        table.add_column("Description", style="white")

        for tool_name, tool_info in sorted(manifest.items()):
            tool_type = tool_info.get("type", "mcp")
            server = tool_info.get("mcp_server", "unknown")
            desc = tool_info.get("description", "").split("\n")[0]
            if len(desc) > 60:
                desc = desc[:57] + "..."

            table.add_row(
                tool_name,
                tool_type,
                server,
                desc
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Failed to get MCP manifest: {e}[/red]")
        sys.exit(1)


def cmd_mcp_refresh(args):
    """Re-discover tools from all MCP servers."""
    from rvbbit.config import get_config
    from rvbbit.mcp_discovery import discover_and_register_mcp_tools
    from rvbbit.trait_registry import get_registry

    console = Console()
    config = get_config()

    if not config.mcp_enabled:
        console.print("[yellow]MCP integration is disabled[/yellow]")
        return

    servers = [s for s in config.mcp_servers if s.enabled]
    if not servers:
        console.print("[yellow]No enabled MCP servers to refresh[/yellow]")
        return

    console.print(f"[cyan]Refreshing {len(servers)} MCP server(s)...[/cyan]\n")

    # Get count before
    registry = get_registry()
    before_count = len([t for t in registry.get_all_traits().keys() if t.startswith("mcp_") or hasattr(registry.get_trait(t), '_tool_type')])

    try:
        # Clear existing MCP tools from registry (optional - could skip this)
        # For now, we'll just re-register (overwrite)

        # Discover and register
        discover_and_register_mcp_tools(servers)

        # Get count after
        after_count = len([t for t in registry.get_all_traits().keys() if hasattr(registry.get_trait(t), '_tool_type')])

        console.print(f"[green]✓ Discovery complete[/green]")
        console.print(f"  MCP tools in registry: {after_count}")
        console.print(f"\n[dim]Use 'rvbbit mcp manifest' to view discovered tools[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to refresh MCP tools: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_mcp_test(args):
    """Test calling an MCP tool."""
    from rvbbit.config import get_config
    from rvbbit.mcp_client import get_mcp_client
    from rich.syntax import Syntax

    console = Console()
    config = get_config()

    if not config.mcp_enabled:
        console.print("[yellow]MCP integration is disabled[/yellow]")
        return

    # Find server
    server = None
    for s in config.mcp_servers:
        if s.name == args.server:
            server = s
            break

    if not server:
        console.print(f"[red]Server '{args.server}' not found[/red]")
        sys.exit(1)

    if not server.enabled:
        console.print(f"[yellow]Server '{args.server}' is disabled[/yellow]")
        sys.exit(1)

    # Parse arguments
    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON arguments: {e}[/red]")
        console.print(f"[dim]Example: --args '{{\"path\": \"/tmp/test.txt\"}}'[/dim]")
        sys.exit(1)

    # Test the tool
    console.print(Panel(
        f"[cyan]Testing MCP tool[/cyan]\n"
        f"Server: [bold]{args.server}[/bold]\n"
        f"Tool: [bold]{args.tool}[/bold]\n"
        f"Args: {json.dumps(tool_args, indent=2)}",
        box=box.ROUNDED
    ))

    try:
        client = get_mcp_client(server, on_progress=lambda msg: console.print(f"[dim]→ {msg}[/dim]"))

        # Call the tool
        result = client.call_tool(args.tool, tool_args)

        # Display result
        console.print("\n[green]✓ Tool call succeeded[/green]\n")

        # Try to format as JSON if it's a dict/list
        if isinstance(result, (dict, list)):
            json_str = json.dumps(result, indent=2, default=str)
            syntax = Syntax(json_str, "json", theme="monokai")
            console.print(syntax)
        elif isinstance(result, str):
            console.print(Panel(result, title="Result", box=box.ROUNDED))
        else:
            console.print(Panel(str(result), title="Result", box=box.ROUNDED))

    except Exception as e:
        console.print(f"\n[red]✗ Tool call failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)
