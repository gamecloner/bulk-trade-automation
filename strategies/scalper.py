"""
Scalping Strategy — High-frequency, small-profit trading.
Uses EMA crossovers, RSI extremes, orderbook imbalance, and momentum
to enter and exit positions rapidly for 0.1-0.3% profit per trade.
"""

import time
from typing import Optional, List

from strategies.base_strategy import BaseStrategy, TradeSignal, Signal
from data.indicators import IndicatorState
from data.price_feed import PriceTick
from data.orderbook import OrderBook
from execution.sdk_executor import OrderSide, OrderType
from utils.logger import log


class ScalpingStrategy(BaseStrategy):
    """
    High-frequency scalping strategy for Bulk.trade perpetuals.

    Entry Conditions (LONG):
    - Fast EMA > Slow EMA (uptrend)
    - RSI < 40 (not overbought, room to run)
    - Orderbook imbalance > 0.55 (buy pressure)
    - MACD histogram positive (momentum confirmation)

    Entry Conditions (SHORT):
    - Fast EMA < Slow EMA (downtrend)
    - RSI > 60 (not oversold, room to fall)
    - Orderbook imbalance < 0.45 (sell pressure)
    - MACD histogram negative

    Exit:
    - Fixed take-profit at profit_target_pct
    - Fixed stop-loss at stop_loss_pct
    - Time-based exit after max_hold_seconds
    - Trailing stop activated after min_profit reached
    """

    def __init__(
        self,
        pairs: List[str],
        profit_target_pct: float = 0.15,
        stop_loss_pct: float = 0.10,
        cooldown_seconds: float = 5.0,
        leverage: int = 10,
        position_size_pct: float = 5.0,  # % of balance per trade
        max_hold_seconds: float = 300,  # 5 minutes max hold
        min_confidence: float = 0.6,
        trailing_stop_pct: float = 0.05,  # Trailing stop after profit
    ):
        super().__init__(name="SCALPER", pairs=pairs)
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        self._cooldown_seconds = cooldown_seconds
        self.leverage = leverage
        self.position_size_pct = position_size_pct
        self.max_hold_seconds = max_hold_seconds
        self.min_confidence = min_confidence
        self.trailing_stop_pct = trailing_stop_pct

        # Internal state per pair
        self._prev_ema_cross: dict = {}  # pair -> "bullish" | "bearish"
        self._consecutive_signals: dict = {}  # pair -> count

    async def analyze(
        self,
        pair: str,
        tick: PriceTick,
        indicators: IndicatorState,
        orderbook: Optional[OrderBook] = None,
    ) -> TradeSignal:
        """
        Core scalping analysis — multi-factor signal generation.
        """
        signal = TradeSignal(pair=pair, timestamp=tick.timestamp)
        engine = self.get_indicator_engine(pair)

        # ── Factor 1: EMA Crossover (Weight: 30%) ──────────────
        ema_score = 0.0
        current_cross = "bullish" if indicators.ema_fast > indicators.ema_slow else "bearish"
        prev_cross = self._prev_ema_cross.get(pair, current_cross)

        if current_cross == "bullish":
            ema_score = 0.3
            if prev_cross == "bearish":
                # Fresh crossover — strong signal
                ema_score = 0.5
        else:
            ema_score = -0.3
            if prev_cross == "bullish":
                ema_score = -0.5

        self._prev_ema_cross[pair] = current_cross

        # ── Factor 2: RSI (Weight: 25%) ────────────────────────
        rsi_score = 0.0
        rsi = indicators.rsi

        if rsi < 25:
            rsi_score = 0.4  # Extremely oversold — strong buy
        elif rsi < 35:
            rsi_score = 0.25  # Oversold
        elif rsi < 45:
            rsi_score = 0.1  # Slightly oversold
        elif rsi > 75:
            rsi_score = -0.4  # Extremely overbought — strong sell
        elif rsi > 65:
            rsi_score = -0.25  # Overbought
        elif rsi > 55:
            rsi_score = -0.1  # Slightly overbought

        # ── Factor 3: Orderbook Imbalance (Weight: 20%) ────────
        ob_score = 0.0
        if orderbook:
            imbalance = orderbook.get_imbalance_ratio(levels=10)
            if imbalance > 0.65:
                ob_score = 0.3  # Strong buy pressure
            elif imbalance > 0.55:
                ob_score = 0.15
            elif imbalance < 0.35:
                ob_score = -0.3  # Strong sell pressure
            elif imbalance < 0.45:
                ob_score = -0.15

            signal.metadata["ob_imbalance"] = round(imbalance, 3)

        # ── Factor 4: MACD Momentum (Weight: 15%) ─────────────
        macd_score = 0.0
        if indicators.macd_histogram > 0:
            macd_score = 0.15 * min(abs(indicators.macd_histogram) * 100, 1)
        elif indicators.macd_histogram < 0:
            macd_score = -0.15 * min(abs(indicators.macd_histogram) * 100, 1)

        # ── Factor 5: Bollinger Band Position (Weight: 10%) ────
        bb_score = 0.0
        if engine.bollinger.ready:
            bb_range = indicators.bollinger_upper - indicators.bollinger_lower
            if bb_range > 0:
                bb_position = (tick.price - indicators.bollinger_lower) / bb_range
                if bb_position < 0.15:
                    bb_score = 0.15  # Near lower band — bounce buy
                elif bb_position > 0.85:
                    bb_score = -0.15  # Near upper band — bounce sell

        # ── Composite Score ────────────────────────────────────
        total_score = ema_score + rsi_score + ob_score + macd_score + bb_score
        confidence = min(abs(total_score), 1.0)

        # Track consecutive signals for confirmation
        prev_count = self._consecutive_signals.get(pair, 0)
        if total_score > 0.1:
            self._consecutive_signals[pair] = max(prev_count + 1, 1) if prev_count > 0 else 1
        elif total_score < -0.1:
            self._consecutive_signals[pair] = min(prev_count - 1, -1) if prev_count < 0 else -1
        else:
            self._consecutive_signals[pair] = 0

        consecutive = abs(self._consecutive_signals.get(pair, 0))

        # Boost confidence with consecutive signals
        if consecutive >= 3:
            confidence = min(confidence * 1.3, 1.0)

        # ── Generate Signal ────────────────────────────────────
        signal.confidence = round(confidence, 3)
        signal.metadata.update({
            "ema_score": round(ema_score, 3),
            "rsi_score": round(rsi_score, 3),
            "ob_score": round(ob_score, 3),
            "macd_score": round(macd_score, 3),
            "bb_score": round(bb_score, 3),
            "total_score": round(total_score, 3),
            "consecutive": self._consecutive_signals.get(pair, 0),
            "rsi": round(rsi, 1),
            "ema_fast": round(indicators.ema_fast, 4),
            "ema_slow": round(indicators.ema_slow, 4),
        })

        if confidence < self.min_confidence:
            signal.signal = Signal.NEUTRAL
            signal.reason = f"Low confidence ({confidence:.2f} < {self.min_confidence})"
            return signal

        # Calculate order parameters
        if total_score > 0:
            # ── BUY / LONG Signal ──
            if confidence >= 0.8:
                signal.signal = Signal.STRONG_BUY
            elif confidence >= 0.6:
                signal.signal = Signal.BUY
            else:
                signal.signal = Signal.WEAK_BUY

            signal.suggested_side = OrderSide.LONG
            signal.suggested_price = tick.price
            signal.suggested_leverage = self.leverage
            signal.stop_loss = tick.price * (1 - self.stop_loss_pct / 100)
            signal.take_profit = tick.price * (1 + self.profit_target_pct / 100)
            signal.reason = self._build_reason("LONG", indicators, confidence)

        else:
            # ── SELL / SHORT Signal ──
            if confidence >= 0.8:
                signal.signal = Signal.STRONG_SELL
            elif confidence >= 0.6:
                signal.signal = Signal.SELL
            else:
                signal.signal = Signal.WEAK_SELL

            signal.suggested_side = OrderSide.SHORT
            signal.suggested_price = tick.price
            signal.suggested_leverage = self.leverage
            signal.stop_loss = tick.price * (1 + self.stop_loss_pct / 100)
            signal.take_profit = tick.price * (1 - self.profit_target_pct / 100)
            signal.reason = self._build_reason("SHORT", indicators, confidence)

        return signal

    def _build_reason(self, direction: str, ind: IndicatorState, confidence: float) -> str:
        """Build a human-readable reason string for the signal."""
        parts = [f"{direction}"]
        if ind.ema_fast > ind.ema_slow:
            parts.append("EMA↑")
        else:
            parts.append("EMA↓")
        parts.append(f"RSI:{ind.rsi:.0f}")
        parts.append(f"MACD:{'+'if ind.macd_histogram > 0 else '-'}")
        parts.append(f"conf:{confidence:.0%}")
        return " | ".join(parts)
