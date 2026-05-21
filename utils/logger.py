"""
Structured logging with rotation, trade logging, and performance tracking.
Uses loguru for clean, colorful output with file rotation.
"""

import sys
import csv
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from loguru import logger as _logger


class TradeLogger:
    """
    Dedicated CSV logger for trade history.
    Each trade is appended as a row for post-analysis.
    """

    HEADERS = [
        "timestamp", "trade_id", "pair", "side", "order_type",
        "price", "quantity", "leverage", "pnl", "pnl_pct",
        "strategy", "execution_mode", "latency_ms", "status", "notes"
    ]

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    def _ensure_headers(self):
        if not self._initialized:
            if not self.filepath.exists() or self.filepath.stat().st_size == 0:
                with open(self.filepath, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(self.HEADERS)
            self._initialized = True

    def log_trade(
        self,
        trade_id: str,
        pair: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
        leverage: int = 1,
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        strategy: str = "",
        execution_mode: str = "",
        latency_ms: float = 0.0,
        status: str = "filled",
        notes: str = "",
    ):
        """Append a single trade record to the CSV."""
        self._ensure_headers()
        row = [
            datetime.now(timezone.utc).isoformat(),
            trade_id,
            pair,
            side,
            order_type,
            f"{price:.8f}",
            f"{quantity:.8f}",
            leverage,
            f"{pnl:.4f}",
            f"{pnl_pct:.4f}",
            strategy,
            execution_mode,
            f"{latency_ms:.2f}",
            status,
            notes,
        ]
        with open(self.filepath, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)


class PerformanceTracker:
    """Tracks bot performance metrics in-memory."""

    def __init__(self):
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_pnl = 0.0
        self.peak_balance = 0.0
        self.max_drawdown = 0.0
        self.start_time: Optional[datetime] = None
        self._trade_pnls: list = []

    def record_trade(self, pnl: float, balance: float):
        """Record a completed trade's P&L."""
        self.total_trades += 1
        self.total_pnl += pnl
        self._trade_pnls.append(pnl)

        if pnl > 0:
            self.winning_trades += 1
        elif pnl < 0:
            self.losing_trades += 1

        # Track drawdown
        if balance > self.peak_balance:
            self.peak_balance = balance
        if self.peak_balance > 0:
            current_drawdown = ((self.peak_balance - balance) / self.peak_balance) * 100
            self.max_drawdown = max(self.max_drawdown, current_drawdown)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def avg_pnl(self) -> float:
        if not self._trade_pnls:
            return 0.0
        return sum(self._trade_pnls) / len(self._trade_pnls)

    @property
    def profit_factor(self) -> float:
        gains = sum(p for p in self._trade_pnls if p > 0)
        losses = abs(sum(p for p in self._trade_pnls if p < 0))
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    @property
    def sharpe_ratio(self) -> float:
        """Simplified Sharpe ratio (assuming risk-free rate = 0)."""
        if len(self._trade_pnls) < 2:
            return 0.0
        import numpy as np
        returns = np.array(self._trade_pnls)
        std = np.std(returns)
        if std == 0:
            return 0.0
        return float(np.mean(returns) / std)

    def summary(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_pnl": f"${self.total_pnl:.2f}",
            "avg_pnl": f"${self.avg_pnl:.4f}",
            "profit_factor": f"{self.profit_factor:.2f}",
            "max_drawdown": f"{self.max_drawdown:.2f}%",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
        }


def setup_logger(log_level: str = "INFO", log_file: Optional[Path] = None):
    """
    Configure loguru with console + file output.
    Call once at startup.
    """
    # Remove default handler
    _logger.remove()

    # Console handler — colorful, concise
    _logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> │ "
            "<level>{level: <8}</level> │ "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> │ "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File handler — full details, rotated daily
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _logger.add(
            str(log_file),
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="1 day",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
        )

    return _logger


# Global convenience — import `log` from this module
log = _logger
