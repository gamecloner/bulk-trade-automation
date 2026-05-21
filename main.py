"""
Bulk Trade Bot — THE GOD KILLER
Main entry point with interactive CLI menu.

Usage:
    python main.py                  # Interactive menu
    python main.py --scalp          # Start scalping directly
    python main.py --arb            # Start arbitrage directly
    python main.py --all            # Start all strategies
    python main.py --monitor        # Monitor only (no trades)
    python main.py --sim            # Simulation mode (no real trades)
"""

import asyncio
import sys
import os
import signal
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.prompt import Prompt, IntPrompt
from rich import box

from config.settings import Settings
from core.engine import TradingEngine
from ui.dashboard import Dashboard
from utils.logger import log, setup_logger

console = Console()


# ── ASCII Menu Banner ─────────────────────────────────────────────

MENU_BANNER = """[bold bright_cyan]
 ████████╗██╗  ██╗███████╗     ██████╗  ██████╗ ██████╗     ██╗  ██╗██╗██╗     ██╗     ███████╗██████╗
 ╚══██╔══╝██║  ██║██╔════╝    ██╔════╝ ██╔═══██╗██╔══██╗    ██║ ██╔╝██║██║     ██║     ██╔════╝██╔══██╗
    ██║   ███████║█████╗      ██║  ███╗██║   ██║██║  ██║    █████╔╝ ██║██║     ██║     █████╗  ██████╔╝
    ██║   ██╔══██║██╔══╝      ██║   ██║██║   ██║██║  ██║    ██╔═██╗ ██║██║     ██║     ██╔══╝  ██╔══██╗
    ██║   ██║  ██║███████╗    ╚██████╔╝╚██████╔╝██████╔╝    ██║  ██╗██║███████╗███████╗███████╗██║  ██║
    ╚═╝   ╚═╝  ╚═╝╚══════╝     ╚═════╝  ╚═════╝ ╚═════╝     ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝
[/bold bright_cyan]
[bright_white]━━━━━━━━━━━━━ ⚡ BULK TRADE ALGORITHMIC TRADING BOT ⚡ ━━━━━━━━━━━━━━[/bright_white]
[dim italic]          Perpetual DEX Automation │ Scalping │ Arbitrage          [/dim italic]"""


def show_menu():
    """Display the main interactive menu."""
    console.clear()
    console.print(MENU_BANNER)
    console.print()

    menu_items = [
        ("1", "Start Scalping Bot", "bright_green", "High-frequency EMA/RSI scalping"),
        ("2", "Start Arbitrage Bot", "bright_yellow", "Cross-venue price discrepancy"),
        ("3", "Start Both Strategies", "bright_cyan", "Multi-strategy mode"),
        ("4", "Monitor Only", "bright_magenta", "Watch prices without trading"),
        ("5", "Simulation Mode", "bright_blue", "Paper trading with simulated prices"),
        ("6", "Configuration", "white", "View/edit settings"),
        ("7", "View Trade History", "dim", "Review past trades"),
        ("0", "Exit", "bright_red", "Shutdown"),
    ]

    table_lines = []
    for key, label, color, desc in menu_items:
        table_lines.append(
            f"  [bold bright_white]\\[{key}][/]  [{color}]{label:<28}[/] [dim]│ {desc}[/]"
        )

    menu_text = "\n".join(table_lines)
    console.print(Panel(
        menu_text,
        title="[bold bright_white]⚡ MAIN MENU[/]",
        box=box.DOUBLE,
        style="bright_cyan",
        padding=(1, 2),
    ))
    console.print()


def show_config():
    """Display current configuration."""
    settings = Settings.get()
    console.print()
    console.print(Panel(
        f"""[bold]Platform:[/]        {settings.platform.url}
[bold]Testnet:[/]         {'✅ Yes' if settings.platform.testnet else '❌ No (MAINNET!)'}
[bold]Execution Mode:[/]  {settings.trading.execution_mode}
[bold]RPC URL:[/]         {settings.platform.rpc_url}

[bold bright_white]── Trading ──[/]
[bold]Pairs:[/]           {', '.join(settings.trading.trading_pairs)}
[bold]Default Leverage:[/] {settings.trading.default_leverage}x
[bold]Max Leverage:[/]     {settings.trading.max_leverage}x
[bold]Max Position:[/]     ${settings.trading.max_position_size_usd:,.2f}
[bold]Max Positions:[/]    {settings.trading.max_concurrent_positions}

[bold bright_white]── Scalping ──[/]
[bold]Profit Target:[/]   {settings.scalping.profit_target_pct}%
[bold]Stop Loss:[/]       {settings.scalping.stop_loss_pct}%
[bold]Cooldown:[/]        {settings.scalping.cooldown_seconds}s
[bold]EMA Fast/Slow:[/]   {settings.scalping.ema_fast}/{settings.scalping.ema_slow}

[bold bright_white]── Arbitrage ──[/]
[bold]Min Spread:[/]      {settings.arbitrage.min_spread_pct}%
[bold]Slippage Tol:[/]    {settings.arbitrage.slippage_tolerance_pct}%
[bold]Exec Window:[/]     {settings.arbitrage.execution_window_ms}ms

[bold bright_white]── Risk ──[/]
[bold]Daily Loss Limit:[/] {settings.trading.daily_loss_limit_pct}%
[bold]Max Drawdown:[/]     {settings.trading.max_drawdown_pct}%

[bold bright_white]── Browser ──[/]
[bold]Headless:[/]        {'Yes' if settings.browser.headless else 'No (visible)'}
[bold]Proxy:[/]           {settings.browser.proxy or 'None'}
[bold]Action Delay:[/]    {settings.browser.min_action_delay_ms}-{settings.browser.max_action_delay_ms}ms""",
        title="[bold bright_white]⚙️ CONFIGURATION[/]",
        box=box.ROUNDED,
        style="bright_blue",
        padding=(1, 2),
    ))

    console.print()
    console.print("[dim]Edit .env file to change settings, then restart.[/]")
    console.print()
    Prompt.ask("[dim]Press Enter to return to menu[/]")


def show_trade_history():
    """Display trade history from CSV."""
    settings = Settings.get()
    trade_file = settings.logging.trade_log_file

    console.print()
    if not trade_file.exists():
        console.print("[yellow]No trade history found yet.[/]")
        Prompt.ask("[dim]Press Enter to return[/]")
        return

    import csv
    with open(trade_file, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]Trade history is empty.[/]")
        Prompt.ask("[dim]Press Enter to return[/]")
        return

    from rich.table import Table
    table = Table(title="Trade History", box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Time", width=20)
    table.add_column("Pair", width=10)
    table.add_column("Side", width=6)
    table.add_column("Price", justify="right", width=14)
    table.add_column("Qty", justify="right", width=10)
    table.add_column("P&L", justify="right", width=10)
    table.add_column("Strategy", width=8)
    table.add_column("Latency", justify="right", width=8)

    for row in rows[-20:]:  # Last 20 trades
        side_color = "green" if row.get("side", "") in ("buy", "long") else "red"
        pnl = float(row.get("pnl", 0))
        pnl_color = "green" if pnl >= 0 else "red"
        table.add_row(
            row.get("timestamp", "")[:19],
            row.get("pair", ""),
            f"[{side_color}]{row.get('side', '').upper()}[/]",
            f"${float(row.get('price', 0)):,.2f}",
            row.get("quantity", ""),
            f"[{pnl_color}]${pnl:+,.4f}[/]",
            row.get("strategy", ""),
            f"{float(row.get('latency_ms', 0)):.0f}ms",
        )

    console.print(table)
    console.print(f"\n[dim]Showing last {min(20, len(rows))} of {len(rows)} trades[/]")
    console.print()
    Prompt.ask("[dim]Press Enter to return[/]")


# ── Engine Runner ─────────────────────────────────────────────────

async def run_engine(
    enable_scalper: bool = True,
    enable_arbitrage: bool = True,
    monitor_only: bool = False,
    use_simulation: bool = False,
):
    """Initialize and run the trading engine with dashboard."""
    engine = TradingEngine()

    # Handle graceful shutdown
    shutdown_event = asyncio.Event()

    def on_shutdown(sig, frame):
        console.print("\n[bold yellow]Shutting down...[/]")
        shutdown_event.set()

    # Register signal handlers (Windows compatible)
    try:
        signal.signal(signal.SIGINT, on_shutdown)
        signal.signal(signal.SIGTERM, on_shutdown)
    except (ValueError, OSError):
        pass  # Can't set signal handler in some environments

    # Initialize
    console.print("[cyan]Initializing engine...[/]")
    if not await engine.initialize():
        console.print("[bold red]Engine initialization failed![/]")
        console.print("[yellow]Falling back to simulation mode...[/]")
        use_simulation = True

    # Start engine and dashboard concurrently
    dashboard = Dashboard(engine)

    engine_task = asyncio.create_task(
        engine.start(
            enable_scalper=enable_scalper and not monitor_only,
            enable_arbitrage=enable_arbitrage and not monitor_only,
            use_simulation=use_simulation,
            monitor_only=monitor_only,
        )
    )

    dashboard_task = asyncio.create_task(dashboard.run(refresh_rate=0.5))

    # Wait for shutdown signal
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        dashboard.stop()
        await engine.stop()
        engine_task.cancel()
        dashboard_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
        try:
            await dashboard_task
        except asyncio.CancelledError:
            pass

    console.print("[bold green]Bot stopped cleanly.[/]")


# ── Main ──────────────────────────────────────────────────────────

def main():
    """Main entry point — interactive menu or CLI args."""

    # Handle CLI arguments
    args = sys.argv[1:]
    if args:
        if "--scalp" in args:
            asyncio.run(run_engine(enable_scalper=True, enable_arbitrage=False))
            return
        elif "--arb" in args:
            asyncio.run(run_engine(enable_scalper=False, enable_arbitrage=True))
            return
        elif "--all" in args:
            asyncio.run(run_engine(enable_scalper=True, enable_arbitrage=True))
            return
        elif "--monitor" in args:
            asyncio.run(run_engine(monitor_only=True))
            return
        elif "--sim" in args:
            asyncio.run(run_engine(use_simulation=True))
            return
        elif "--help" in args or "-h" in args:
            console.print(__doc__)
            return

    # Interactive menu loop
    while True:
        show_menu()
        choice = Prompt.ask(
            "[bold bright_white]Select option[/]",
            choices=["0", "1", "2", "3", "4", "5", "6", "7"],
            default="5",
        )

        if choice == "0":
            console.print("[bright_cyan]Goodbye! ⚡[/]")
            break
        elif choice == "1":
            asyncio.run(run_engine(enable_scalper=True, enable_arbitrage=False))
        elif choice == "2":
            asyncio.run(run_engine(enable_scalper=False, enable_arbitrage=True))
        elif choice == "3":
            asyncio.run(run_engine(enable_scalper=True, enable_arbitrage=True))
        elif choice == "4":
            asyncio.run(run_engine(monitor_only=True))
        elif choice == "5":
            asyncio.run(run_engine(use_simulation=True))
        elif choice == "6":
            show_config()
        elif choice == "7":
            show_trade_history()


if __name__ == "__main__":
    main()
