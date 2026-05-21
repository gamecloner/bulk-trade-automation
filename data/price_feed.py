"""
Real-time price feed aggregator.
Connects to multiple sources: Bulk.trade WebSocket, Binance WS, and browser scraping.
Provides unified price stream for all strategies.
"""

import asyncio
import json
import time
from typing import Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import deque

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from utils.logger import log


@dataclass
class PriceTick:
    """A single price update."""
    pair: str
    price: float
    bid: float = 0.0
    ask: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"

    @property
    def spread(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0

    @property
    def spread_pct(self) -> float:
        if self.bid > 0:
            return (self.spread / self.bid) * 100
        return 0.0

    @property
    def mid_price(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.price


class PriceFeed:
    """
    Aggregates price data from multiple sources.
    Provides real-time price callbacks and price history buffers.
    """

    def __init__(self):
        self._subscribers: List[Callable] = []
        self._latest_prices: Dict[str, Dict[str, PriceTick]] = {}  # pair -> {source: tick}
        self._price_history: Dict[str, deque] = {}  # pair -> deque of ticks
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self.history_size = 1000

    def subscribe(self, callback: Callable):
        """Register a callback for price updates. callback(tick: PriceTick)"""
        self._subscribers.append(callback)

    async def _notify(self, tick: PriceTick):
        """Notify all subscribers of a new price tick."""
        # Store latest
        if tick.pair not in self._latest_prices:
            self._latest_prices[tick.pair] = {}
        self._latest_prices[tick.pair][tick.source] = tick

        # Store history
        if tick.pair not in self._price_history:
            self._price_history[tick.pair] = deque(maxlen=self.history_size)
        self._price_history[tick.pair].append(tick)

        # Notify subscribers
        for cb in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(tick)
                else:
                    cb(tick)
            except Exception as e:
                log.error(f"Price subscriber error: {e}")

    def get_latest(self, pair: str, source: Optional[str] = None) -> Optional[PriceTick]:
        """Get the most recent price tick for a pair."""
        if pair not in self._latest_prices:
            return None
        sources = self._latest_prices[pair]
        if source:
            return sources.get(source)
        # Return the most recent across all sources
        if not sources:
            return None
        return max(sources.values(), key=lambda t: t.timestamp)

    def get_history(self, pair: str, count: int = 100) -> List[PriceTick]:
        """Get recent price history for a pair."""
        if pair not in self._price_history:
            return []
        history = self._price_history[pair]
        return list(history)[-count:]

    def get_all_latest(self) -> Dict[str, PriceTick]:
        """Get latest price for all pairs."""
        result = {}
        for pair, sources in self._latest_prices.items():
            if sources:
                result[pair] = max(sources.values(), key=lambda t: t.timestamp)
        return result

    # ── Binance WebSocket Feed ──────────────────────────────────

    async def start_binance_feed(
        self,
        pairs: List[str],
        pair_mapping: Dict[str, str],
        ws_url: str = "wss://stream.binance.com:9443/ws",
    ):
        """
        Connect to Binance WebSocket for real-time price data.
        Used as external reference for arbitrage comparison.
        """
        if not HAS_WEBSOCKETS:
            log.warning("websockets not installed — Binance feed disabled")
            return

        # Build stream names
        streams = []
        reverse_map = {}
        for pair, binance_sym in pair_mapping.items():
            if pair in pairs:
                streams.append(f"{binance_sym}@ticker")
                reverse_map[binance_sym.upper()] = pair

        if not streams:
            log.warning("No matching pairs for Binance feed")
            return

        stream_url = f"{ws_url}/{'/'.join(streams)}"
        log.info(f"Connecting to Binance WS: {len(streams)} streams")

        while self._running:
            try:
                async with websockets.connect(stream_url, ping_interval=20) as ws:
                    log.info("Binance WebSocket connected")
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            symbol = data.get("s", "")
                            if symbol in reverse_map:
                                tick = PriceTick(
                                    pair=reverse_map[symbol],
                                    price=float(data.get("c", 0)),
                                    bid=float(data.get("b", 0)),
                                    ask=float(data.get("a", 0)),
                                    high=float(data.get("h", 0)),
                                    low=float(data.get("l", 0)),
                                    volume=float(data.get("v", 0)),
                                    timestamp=time.time(),
                                    source="binance",
                                )
                                await self._notify(tick)
                        except (KeyError, ValueError) as e:
                            log.debug(f"Binance parse error: {e}")
            except Exception as e:
                log.error(f"Binance WS error: {e}")
                if self._running:
                    log.info("Reconnecting to Binance in 5s...")
                    await asyncio.sleep(5)

    # ── Bulk.trade Price Feed ──────────────────────────────────

    async def start_bulk_ws_feed(self, platform_url: str, pairs: List[str]):
        """
        Connect to Bulk.trade WebSocket for native price data.
        This is the primary price source when SDK mode is active.
        """
        if not HAS_WEBSOCKETS:
            log.warning("websockets not installed — Bulk WS feed disabled")
            return

        # Convert HTTPS to WSS
        ws_url = platform_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = f"{ws_url}/ws/prices"

        log.info(f"Connecting to Bulk.trade WS: {ws_url}")

        while self._running:
            try:
                async with websockets.connect(ws_url, ping_interval=20) as ws:
                    # Subscribe to pairs
                    subscribe_msg = json.dumps({
                        "method": "subscribe",
                        "params": {
                            "channels": [f"ticker.{pair}" for pair in pairs]
                        }
                    })
                    await ws.send(subscribe_msg)
                    log.info(f"Bulk.trade WS connected, subscribed to {pairs}")

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            if "pair" in data and "price" in data:
                                tick = PriceTick(
                                    pair=data["pair"],
                                    price=float(data["price"]),
                                    bid=float(data.get("bid", 0)),
                                    ask=float(data.get("ask", 0)),
                                    high=float(data.get("high", 0)),
                                    low=float(data.get("low", 0)),
                                    volume=float(data.get("volume", 0)),
                                    timestamp=time.time(),
                                    source="bulk",
                                )
                                await self._notify(tick)
                        except (KeyError, ValueError) as e:
                            log.debug(f"Bulk WS parse error: {e}")
            except Exception as e:
                log.warning(f"Bulk.trade WS unavailable: {e}")
                if self._running:
                    log.info("Reconnecting to Bulk.trade in 10s...")
                    await asyncio.sleep(10)

    # ── HTTP Polling Fallback ──────────────────────────────────

    async def start_http_polling(
        self,
        platform_url: str,
        pairs: List[str],
        interval: float = 2.0,
    ):
        """
        Fallback: Poll Bulk.trade HTTP API for prices.
        Slower than WebSocket but more reliable.
        """
        if not HAS_AIOHTTP:
            log.warning("aiohttp not installed — HTTP polling disabled")
            return

        log.info(f"Starting HTTP price polling (interval: {interval}s)")

        async with aiohttp.ClientSession() as session:
            while self._running:
                for pair in pairs:
                    try:
                        url = f"{platform_url}/api/v1/ticker/{pair.replace('/', '_')}"
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                tick = PriceTick(
                                    pair=pair,
                                    price=float(data.get("last", data.get("price", 0))),
                                    bid=float(data.get("bid", 0)),
                                    ask=float(data.get("ask", 0)),
                                    high=float(data.get("high_24h", 0)),
                                    low=float(data.get("low_24h", 0)),
                                    volume=float(data.get("volume_24h", 0)),
                                    timestamp=time.time(),
                                    source="bulk_http",
                                )
                                await self._notify(tick)
                    except Exception as e:
                        log.debug(f"HTTP poll error for {pair}: {e}")
                await asyncio.sleep(interval)

    # ── Simulated Feed (for testing) ──────────────────────────

    async def start_simulated_feed(self, pairs: List[str], base_prices: Optional[Dict[str, float]] = None):
        """
        Generate simulated price data for testing.
        Produces realistic random walk with volatility.
        """
        import random

        if base_prices is None:
            base_prices = {
                "SOL/USD": 170.0,
                "BTC/USD": 67500.0,
                "ETH/USD": 3800.0,
            }

        prices = {pair: base_prices.get(pair, 100.0) for pair in pairs}
        log.info(f"Starting simulated price feed for {pairs}")

        while self._running:
            for pair in pairs:
                # Random walk with mean reversion
                price = prices[pair]
                volatility = price * 0.001  # 0.1% per tick
                change = random.gauss(0, volatility)

                # Mean reversion toward base
                base = base_prices.get(pair, price)
                reversion = (base - price) * 0.001
                price += change + reversion
                prices[pair] = price

                tick = PriceTick(
                    pair=pair,
                    price=price,
                    bid=price * 0.9999,
                    ask=price * 1.0001,
                    high=price * 1.002,
                    low=price * 0.998,
                    volume=random.uniform(100, 10000),
                    timestamp=time.time(),
                    source="simulated",
                )
                await self._notify(tick)

            await asyncio.sleep(0.5)

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(
        self,
        pairs: List[str],
        platform_url: str = "",
        binance_ws_url: str = "",
        pair_mapping: Optional[Dict[str, str]] = None,
        use_simulation: bool = False,
    ):
        """Start all configured price feeds."""
        self._running = True

        if use_simulation:
            self._tasks.append(
                asyncio.create_task(self.start_simulated_feed(pairs))
            )
        else:
            # Binance external feed (always try)
            if binance_ws_url and pair_mapping:
                self._tasks.append(
                    asyncio.create_task(
                        self.start_binance_feed(pairs, pair_mapping, binance_ws_url)
                    )
                )

            # Bulk.trade native feed
            if platform_url:
                self._tasks.append(
                    asyncio.create_task(self.start_bulk_ws_feed(platform_url, pairs))
                )
                # HTTP polling as backup
                self._tasks.append(
                    asyncio.create_task(self.start_http_polling(platform_url, pairs))
                )

        log.info(f"Price feed started with {len(self._tasks)} source(s)")

    async def stop(self):
        """Stop all price feeds."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        log.info("Price feed stopped")
