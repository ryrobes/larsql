import time
import sys
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rvbbit.state import list_running_sessions

console = Console()

def monitor_loop():
    with Live(console=console, refresh_per_second=1) as live:
        while True:
            sessions = list_running_sessions()
            
            table = Table(title="🌊 Active RVBBIT Cascades")
            table.add_column("Session ID", style="cyan")
            table.add_column("Cascade", style="magenta")
            table.add_column("Phase", style="green")
            table.add_column("Depth", style="blue")
            table.add_column("Last Update", style="yellow")
            
            for s in sessions:
                last_up = time.time() - s["last_update"]
                table.add_row(
                    s["session_id"],
                    s["cascade_id"],
                    s.get("current_cell", "-"),
                    str(s.get("depth", 0)),
                    f"{last_up:.1f}s ago"
                )
            
            live.update(table)
            time.sleep(1)

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
