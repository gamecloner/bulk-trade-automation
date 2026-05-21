"""
Technical indicators computed incrementally for real-time trading.
All indicators work on price buffers and update with each new price tick.
Optimized for speed — no full recomputation on each tick.
"""

import numpy as np
from collections import deque
from typing import Optional, Dict
from dataclasses import dataclass, field


@dataclass
class IndicatorState:
    """Snapshot of all indicator values at current tick."""
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    ema_trend: float = 0.0  # 50-period EMA for trend
    rsi: float = 50.0
    vwap: float = 0.0
    bollinger_upper: float = 0.0
    bollinger_middle: float = 0.0
    bollinger_lower: float = 0.0
    atr: float = 0.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    momentum: float = 0.0
    timestamp: float = 0.0


class EMA:
    """Exponential Moving Average — incremental computation."""

    def __init__(self, period: int):
        self.period = period
        self.multiplier = 2.0 / (period + 1)
        self.value: Optional[float] = None
        self._count = 0
        self._sum = 0.0

    def update(self, price: float) -> float:
        self._count += 1
        if self.value is None:
            # Warm up: use SMA for first `period` values
            self._sum += price
            if self._count >= self.period:
                self.value = self._sum / self.period
            return self._sum / self._count
        else:
            self.value = (price - self.value) * self.multiplier + self.value
            return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


class RSI:
    """Relative Strength Index — Wilder's smoothing method."""

    def __init__(self, period: int = 14):
        self.period = period
        self.avg_gain: Optional[float] = None
        self.avg_loss: Optional[float] = None
        self.prev_price: Optional[float] = None
        self._gains: list = []
        self._losses: list = []
        self.value: float = 50.0

    def update(self, price: float) -> float:
        if self.prev_price is None:
            self.prev_price = price
            return 50.0

        change = price - self.prev_price
        self.prev_price = price
        gain = max(change, 0)
        loss = abs(min(change, 0))

        if self.avg_gain is None:
            # Warm-up phase
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) >= self.period:
                self.avg_gain = sum(self._gains) / self.period
                self.avg_loss = sum(self._losses) / self.period
        else:
            # Wilder's smoothing
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period

        if self.avg_gain is not None and self.avg_loss is not None:
            if self.avg_loss == 0:
                self.value = 100.0
            else:
                rs = self.avg_gain / self.avg_loss
                self.value = 100 - (100 / (1 + rs))

        return self.value

    @property
    def ready(self) -> bool:
        return self.avg_gain is not None


class VWAP:
    """Volume-Weighted Average Price — session-based."""

    def __init__(self):
        self.cumulative_tp_vol = 0.0  # sum(typical_price * volume)
        self.cumulative_vol = 0.0
        self.value: float = 0.0

    def update(self, high: float, low: float, close: float, volume: float) -> float:
        typical_price = (high + low + close) / 3.0
        self.cumulative_tp_vol += typical_price * volume
        self.cumulative_vol += volume
        if self.cumulative_vol > 0:
            self.value = self.cumulative_tp_vol / self.cumulative_vol
        return self.value

    def reset(self):
        """Reset for new trading session."""
        self.cumulative_tp_vol = 0.0
        self.cumulative_vol = 0.0
        self.value = 0.0


class BollingerBands:
    """Bollinger Bands — SMA ± k*stdev."""

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std
        self._prices: deque = deque(maxlen=period)
        self.upper: float = 0.0
        self.middle: float = 0.0
        self.lower: float = 0.0

    def update(self, price: float) -> tuple:
        self._prices.append(price)
        if len(self._prices) < self.period:
            self.middle = np.mean(list(self._prices))
            self.upper = self.middle
            self.lower = self.middle
            return (self.upper, self.middle, self.lower)

        prices_arr = np.array(list(self._prices))
        self.middle = float(np.mean(prices_arr))
        std = float(np.std(prices_arr))
        self.upper = self.middle + self.num_std * std
        self.lower = self.middle - self.num_std * std
        return (self.upper, self.middle, self.lower)

    @property
    def ready(self) -> bool:
        return len(self._prices) >= self.period

    @property
    def bandwidth(self) -> float:
        if self.middle == 0:
            return 0.0
        return (self.upper - self.lower) / self.middle


class ATR:
    """Average True Range — measures volatility."""

    def __init__(self, period: int = 14):
        self.period = period
        self.prev_close: Optional[float] = None
        self._tr_values: list = []
        self.value: float = 0.0

    def update(self, high: float, low: float, close: float) -> float:
        if self.prev_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - self.prev_close),
                abs(low - self.prev_close),
            )
        self.prev_close = close

        if len(self._tr_values) < self.period:
            self._tr_values.append(tr)
            self.value = sum(self._tr_values) / len(self._tr_values)
        else:
            # Wilder's smoothing
            self.value = (self.value * (self.period - 1) + tr) / self.period

        return self.value

    @property
    def ready(self) -> bool:
        return len(self._tr_values) >= self.period


class MACD:
    """Moving Average Convergence Divergence."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.ema_fast = EMA(fast)
        self.ema_slow = EMA(slow)
        self.ema_signal = EMA(signal)
        self.macd_line: float = 0.0
        self.signal_line: float = 0.0
        self.histogram: float = 0.0

    def update(self, price: float) -> tuple:
        fast_val = self.ema_fast.update(price)
        slow_val = self.ema_slow.update(price)

        if self.ema_fast.ready and self.ema_slow.ready:
            self.macd_line = fast_val - slow_val
            self.signal_line = self.ema_signal.update(self.macd_line)
            self.histogram = self.macd_line - self.signal_line

        return (self.macd_line, self.signal_line, self.histogram)

    @property
    def ready(self) -> bool:
        return self.ema_fast.ready and self.ema_slow.ready and self.ema_signal.ready


class IndicatorEngine:
    """
    Manages all indicators for a single trading pair.
    Feed it price ticks and it maintains all indicator states.
    """

    def __init__(
        self,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        ema_trend_period: int = 50,
        rsi_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        atr_period: int = 14,
    ):
        self.ema_fast = EMA(ema_fast_period)
        self.ema_slow = EMA(ema_slow_period)
        self.ema_trend = EMA(ema_trend_period)
        self.rsi = RSI(rsi_period)
        self.vwap = VWAP()
        self.bollinger = BollingerBands(bb_period, bb_std)
        self.atr = ATR(atr_period)
        self.macd = MACD()

        self._price_buffer: deque = deque(maxlen=200)
        self._tick_count: int = 0
        self.state = IndicatorState()

    def update(
        self,
        price: float,
        high: Optional[float] = None,
        low: Optional[float] = None,
        volume: float = 0.0,
        timestamp: float = 0.0,
    ) -> IndicatorState:
        """
        Update all indicators with a new price tick.
        If high/low not provided, uses price for all.
        Returns the current indicator state snapshot.
        """
        self._tick_count += 1
        self._price_buffer.append(price)

        if high is None:
            high = price
        if low is None:
            low = price

        # Update all indicators
        self.state.ema_fast = self.ema_fast.update(price)
        self.state.ema_slow = self.ema_slow.update(price)
        self.state.ema_trend = self.ema_trend.update(price)
        self.state.rsi = self.rsi.update(price)

        if volume > 0:
            self.state.vwap = self.vwap.update(high, low, price, volume)

        bb = self.bollinger.update(price)
        self.state.bollinger_upper = bb[0]
        self.state.bollinger_middle = bb[1]
        self.state.bollinger_lower = bb[2]

        self.state.atr = self.atr.update(high, low, price)

        macd = self.macd.update(price)
        self.state.macd = macd[0]
        self.state.macd_signal = macd[1]
        self.state.macd_histogram = macd[2]

        # Momentum (rate of change over last 10 ticks)
        if len(self._price_buffer) >= 10:
            self.state.momentum = (
                (price - self._price_buffer[-10]) / self._price_buffer[-10]
            ) * 100

        self.state.timestamp = timestamp
        return self.state

    @property
    def ready(self) -> bool:
        """True when all indicators have enough data."""
        return (
            self.ema_fast.ready
            and self.ema_slow.ready
            and self.rsi.ready
        )

    @property
    def ema_crossover_bullish(self) -> bool:
        """Fast EMA crossed above slow EMA."""
        return self.state.ema_fast > self.state.ema_slow

    @property
    def ema_crossover_bearish(self) -> bool:
        """Fast EMA crossed below slow EMA."""
        return self.state.ema_fast < self.state.ema_slow

    @property
    def is_oversold(self) -> bool:
        return self.state.rsi < 30

    @property
    def is_overbought(self) -> bool:
        return self.state.rsi > 70

    def get_signal_strength(self) -> float:
        """
        Composite signal strength from -1.0 (strong sell) to +1.0 (strong buy).
        Combines multiple indicators.
        """
        score = 0.0
        weight_total = 0.0

        # EMA trend (weight: 3)
        if self.ema_fast.ready and self.ema_slow.ready:
            if self.state.ema_fast > self.state.ema_slow:
                score += 3.0
            else:
                score -= 3.0
            weight_total += 3.0

        # RSI (weight: 2)
        if self.rsi.ready:
            rsi_score = (50 - self.state.rsi) / 50  # Normalized: -1 to +1
            score += rsi_score * 2.0
            weight_total += 2.0

        # MACD (weight: 2)
        if self.macd.ready:
            if self.state.macd_histogram > 0:
                score += 2.0
            else:
                score -= 2.0
            weight_total += 2.0

        # Bollinger position (weight: 1)
        if self.bollinger.ready:
            last_price = self._price_buffer[-1] if self._price_buffer else 0
            bb_range = self.state.bollinger_upper - self.state.bollinger_lower
            if bb_range > 0:
                bb_position = (last_price - self.state.bollinger_lower) / bb_range
                bb_score = 1 - 2 * bb_position  # -1 at top, +1 at bottom
                score += bb_score
                weight_total += 1.0

        if weight_total == 0:
            return 0.0
        return max(-1.0, min(1.0, score / weight_total))
