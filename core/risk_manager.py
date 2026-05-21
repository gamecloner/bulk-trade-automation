"""
Risk Manager — Position sizing, drawdown protection, and kill switches.
Guards against catastrophic losses by enforcing strict risk parameters.
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from execution.sdk_executor import Order, Position, OrderSide
from strategies.base_strategy import TradeSignal
from utils.logger import log


@dataclass
class RiskState:
    """Current risk metrics snapshot."""
    balance: float = 0.0
    equity: float = 0.0
    starting_balance: float = 0.0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    open_positions: int = 0
    total_exposure: float = 0.0
    max_drawdown_hit: float = 0.0
    is_kill_switch_active: bool = False
    kill_switch_reason: str = ""


class RiskManager:
    """
    Enforces risk limits and position sizing rules.

    Kill Switch Triggers:
    - Daily loss exceeds daily_loss_limit_pct
    - Max drawdown exceeds max_drawdown_pct
    - Manual emergency stop
    """

    def __init__(
        self,
        max_position_size_usd: float = 1000.0,
        max_concurrent_positions: int = 3,
        daily_loss_limit_pct: float = 5.0,
        max_drawdown_pct: float = 10.0,
        max_leverage: int = 20,
        max_single_trade_risk_pct: float = 2.0,
    ):
        self.max_position_size_usd = max_position_size_usd
        self.max_concurrent_positions = max_concurrent_positions
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_leverage = max_leverage
        self.max_single_trade_risk_pct = max_single_trade_risk_pct

        # State tracking
        self._starting_balance: float = 0.0
        self._peak_balance: float = 0.0
        self._daily_start_balance: float = 0.0
        self._daily_pnl: float = 0.0
        self._day_start_time: float = time.time()
        self._kill_switch: bool = False
        self._kill_switch_reason: str = ""
        self._trade_history: List[Dict] = []
        self._current_positions: List[Position] = []

    def initialize(self, balance: float):
        """Set initial balance. Call once at startup."""
        self._starting_balance = balance
        self._peak_balance = balance
        self._daily_start_balance = balance
        log.info(f"Risk manager initialized with balance: ${balance:.2f}")

    def update_balance(self, balance: float):
        """Update current balance and check risk limits."""
        if balance > self._peak_balance:
            self._peak_balance = balance

        # Check for new trading day
        if time.time() - self._day_start_time > 86400:
            self._daily_start_balance = balance
            self._daily_pnl = 0.0
            self._day_start_time = time.time()
            log.info("New trading day — daily P&L reset")

        # Calculate daily P&L
        self._daily_pnl = balance - self._daily_start_balance
        daily_pnl_pct = (self._daily_pnl / self._daily_start_balance * 100) if self._daily_start_balance > 0 else 0

        # Calculate drawdown
        drawdown_pct = 0.0
        if self._peak_balance > 0:
            drawdown_pct = ((self._peak_balance - balance) / self._peak_balance) * 100

        # ── Kill Switch Checks ──────────────────────────────────
        if daily_pnl_pct < -self.daily_loss_limit_pct:
            self._activate_kill_switch(
                f"Daily loss limit hit: {daily_pnl_pct:.2f}% (limit: -{self.daily_loss_limit_pct}%)"
            )

        if drawdown_pct > self.max_drawdown_pct:
            self._activate_kill_switch(
                f"Max drawdown hit: {drawdown_pct:.2f}% (limit: {self.max_drawdown_pct}%)"
            )

    def update_positions(self, positions: List[Position]):
        """Update current open positions."""
        self._current_positions = positions

    def _activate_kill_switch(self, reason: str):
        """Activate emergency kill switch — stops all trading."""
        if not self._kill_switch:
            self._kill_switch = True
            self._kill_switch_reason = reason
            log.error(f"🚨 KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Manually deactivate the kill switch."""
        self._kill_switch = False
        self._kill_switch_reason = ""
        log.warning("Kill switch manually deactivated")

    # ── Pre-Trade Checks ──────────────────────────────────────

    def can_open_position(self, signal: TradeSignal, balance: float) -> tuple:
        """
        Check if a new position is allowed given current risk constraints.
        Returns (allowed: bool, reason: str).
        """
        # Kill switch check
        if self._kill_switch:
            return False, f"Kill switch active: {self._kill_switch_reason}"

        # Max concurrent positions
        if len(self._current_positions) >= self.max_concurrent_positions:
            return False, f"Max positions reached ({self.max_concurrent_positions})"

        # Check if we already have a position in this pair
        for pos in self._current_positions:
            if pos.pair == signal.pair:
                return False, f"Already have position in {signal.pair}"

        # Leverage check
        if signal.suggested_leverage > self.max_leverage:
            return False, f"Leverage {signal.suggested_leverage}x exceeds max {self.max_leverage}x"

        # Balance check
        if balance <= 0:
            return False, "No balance available"

        return True, "OK"

    def calculate_position_size(
        self,
        signal: TradeSignal,
        balance: float,
        current_price: float,
    ) -> float:
        """
        Calculate the optimal position size based on risk parameters.
        Uses fixed-fractional position sizing.
        """
        if balance <= 0 or current_price <= 0:
            return 0.0

        # Maximum risk per trade (as USD)
        max_risk_usd = balance * (self.max_single_trade_risk_pct / 100)

        # Position size based on stop-loss distance
        if signal.stop_loss > 0 and current_price > 0:
            stop_distance_pct = abs(current_price - signal.stop_loss) / current_price
            if stop_distance_pct > 0:
                # Size = Risk / (Stop Distance * Leverage)
                position_size_usd = max_risk_usd / stop_distance_pct
            else:
                position_size_usd = max_risk_usd
        else:
            # Fallback: fixed percentage of balance
            position_size_usd = balance * (5.0 / 100)  # 5% default

        # Apply position size limits
        position_size_usd = min(position_size_usd, self.max_position_size_usd)
        position_size_usd = min(position_size_usd, balance * 0.5)  # Never risk more than 50% of balance

        # Convert to quantity
        quantity = position_size_usd / current_price
        return round(quantity, 6)

    def validate_order(self, order: Order, balance: float) -> tuple:
        """
        Final validation before order submission.
        Returns (valid: bool, reason: str).
        """
        if self._kill_switch:
            return False, f"Kill switch: {self._kill_switch_reason}"

        notional = order.quantity * order.price * order.leverage
        if notional > self.max_position_size_usd * order.leverage:
            return False, f"Notional ${notional:.2f} exceeds max"

        if order.leverage > self.max_leverage:
            return False, f"Leverage {order.leverage}x exceeds max {self.max_leverage}x"

        # Margin requirement check
        margin_required = (order.quantity * order.price) / order.leverage if order.leverage > 0 else order.quantity * order.price
        if margin_required > balance * 0.8:  # Keep 20% buffer
            return False, f"Margin ${margin_required:.2f} exceeds 80% of balance ${balance:.2f}"

        return True, "OK"

    def record_trade(self, pnl: float, pair: str):
        """Record a completed trade for risk tracking."""
        self._daily_pnl += pnl
        self._trade_history.append({
            "pair": pair,
            "pnl": pnl,
            "timestamp": time.time(),
            "daily_pnl": self._daily_pnl,
        })

    def get_state(self, balance: float = 0.0) -> RiskState:
        """Get current risk state snapshot."""
        daily_pnl_pct = (self._daily_pnl / self._daily_start_balance * 100) if self._daily_start_balance > 0 else 0
        drawdown = ((self._peak_balance - balance) / self._peak_balance * 100) if self._peak_balance > 0 else 0

        return RiskState(
            balance=balance,
            equity=balance + sum(p.unrealized_pnl for p in self._current_positions),
            starting_balance=self._starting_balance,
            total_pnl=balance - self._starting_balance,
            daily_pnl=self._daily_pnl,
            open_positions=len(self._current_positions),
            total_exposure=sum(p.notional for p in self._current_positions),
            max_drawdown_hit=drawdown,
            is_kill_switch_active=self._kill_switch,
            kill_switch_reason=self._kill_switch_reason,
        )

    @property
    def is_trading_allowed(self) -> bool:
        return not self._kill_switch
