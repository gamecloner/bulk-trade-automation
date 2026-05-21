"""
Browser Executor — Stealth Playwright browser automation.
Automates trading through the web UI when the API is blocked.
Injects mock Phantom wallet, reads DOM for prices/positions, clicks to trade.
"""

import asyncio
import json
import time
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from utils.logger import log
from utils.anti_detect import (
    STEALTH_SCRIPTS,
    human_click,
    human_type,
    human_move_mouse,
    random_delay,
    random_scroll,
    random_viewport,
    random_user_agent,
)
from utils.crypto_utils import SolanaWallet
from execution.wallet_provider import generate_wallet_injection_script, generate_wallet_detection_script
from execution.sdk_executor import Order, OrderSide, OrderType, OrderStatus, Position

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


class BrowserExecutor:
    """
    Automates trading via the Bulk.trade web UI using Playwright.
    Bypasses API restrictions by simulating human browser interaction.

    Key features:
    - Stealth browser with anti-detection patches
    - Mock Phantom wallet injection (no extension needed)
    - Human-like mouse movement and typing
    - DOM scraping for price/position data
    - Click-based order placement
    """

    def __init__(
        self,
        platform_url: str,
        wallet: SolanaWallet,
        headless: bool = True,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
        min_delay_ms: int = 200,
        max_delay_ms: int = 800,
    ):
        self.platform_url = platform_url.rstrip("/")
        self.wallet = wallet
        self.headless = headless
        self.proxy = proxy
        self.user_data_dir = user_data_dir
        self.min_delay = min_delay_ms
        self.max_delay = max_delay_ms

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._connected = False
        self._wallet_connected = False

        # Selectors — will be auto-detected on first load
        self._selectors = {
            # Trading form
            "market_selector": "[data-testid='market-selector'], .market-select, .pair-selector",
            "buy_button": "[data-testid='buy-btn'], .buy-button, button:has-text('Buy'), button:has-text('Long')",
            "sell_button": "[data-testid='sell-btn'], .sell-button, button:has-text('Sell'), button:has-text('Short')",
            "quantity_input": "[data-testid='quantity-input'], input[name='quantity'], input[name='size'], .size-input input",
            "price_input": "[data-testid='price-input'], input[name='price'], .price-input input",
            "leverage_slider": "[data-testid='leverage'], .leverage-slider, input[type='range']",
            "leverage_input": "input[name='leverage'], .leverage-input input",
            "submit_order": "[data-testid='submit-order'], .submit-btn, button:has-text('Place Order'), button[type='submit']",
            "order_type_market": "button:has-text('Market'), [data-type='market']",
            "order_type_limit": "button:has-text('Limit'), [data-type='limit']",

            # Price display
            "current_price": "[data-testid='current-price'], .mark-price, .current-price, .price-display",
            "bid_price": "[data-testid='bid'], .bid-price, .best-bid",
            "ask_price": "[data-testid='ask'], .ask-price, .best-ask",

            # Positions
            "positions_tab": "button:has-text('Positions'), [data-tab='positions']",
            "position_rows": "[data-testid='position-row'], .position-row, tr.position",
            "close_position_btn": "button:has-text('Close'), .close-btn",

            # Balance
            "balance_display": "[data-testid='balance'], .balance, .equity-display",

            # Wallet connect
            "connect_wallet_btn": "button:has-text('Connect'), button:has-text('Connect Wallet')",

            # Order book
            "orderbook_bids": ".orderbook-bids, [data-side='bid']",
            "orderbook_asks": ".orderbook-asks, [data-side='ask']",
        }

    async def connect(self) -> bool:
        """
        Launch stealth browser, navigate to platform, and inject mock wallet.
        """
        if not HAS_PLAYWRIGHT:
            log.error("playwright not installed — run: pip install playwright && playwright install chromium")
            return False

        try:
            self._playwright = await async_playwright().start()

            # Browser launch options
            viewport = random_viewport()
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                f"--window-size={viewport['width']},{viewport['height']}",
            ]

            if self.proxy:
                launch_args.append(f"--proxy-server={self.proxy}")

            # Launch browser
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=launch_args,
            )

            # Create context with stealth settings
            context_opts = {
                "viewport": viewport,
                "user_agent": random_user_agent(),
                "locale": "en-US",
                "timezone_id": "America/New_York",
                "color_scheme": "dark",
                "has_touch": False,
                "is_mobile": False,
                "java_script_enabled": True,
            }

            if self.user_data_dir and self.user_data_dir.exists():
                # Reuse cookies/storage from previous sessions
                storage_file = self.user_data_dir / "storage.json"
                if storage_file.exists():
                    context_opts["storage_state"] = str(storage_file)

            self._context = await self._browser.new_context(**context_opts)

            # Inject stealth scripts before any page loads
            await self._context.add_init_script(STEALTH_SCRIPTS)

            # Inject wallet provider before page loads
            wallet_script = generate_wallet_injection_script(
                keypair_bytes=self.wallet.to_js_keypair_array(),
                public_key=self.wallet.public_key,
            )
            await self._context.add_init_script(wallet_script)

            # Create page and navigate
            self._page = await self._context.new_page()

            # Set up console message handler for debugging
            self._page.on("console", lambda msg: log.debug(f"[BROWSER] {msg.text}") if "WALLET" in msg.text or "STEALTH" in msg.text else None)

            log.info(f"Navigating to {self.platform_url}...")
            await self._page.goto(self.platform_url, wait_until="networkidle", timeout=30000)

            # Wait for page to fully load
            await asyncio.sleep(3)

            # Verify wallet injection
            wallet_status = await self._page.evaluate(generate_wallet_detection_script())
            status = json.loads(wallet_status)
            log.info(f"Wallet injection status: {status}")

            if status.get("isConnected"):
                self._wallet_connected = True
                log.info(f"✅ Wallet connected: {status.get('publicKey', 'unknown')}")
            else:
                # Try clicking Connect Wallet button
                await self._try_connect_wallet()

            self._connected = True
            log.info("✅ Browser executor connected successfully")

            # Save browser state for future sessions
            if self.user_data_dir:
                self.user_data_dir.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(path=str(self.user_data_dir / "storage.json"))

            return True

        except Exception as e:
            log.error(f"Browser executor connection failed: {e}")
            await self.disconnect()
            return False

    async def _try_connect_wallet(self):
        """Attempt to click the Connect Wallet button on the page."""
        try:
            btn = await self._page.query_selector(self._selectors["connect_wallet_btn"])
            if btn:
                await human_click(self._page, self._selectors["connect_wallet_btn"])
                await asyncio.sleep(2)

                # Check for Phantom option in wallet selection modal
                phantom_btn = await self._page.query_selector("button:has-text('Phantom'), [data-wallet='phantom']")
                if phantom_btn:
                    await phantom_btn.click()
                    await asyncio.sleep(2)

                # Verify connection
                wallet_status = await self._page.evaluate(generate_wallet_detection_script())
                status = json.loads(wallet_status)
                if status.get("isConnected"):
                    self._wallet_connected = True
                    log.info("✅ Wallet connected via UI button")
                else:
                    log.warning("Wallet connection via UI failed — mock may need adjustment")
        except Exception as e:
            log.warning(f"Could not click Connect Wallet: {e}")

    async def disconnect(self):
        """Close browser and clean up."""
        try:
            if self._context and self.user_data_dir:
                try:
                    self.user_data_dir.mkdir(parents=True, exist_ok=True)
                    await self._context.storage_state(path=str(self.user_data_dir / "storage.json"))
                except Exception:
                    pass
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            log.debug(f"Cleanup error: {e}")

        self._connected = False
        self._wallet_connected = False
        log.info("Browser executor disconnected")

    # ── DOM Reading Methods ──────────────────────────────────

    async def read_price(self, pair: str = "") -> float:
        """Read current market price from the DOM."""
        if not self._page:
            return 0.0

        try:
            # Try multiple selectors
            for selector in self._selectors["current_price"].split(", "):
                element = await self._page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    # Extract number from text (handles $1,234.56 format)
                    price_match = re.search(r'[\d,]+\.?\d*', text.replace(",", ""))
                    if price_match:
                        return float(price_match.group())

            # Fallback: try reading from any price-like element
            price_elements = await self._page.query_selector_all("[class*='price'], [class*='Price']")
            for elem in price_elements[:5]:
                text = await elem.inner_text()
                price_match = re.search(r'[\d,]+\.?\d*', text.replace(",", ""))
                if price_match:
                    val = float(price_match.group())
                    if val > 0.01:  # Sanity check
                        return val
        except Exception as e:
            log.debug(f"Read price error: {e}")

        return 0.0

    async def read_balance(self) -> float:
        """Read account balance from the DOM."""
        if not self._page:
            return 0.0

        try:
            for selector in self._selectors["balance_display"].split(", "):
                element = await self._page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    balance_match = re.search(r'[\d,]+\.?\d*', text.replace(",", ""))
                    if balance_match:
                        return float(balance_match.group())
        except Exception as e:
            log.debug(f"Read balance error: {e}")
        return 0.0

    async def read_positions(self) -> List[Position]:
        """Scrape open positions from the DOM."""
        if not self._page:
            return []

        positions = []
        try:
            # Click positions tab if it exists
            positions_tab = await self._page.query_selector(self._selectors["positions_tab"])
            if positions_tab:
                await positions_tab.click()
                await asyncio.sleep(0.5)

            # Read position rows
            rows = await self._page.query_selector_all(self._selectors["position_rows"])
            for row in rows:
                try:
                    text = await row.inner_text()
                    # Parse position data from text
                    # Format varies by platform, but typically:
                    # PAIR | SIDE | SIZE | ENTRY | MARK | PNL | LEVERAGE
                    parts = text.split()
                    if len(parts) >= 4:
                        position = Position(
                            pair=parts[0] if "/" in parts[0] else f"{parts[0]}/USD",
                            side="long" if any(s in text.lower() for s in ["long", "buy"]) else "short",
                        )

                        # Extract numbers
                        numbers = re.findall(r'-?[\d,]+\.?\d*', text.replace(",", ""))
                        if len(numbers) >= 2:
                            position.entry_price = float(numbers[0]) if float(numbers[0]) > 1 else 0
                            position.current_price = float(numbers[1]) if len(numbers) > 1 and float(numbers[1]) > 1 else 0

                        for num_str in numbers:
                            val = float(num_str)
                            if 0.001 < abs(val) < 1000 and position.quantity == 0:
                                position.quantity = abs(val)
                            elif "%" in text and position.unrealized_pnl == 0:
                                position.unrealized_pnl = val

                        positions.append(position)
                except Exception as e:
                    log.debug(f"Position parse error: {e}")

        except Exception as e:
            log.debug(f"Read positions error: {e}")

        return positions

    async def read_orderbook(self) -> Dict:
        """Scrape order book data from the DOM."""
        result = {"bids": [], "asks": []}
        if not self._page:
            return result

        try:
            # Read bids
            bid_elements = await self._page.query_selector_all(
                f"{self._selectors['orderbook_bids']} [class*='row'], {self._selectors['orderbook_bids']} tr"
            )
            for elem in bid_elements[:20]:
                text = await elem.inner_text()
                numbers = re.findall(r'[\d,]+\.?\d*', text.replace(",", ""))
                if len(numbers) >= 2:
                    result["bids"].append((float(numbers[0]), float(numbers[1])))

            # Read asks
            ask_elements = await self._page.query_selector_all(
                f"{self._selectors['orderbook_asks']} [class*='row'], {self._selectors['orderbook_asks']} tr"
            )
            for elem in ask_elements[:20]:
                text = await elem.inner_text()
                numbers = re.findall(r'[\d,]+\.?\d*', text.replace(",", ""))
                if len(numbers) >= 2:
                    result["asks"].append((float(numbers[0]), float(numbers[1])))

        except Exception as e:
            log.debug(f"Read orderbook error: {e}")

        return result

    # ── Order Placement ──────────────────────────────────────

    async def select_market(self, pair: str) -> bool:
        """Select a trading pair in the UI."""
        if not self._page:
            return False

        try:
            selector = await self._page.query_selector(self._selectors["market_selector"])
            if selector:
                await human_click(self._page, self._selectors["market_selector"])
                await random_delay(self.min_delay, self.max_delay)

                # Look for the pair in the dropdown
                pair_option = await self._page.query_selector(
                    f"[data-pair='{pair}'], button:has-text('{pair}'), "
                    f"li:has-text('{pair}'), div:has-text('{pair}')"
                )
                if pair_option:
                    await pair_option.click()
                    await random_delay(300, 600)
                    log.info(f"Selected market: {pair}")
                    return True

            # Try direct URL navigation
            pair_slug = pair.replace("/", "-").lower()
            await self._page.goto(
                f"{self.platform_url}/trade/{pair_slug}",
                wait_until="networkidle",
                timeout=15000,
            )
            await asyncio.sleep(2)
            return True

        except Exception as e:
            log.warning(f"Could not select market {pair}: {e}")
            return False

    async def set_leverage(self, leverage: int) -> bool:
        """Set the leverage in the UI."""
        if not self._page:
            return False

        try:
            # Try input field first
            lev_input = await self._page.query_selector(self._selectors["leverage_input"])
            if lev_input:
                await lev_input.fill(str(leverage))
                await random_delay(200, 400)
                return True

            # Try slider
            slider = await self._page.query_selector(self._selectors["leverage_slider"])
            if slider:
                # Click on the correct position of the slider
                box = await slider.bounding_box()
                if box:
                    # Assume slider goes from 1x to 20x
                    ratio = (leverage - 1) / 19
                    target_x = box["x"] + box["width"] * ratio
                    target_y = box["y"] + box["height"] / 2
                    await human_move_mouse(self._page, int(target_x), int(target_y))
                    await self._page.mouse.click(int(target_x), int(target_y))
                    return True

            # Try leverage buttons (some UIs have preset buttons)
            lev_btn = await self._page.query_selector(f"button:has-text('{leverage}x')")
            if lev_btn:
                await lev_btn.click()
                return True

        except Exception as e:
            log.warning(f"Could not set leverage to {leverage}x: {e}")
        return False

    async def place_order(self, order: Order) -> Order:
        """
        Place an order through the web UI by clicking buttons and filling forms.
        """
        start_time = time.time()

        if not self._page or not self._connected:
            order.status = OrderStatus.REJECTED
            order.error = "Browser not connected"
            return order

        try:
            # 1. Select market
            await self.select_market(order.pair)
            await random_delay(self.min_delay, self.max_delay)

            # 2. Select order type (Market / Limit)
            if order.order_type == OrderType.MARKET:
                market_btn = await self._page.query_selector(self._selectors["order_type_market"])
                if market_btn:
                    await market_btn.click()
                    await random_delay(200, 400)
            elif order.order_type == OrderType.LIMIT:
                limit_btn = await self._page.query_selector(self._selectors["order_type_limit"])
                if limit_btn:
                    await limit_btn.click()
                    await random_delay(200, 400)

                # Enter price for limit orders
                price_input = await self._page.query_selector(self._selectors["price_input"])
                if price_input:
                    await price_input.fill(str(order.price))
                    await random_delay(200, 400)

            # 3. Set leverage
            if order.leverage > 1:
                await self.set_leverage(order.leverage)
                await random_delay(200, 400)

            # 4. Enter quantity
            qty_input = await self._page.query_selector(self._selectors["quantity_input"])
            if qty_input:
                await qty_input.click()
                await qty_input.fill("")
                await asyncio.sleep(0.1)
                await qty_input.fill(str(order.quantity))
                await random_delay(300, 600)

            # 5. Click Buy or Sell
            if order.side in (OrderSide.BUY, OrderSide.LONG):
                await human_click(self._page, self._selectors["buy_button"])
            else:
                await human_click(self._page, self._selectors["sell_button"])

            await random_delay(500, 1000)

            # 6. Confirm order if there's a confirmation dialog
            confirm_btn = await self._page.query_selector(
                "button:has-text('Confirm'), button:has-text('Yes'), "
                "button:has-text('Place Order'), [data-testid='confirm-order']"
            )
            if confirm_btn:
                await confirm_btn.click()
                await random_delay(500, 1000)

            # 7. Check for success/error messages
            await asyncio.sleep(1)
            success = await self._page.query_selector(
                ".toast-success, .notification-success, [class*='success']"
            )
            error = await self._page.query_selector(
                ".toast-error, .notification-error, [class*='error']"
            )

            latency = (time.time() - start_time) * 1000

            if error:
                error_text = await error.inner_text()
                order.status = OrderStatus.REJECTED
                order.error = error_text[:200]
                log.warning(f"Order {order.id} rejected by UI: {error_text[:100]}")
            else:
                # Assume success if no error
                order.status = OrderStatus.FILLED
                order.filled_price = await self.read_price()
                order.filled_quantity = order.quantity
                log.info(
                    f"Order {order.id} placed via browser: {order.side.value} {order.pair} "
                    f"qty={order.quantity} [{latency:.0f}ms]"
                )

            # Screenshot for debugging
            if self.user_data_dir:
                screenshot_path = self.user_data_dir / f"order_{order.id}.png"
                await self._page.screenshot(path=str(screenshot_path))

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.error = str(e)
            log.error(f"Browser order {order.id} error: {e}")

        order.updated_at = time.time()
        return order

    async def close_position(self, position_index: int = 0) -> bool:
        """Close a position by clicking the Close button in the positions table."""
        if not self._page:
            return False

        try:
            # Navigate to positions tab
            positions_tab = await self._page.query_selector(self._selectors["positions_tab"])
            if positions_tab:
                await positions_tab.click()
                await random_delay(300, 600)

            # Find close buttons
            close_buttons = await self._page.query_selector_all(self._selectors["close_position_btn"])
            if position_index < len(close_buttons):
                await close_buttons[position_index].click()
                await random_delay(500, 1000)

                # Confirm
                confirm = await self._page.query_selector("button:has-text('Confirm'), button:has-text('Close Position')")
                if confirm:
                    await confirm.click()
                    await random_delay(500, 1000)

                log.info(f"Position {position_index} closed via browser")
                return True
        except Exception as e:
            log.error(f"Close position error: {e}")
        return False

    async def take_screenshot(self, name: str = "screenshot") -> Optional[str]:
        """Take a screenshot for debugging."""
        if not self._page:
            return None
        try:
            if self.user_data_dir:
                path = self.user_data_dir / f"{name}.png"
                await self._page.screenshot(path=str(path))
                return str(path)
        except Exception as e:
            log.debug(f"Screenshot error: {e}")
        return None

    @property
    def is_available(self) -> bool:
        return self._connected and self._wallet_connected

    async def get_balance(self) -> float:
        """Wrapper for balance reading."""
        return await self.read_balance()

    async def get_positions(self) -> List[Position]:
        """Wrapper for position reading."""
        return await self.read_positions()

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel is harder in browser mode — try to find cancel button."""
        log.warning("Order cancellation in browser mode is limited")
        return False

    async def cancel_all_orders(self, pair: Optional[str] = None) -> int:
        """Cancel all orders in browser mode."""
        log.warning("Bulk cancel in browser mode not fully supported")
        return 0
