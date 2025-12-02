from .base import simple_eddy

@simple_eddy
def ask_human(question: str) -> str:
    """
    Pauses execution to ask the human user a question.
    Useful for clarifications, approvals, or additional data.
    """
    # In a CLI environment, we use input().
    # In a web app, this would be replaced by a custom callback 
    # (e.g., sending a websocket event and waiting).
    from rich.console import Console
    from rich.prompt import Prompt
    
    console = Console()
    console.print(f"\n[bold yellow]🤖 Agent asks:[/bold yellow] {question}")
    answer = Prompt.ask("[bold green]👤 You[/bold green]")
    return answer
