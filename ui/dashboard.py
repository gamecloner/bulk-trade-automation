"""
Terminal Dashboard — Rich live-updating UI for monitoring the trading bot.
Displays P&L, positions, signals, orderbook, and system status.
"""

import asyncio
import time
from typing import Optional

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

from utils.logger import log


# ── ASCII Art Banner ──────────────────────────────────────────────

BANNER = """
[bold bright_cyan]
 ████████╗██╗  ██╗███████╗     ██████╗  ██████╗ ██████╗     ██╗  ██╗██╗██╗     ██╗     ███████╗██████╗
 ╚══██╔══╝██║  ██║██╔════╝    ██╔════╝ ██╔═══██╗██╔══██╗    ██║ ██╔╝██║██║     ██║     ██╔════╝██╔══██╗
    ██║   ███████║█████╗      ██║  ███╗██║   ██║██║  ██║    █████╔╝ ██║██║     ██║     █████╗  ██████╔╝
    ██║   ██╔══██║██╔══╝      ██║   ██║██║   ██║██║  ██║    ██╔═██╗ ██║██║     ██║     ██╔══╝  ██╔══██╗
    ██║   ██║  ██║███████╗    ╚██████╔╝╚██████╔╝██████╔╝    ██║  ██╗██║███████╗███████╗███████╗██║  ██║
    ╚═╝   ╚═╝  ╚═╝╚══════╝     ╚═════╝  ╚═════╝ ╚═════╝     ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝
[/bold bright_cyan]
[dim]━━━━━━━━━━━━━━━ ⚡ BULK TRADE ALGORITHMIC TRADING BOT ⚡ ━━━━━━━━━━━━━━━[/dim]
"""


class Dashboard:
    """
    Real-time terminal dashboard using Rich library.
    Updates live with trading data from the engine.
    """

    def __init__(self, engine):
        self.engine = engine
        self.console = Console()
        self._live: Optional[Live] = None
        self._running = False

    def _make_header(self) -> Panel:
        """Create the top header panel."""
        return Panel(
            Align.center(Text.from_markup(BANNER)),
            box=box.DOUBLE,
            style="bright_cyan",
            padding=(0, 0),
        )

    def _make_status_bar(self) -> Panel:
        """Create status bar with mode, balance, P&L."""
        e = self.engine
        risk = e.risk_manager.get_state(e.balance) if e.risk_manager else None

        # Uptime
        uptime_s = int(e.uptime)
        uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m {uptime_s % 60}s"

        # P&L
        total_pnl = risk.total_pnl if risk else 0
        daily_pnl = risk.daily_pnl if risk else 0
        pnl_color = "green" if total_pnl >= 0 else "red"
        daily_color = "green" if daily_pnl >= 0 else "red"

        # Mode indicator
        mode_colors = {
            "running": "bold green",
            "monitoring": "bold yellow",
            "simulation": "bold magenta",
            "initializing": "bold cyan",
            "stopped": "bold red",
        }
        mode_style = mode_colors.get(e.mode, "white")

        status = Table(show_header=False, box=None, expand=True, padding=(0, 1))
        status.add_column(ratio=1)
        status.add_column(ratio=1)
        status.add_column(ratio=1)
        status.add_column(ratio=1)
        status.add_column(ratio=1)

        status.add_row(
            f"[bold]Mode:[/] [{mode_style}]{e.mode.upper()}[/]",
            f"[bold]Executor:[/] [cyan]{e.execution_mode}[/]",
            f"[bold]Balance:[/] [bright_white]${e.balance:,.2f}[/]",
            f"[bold]P&L:[/] [{pnl_color}]${total_pnl:+,.2f}[/]",
            f"[bold]Daily:[/] [{daily_color}]${daily_pnl:+,.2f}[/]",
        )
        status.add_row(
            f"[bold]Pairs:[/] {len(e.settings.trading.trading_pairs)}",
            f"[bold]Strategies:[/] {len(e.strategies)}",
            f"[bold]Ticks:[/] {e.tick_count:,}",
            f"[bold]Trades:[/] {e.performance.total_trades}",
            f"[bold]Uptime:[/] {uptime_str}",
        )

        return Panel(status, title="[bold bright_white]⚡ STATUS[/]", box=box.ROUNDED, style="bright_blue")

    def _make_positions_table(self) -> Panel:
        """Create positions panel."""
        table = Table(box=box.SIMPLE_HEAVY, expand=True, show_edge=False)
        table.add_column("Pair", style="bright_white", width=10)
        table.add_column("Side", width=6)
        table.add_column("Size", justify="right", width=10)
        table.add_column("Entry", justify="right", width=12)
        table.add_column("Current", justify="right", width=12)
        table.add_column("Leverage", justify="center", width=8)
        table.add_column("P&L", justify="right", width=12)
        table.add_column("P&L %", justify="right", width=8)

        positions = self.engine.order_manager.positions if self.engine.order_manager else []

        if not positions:
            table.add_row("[dim]No open positions[/]", "", "", "", "", "", "", "")
        else:
            for pos in positions:
                side_color = "green" if pos.side == "long" else "red"
                pnl_color = "green" if pos.unrealized_pnl >= 0 else "red"
                table.add_row(
                    pos.pair,
                    f"[{side_color}]{pos.side.upper()}[/]",
                    f"{pos.quantity:.4f}",
                    f"${pos.entry_price:,.2f}",
                    f"${pos.current_price:,.2f}",
                    f"{pos.leverage}x",
                    f"[{pnl_color}]${pos.unrealized_pnl:+,.2f}[/]",
                    f"[{pnl_color}]{pos.pnl_pct:+.2f}%[/]",
                )

        return Panel(table, title="[bold bright_white]📊 POSITIONS[/]", box=box.ROUNDED, style="bright_green")

    def _make_signals_panel(self) -> Panel:
        """Create signals panel."""
        table = Table(box=box.SIMPLE, expand=True, show_edge=False)
        table.add_column("Strategy", width=10)
        table.add_column("Pair", width=10)
        table.add_column("Signal", width=12)
        table.add_column("Confidence", justify="right", width=10)
        table.add_column("Reason", ratio=1)

        signals = list(self.engine.last_signals.values())
        # Show most recent 8 signals
        recent = sorted(signals, key=lambda s: s.timestamp, reverse=True)[:8]

        if not recent:
            table.add_row("[dim]Waiting for signals...[/]", "", "", "", "")
        else:
            for sig in recent:
                signal_colors = {
                    "STRONG_BUY": "bold green",
                    "BUY": "green",
                    "WEAK_BUY": "dark_green",
                    "NEUTRAL": "dim",
                    "WEAK_SELL": "dark_red",
                    "SELL": "red",
                    "STRONG_SELL": "bold red",
                }
                color = signal_colors.get(sig.signal.value, "white")
                conf_bar = "█" * int(sig.confidence * 10) + "░" * (10 - int(sig.confidence * 10))

                table.add_row(
                    sig.strategy_name,
                    sig.pair,
                    f"[{color}]{sig.signal.value}[/]",
                    f"[{color}]{conf_bar} {sig.confidence:.0%}[/]",
                    f"[dim]{sig.reason[:50]}[/]" if sig.reason else "",
                )

        return Panel(table, title="[bold bright_white]📡 SIGNALS[/]", box=box.ROUNDED, style="bright_yellow")

    def _make_recent_trades(self) -> Panel:
        """Create recent trades panel."""
        table = Table(box=box.SIMPLE, expand=True, show_edge=False)
        table.add_column("Time", width=8)
        table.add_column("Side", width=6)
        table.add_column("Pair", width=10)
        table.add_column("Price", justify="right", width=12)
        table.add_column("Qty", justify="right", width=10)
        table.add_column("Status", width=10)

        orders = self.engine.order_manager.get_recent_orders(6) if self.engine.order_manager else []

        if not orders:
            table.add_row("[dim]No trades yet...[/]", "", "", "", "", "")
        else:
            for order in orders:
                t = time.strftime("%H:%M:%S", time.localtime(order.created_at))
                side_color = "green" if order.side.value in ("buy", "long") else "red"
                status_color = "green" if order.status == "filled" else "red" if order.status == "rejected" else "yellow"
                table.add_row(
                    t,
                    f"[{side_color}]{order.side.value.upper()}[/]",
                    order.pair,
                    f"${order.filled_price or order.price:,.2f}",
                    f"{order.quantity:.4f}",
                    f"[{status_color}]{order.status.upper() if isinstance(order.status, str) else order.status.value.upper()}[/]",
                )

        return Panel(table, title="[bold bright_white]📜 RECENT TRADES[/]", box=box.ROUNDED, style="bright_magenta")

    def _make_prices_panel(self) -> Panel:
        """Create live prices panel."""
        table = Table(box=box.SIMPLE, expand=True, show_edge=False)
        table.add_column("Pair", width=10)
        table.add_column("Price", justify="right", width=14)
        table.add_column("Bid", justify="right", width=12)
        table.add_column("Ask", justify="right", width=12)
        table.add_column("Spread", justify="right", width=8)
        table.add_column("Source", width=10)

        all_prices = self.engine.price_feed.get_all_latest()

        if not all_prices:
            table.add_row("[dim]Connecting...[/]", "", "", "", "", "")
        else:
            for pair, tick in sorted(all_prices.items()):
                age = time.time() - tick.timestamp
                freshness = "[green]●[/]" if age < 5 else "[yellow]●[/]" if age < 30 else "[red]●[/]"
                table.add_row(
                    f"{freshness} {pair}",
                    f"[bright_white]${tick.price:,.2f}[/]",
                    f"[green]${tick.bid:,.2f}[/]" if tick.bid > 0 else "[dim]-[/]",
                    f"[red]${tick.ask:,.2f}[/]" if tick.ask > 0 else "[dim]-[/]",
                    f"{tick.spread_pct:.3f}%" if tick.spread_pct > 0 else "[dim]-[/]",
                    tick.source,
                )

        return Panel(table, title="[bold bright_white]💰 LIVE PRICES[/]", box=box.ROUNDED, style="bright_cyan")

    def _make_risk_panel(self) -> Panel:
        """Create risk metrics panel."""
        risk = self.engine.risk_manager.get_state(self.engine.balance) if self.engine.risk_manager else None
        perf = self.engine.performance

        table = Table(box=None, expand=True, show_header=False)
        table.add_column(ratio=1)
        table.add_column(ratio=1)

        if risk:
            ks_indicator = "[bold red]🔴 ACTIVE[/]" if risk.is_kill_switch_active else "[bold green]🟢 OK[/]"
            dd_color = "green" if risk.max_drawdown_hit < 5 else "yellow" if risk.max_drawdown_hit < 8 else "red"

            table.add_row(
                f"[bold]Kill Switch:[/] {ks_indicator}",
                f"[bold]Drawdown:[/] [{dd_color}]{risk.max_drawdown_hit:.2f}%[/]",
            )
            table.add_row(
                f"[bold]Positions:[/] {risk.open_positions}/{self.engine.settings.trading.max_concurrent_positions}",
                f"[bold]Exposure:[/] ${risk.total_exposure:,.2f}",
            )
            table.add_row(
                f"[bold]Win Rate:[/] {perf.win_rate:.1f}%",
                f"[bold]Profit Factor:[/] {perf.profit_factor:.2f}",
            )
            if risk.kill_switch_reason:
                table.add_row(f"[bold red]Reason:[/] {risk.kill_switch_reason}", "")
        else:
            table.add_row("[dim]Initializing...[/]", "")

        return Panel(table, title="[bold bright_white]🛡️ RISK[/]", box=box.ROUNDED, style="bright_red")

    def _make_layout(self) -> Layout:
        """Build the full dashboard layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=10),
            Layout(name="status", size=5),
            Layout(name="main", ratio=1),
            Layout(name="bottom", size=12),
        )

        # Main area: positions + signals
        layout["main"].split_row(
            Layout(name="left", ratio=3),
            Layout(name="right", ratio=2),
        )

        # Bottom area: trades + prices + risk
        layout["bottom"].split_row(
            Layout(name="trades", ratio=2),
            Layout(name="prices", ratio=2),
            Layout(name="risk", ratio=1),
        )

        # Populate
        layout["header"].update(self._make_header())
        layout["status"].update(self._make_status_bar())
        layout["left"].update(self._make_positions_table())
        layout["right"].update(self._make_signals_panel())
        layout["trades"].update(self._make_recent_trades())
        layout["prices"].update(self._make_prices_panel())
        layout["risk"].update(self._make_risk_panel())

        return layout

    async def run(self, refresh_rate: float = 0.5):
        """Run the dashboard with live updates."""
        self._running = True

        with Live(
            self._make_layout(),
            console=self.console,
            refresh_per_second=int(1 / refresh_rate),
            screen=True,
        ) as live:
            self._live = live
            while self._running and self.engine.is_running:
                try:
                    live.update(self._make_layout())
                except Exception as e:
                    log.debug(f"Dashboard render error: {e}")
                await asyncio.sleep(refresh_rate)

    def stop(self):
        """Stop the dashboard."""
        self._running = False
