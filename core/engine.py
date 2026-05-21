"""
Trading Engine — Main orchestrator that connects all components.
Initializes executors, starts price feeds, runs strategy loops, and manages lifecycle.
"""

import asyncio
import time
from typing import List, Optional, Dict

from config.settings import Settings, EXECUTION_MODE_SDK, EXECUTION_MODE_BROWSER, EXECUTION_MODE_AUTO
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from data.price_feed import PriceFeed, PriceTick
from data.orderbook import OrderBookManager
from strategies.base_strategy import BaseStrategy, TradeSignal
from strategies.scalper import ScalpingStrategy
from strategies.arbitrage import ArbitrageStrategy
from execution.sdk_executor import SDKExecutor
from execution.browser_executor import BrowserExecutor
from utils.crypto_utils import load_or_create_wallet, SolanaWallet
from utils.logger import log, setup_logger, TradeLogger, PerformanceTracker


class TradingEngine:
    """
    Core trading engine that orchestrates everything:
    1. Initializes wallet and executor (SDK or Browser)
    2. Starts price feeds
    3. Runs trading strategies
    4. Manages risk and orders
    5. Feeds data to dashboard
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings.get()
        self._running = False
        self._mode = "initializing"

        # Components (initialized in start())
        self.wallet: Optional[SolanaWallet] = None
        self.sdk_executor: Optional[SDKExecutor] = None
        self.browser_executor: Optional[BrowserExecutor] = None
        self.active_executor = None
        self.execution_mode: str = "none"

        self.price_feed = PriceFeed()
        self.orderbook_mgr = OrderBookManager()
        self.risk_manager = RiskManager(
            max_position_size_usd=self.settings.trading.max_position_size_usd,
            max_concurrent_positions=self.settings.trading.max_concurrent_positions,
            daily_loss_limit_pct=self.settings.trading.daily_loss_limit_pct,
            max_drawdown_pct=self.settings.trading.max_drawdown_pct,
            max_leverage=self.settings.trading.max_leverage,
        )
        self.order_manager: Optional[OrderManager] = None
        self.performance = PerformanceTracker()

        self.strategies: List[BaseStrategy] = []
        self._tasks: List[asyncio.Task] = []

        # Live state for dashboard
        self.balance: float = 0.0
        self.last_signals: Dict[str, TradeSignal] = {}
        self.tick_count: int = 0
        self.start_time: float = 0.0

    # ── Initialization ────────────────────────────────────────

    async def initialize(self) -> bool:
        """Initialize all components. Returns True if ready to trade."""
        s = self.settings
        self._mode = "initializing"

        # Setup logging
        setup_logger(s.logging.level, s.logging.log_file)
        log.info("=" * 60)
        log.info("⚡ BULK TRADE BOT — THE GOD KILLER ⚡")
        log.info("=" * 60)
        log.info(f"Config: {s}")

        # 1. Load/create wallet
        log.info("Loading wallet...")
        try:
            self.wallet = load_or_create_wallet(
                private_key=s.wallet.private_key,
                auto_generate=s.wallet.auto_generate,
                keypair_dir=s.wallet.keypair_dir,
            )
            log.info(f"Wallet: {self.wallet.public_key}")
        except Exception as e:
            log.error(f"Wallet initialization failed: {e}")
            return False

        # 2. Initialize trade logger
        trade_logger = TradeLogger(s.logging.trade_log_file)
        self.order_manager = OrderManager(trade_logger=trade_logger)

        # 3. Connect executor
        await self._connect_executor()

        if not self.active_executor:
            log.error("No executor available — cannot trade")
            return False

        self.order_manager.set_executor(self.active_executor, self.execution_mode)

        # 4. Get initial balance
        self.balance = await self.order_manager.get_balance()
        if self.balance <= 0:
            log.warning(f"Balance is ${self.balance:.2f} — using default $10,000 for testnet")
            self.balance = 10000.0  # Default testnet balance

        self.risk_manager.initialize(self.balance)
        self.performance.start_time = time.time()

        log.info(f"Balance: ${self.balance:.2f}")
        log.info(f"Execution mode: {self.execution_mode}")
        self._mode = "ready"
        return True

    async def _connect_executor(self):
        """Connect to the appropriate executor based on configuration."""
        s = self.settings
        mode = s.trading.execution_mode

        if mode in (EXECUTION_MODE_SDK, EXECUTION_MODE_AUTO):
            # Try SDK first
            log.info("Attempting SDK connection...")
            self.sdk_executor = SDKExecutor(
                platform_url=s.platform.url,
                wallet=self.wallet,
                rpc_url=s.platform.rpc_url,
            )
            if await self.sdk_executor.connect():
                self.active_executor = self.sdk_executor
                self.execution_mode = "sdk"
                log.info("✅ SDK executor connected")
                return
            else:
                log.warning("SDK connection failed")

        if mode in (EXECUTION_MODE_BROWSER, EXECUTION_MODE_AUTO):
            # Try Browser
            log.info("Attempting browser connection...")
            try:
                self.browser_executor = BrowserExecutor(
                    platform_url=s.platform.url,
                    wallet=self.wallet,
                    headless=s.browser.headless,
                    proxy=s.browser.proxy,
                    user_data_dir=s.browser.user_data_dir,
                    min_delay_ms=s.browser.min_action_delay_ms,
                    max_delay_ms=s.browser.max_action_delay_ms,
                )
                if await self.browser_executor.connect():
                    self.active_executor = self.browser_executor
                    self.execution_mode = "browser"
                    log.info("✅ Browser executor connected")
                    return
                else:
                    log.warning("Browser connection failed")
            except Exception as e:
                log.warning(f"Browser executor error: {e}")

        # Fallback: simulation mode
        log.warning("⚠️ No executor available — running in SIMULATION mode")
        self.execution_mode = "simulation"
        self.active_executor = self._create_simulation_executor()

    def _create_simulation_executor(self):
        """Create a mock executor for dry-run testing."""
        class SimulationExecutor:
            async def place_order(self, order):
                order.status = "filled"
                order.filled_price = order.price
                order.filled_quantity = order.quantity
                log.info(f"[SIM] Order filled: {order.side.value} {order.pair} @ ${order.price:.2f}")
                return order

            async def cancel_order(self, order_id):
                return True

            async def cancel_all_orders(self, pair=None):
                return 0

            async def get_positions(self):
                return []

            async def close_position(self, position_id):
                return True

            async def get_balance(self):
                return 10000.0

            @property
            def is_available(self):
                return True

        return SimulationExecutor()

    # ── Strategy Setup ────────────────────────────────────────

    def setup_strategies(
        self,
        enable_scalper: bool = True,
        enable_arbitrage: bool = True,
    ):
        """Initialize and register trading strategies."""
        s = self.settings
        pairs = s.trading.trading_pairs

        if enable_scalper:
            scalper = ScalpingStrategy(
                pairs=pairs,
                profit_target_pct=s.scalping.profit_target_pct,
                stop_loss_pct=s.scalping.stop_loss_pct,
                cooldown_seconds=s.scalping.cooldown_seconds,
                leverage=s.trading.default_leverage,
            )
            self.strategies.append(scalper)
            log.info(f"Strategy registered: {scalper}")

        if enable_arbitrage:
            arbitrage = ArbitrageStrategy(
                pairs=pairs,
                price_feed=self.price_feed,
                min_spread_pct=s.arbitrage.min_spread_pct,
                slippage_tolerance_pct=s.arbitrage.slippage_tolerance_pct,
                execution_window_ms=s.arbitrage.execution_window_ms,
                min_profit_usd=s.arbitrage.min_profit_usd,
                leverage=s.trading.default_leverage,
            )
            self.strategies.append(arbitrage)
            log.info(f"Strategy registered: {arbitrage}")

    # ── Main Trading Loop ─────────────────────────────────────

    async def _on_price_tick(self, tick: PriceTick):
        """
        Process a price tick through all strategies.
        This is the core trading loop — called on every price update.
        """
        self.tick_count += 1

        # Update orderbook
        orderbook = self.orderbook_mgr.get_book(tick.pair)

        # Run each strategy
        for strategy in self.strategies:
            if not strategy.enabled:
                continue

            try:
                signal = await strategy.on_tick(tick, orderbook)

                if signal:
                    self.last_signals[f"{strategy.name}:{tick.pair}"] = signal

                    if signal.is_actionable and self.risk_manager.is_trading_allowed:
                        await self._execute_signal(signal, tick)

            except Exception as e:
                log.error(f"Strategy {strategy.name} tick error: {e}")

        # Periodic position sync (every 50 ticks)
        if self.tick_count % 50 == 0:
            await self._sync_state()

    async def _execute_signal(self, signal: TradeSignal, tick: PriceTick):
        """Execute a trading signal if risk checks pass."""
        # Pre-trade risk check
        allowed, reason = self.risk_manager.can_open_position(signal, self.balance)
        if not allowed:
            log.debug(f"Signal blocked by risk manager: {reason}")
            return

        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(
            signal=signal,
            balance=self.balance,
            current_price=tick.price,
        )

        if quantity <= 0:
            log.debug("Calculated position size is zero — skipping")
            return

        # Create order from signal
        order = self.order_manager.create_order_from_signal(signal, quantity, self.balance)

        # Final order validation
        valid, reason = self.risk_manager.validate_order(order, self.balance)
        if not valid:
            log.debug(f"Order validation failed: {reason}")
            return

        # Submit!
        result = await self.order_manager.submit_order(order)

        if result.status == "filled":
            # Record for strategy cooldown
            for strategy in self.strategies:
                if strategy.name == signal.strategy_name:
                    strategy.record_trade(signal.pair)

            # Record for performance tracking
            self.performance.record_trade(0.0, self.balance)  # P&L tracked on close

    async def _sync_state(self):
        """Periodically sync balance and positions."""
        try:
            new_balance = await self.order_manager.get_balance()
            if new_balance > 0:
                self.balance = new_balance

            positions = await self.order_manager.sync_positions()
            self.risk_manager.update_positions(positions)
            self.risk_manager.update_balance(self.balance)
        except Exception as e:
            log.debug(f"State sync error: {e}")

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(
        self,
        enable_scalper: bool = True,
        enable_arbitrage: bool = True,
        use_simulation: bool = False,
        monitor_only: bool = False,
    ):
        """
        Start the trading engine.

        Args:
            enable_scalper: Enable scalping strategy
            enable_arbitrage: Enable arbitrage strategy
            use_simulation: Use simulated price feed (for testing)
            monitor_only: Only monitor prices, don't trade
        """
        self._running = True
        self.start_time = time.time()
        self._mode = "running" if not monitor_only else "monitoring"

        # Setup strategies
        if not monitor_only:
            self.setup_strategies(enable_scalper, enable_arbitrage)

        # Subscribe to price feed
        self.price_feed.subscribe(self._on_price_tick)

        # Start price feeds
        s = self.settings
        await self.price_feed.start(
            pairs=s.trading.trading_pairs,
            platform_url=s.platform.url,
            binance_ws_url=s.feeds.binance_ws_url,
            pair_mapping=s.feeds.pair_mapping,
            use_simulation=use_simulation or (self.execution_mode == "simulation"),
        )

        log.info(f"🚀 Engine started in {self._mode} mode")
        log.info(f"   Pairs: {s.trading.trading_pairs}")
        log.info(f"   Strategies: {[s.name for s in self.strategies]}")
        log.info(f"   Executor: {self.execution_mode}")

        # Keep running until stopped
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self):
        """Stop the trading engine gracefully."""
        self._running = False
        self._mode = "stopping"

        log.info("Stopping engine...")

        # Cancel all orders
        if self.order_manager:
            await self.order_manager.cancel_all()

        # Stop price feeds
        await self.price_feed.stop()

        # Disconnect executors
        if self.sdk_executor:
            await self.sdk_executor.disconnect()
        if self.browser_executor:
            await self.browser_executor.disconnect()

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()

        self._mode = "stopped"
        log.info("Engine stopped")

        # Print final stats
        stats = self.performance.summary()
        log.info(f"Final stats: {stats}")

    async def emergency_stop(self):
        """Emergency: close all positions and stop immediately."""
        log.error("🚨 EMERGENCY STOP INITIATED")
        self.risk_manager._activate_kill_switch("Manual emergency stop")

        if self.order_manager:
            await self.order_manager.cancel_all()
            await self.order_manager.close_all_positions()

        await self.stop()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def uptime(self) -> float:
        if self.start_time > 0:
            return time.time() - self.start_time
        return 0.0
