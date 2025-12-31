import time
import sys
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rvbbit.session_state import get_active_sessions

console = Console()

def monitor_loop():
    with Live(console=console, refresh_per_second=1) as live:
        while True:
            sessions = get_active_sessions()

            table = Table(title="Active RVBBIT Cascades")
            table.add_column("Session ID", style="cyan")
            table.add_column("Cascade", style="magenta")
            table.add_column("Cell", style="green")
            table.add_column("Status", style="blue")
            table.add_column("Last Update", style="yellow")

            now = datetime.now(timezone.utc)
            for s in sessions:
                # Calculate time since last update
                if s.updated_at:
                    delta = (now - s.updated_at).total_seconds()
                    last_up = f"{delta:.1f}s ago"
                else:
                    last_up = "-"

                table.add_row(
                    s.session_id,
                    s.cascade_id,
                    s.current_cell or "-",
                    s.status.value if s.status else "-",
                    last_up
                )

            live.update(table)
            time.sleep(1)

if __name__ == "__main__":
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
