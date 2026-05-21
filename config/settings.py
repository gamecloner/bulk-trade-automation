"""
Centralized configuration for Bulk Trade Bot.
Loads from .env file and provides typed access to all settings.
"""

import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)
else:
    load_dotenv(_PROJECT_ROOT / ".env.example")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _get_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes")


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _get_list(key: str, default: str = "") -> List[str]:
    raw = os.getenv(key, default)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Execution Modes ──────────────────────────────────────────────
EXECUTION_MODE_SDK = "sdk"
EXECUTION_MODE_BROWSER = "browser"
EXECUTION_MODE_AUTO = "auto"


@dataclass
class WalletConfig:
    """Solana wallet configuration."""
    private_key: str = field(default_factory=lambda: _get("SOLANA_PRIVATE_KEY"))
    auto_generate: bool = field(default_factory=lambda: _get_bool("AUTO_GENERATE_WALLET", True))
    keypair_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "wallets")

    def __post_init__(self):
        self.keypair_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class PlatformConfig:
    """Platform connection settings."""
    url: str = field(default_factory=lambda: _get("PLATFORM_URL", "https://early.bulk.trade"))
    testnet: bool = field(default_factory=lambda: _get_bool("TESTNET", True))
    rpc_url: str = field(default_factory=lambda: _get("SOLANA_RPC_URL", "https://api.devnet.solana.com"))


@dataclass
class TradingConfig:
    """Trading parameters."""
    execution_mode: str = field(default_factory=lambda: _get("EXECUTION_MODE", "auto"))
    default_leverage: int = field(default_factory=lambda: _get_int("DEFAULT_LEVERAGE", 10))
    max_leverage: int = field(default_factory=lambda: _get_int("MAX_LEVERAGE", 20))
    max_position_size_usd: float = field(default_factory=lambda: _get_float("MAX_POSITION_SIZE_USD", 1000))
    max_concurrent_positions: int = field(default_factory=lambda: _get_int("MAX_CONCURRENT_POSITIONS", 3))
    daily_loss_limit_pct: float = field(default_factory=lambda: _get_float("DAILY_LOSS_LIMIT_PCT", 5.0))
    max_drawdown_pct: float = field(default_factory=lambda: _get_float("MAX_DRAWDOWN_PCT", 10.0))
    trading_pairs: List[str] = field(default_factory=lambda: _get_list("TRADING_PAIRS", "SOL/USD,BTC/USD,ETH/USD"))


@dataclass
class ScalpingConfig:
    """Scalping strategy parameters."""
    profit_target_pct: float = field(default_factory=lambda: _get_float("SCALP_PROFIT_TARGET_PCT", 0.15))
    stop_loss_pct: float = field(default_factory=lambda: _get_float("SCALP_STOP_LOSS_PCT", 0.10))
    cooldown_seconds: int = field(default_factory=lambda: _get_int("SCALP_COOLDOWN_SECONDS", 5))
    ema_fast: int = field(default_factory=lambda: _get_int("SCALP_EMA_FAST", 9))
    ema_slow: int = field(default_factory=lambda: _get_int("SCALP_EMA_SLOW", 21))
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    min_volume_threshold: float = 100.0  # Minimum volume to consider entry


@dataclass
class ArbitrageConfig:
    """Arbitrage strategy parameters."""
    min_spread_pct: float = field(default_factory=lambda: _get_float("ARB_MIN_SPREAD_PCT", 0.08))
    execution_window_ms: int = field(default_factory=lambda: _get_int("ARB_EXECUTION_WINDOW_MS", 2000))
    slippage_tolerance_pct: float = field(default_factory=lambda: _get_float("ARB_SLIPPAGE_TOLERANCE_PCT", 0.05))
    price_staleness_ms: int = 5000  # Max age of price data before considered stale
    min_profit_usd: float = 0.50  # Minimum absolute profit to execute


@dataclass
class BrowserConfig:
    """Browser automation settings."""
    headless: bool = field(default_factory=lambda: _get_bool("HEADLESS", True))
    proxy: Optional[str] = field(default_factory=lambda: _get("BROWSER_PROXY") or None)
    min_action_delay_ms: int = field(default_factory=lambda: _get_int("MIN_ACTION_DELAY_MS", 200))
    max_action_delay_ms: int = field(default_factory=lambda: _get_int("MAX_ACTION_DELAY_MS", 800))
    viewport_width: int = 1920
    viewport_height: int = 1080
    user_data_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / ".browser_data")


@dataclass
class ExternalFeedConfig:
    """External price feed configuration."""
    binance_ws_url: str = field(
        default_factory=lambda: _get("BINANCE_WS_URL", "wss://stream.binance.com:9443/ws")
    )
    use_pyth: bool = field(default_factory=lambda: _get_bool("PYTH_PRICE_FEED", True))
    # Binance symbol mapping for Bulk.trade pairs
    pair_mapping: dict = field(default_factory=lambda: {
        "SOL/USD": "solusdt",
        "BTC/USD": "btcusdt",
        "ETH/USD": "ethusdt",
    })


@dataclass
class LogConfig:
    """Logging configuration."""
    level: str = field(default_factory=lambda: _get("LOG_LEVEL", "INFO"))
    log_file: Path = field(default_factory=lambda: _PROJECT_ROOT / _get("LOG_FILE", "logs/bot.log"))
    trade_log_file: Path = field(
        default_factory=lambda: _PROJECT_ROOT / _get("TRADE_LOG_FILE", "logs/trades.csv")
    )

    def __post_init__(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.trade_log_file.parent.mkdir(parents=True, exist_ok=True)


class Settings:
    """
    Master settings container. Singleton — use Settings.get() to access.
    All sub-configs are lazily initialized on first access.
    """
    _instance: Optional["Settings"] = None

    def __init__(self):
        self.wallet = WalletConfig()
        self.platform = PlatformConfig()
        self.trading = TradingConfig()
        self.scalping = ScalpingConfig()
        self.arbitrage = ArbitrageConfig()
        self.browser = BrowserConfig()
        self.feeds = ExternalFeedConfig()
        self.logging = LogConfig()

    @classmethod
    def get(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reload(cls) -> "Settings":
        """Force reload from environment."""
        cls._instance = None
        load_dotenv(_ENV_PATH, override=True)
        return cls.get()

    @property
    def is_sdk_mode(self) -> bool:
        return self.trading.execution_mode in (EXECUTION_MODE_SDK, EXECUTION_MODE_AUTO)

    @property
    def is_browser_mode(self) -> bool:
        return self.trading.execution_mode in (EXECUTION_MODE_BROWSER, EXECUTION_MODE_AUTO)

    def __repr__(self) -> str:
        return (
            f"Settings(\n"
            f"  platform={self.platform.url} [{'testnet' if self.platform.testnet else 'MAINNET'}]\n"
            f"  mode={self.trading.execution_mode}\n"
            f"  pairs={self.trading.trading_pairs}\n"
            f"  leverage={self.trading.default_leverage}x (max {self.trading.max_leverage}x)\n"
            f"  max_position=${self.trading.max_position_size_usd}\n"
            f")"
        )
