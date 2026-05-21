# ⚡ THE GOD KILLER — Bulk Trade Algorithmic Trading Bot

A production-grade algorithmic trading bot for [Bulk.trade](https://early.bulk.trade/) (Solana Perpetual DEX) testnet.

Features dual execution modes: **direct SDK/API** for maximum speed, and **stealth browser automation** when the API is blocked.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    main.py (CLI Menu)                │
├──────────────────────┬──────────────────────────────┤
│   Trading Engine     │       Dashboard (Rich)       │
│   ┌──────────────┐   │   ┌──────────────────────┐   │
│   │ Price Feed   │───┼──▶│ Live P&L / Positions │   │
│   │ (WS/HTTP)    │   │   │ Signals / Orderbook  │   │
│   └──────┬───────┘   │   └──────────────────────┘   │
│          │           │                              │
│   ┌──────▼───────┐   │                              │
│   │ Strategies   │   │                              │
│   │ • Scalper    │   │                              │
│   │ • Arbitrage  │   │                              │
│   └──────┬───────┘   │                              │
│          │           │                              │
│   ┌──────▼───────┐   │                              │
│   │ Risk Manager │   │                              │
│   │ (Kill Switch)│   │                              │
│   └──────┬───────┘   │                              │
│          │           │                              │
│   ┌──────▼───────┐   │                              │
│   │Order Manager │   │                              │
│   └──────┬───────┘   │                              │
│          │           │                              │
│   ┌──────▼───────────────────────────────────────┐  │
│   │          Execution Layer                     │  │
│   │  ┌─────────────┐    ┌──────────────────────┐│  │
│   │  │ SDK Executor │    │ Browser Executor     ││  │
│   │  │ (Direct API) │    │ (Playwright Stealth) ││  │
│   │  └─────────────┘    │ + Phantom Wallet Mock ││  │
│   │                     └──────────────────────┘│  │
│   └─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd "bulk trade bot"
pip install -r requirements.txt

# Install Playwright browsers (for browser automation mode)
playwright install chromium
```

### 2. Configure

```bash
# Copy the example config
copy .env.example .env

# Edit .env with your settings (optional - defaults work for testnet)
```

### 3. Run

```bash
# Interactive menu
python main.py

# Or direct CLI
python main.py --sim       # Simulation mode (recommended first run)
python main.py --scalp     # Scalping only
python main.py --arb       # Arbitrage only
python main.py --all       # All strategies
python main.py --monitor   # Watch prices only
```

---

## ⚡ Execution Modes

| Mode | Speed | Reliability | When to Use |
|------|-------|-------------|-------------|
| **SDK** | ⚡⚡⚡ Fastest | High | API is available |
| **Browser** | ⚡ Slower | Medium | API is blocked |
| **Auto** | ⚡⚡⚡→⚡ | High | Default — tries SDK, falls back to browser |
| **Simulation** | ⚡⚡ | N/A | Testing & development |

### Browser Automation Features
- **Stealth Patches**: Removes `navigator.webdriver`, fakes WebGL, plugins, etc.
- **Mock Phantom Wallet**: Injects a fake `window.solana` provider — no extension needed
- **Human-like Movement**: Bezier curve mouse paths, variable typing speed
- **Anti-Detection**: Randomized viewport, user-agent, fingerprints

---

## 📊 Trading Strategies

### Scalper
High-frequency strategy using 5 factors:
- **EMA Crossover** (9/21 period) — trend direction
- **RSI** (14 period) — overbought/oversold
- **Orderbook Imbalance** — buy/sell pressure
- **MACD Histogram** — momentum confirmation
- **Bollinger Bands** — mean reversion at extremes

Targets: 0.15% profit, 0.10% stop-loss, 5s cooldown

### Arbitrage
Cross-venue price discrepancy exploitation:
- Compares Bulk.trade vs Binance prices
- Executes when spread > 0.08% (net of fees)
- Convergence-based take-profit targeting
- Staleness checks prevent stale-price trades

---

## 🛡️ Risk Management

- **Position Sizing**: Fixed-fractional based on stop-loss distance
- **Daily Loss Limit**: Auto-stops at -5% daily P&L
- **Max Drawdown**: Kill switch at -10% from peak
- **Max Positions**: Configurable concurrent position limit
- **Emergency Stop**: Ctrl+C closes all positions gracefully

---

## 📁 Project Structure

```
bulk trade bot/
├── config/
│   └── settings.py          # Configuration from .env
├── core/
│   ├── engine.py             # Main orchestrator
│   ├── order_manager.py      # Order lifecycle
│   └── risk_manager.py       # Risk limits & kill switch
├── execution/
│   ├── sdk_executor.py       # Direct API execution
│   ├── browser_executor.py   # Playwright browser automation
│   └── wallet_provider.py    # Mock Phantom wallet injection
├── strategies/
│   ├── base_strategy.py      # Abstract strategy interface
│   ├── scalper.py            # HFT scalping
│   └── arbitrage.py          # Cross-venue arbitrage
├── data/
│   ├── price_feed.py         # Multi-source price aggregation
│   ├── orderbook.py          # Order book analysis
│   └── indicators.py         # EMA, RSI, VWAP, BB, ATR, MACD
├── ui/
│   └── dashboard.py          # Rich terminal dashboard
├── utils/
│   ├── logger.py             # Logging + trade CSV
│   ├── crypto_utils.py       # Solana wallet management
│   └── anti_detect.py        # Browser stealth utilities
├── main.py                   # Entry point + CLI menu
├── requirements.txt          # Dependencies
├── .env.example              # Config template
└── README.md                 # This file
```

---

## ⚠️ Disclaimer

This bot is for **testnet use only**. Trading on mainnet carries real financial risk.
Always test thoroughly before deploying with real funds.
