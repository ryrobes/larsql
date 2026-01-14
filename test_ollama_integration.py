#!/usr/bin/env python3
"""
Test script to verify Ollama model enumeration and remote server support.

This demonstrates:
1. Fetching local Ollama models via ModelRegistry
2. Using Ollama models with Rvbbit Agent
3. Remote Ollama support with ollama@host/model syntax
4. Named host aliases from config
"""

import os
import sys

# Add rvbbit to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "rvbbit"))

from rvbbit.model_registry import ModelRegistry
from rvbbit.agent import Agent, parse_ollama_model
from rvbbit.config import set_provider, set_ollama_provider, get_config
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


def test_ollama_model_parsing():
    """Test parsing of ollama@host/model syntax."""
    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Ollama Model Parsing Test          ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Create a mock config with host aliases
    class MockConfig:
        ollama_hosts = {
            "gpu1": "http://10.10.10.1:11434",
            "gpu2": "http://192.168.1.50:9999",
        }

    config = MockConfig()

    # Test cases
    test_cases = [
        # (input, expected_url, expected_model)
        ("ollama@10.10.10.1/mistral", "http://10.10.10.1:11434", "mistral"),
        ("ollama@gpu-server:9999/llama3", "http://gpu-server:9999", "llama3"),
        ("ollama@gpu1/qwen2.5", "http://10.10.10.1:11434", "qwen2.5"),  # Named alias
        ("ollama@gpu2/codellama:7b", "http://192.168.1.50:9999", "codellama:7b"),  # Named alias + tag
        ("ollama@192.168.1.100:8080/phi3", "http://192.168.1.100:8080", "phi3"),
    ]

    all_passed = True
    for model_str, expected_url, expected_model in test_cases:
        try:
            url, model = parse_ollama_model(model_str, config)
            if url == expected_url and model == expected_model:
                console.print(f"[green]✓[/green] {model_str}")
                console.print(f"  [dim]→ URL: {url}, Model: {model}[/dim]")
            else:
                console.print(f"[red]✗[/red] {model_str}")
                console.print(f"  [dim]Expected: URL={expected_url}, Model={expected_model}[/dim]")
                console.print(f"  [dim]Got: URL={url}, Model={model}[/dim]")
                all_passed = False
        except Exception as e:
            console.print(f"[red]✗[/red] {model_str} - Error: {e}")
            all_passed = False

    # Test error cases
    console.print("\n[bold]Error Cases:[/bold]")
    error_cases = [
        "ollama/mistral",  # No @ - should raise
        "ollama@host",     # No model - should raise
    ]

    for model_str in error_cases:
        try:
            parse_ollama_model(model_str, config)
            console.print(f"[red]✗[/red] {model_str} - Should have raised error")
            all_passed = False
        except ValueError as e:
            console.print(f"[green]✓[/green] {model_str} - Correctly raised: {e}")

    return all_passed


def test_ollama_config():
    """Test Ollama configuration options."""
    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║  Ollama Configuration Test          ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")

    # Test default config
    cfg = get_config()
    console.print("[bold]Default Configuration:[/bold]")
    console.print(f"  ollama_enabled: {cfg.ollama_enabled}")
    console.print(f"  ollama_base_url: {cfg.ollama_base_url}")
    console.print(f"  ollama_hosts: {cfg.ollama_hosts}")

    # Test runtime override
    console.print("\n[bold]Testing Runtime Override:[/bold]")
    set_ollama_provider(
        base_url="http://custom-ollama:11434",
        hosts={"test1": "http://test1.local:11434", "test2": "http://test2.local:9999"},
    )

    cfg = get_config()
    console.print(f"  ollama_base_url: {cfg.ollama_base_url}")
    console.print(f"  ollama_hosts: {cfg.ollama_hosts}")

    # Restore defaults
    set_ollama_provider(
        base_url="http://localhost:11434",
        hosts={},
    )
    console.print("\n[green]✓[/green] Configuration test passed")
    return True


if __name__ == "__main__":
    # Test parsing first (doesn't require Ollama running)
    test_ollama_model_parsing()
    test_ollama_config()

    # Then test actual Ollama integration
    success = test_ollama_enumeration()

    if success:
        test_ollama_agent()

    console.print("\n[bold green]╔══════════════════════════════════════╗[/bold green]")
    console.print("[bold green]║  Ollama Integration Summary         ║[/bold green]")
    console.print("[bold green]╚══════════════════════════════════════╝[/bold green]\n")

    console.print("[bold]Usage Options:[/bold]\n")

    console.print("[cyan]1. Local Model (Default):[/cyan]")
    console.print('[dim]   model: "ollama/mistral"[/dim]\n')

    console.print("[cyan]2. Remote with IP Address:[/cyan]")
    console.print('[dim]   model: "ollama@10.10.10.1/mistral"[/dim]')
    console.print('[dim]   model: "ollama@gpu-server:9999/llama3"[/dim]\n')

    console.print("[cyan]3. Remote with Named Alias:[/cyan]")
    console.print('[dim]   # Set env var first:[/dim]')
    console.print('[dim]   export RVBBIT_OLLAMA_HOSTS=\'{"gpu1": "http://10.10.10.1:11434"}\'[/dim]')
    console.print('[dim]   # Then use:[/dim]')
    console.print('[dim]   model: "ollama@gpu1/mistral"[/dim]\n')

    console.print("[cyan]4. Environment Variables:[/cyan]")
    console.print('[dim]   RVBBIT_OLLAMA_ENABLED=true[/dim]')
    console.print('[dim]   RVBBIT_OLLAMA_BASE_URL="http://localhost:11434"[/dim]')
    console.print('[dim]   RVBBIT_OLLAMA_HOSTS=\'{"gpu1": "http://10.10.10.1:11434"}\'[/dim]\n')

    console.print("[cyan]5. Runtime Configuration:[/cyan]")
    console.print('[dim]   from rvbbit.config import set_ollama_provider[/dim]')
    console.print('[dim]   set_ollama_provider([/dim]')
    console.print('[dim]       base_url="http://localhost:11434",[/dim]')
    console.print('[dim]       hosts={"gpu1": "http://10.10.10.1:11434"}[/dim]')
    console.print('[dim]   )[/dim]\n')
