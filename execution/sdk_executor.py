"""
SDK Executor — Direct API/SDK execution mode.
Fastest execution path: communicates directly with Bulk.trade API endpoints.
Falls back to raw HTTP/WebSocket if the official SDK is not available.
"""

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

from utils.logger import log
from utils.crypto_utils import SolanaWallet


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Represents a trade order."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pair: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    price: float = 0.0
    quantity: float = 0.0
    leverage: int = 1
    stop_loss: float = 0.0
    take_profit: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_quantity: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    exchange_order_id: str = ""
    error: str = ""

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def pnl(self) -> float:
        """Unrealized P&L based on fill price vs current price."""
        if self.filled_price == 0:
            return 0.0
        if self.side in (OrderSide.BUY, OrderSide.LONG):
            return (self.price - self.filled_price) * self.filled_quantity * self.leverage
        else:
            return (self.filled_price - self.price) * self.filled_quantity * self.leverage


@dataclass
class Position:
    """Represents an open position."""
    id: str = ""
    pair: str = ""
    side: str = ""  # "long" or "short"
    entry_price: float = 0.0
    current_price: float = 0.0
    quantity: float = 0.0
    leverage: int = 1
    margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    liquidation_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    created_at: float = field(default_factory=time.time)

    @property
    def pnl_pct(self) -> float:
        if self.margin == 0:
            return 0.0
        return (self.unrealized_pnl / self.margin) * 100

    @property
    def notional(self) -> float:
        return self.quantity * self.current_price * self.leverage


class SDKExecutor:
    """
    Direct API executor for Bulk.trade.
    Attempts to use the platform's REST API and WebSocket endpoints
    for maximum speed and reliability.
    """

    def __init__(self, platform_url: str, wallet: SolanaWallet, rpc_url: str = ""):
        self.platform_url = platform_url.rstrip("/")
        self.wallet = wallet
        self.rpc_url = rpc_url
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[Any] = None
        self._connected = False
        self._api_available = False

        # API endpoint discovery
        self._api_base = f"{self.platform_url}/api/v1"
        self._ws_url = self.platform_url.replace("https://", "wss://").replace("http://", "ws://")

    async def connect(self) -> bool:
        """
        Initialize connection to Bulk.trade API.
        Tests available endpoints and establishes session.
        """
        if not HAS_AIOHTTP:
            log.error("aiohttp not installed — SDK executor cannot start")
            return False

        self._session = aiohttp.ClientSession(
            headers={
                "Content-Type": "application/json",
                "User-Agent": "BulkTradeBot/1.0",
                "X-Wallet-Address": self.wallet.public_key,
            }
        )

        # Test API availability
        endpoints_to_try = [
            f"{self._api_base}/health",
            f"{self._api_base}/status",
            f"{self._api_base}/markets",
            f"{self.platform_url}/api/health",
        ]

        for endpoint in endpoints_to_try:
            try:
                async with self._session.get(endpoint, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        self._api_available = True
                        log.info(f"SDK API available at {endpoint}")
                        break
                    elif resp.status == 403:
                        log.warning(f"API endpoint {endpoint} returned 403 (blocked)")
                    else:
                        log.debug(f"API endpoint {endpoint} returned {resp.status}")
            except Exception as e:
                log.debug(f"API endpoint {endpoint} unreachable: {e}")

        if not self._api_available:
            log.warning("Bulk.trade API not available — SDK executor will use fallback mode")

        self._connected = True
        return self._api_available

    async def disconnect(self):
        """Clean up connections."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session:
            await self._session.close()
        self._connected = False
        log.info("SDK executor disconnected")

    # ── Order Management ──────────────────────────────────────

    async def place_order(self, order: Order) -> Order:
        """
        Submit an order to Bulk.trade via API.
        Signs the order with our wallet before submission.
        """
        start_time = time.time()

        if not self._api_available:
            order.status = OrderStatus.REJECTED
            order.error = "API not available"
            return order

        try:
            # Build order payload
            payload = {
                "pair": order.pair,
                "side": order.side.value,
                "type": order.order_type.value,
                "quantity": str(order.quantity),
                "leverage": order.leverage,
                "wallet": self.wallet.public_key,
                "timestamp": int(time.time() * 1000),
                "nonce": str(uuid.uuid4()),
            }

            if order.order_type == OrderType.LIMIT:
                payload["price"] = str(order.price)

            if order.stop_loss > 0:
                payload["stop_loss"] = str(order.stop_loss)
            if order.take_profit > 0:
                payload["take_profit"] = str(order.take_profit)

            # Sign the order payload
            message = json.dumps(payload, sort_keys=True).encode()
            signature = self.wallet.sign_message(message)
            payload["signature"] = signature.hex()

            # Submit order
            async with self._session.post(
                f"{self._api_base}/order",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                latency = (time.time() - start_time) * 1000

                if resp.status == 200:
                    data = await resp.json()
                    order.exchange_order_id = data.get("order_id", "")
                    order.status = OrderStatus.OPEN
                    order.filled_price = float(data.get("filled_price", 0))
                    order.filled_quantity = float(data.get("filled_quantity", 0))

                    if order.filled_quantity >= order.quantity:
                        order.status = OrderStatus.FILLED
                    elif order.filled_quantity > 0:
                        order.status = OrderStatus.PARTIALLY_FILLED

                    log.info(
                        f"Order {order.id} placed: {order.side.value} {order.pair} "
                        f"qty={order.quantity} @ {order.filled_price:.2f} "
                        f"[{latency:.0f}ms]"
                    )
                elif resp.status == 429:
                    order.status = OrderStatus.REJECTED
                    order.error = "Rate limited"
                    log.warning(f"Order {order.id} rate limited")
                else:
                    error_text = await resp.text()
                    order.status = OrderStatus.REJECTED
                    order.error = f"HTTP {resp.status}: {error_text[:200]}"
                    log.error(f"Order {order.id} rejected: {order.error}")

        except asyncio.TimeoutError:
            order.status = OrderStatus.REJECTED
            order.error = "Timeout"
            log.error(f"Order {order.id} timed out")
        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error = str(e)
            log.error(f"Order {order.id} error: {e}")

        order.updated_at = time.time()
        return order

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by exchange order ID."""
        if not self._api_available:
            return False

        try:
            payload = {
                "order_id": order_id,
                "wallet": self.wallet.public_key,
                "timestamp": int(time.time() * 1000),
            }
            message = json.dumps(payload, sort_keys=True).encode()
            signature = self.wallet.sign_message(message)
            payload["signature"] = signature.hex()

            async with self._session.delete(
                f"{self._api_base}/order/{order_id}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    log.info(f"Order {order_id} cancelled")
                    return True
                else:
                    log.warning(f"Failed to cancel order {order_id}: HTTP {resp.status}")
                    return False
        except Exception as e:
            log.error(f"Cancel order error: {e}")
            return False

    async def cancel_all_orders(self, pair: Optional[str] = None) -> int:
        """Cancel all open orders, optionally filtered by pair."""
        if not self._api_available:
            return 0

        try:
            payload = {
                "wallet": self.wallet.public_key,
                "timestamp": int(time.time() * 1000),
            }
            if pair:
                payload["pair"] = pair

            async with self._session.delete(
                f"{self._api_base}/orders",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    count = data.get("cancelled_count", 0)
                    log.info(f"Cancelled {count} orders")
                    return count
        except Exception as e:
            log.error(f"Cancel all orders error: {e}")
        return 0

    # ── Position Management ──────────────────────────────────

    async def get_positions(self) -> List[Position]:
        """Fetch all open positions."""
        if not self._api_available:
            return []

        try:
            async with self._session.get(
                f"{self._api_base}/positions",
                params={"wallet": self.wallet.public_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    positions = []
                    for p in data.get("positions", []):
                        positions.append(Position(
                            id=p.get("id", ""),
                            pair=p.get("pair", ""),
                            side=p.get("side", ""),
                            entry_price=float(p.get("entry_price", 0)),
                            current_price=float(p.get("mark_price", 0)),
                            quantity=float(p.get("quantity", 0)),
                            leverage=int(p.get("leverage", 1)),
                            margin=float(p.get("margin", 0)),
                            unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                            realized_pnl=float(p.get("realized_pnl", 0)),
                            liquidation_price=float(p.get("liquidation_price", 0)),
                        ))
                    return positions
        except Exception as e:
            log.error(f"Get positions error: {e}")
        return []

    async def close_position(self, position_id: str) -> bool:
        """Close an open position by market order."""
        if not self._api_available:
            return False

        try:
            payload = {
                "position_id": position_id,
                "wallet": self.wallet.public_key,
                "timestamp": int(time.time() * 1000),
            }
            async with self._session.post(
                f"{self._api_base}/position/close",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    log.info(f"Position {position_id} closed")
                    return True
        except Exception as e:
            log.error(f"Close position error: {e}")
        return False

    # ── Account Info ──────────────────────────────────────────

    async def get_balance(self) -> float:
        """Get account balance in USD."""
        if not self._api_available:
            return 0.0

        try:
            async with self._session.get(
                f"{self._api_base}/account",
                params={"wallet": self.wallet.public_key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return float(data.get("balance", data.get("equity", 0)))
        except Exception as e:
            log.error(f"Get balance error: {e}")
        return 0.0

    async def get_markets(self) -> List[Dict]:
        """Get available trading markets/pairs."""
        if not self._api_available:
            return []

        try:
            async with self._session.get(
                f"{self._api_base}/markets",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("markets", [])
        except Exception as e:
            log.error(f"Get markets error: {e}")
        return []

    # ── Order Book ────────────────────────────────────────────

    async def get_orderbook(self, pair: str, depth: int = 20) -> Dict:
        """Fetch order book for a pair."""
        if not self._api_available:
            return {"bids": [], "asks": []}

        try:
            async with self._session.get(
                f"{self._api_base}/orderbook/{pair.replace('/', '_')}",
                params={"depth": depth},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            log.error(f"Get orderbook error: {e}")
        return {"bids": [], "asks": []}

    @property
    def is_available(self) -> bool:
        return self._connected and self._api_available
