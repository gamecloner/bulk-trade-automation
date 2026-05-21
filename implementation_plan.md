# Bulk.trade Testnet Algorithmic Trading Bot

> **Platform**: [Bulk Trade](https://early.bulk.trade/) — Solana Perpetual DEX (Testnet/Alphanet)
> **Strategies**: Scalping + Arbitrage
> **Approach**: Dual-mode (SDK-first, Browser Automation fallback)

## Background

Bulk.trade is a high-performance decentralized perpetual exchange on Solana with an in-memory matching engine embedded in validator nodes. It supports BTC/USD, ETH/USD, SOL/USD with up to 20x leverage, gasless trading, and FIFO order matching.

The platform has official SDKs ([bulk-client](https://github.com/Bulk-trade/bulk-client), [bulk-keychain](https://github.com/Bulk-trade/bulk-keychain)) but the user reports API access is restricted. We build a **dual-mode bot** that can operate via:

1. **Mode A — Direct SDK/API** (fast, low-latency, preferred)
2. **Mode B — Stealth Browser Automation** (when API is blocked, uses Playwright + wallet injection)

---

## User Review Required

> [!IMPORTANT]
> **Wallet Security**: The bot will need access to your Solana private key (testnet only). Keys are stored locally and never transmitted. Confirm you're comfortable with this for testnet usage.

> [!WARNING]
> **Anti-Bot Detection**: Browser automation mode uses stealth techniques to avoid detection. On testnet this is low-risk, but on mainnet this could result in account restrictions. This build is **testnet-only**.

## Open Questions

1. **Which testnet URL?** Is it `early.bulk.trade` or `alphanet.bulk.trade`? Both have been mentioned for their testnet.
2. **Wallet**: Do you already have a Phantom/Solana wallet with testnet funds, or should the bot generate keypairs and auto-claim faucet tokens?
3. **Markets**: Which pairs to trade? (BTC/USD, ETH/USD, SOL/USD, or all?)
4. **Leverage**: What max leverage? (Platform supports up to 20x)
5. **Dashboard**: Do you want a web-based dashboard (browser UI) or a terminal/CLI dashboard (like your previous "THE GOD KILLER" style)?

---

## Proposed Changes

### Project Structure

```
bulk trade bot/
├── config/
│   ├── settings.py          # [NEW] All configuration & environment variables
│   └── strategies.py        # [NEW] Strategy parameters (scalping, arb thresholds)
├── core/
│   ├── __init__.py           # [NEW]
│   ├── engine.py             # [NEW] Main trading engine orchestrator
│   ├── order_manager.py      # [NEW] Order placement, tracking, cancellation
│   └── risk_manager.py       # [NEW] Position limits, stop-loss, drawdown protection
├── execution/
│   ├── __init__.py           # [NEW]
│   ├── sdk_executor.py       # [NEW] Mode A: Direct API/SDK execution
│   ├── browser_executor.py   # [NEW] Mode B: Playwright stealth browser automation
│   └── wallet_provider.py    # [NEW] Wallet injection & Phantom mock provider
├── strategies/
│   ├── __init__.py           # [NEW]
│   ├── base_strategy.py      # [NEW] Abstract strategy interface
│   ├── scalper.py            # [NEW] HFT scalping strategy
│   └── arbitrage.py          # [NEW] Cross-market arbitrage strategy
├── data/
│   ├── __init__.py           # [NEW]
│   ├── price_feed.py         # [NEW] Real-time price data via WebSocket/scraping
│   ├── orderbook.py          # [NEW] Order book aggregation & analysis
│   └── indicators.py         # [NEW] Technical indicators (EMA, RSI, VWAP, Bollinger)
├── ui/
│   ├── __init__.py           # [NEW]
│   └── dashboard.py          # [NEW] Rich terminal dashboard (live P&L, positions)
├── utils/
│   ├── __init__.py           # [NEW]
│   ├── logger.py             # [NEW] Structured logging with rotation
│   ├── crypto_utils.py       # [NEW] Solana keypair management, signing
│   └── anti_detect.py        # [NEW] Browser fingerprint randomization
├── main.py                   # [NEW] Entry point with CLI menu
├── requirements.txt          # [NEW] All dependencies
├── .env.example              # [NEW] Environment variable template
└── README.md                 # [NEW] Setup & usage guide
```

---

### Component 1: Configuration Layer

#### [NEW] [settings.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/config/settings.py)
- Platform URLs (testnet/mainnet toggle)
- Wallet configuration (private key from `.env`)
- Execution mode selection (SDK vs Browser)
- RPC endpoint configuration
- Trading parameters (max position size, leverage limits)

#### [NEW] [strategies.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/config/strategies.py)
- Scalping parameters: tick size, profit target (0.05-0.2%), stop-loss, cooldown
- Arbitrage parameters: min spread threshold, execution window, slippage tolerance
- Risk parameters: max drawdown %, max concurrent positions, daily loss limit

---

### Component 2: Core Trading Engine

#### [NEW] [engine.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/core/engine.py)
Main orchestrator that:
- Initializes the execution layer (SDK or Browser)
- Connects to price feeds
- Runs strategy loops in async event loop
- Manages position lifecycle
- Feeds data to dashboard

#### [NEW] [order_manager.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/core/order_manager.py)
- Order creation (market, limit, stop-loss, take-profit)
- Order state tracking (pending → filled → closed)
- Batch order support (bulk cancel, bulk place)
- Order history and fill tracking

#### [NEW] [risk_manager.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/core/risk_manager.py)
- Position size calculation based on account balance
- Maximum drawdown enforcement (kill switch at -X%)
- Per-trade risk limits
- Correlation-based position limits
- Emergency stop (manual override)

---

### Component 3: Execution Layer (The Key Innovation)

#### [NEW] [sdk_executor.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/execution/sdk_executor.py)
**Mode A — Direct SDK Integration**
```python
# Uses bulk-client SDK if available
# Falls back to raw HTTP/WebSocket if SDK is restricted
class SDKExecutor:
    async def connect()          # Initialize SDK connection
    async def place_order()      # Submit order via API
    async def cancel_order()     # Cancel by order ID
    async def get_positions()    # Fetch open positions
    async def get_orderbook()    # Real-time orderbook
    async def stream_prices()    # WebSocket price stream
```

#### [NEW] [browser_executor.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/execution/browser_executor.py)
**Mode B — Stealth Browser Automation** (when API is blocked)
```python
# Uses Playwright with stealth patches + wallet injection
class BrowserExecutor:
    async def launch_browser()   # Stealth Chromium with anti-detection
    async def connect_wallet()   # Inject mock Phantom provider
    async def navigate_to_trade()# Go to trading interface
    async def place_order()      # Click-based order placement
    async def read_positions()   # Scrape position data from DOM
    async def read_orderbook()   # Scrape orderbook from DOM
    async def read_price()       # Scrape current price
```

Key stealth features:
- `navigator.webdriver` removal
- Consistent WebGL/Canvas fingerprints
- Realistic mouse movement patterns (Bezier curves)
- Random delays between actions (human-like timing)
- Viewport/User-Agent randomization
- Residential proxy support

#### [NEW] [wallet_provider.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/execution/wallet_provider.py)
Mock Phantom wallet that auto-approves transactions:
```python
# Injects a fake window.solana provider that:
# - Auto-connects with our keypair
# - Auto-signs transactions
# - Auto-approves all prompts
# No need for actual Phantom extension!
```

---

### Component 4: Trading Strategies

#### [NEW] [scalper.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/strategies/scalper.py)
High-frequency scalping strategy:
- **Entry signals**: EMA crossover (9/21), RSI extremes, orderbook imbalance
- **Exit signals**: Fixed take-profit (0.1-0.3%), trailing stop, time-based exit
- **Execution**: Market orders for speed, limit orders for better fills
- **Frequency**: Targets 50-200 trades per session
- **Edge**: Orderbook depth analysis + momentum detection

#### [NEW] [arbitrage.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/strategies/arbitrage.py)
Cross-reference arbitrage:
- Compare Bulk.trade prices vs external feeds (Binance, Pyth, Switchboard)
- Detect price discrepancies > threshold
- Execute when spread covers fees + slippage
- Supports triangular arb across pairs (BTC/USD → ETH/USD → ETH/BTC)

---

### Component 5: Data Layer

#### [NEW] [price_feed.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/data/price_feed.py)
- WebSocket connection to Bulk.trade for real-time prices
- Fallback: Browser DOM scraping for price data
- External feeds: Binance WebSocket, Pyth Oracle for arb comparison
- Price history buffer (in-memory ring buffer for indicators)

#### [NEW] [orderbook.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/data/orderbook.py)
- Real-time orderbook reconstruction
- Bid/ask spread tracking
- Depth analysis (support/resistance detection)
- Imbalance ratio calculation

#### [NEW] [indicators.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/data/indicators.py)
- EMA (9, 21, 50 periods)
- RSI (14 period)
- VWAP
- Bollinger Bands
- ATR (for dynamic stop-loss)
- All computed incrementally (no full recomputation)

---

### Component 6: Terminal Dashboard

#### [NEW] [dashboard.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/ui/dashboard.py)
Rich terminal UI using `rich` library:
```
╔══════════════════════════════════════════════════════════╗
║          ⚡ BULK TRADE BOT — THE GOD KILLER ⚡           ║
╠══════════════════════════════════════════════════════════╣
║ Mode: BROWSER │ Market: SOL/USD │ Leverage: 10x         ║
║ Balance: $10,000.00  │ P&L: +$127.50 (+1.27%)          ║
╠══════════════════════════════════════════════════════════╣
║ POSITIONS                                                ║
║ SOL/USD  LONG   10x  Entry: $168.50  Current: $169.20   ║
║ BTC/USD  SHORT  5x   Entry: $67,450  Current: $67,380   ║
╠══════════════════════════════════════════════════════════╣
║ RECENT TRADES                       │ SIGNALS            ║
║ 09:15:23 BUY  SOL  $168.50 +0.12%  │ RSI: 45 ▬▬▬▮▬▬    ║
║ 09:14:58 SELL BTC  $67,450 +0.08%  │ EMA: BULLISH ↑     ║
║ 09:14:12 BUY  ETH  $3,820  -0.03%  │ VOL: HIGH ████     ║
╠══════════════════════════════════════════════════════════╣
║ ORDERBOOK (SOL/USD)                                      ║
║ ASK ████████ $169.50 (250)                               ║
║ ASK ████     $169.25 (120)                               ║
║ --- SPREAD: $0.15 (0.09%) ---                           ║
║ BID ██████   $169.10 (180)                               ║
║ BID ████████████ $168.90 (350)                           ║
╚══════════════════════════════════════════════════════════╝
```

---

### Component 7: Utilities

#### [NEW] [anti_detect.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/utils/anti_detect.py)
- Browser fingerprint generation (consistent per session)
- Human-like mouse movement (Bezier curve interpolation)
- Typing simulation with realistic WPM variance
- Random scroll patterns
- Cookie/localStorage management

#### [NEW] [crypto_utils.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/utils/crypto_utils.py)
- Solana keypair generation & management
- Transaction signing (ed25519)
- Base58 encoding/decoding
- Wallet file management

#### [NEW] [logger.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/utils/logger.py)
- Structured JSON logging
- File rotation (daily)
- Trade log (separate CSV for analysis)
- Performance metrics

---

### Entry Point

#### [NEW] [main.py](file:///c:/Users/singh/Downloads/bulk%20trade%20bot/main.py)
```
╔═══════════════════════════════════════╗
║    ⚡ THE GOD KILLER — BULK BOT ⚡    ║
╠═══════════════════════════════════════╣
║  [1] Start Scalping Bot              ║
║  [2] Start Arbitrage Bot             ║
║  [3] Start Both (Multi-Strategy)     ║
║  [4] Monitor Only (No Trading)       ║
║  [5] Configuration                   ║
║  [6] View Trade History              ║
║  [0] Exit                            ║
╚═══════════════════════════════════════╝
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Async Runtime | `asyncio` + `aiohttp` |
| Browser Automation | `playwright` + custom stealth |
| Solana Interaction | `solders` + `solana-py` |
| Price Feeds | `websockets` (Binance WS) |
| CLI Dashboard | `rich` (live panels) |
| Data Processing | `numpy` (indicators) |
| Configuration | `python-dotenv` |
| Logging | `loguru` |

---

## Verification Plan

### Automated Tests
1. **Unit Tests**: Strategy signal generation with mock price data
2. **Integration Test**: Connect to testnet, place a limit order, verify fill
3. **Dry Run Mode**: Execute full strategy loop with paper trading (no real orders)
4. **Browser Test**: Launch Playwright, connect to testnet UI, verify DOM element detection

### Manual Verification
1. Run bot in monitor mode — verify price feeds are accurate
2. Execute single test trade via both SDK and browser modes
3. Verify P&L calculation accuracy
4. Stress test with rapid order placement
5. Verify emergency stop kills all positions
