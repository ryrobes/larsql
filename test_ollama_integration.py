#!/usr/bin/env python3
"""
Test script to verify Ollama model enumeration.

This demonstrates:
1. Fetching local Ollama models via ModelRegistry
2. Using Ollama models with Windlass Agent
"""

import os
import sys

# Add windlass to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "windlass"))

from rvbbit.model_registry import ModelRegistry
from rvbbit.agent import Agent
from rvbbit.config import set_provider
from rich.console import Console
from rich.table import Table

console = Console()


def test_ollama_enumeration():
    """Test that ModelRegistry can enumerate Ollama models."""
    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Ollama Model Enumeration Test      ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Force refresh to fetch both OpenRouter and Ollama models
    console.print("[yellow]Refreshing model registry...[/yellow]")
    registry = ModelRegistry.get_instance()
    registry.refresh(force=True)

    # Get all models
    all_models = ModelRegistry.get_all_models()
    local_models = ModelRegistry.get_local_models()

    console.print(f"\n[green]✓[/green] Total models: {len(all_models)}")
    console.print(f"[green]✓[/green] Local Ollama models: {len(local_models)}")

    # Display Ollama models in a table
    if local_models:
        console.print("\n[bold]Local Ollama Models:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Model ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Description", style="dim")

        for model in local_models:
            table.add_row(
                model.id,
                model.name,
                model.description
            )

        console.print(table)
    else:
        console.print("\n[yellow]⚠ No Ollama models found. Is Ollama running?[/yellow]")
        console.print("[dim]Start Ollama: ollama serve[/dim]")
        return False

    return True


def test_ollama_agent():
    """Test using an Ollama model with Agent."""
    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Ollama Agent Integration Test      ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Get local models
    local_models = ModelRegistry.get_local_models()
    if not local_models:
        console.print("[yellow]Skipping agent test - no Ollama models available[/yellow]")
        return

    # Use the first available Ollama model
    model = local_models[0]
    console.print(f"[cyan]Testing with model:[/cyan] {model.id}")

    # Configure agent to use Ollama
    # Option 1: Use model prefix (already supported)
    agent = Agent(
        model=model.id,  # e.g., "ollama/gpt-oss:20b"
        system_prompt="You are a helpful assistant. Respond concisely.",
        base_url=None,  # Will auto-detect from model prefix
        api_key=None
    )

    # Simple test prompt
    try:
        console.print("\n[yellow]Sending test prompt...[/yellow]")
        response = agent.run(input_message="Say 'Hello from Ollama!' and nothing else.")

        console.print("\n[bold green]✓ Response:[/bold green]")
        console.print(f"[dim]{response.get('content', 'No content')}[/dim]")
        console.print(f"\n[green]✓ Model:[/green] {response.get('model', 'unknown')}")
        cost = response.get('cost') or 0
        console.print(f"[green]✓ Cost:[/green] ${cost:.4f} (should be $0.00 for local)")

    except Exception as e:
        console.print(f"\n[red]✗ Agent test failed:[/red] {e}")
        console.print("\n[yellow]Make sure Ollama is running:[/yellow]")
        console.print("[dim]  ollama serve[/dim]")
        return

    # Option 2: Use provider override (also supported)
    console.print("\n[cyan]Testing with provider override...[/cyan]")
    set_provider(
        base_url="http://localhost:11434",
        model="gpt-oss:20b"  # No ollama/ prefix needed when using base_url
    )

    console.print("[green]✓ Provider configured for Ollama[/green]")
    console.print("[dim]  Base URL: http://localhost:11434[/dim]")
    console.print(f"[dim]  Model: {model.name}[/dim]")


if __name__ == "__main__":
    success = test_ollama_enumeration()

    if success:
        test_ollama_agent()

    console.print("\n[bold green]╔══════════════════════════════════════╗[/bold green]")
    console.print("[bold green]║  Ollama Integration Summary         ║[/bold green]")
    console.print("[bold green]╚══════════════════════════════════════╝[/bold green]\n")

    console.print("[bold]Usage Options:[/bold]\n")

    console.print("[cyan]1. Model Prefix (Recommended):[/cyan]")
    console.print('[dim]   model: "ollama/gpt-oss:20b"[/dim]\n')

    console.print("[cyan]2. Environment Variable:[/cyan]")
    console.print('[dim]   export WINDLASS_PROVIDER_BASE_URL="http://localhost:11434"[/dim]')
    console.print('[dim]   export WINDLASS_DEFAULT_MODEL="gpt-oss:20b"[/dim]\n')

    console.print("[cyan]3. Runtime Configuration:[/cyan]")
    console.print('[dim]   from rvbbit.config import set_provider[/dim]')
    console.print('[dim]   set_provider(base_url="http://localhost:11434", model="gpt-oss:20b")[/dim]\n')

    console.print("[bold]Available Models:[/bold]")
    console.print("[dim]   - ollama/gpt-oss:20b[/dim]")
    console.print("[dim]   - ollama/qwen2.5:3b[/dim]\n")
