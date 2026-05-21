"""
Order Manager — Tracks all orders, manages fills, and coordinates execution.
Bridges strategies and executors.
"""

import asyncio
import time
import uuid
from typing import Callable, Dict, List, Optional

from execution.sdk_executor import Order, OrderSide, OrderType, OrderStatus, Position
from strategies.base_strategy import TradeSignal
from utils.logger import log, TradeLogger


class OrderManager:
    """
    Central order management system.
    Handles order creation, tracking, fill management, and history.
    """

    def __init__(self, trade_logger: Optional[TradeLogger] = None):
        self._orders: Dict[str, Order] = {}  # id -> Order
        self._active_orders: Dict[str, Order] = {}  # id -> active Order
        self._positions: List[Position] = []
        self._trade_logger = trade_logger
        self._executor = None  # Set by engine
        self._execution_mode: str = "sdk"
        self._total_trades: int = 0
        self._total_pnl: float = 0.0
        self._on_fill_callbacks: List[Callable] = []

    def set_executor(self, executor, mode: str = "sdk"):
        """Set the executor (SDK or Browser) for order routing."""
        self._executor = executor
        self._execution_mode = mode
        log.info(f"Order manager using {mode} executor")

    def on_fill(self, callback: Callable):
        """Register callback for order fills."""
        self._on_fill_callbacks.append(callback)

    # ── Order Creation ────────────────────────────────────────

    def create_order_from_signal(
        self,
        signal: TradeSignal,
        quantity: float,
        balance: float = 0.0,
    ) -> Order:
        """Create an Order from a TradeSignal."""
        order = Order(
            id=f"{signal.strategy_name[:3]}_{str(uuid.uuid4())[:6]}",
            pair=signal.pair,
            side=signal.suggested_side or OrderSide.BUY,
            order_type=OrderType.MARKET,
            price=signal.suggested_price,
            quantity=quantity,
            leverage=signal.suggested_leverage,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        return order

    # ── Order Execution ──────────────────────────────────────

    async def submit_order(self, order: Order) -> Order:
        """Submit an order through the active executor."""
        if not self._executor:
            order.status = OrderStatus.REJECTED
            order.error = "No executor configured"
            log.error("Cannot submit order: no executor set")
            return order

        # Store order
        self._orders[order.id] = order
        self._active_orders[order.id] = order

        log.info(
            f"📤 Submitting order {order.id}: "
            f"{order.side.value} {order.pair} qty={order.quantity:.6f} "
            f"@ ${order.price:.2f} {order.leverage}x [{self._execution_mode}]"
        )

        start_time = time.time()

        try:
            # Execute through the active executor
            result = await self._executor.place_order(order)
            latency_ms = (time.time() - start_time) * 1000

            # Update stored order with result
            self._orders[order.id] = result

            if result.status == OrderStatus.FILLED:
                self._total_trades += 1
                self._active_orders.pop(order.id, None)

                # Log the trade
                if self._trade_logger:
                    self._trade_logger.log_trade(
                        trade_id=result.id,
                        pair=result.pair,
                        side=result.side.value,
                        order_type=result.order_type.value,
                        price=result.filled_price or result.price,
                        quantity=result.filled_quantity or result.quantity,
                        leverage=result.leverage,
                        strategy=result.id.split("_")[0],
                        execution_mode=self._execution_mode,
                        latency_ms=latency_ms,
                        status="filled",
                    )

                # Notify fill callbacks
                for cb in self._on_fill_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(result)
                        else:
                            cb(result)
                    except Exception as e:
                        log.error(f"Fill callback error: {e}")

                log.info(
                    f"✅ Order {result.id} FILLED: {result.side.value} {result.pair} "
                    f"qty={result.filled_quantity:.6f} @ ${result.filled_price:.2f} "
                    f"[{latency_ms:.0f}ms]"
                )

            elif result.status == OrderStatus.REJECTED:
                self._active_orders.pop(order.id, None)
                log.warning(f"❌ Order {result.id} REJECTED: {result.error}")

            elif result.status == OrderStatus.OPEN:
                log.info(f"⏳ Order {result.id} OPEN (pending fill)")

            return result

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error = str(e)
            self._active_orders.pop(order.id, None)
            log.error(f"Order submission error: {e}")
            return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an active order."""
        if order_id not in self._active_orders:
            log.warning(f"Order {order_id} not found in active orders")
            return False

        if self._executor:
            order = self._active_orders[order_id]
            success = await self._executor.cancel_order(order.exchange_order_id or order_id)
            if success:
                order.status = OrderStatus.CANCELLED
                self._active_orders.pop(order_id, None)
                log.info(f"Order {order_id} cancelled")
            return success
        return False

    async def cancel_all(self, pair: Optional[str] = None) -> int:
        """Cancel all active orders."""
        if self._executor:
            count = await self._executor.cancel_all_orders(pair)
            # Update local state
            to_remove = []
            for oid, order in self._active_orders.items():
                if pair is None or order.pair == pair:
                    order.status = OrderStatus.CANCELLED
                    to_remove.append(oid)
            for oid in to_remove:
                self._active_orders.pop(oid, None)
            return max(count, len(to_remove))
        return 0

    # ── Position Management ──────────────────────────────────

    async def sync_positions(self) -> List[Position]:
        """Fetch current positions from the executor."""
        if self._executor:
            try:
                self._positions = await self._executor.get_positions()
            except Exception as e:
                log.error(f"Position sync error: {e}")
        return self._positions

    async def close_position(self, position_id: str) -> bool:
        """Close a specific position."""
        if self._executor:
            return await self._executor.close_position(position_id)
        return False

    async def close_all_positions(self) -> int:
        """Emergency: close all open positions."""
        count = 0
        for pos in self._positions:
            if await self.close_position(pos.id):
                count += 1
        log.info(f"Closed {count} positions")
        return count

    # ── Balance ──────────────────────────────────────────────

    async def get_balance(self) -> float:
        """Get current account balance."""
        if self._executor:
            try:
                return await self._executor.get_balance()
            except Exception as e:
                log.error(f"Balance fetch error: {e}")
        return 0.0

    # ── Stats & History ──────────────────────────────────────

    def get_recent_orders(self, count: int = 20) -> List[Order]:
        """Get most recent orders."""
        all_orders = sorted(
            self._orders.values(),
            key=lambda o: o.created_at,
            reverse=True,
        )
        return all_orders[:count]

    def get_active_orders(self) -> List[Order]:
        """Get currently active orders."""
        return list(self._active_orders.values())

    @property
    def positions(self) -> List[Position]:
        return self._positions

    @property
    def total_trades(self) -> int:
        return self._total_trades

    @property
    def stats(self) -> Dict:
        filled = [o for o in self._orders.values() if o.status == OrderStatus.FILLED]
        rejected = [o for o in self._orders.values() if o.status == OrderStatus.REJECTED]
        return {
            "total_submitted": len(self._orders),
            "filled": len(filled),
            "rejected": len(rejected),
            "active": len(self._active_orders),
            "positions": len(self._positions),
        }
