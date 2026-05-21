"""
Order book aggregation and analysis.
Reconstructs and analyzes the order book for trading decisions.
"""

import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from utils.logger import log


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""
    price: float
    quantity: float
    order_count: int = 1
    timestamp: float = field(default_factory=time.time)

    @property
    def notional(self) -> float:
        """Total USD value at this level."""
        return self.price * self.quantity


@dataclass
class OrderBookSnapshot:
    """Complete order book state at a point in time."""
    pair: str
    bids: List[OrderBookLevel] = field(default_factory=list)  # Sorted desc by price
    asks: List[OrderBookLevel] = field(default_factory=list)  # Sorted asc by price
    timestamp: float = field(default_factory=time.time)

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> float:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return 0.0

    @property
    def spread_pct(self) -> float:
        if self.best_bid and self.best_bid.price > 0:
            return (self.spread / self.best_bid.price) * 100
        return 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return 0.0


class OrderBook:
    """
    Maintains and analyzes the order book for a trading pair.
    Supports both full snapshots and incremental updates.
    """

    def __init__(self, pair: str, max_depth: int = 50):
        self.pair = pair
        self.max_depth = max_depth
        self._bids: Dict[float, OrderBookLevel] = {}  # price -> level
        self._asks: Dict[float, OrderBookLevel] = {}
        self._last_update: float = 0.0
        self._update_count: int = 0

    def update_snapshot(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]):
        """
        Replace entire order book with a new snapshot.
        bids/asks: list of (price, quantity) tuples.
        """
        self._bids.clear()
        self._asks.clear()

        for price, qty in bids:
            if qty > 0:
                self._bids[price] = OrderBookLevel(price=price, quantity=qty)

        for price, qty in asks:
            if qty > 0:
                self._asks[price] = OrderBookLevel(price=price, quantity=qty)

        self._last_update = time.time()
        self._update_count += 1

    def update_level(self, side: str, price: float, quantity: float):
        """
        Incremental update: add/modify/remove a single level.
        quantity=0 means remove the level.
        """
        book = self._bids if side == "bid" else self._asks

        if quantity <= 0:
            book.pop(price, None)
        else:
            book[price] = OrderBookLevel(
                price=price,
                quantity=quantity,
                timestamp=time.time(),
            )

        self._last_update = time.time()
        self._update_count += 1

    def get_snapshot(self) -> OrderBookSnapshot:
        """Get current order book as a sorted snapshot."""
        sorted_bids = sorted(self._bids.values(), key=lambda l: -l.price)[:self.max_depth]
        sorted_asks = sorted(self._asks.values(), key=lambda l: l.price)[:self.max_depth]

        return OrderBookSnapshot(
            pair=self.pair,
            bids=sorted_bids,
            asks=sorted_asks,
            timestamp=self._last_update,
        )

    # ── Analysis Methods ──────────────────────────────────────

    def get_depth(self, side: str, levels: int = 10) -> float:
        """Total quantity available in top N levels."""
        book = self._bids if side == "bid" else self._asks
        sorted_levels = sorted(
            book.values(),
            key=lambda l: -l.price if side == "bid" else l.price,
        )
        return sum(l.quantity for l in sorted_levels[:levels])

    def get_notional_depth(self, side: str, levels: int = 10) -> float:
        """Total USD value available in top N levels."""
        book = self._bids if side == "bid" else self._asks
        sorted_levels = sorted(
            book.values(),
            key=lambda l: -l.price if side == "bid" else l.price,
        )
        return sum(l.notional for l in sorted_levels[:levels])

    def get_imbalance_ratio(self, levels: int = 10) -> float:
        """
        Order book imbalance ratio.
        > 0.5 = more bid pressure (bullish)
        < 0.5 = more ask pressure (bearish)
        = 0.5 = balanced
        """
        bid_depth = self.get_depth("bid", levels)
        ask_depth = self.get_depth("ask", levels)
        total = bid_depth + ask_depth
        if total == 0:
            return 0.5
        return bid_depth / total

    def get_weighted_mid_price(self, levels: int = 5) -> float:
        """
        Volume-weighted mid price using top N levels.
        More accurate than simple mid for large orders.
        """
        snapshot = self.get_snapshot()
        if not snapshot.bids or not snapshot.asks:
            return snapshot.mid_price

        bid_levels = snapshot.bids[:levels]
        ask_levels = snapshot.asks[:levels]

        bid_vwap = sum(l.price * l.quantity for l in bid_levels)
        bid_vol = sum(l.quantity for l in bid_levels)
        ask_vwap = sum(l.price * l.quantity for l in ask_levels)
        ask_vol = sum(l.quantity for l in ask_levels)

        if bid_vol + ask_vol == 0:
            return snapshot.mid_price

        # Weight by opposite side's volume (asks weight bid price, bids weight ask price)
        weighted = (bid_vwap / bid_vol * ask_vol + ask_vwap / ask_vol * bid_vol) / (bid_vol + ask_vol)
        return weighted

    def estimate_slippage(self, side: str, quantity: float) -> float:
        """
        Estimate price slippage for a market order of given quantity.
        Returns the average execution price.
        """
        book = self._asks if side == "buy" else self._bids
        sorted_levels = sorted(
            book.values(),
            key=lambda l: l.price if side == "buy" else -l.price,
        )

        remaining = quantity
        total_cost = 0.0
        total_filled = 0.0

        for level in sorted_levels:
            fill = min(remaining, level.quantity)
            total_cost += fill * level.price
            total_filled += fill
            remaining -= fill
            if remaining <= 0:
                break

        if total_filled == 0:
            return 0.0

        avg_price = total_cost / total_filled
        return avg_price

    def detect_walls(self, threshold_multiplier: float = 3.0) -> Dict[str, List[OrderBookLevel]]:
        """
        Detect large orders ("walls") that are significantly larger than average.
        These often act as support/resistance levels.
        """
        result = {"bid_walls": [], "ask_walls": []}

        for side, key in [("bid", "bid_walls"), ("ask", "ask_walls")]:
            book = self._bids if side == "bid" else self._asks
            if not book:
                continue
            quantities = [l.quantity for l in book.values()]
            if not quantities:
                continue
            avg_qty = sum(quantities) / len(quantities)
            threshold = avg_qty * threshold_multiplier

            for level in book.values():
                if level.quantity >= threshold:
                    result[key].append(level)

        return result

    @property
    def is_stale(self) -> bool:
        """True if order book hasn't been updated in 30 seconds."""
        return time.time() - self._last_update > 30


class OrderBookManager:
    """Manages order books for multiple trading pairs."""

    def __init__(self, max_depth: int = 50):
        self.max_depth = max_depth
        self._books: Dict[str, OrderBook] = {}

    def get_book(self, pair: str) -> OrderBook:
        """Get or create an order book for a pair."""
        if pair not in self._books:
            self._books[pair] = OrderBook(pair, self.max_depth)
        return self._books[pair]

    def get_all_snapshots(self) -> Dict[str, OrderBookSnapshot]:
        """Get snapshots for all tracked pairs."""
        return {pair: book.get_snapshot() for pair, book in self._books.items()}
