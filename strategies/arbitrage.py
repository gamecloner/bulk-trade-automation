"""
Arbitrage Strategy — Cross-venue price discrepancy exploitation.
Compares Bulk.trade prices against external feeds (Binance, Pyth)
and executes when spreads exceed fee + slippage thresholds.
"""

import time
from typing import Optional, List, Dict

from strategies.base_strategy import BaseStrategy, TradeSignal, Signal
from data.indicators import IndicatorState
from data.price_feed import PriceTick, PriceFeed
from data.orderbook import OrderBook
from execution.sdk_executor import OrderSide
from utils.logger import log


class ArbitrageStrategy(BaseStrategy):
    """
    Cross-venue arbitrage strategy.

    Monitors price differences between Bulk.trade and external exchanges.
    When the spread exceeds the minimum threshold (accounting for fees),
    it generates a signal to exploit the discrepancy.

    Types of arbitrage supported:
    1. Simple: Bulk vs Binance price difference
    2. Triangular: BTC/USD → ETH/USD → ETH/BTC cycle (future)
    """

    def __init__(
        self,
        pairs: List[str],
        price_feed: PriceFeed,
        min_spread_pct: float = 0.08,
        slippage_tolerance_pct: float = 0.05,
        execution_window_ms: int = 2000,
        min_profit_usd: float = 0.50,
        leverage: int = 5,
        position_size_pct: float = 10.0,
        price_staleness_ms: int = 5000,
        cooldown_seconds: float = 3.0,
    ):
        super().__init__(name="ARBITRAGE", pairs=pairs)
        self.price_feed = price_feed
        self.min_spread_pct = min_spread_pct
        self.slippage_tolerance_pct = slippage_tolerance_pct
        self.execution_window_ms = execution_window_ms
        self.min_profit_usd = min_profit_usd
        self.leverage = leverage
        self.position_size_pct = position_size_pct
        self.price_staleness_ms = price_staleness_ms
        self._cooldown_seconds = cooldown_seconds

        # Track opportunities
        self._opportunity_count: Dict[str, int] = {}
        self._total_arb_pnl: float = 0.0
        self._arb_attempts: int = 0

    async def analyze(
        self,
        pair: str,
        tick: PriceTick,
        indicators: IndicatorState,
        orderbook: Optional[OrderBook] = None,
    ) -> TradeSignal:
        """
        Compare Bulk.trade price with external reference prices.
        Generate signal when spread exceeds threshold.
        """
        signal = TradeSignal(pair=pair, timestamp=tick.timestamp)
        signal.strategy_name = self.name

        # Get the Bulk.trade price (from the current tick)
        bulk_price = tick.price
        bulk_source = tick.source

        # Get external reference prices
        external_prices = self._get_external_prices(pair)

        if not external_prices:
            signal.signal = Signal.NEUTRAL
            signal.reason = "No external price data available"
            return signal

        # Find the best arbitrage opportunity
        best_opportunity = None
        best_spread_pct = 0.0

        for source, ext_price in external_prices.items():
            if ext_price <= 0 or bulk_price <= 0:
                continue

            # Check price staleness
            ext_tick = self.price_feed.get_latest(pair, source)
            if ext_tick:
                age_ms = (time.time() - ext_tick.timestamp) * 1000
                if age_ms > self.price_staleness_ms:
                    log.debug(f"Skipping stale {source} price for {pair} (age: {age_ms:.0f}ms)")
                    continue

            # Calculate spread
            spread_pct = ((bulk_price - ext_price) / ext_price) * 100

            if abs(spread_pct) > abs(best_spread_pct):
                best_spread_pct = spread_pct
                best_opportunity = {
                    "source": source,
                    "ext_price": ext_price,
                    "bulk_price": bulk_price,
                    "spread_pct": spread_pct,
                }

        if best_opportunity is None:
            signal.signal = Signal.NEUTRAL
            signal.reason = "No viable arbitrage opportunity"
            return signal

        spread_pct = best_opportunity["spread_pct"]
        ext_price = best_opportunity["ext_price"]
        source = best_opportunity["source"]

        # Store metadata
        signal.metadata = {
            "bulk_price": round(bulk_price, 4),
            "ext_price": round(ext_price, 4),
            "ext_source": source,
            "spread_pct": round(spread_pct, 4),
            "min_spread_pct": self.min_spread_pct,
            "net_spread_pct": round(abs(spread_pct) - self.slippage_tolerance_pct, 4),
        }

        # Check if spread exceeds minimum threshold
        net_spread = abs(spread_pct) - self.slippage_tolerance_pct
        if net_spread < self.min_spread_pct:
            signal.signal = Signal.NEUTRAL
            signal.reason = (
                f"Spread {abs(spread_pct):.3f}% < threshold {self.min_spread_pct}% "
                f"(net: {net_spread:.3f}%)"
            )
            return signal

        # ── Arbitrage Opportunity Detected! ─────────────────────
        self._arb_attempts += 1
        self._opportunity_count[pair] = self._opportunity_count.get(pair, 0) + 1

        # Determine direction:
        # If Bulk price > External price → Bulk is overpriced → SHORT on Bulk
        # If Bulk price < External price → Bulk is underpriced → LONG on Bulk
        confidence = min(abs(spread_pct) / (self.min_spread_pct * 3), 1.0)

        if spread_pct > 0:
            # Bulk price is HIGHER than external → SHORT on Bulk
            signal.signal = Signal.STRONG_SELL if confidence > 0.8 else Signal.SELL
            signal.suggested_side = OrderSide.SHORT
            signal.suggested_price = bulk_price
            signal.stop_loss = bulk_price * (1 + self.min_spread_pct / 100)
            signal.take_profit = ext_price  # Target convergence to external price
            signal.reason = (
                f"BULK OVERPRICED | Bulk: ${bulk_price:.2f} > {source}: ${ext_price:.2f} | "
                f"Spread: {spread_pct:+.3f}% | SHORT to capture convergence"
            )
        else:
            # Bulk price is LOWER than external → LONG on Bulk
            signal.signal = Signal.STRONG_BUY if confidence > 0.8 else Signal.BUY
            signal.suggested_side = OrderSide.LONG
            signal.suggested_price = bulk_price
            signal.stop_loss = bulk_price * (1 - self.min_spread_pct / 100)
            signal.take_profit = ext_price  # Target convergence to external price
            signal.reason = (
                f"BULK UNDERPRICED | Bulk: ${bulk_price:.2f} < {source}: ${ext_price:.2f} | "
                f"Spread: {spread_pct:+.3f}% | LONG to capture convergence"
            )

        signal.confidence = round(confidence, 3)
        signal.suggested_leverage = self.leverage

        log.info(
            f"🎯 ARB OPPORTUNITY [{pair}] | "
            f"Spread: {spread_pct:+.3f}% | "
            f"{signal.signal.value} | "
            f"Confidence: {confidence:.0%}"
        )

        return signal

    def _get_external_prices(self, pair: str) -> Dict[str, float]:
        """
        Collect prices from all external sources for a pair.
        Returns {source_name: price} dict.
        """
        prices = {}
        all_sources = self.price_feed._latest_prices.get(pair, {})

        for source, tick in all_sources.items():
            # Skip the Bulk.trade native prices
            if source in ("bulk", "bulk_http", "browser"):
                continue
            if tick.price > 0:
                prices[source] = tick.price

        return prices

    def get_stats(self) -> Dict:
        """Get arbitrage strategy statistics."""
        return {
            "total_opportunities": sum(self._opportunity_count.values()),
            "opportunities_by_pair": dict(self._opportunity_count),
            "total_attempts": self._arb_attempts,
            "total_arb_pnl": f"${self._total_arb_pnl:.2f}",
        }
