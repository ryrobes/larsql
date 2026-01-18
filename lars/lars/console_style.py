"""
Console styling utilities for LARS.

Provides Rich-styled prefixes and formatting to replace emoji usage
in console output with eye-catching colored text.

Usage:
    from lars.console_style import S, styled_print

    # Use style prefixes in Rich console.print():
    console.print(f"{S.OK} Task completed")
    console.print(f"{S.ERR} Something failed")

    # Or use styled_print for plain print() with Rich markup:
    styled_print(f"{S.WARN} Watch out!")
"""

from rich.console import Console
from rich.text import Text

# Module-level console instance
_console = Console()


class S:
    """
    Style prefixes for console output.

    These replace emoji characters with Rich-styled text markers
    that are visually distinctive and professional.

    Categories:
    - Status: OK, ERR, WARN, INFO
    - Actions: RUN, DONE, SKIP, RETRY
    - Resources: DB, LINK, SAVE, LOAD
    - Progress: START, STOP, PAUSE
    - Features: PARALLEL, PREWARM, MAP, CASCADE
    """

    # === STATUS INDICATORS ===
    # Success/completion (replaces: ✓, ✅)
    OK = "[bold green][OK][/bold green]"
    DONE = "[bold green][DONE][/bold green]"
    PASS = "[bold green][PASS][/bold green]"
    WIN = "[bold green][WIN][/bold green]"

    # Error/failure (replaces: ❌)
    ERR = "[bold red][ERR][/bold red]"
    FAIL = "[bold red][FAIL][/bold red]"

    # Warning (replaces: ⚠️)
    WARN = "[bold yellow][WARN][/bold yellow]"

    # Info (replaces: ℹ️)
    INFO = "[bold blue][INFO][/bold blue]"
    NOTE = "[bold blue][NOTE][/bold blue]"

    # === ACTION INDICATORS ===
    # Running/executing (replaces: 🚀, ▶️)
    RUN = "[bold magenta][RUN][/bold magenta]"
    EXEC = "[bold magenta][EXEC][/bold magenta]"
    START = "[bold magenta][START][/bold magenta]"
    LAUNCH = "[bold magenta][LAUNCH][/bold magenta]"

    # Stopping/pausing (replaces: ⏸️, ⏹️)
    STOP = "[bold red][STOP][/bold red]"
    PAUSE = "[bold yellow][PAUSE][/bold yellow]"

    # Skip (replaces: ⏭️)
    SKIP = "[dim][SKIP][/dim]"

    # Delete/remove (replaces: 🗑️)
    DEL = "[bold red][DEL][/bold red]"

    # Retry/loop (replaces: 🔄)
    RETRY = "[bold cyan][RETRY][/bold cyan]"
    LOOP = "[bold cyan][LOOP][/bold cyan]"
    SYNC = "[bold cyan][SYNC][/bold cyan]"

    # === RESOURCE INDICATORS ===
    # Database/storage (replaces: 💾, 🗄️)
    DB = "[bold blue][DB][/bold blue]"
    QUERY = "[bold blue][QUERY][/bold blue]"
    SAVE = "[bold blue][SAVE][/bold blue]"
    LOAD = "[bold blue][LOAD][/bold blue]"
    STORE = "[bold blue][STORE][/bold blue]"

    # Connection/link (replaces: 🔗)
    LINK = "[bold cyan][LINK][/bold cyan]"
    ATTACH = "[bold cyan][ATTACH][/bold cyan]"
    CONN = "[bold cyan][CONN][/bold cyan]"

    # Config/setup (replaces: 🔧, ⚙️)
    CFG = "[bold white][CFG][/bold white]"
    SETUP = "[bold white][SETUP][/bold white]"
    INIT = "[bold white][INIT][/bold white]"

    # === FEATURE INDICATORS ===
    # Parallel/fast (replaces: ⚡)
    FAST = "[bold yellow][FAST][/bold yellow]"
    PARALLEL = "[bold yellow][PARALLEL][/bold yellow]"

    # Prewarm/cache (replaces: 🔥)
    PREWARM = "[bold red][PREWARM][/bold red]"
    CACHE = "[bold red][CACHE][/bold red]"
    HOT = "[bold red][HOT][/bold red]"

    # Map/batch operations
    MAP = "[bold magenta][MAP][/bold magenta]"
    BATCH = "[bold magenta][BATCH][/bold magenta]"

    # Cascade/flow (replaces: cascade-related emojis)
    CASCADE = "[bold cyan][CASCADE][/bold cyan]"
    CELL = "[bold cyan][CELL][/bold cyan]"
    FLOW = "[bold cyan][FLOW][/bold cyan]"
    TAKE = "[bold blue][TAKE][/bold blue]"
    PIPELINE = "[bold cyan][PIPE][/bold cyan]"
    FOLDER = "[dim][DIR][/dim]"
    FILE = "[dim][FILE][/dim]"

    # === VALIDATION/SECURITY ===
    # Ward/guard (replaces: 🛡️)
    WARD = "[bold cyan][WARD][/bold cyan]"
    GUARD = "[bold cyan][GUARD][/bold cyan]"
    CHECK = "[bold cyan][CHECK][/bold cyan]"

    # === AI/MODEL INDICATORS ===
    # Agent/model (replaces: 🤖)
    AGENT = "[bold magenta][AGENT][/bold magenta]"
    MODEL = "[bold magenta][MODEL][/bold magenta]"
    LLM = "[bold magenta][LLM][/bold magenta]"

    # Analysis/thinking (replaces: 🧠)
    THINK = "[bold magenta][THINK][/bold magenta]"
    ANALYZE = "[bold magenta][ANALYZE][/bold magenta]"

    # === UI/INTERACTION ===
    # Screenshot/image (replaces: 📸, 📷)
    SNAP = "[bold white][SNAP][/bold white]"
    IMG = "[bold white][IMG][/bold white]"
    VIDEO = "[bold white][VIDEO][/bold white]"

    # Chart/data (replaces: 📊)
    CHART = "[bold white][CHART][/bold white]"
    DATA = "[bold white][DATA][/bold white]"

    # Web/browser (replaces: 🌐)
    WEB = "[bold blue][WEB][/bold blue]"
    BROWSER = "[bold blue][BROWSER][/bold blue]"

    # Notes/clipboard (replaces: 📝, 📋)
    NOTES = "[dim][NOTES][/dim]"
    CLIP = "[dim][CLIP][/dim]"
    LOG = "[dim][LOG][/dim]"

    # === MISC ===
    # Target/goal (replaces: 🎯)
    TARGET = "[bold green][TARGET][/bold green]"
    GOAL = "[bold green][GOAL][/bold green]"

    # Search/research (replaces: 🔬)
    SEARCH = "[bold white][SEARCH][/bold white]"
    RESEARCH = "[bold white][RESEARCH][/bold white]"

    # Handoff/transfer (replaces: handoff emoji)
    HANDOFF = "[bold yellow][HANDOFF][/bold yellow]"

    # Context/memory (replaces: various)
    CTX = "[bold white][CTX][/bold white]"
    MEM = "[bold white][MEM][/bold white]"

    # Running status indicators (replaces: 🟢, 🟡, 🔴)
    STATUS_OK = "[bold green][RUNNING][/bold green]"
    STATUS_WARN = "[bold yellow][DEGRADED][/bold yellow]"
    STATUS_ERR = "[bold red][DOWN][/bold red]"

    # Background job status
    JOB = "[bold blue][JOB][/bold blue]"
    BG = "[bold blue][BG][/bold blue]"

    # Tips/help (replaces: 💡)
    TIP = "[bold yellow][TIP][/bold yellow]"
    HELP = "[bold yellow][HELP][/bold yellow]"

    # === ADDITIONAL STYLES (added for migration) ===
    # Mutation/genetic (replaces: 🧬)
    MUT = "[bold yellow][MUT][/bold yellow]"

    # View/inspect (replaces: 👁️)
    VIEW = "[dim cyan][VIEW][/dim cyan]"

    # Explosion/error (replaces: 💥)
    BOOM = "[bold red][BOOM][/bold red]"

    # Compression (replaces: 🗜️)
    COMPRESS = "[dim cyan][COMPRESS][/dim cyan]"

    # Pin/location (replaces: 📍)
    PIN = "[bold magenta][PIN][/bold magenta]"

    # Video/media (replaces: 🎬)
    VIDEO = "[dim][VIDEO][/dim]"

    # Art/image generation (replaces: 🎨)
    ART = "[bold magenta][ART][/bold magenta]"

    # Evaluation/scoring (replaces: ⚖️)
    EVAL = "[bold yellow][EVAL][/bold yellow]"


def styled_print(message: str, **kwargs):
    """
    Print a message with Rich styling.

    Wrapper around rich console.print() for use in places
    that previously used plain print() with emojis.

    Args:
        message: The message with Rich markup
        **kwargs: Additional arguments passed to console.print()
    """
    _console.print(message, **kwargs)


def get_console() -> Console:
    """Get the module's Rich console instance."""
    return _console


# Mapping from emoji to style prefix for reference during migration
EMOJI_TO_STYLE = {
    # Success
    "✓": "S.OK",
    "✅": "S.DONE",
    "🏆": "S.WIN",

    # Error
    "❌": "S.ERR",

    # Warning
    "⚠️": "S.WARN",

    # Info
    "ℹ️": "S.INFO",

    # Running
    "🚀": "S.RUN",
    "▶️": "S.EXEC",

    # Stop
    "⏹️": "S.STOP",
    "⏸️": "S.PAUSE",

    # Retry
    "🔄": "S.RETRY",

    # Database
    "💾": "S.SAVE",

    # Link
    "🔗": "S.LINK",

    # Config
    "🔧": "S.CFG",

    # Fast
    "⚡": "S.FAST",

    # Prewarm
    "🔥": "S.PREWARM",

    # Ward
    "🛡️": "S.WARD",

    # Agent
    "🤖": "S.AGENT",

    # Think
    "🧠": "S.THINK",

    # Screenshot
    "📸": "S.SNAP",
    "📷": "S.SNAP",

    # Chart
    "📊": "S.CHART",

    # Web
    "🌐": "S.WEB",

    # Notes
    "📝": "S.NOTES",
    "📋": "S.CLIP",

    # Target
    "🎯": "S.TARGET",

    # Search
    "🔬": "S.SEARCH",

    # Status
    "🟢": "S.STATUS_OK",
    "🟡": "S.STATUS_WARN",
    "🔴": "S.STATUS_ERR",

    # Tip
    "💡": "S.TIP",
}
