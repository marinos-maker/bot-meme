"""
Configuration module — loads environment variables and defines constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
SUPABASE_DB_URL: str = os.getenv("SUPABASE_DB_URL", "")

# ── API Keys ──────────────────────────────────────────────────────────────────
BIRDEYE_API_KEY: str = os.getenv("BIRDEYE_API_KEY", "")
DEXSCREENER_API_URL: str = os.getenv(
    "DEXSCREENER_API_URL", "https://api.dexscreener.com/latest"
)
HELIUS_API_KEY: str = os.getenv("HELIUS_API_KEY", "")
HELIUS_BASE_URL: str = "https://api.helius.xyz"
HELIUS_RPC_URL: str = "https://beta.helius-rpc.com/?api-key=fdbec49d-1c82-452f-8adc-cf5c534fe74d"
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Trading Filters ──────────────────────────────────────────────────────────
LIQUIDITY_MIN: float = float(os.getenv("LIQUIDITY_MIN", "40000"))
MCAP_MAX: float = float(os.getenv("MCAP_MAX", "3000000"))
TOP10_MAX_RATIO: float = float(os.getenv("TOP10_MAX_RATIO", "0.35"))

# ── Scoring ───────────────────────────────────────────────────────────────────
SIGNAL_PERCENTILE: float = float(os.getenv("SIGNAL_PERCENTILE", "0.95"))

# ── Instability Index Weights (default, can be overridden by optimizer) ──────
WEIGHT_SA: float = 2.0        # Stealth Accumulation
WEIGHT_HOLDER: float = 1.5    # Holder Acceleration
WEIGHT_VS: float = 1.5        # Volatility Shift
WEIGHT_SWR: float = 2.0       # Smart Wallet Rotation
WEIGHT_SELL: float = 2.0      # Sell Pressure (subtracted)

# ── Smart Wallet Thresholds ───────────────────────────────────────────────────
SW_MIN_ROI: float = 2.5
SW_MIN_TRADES: int = 15
SW_MIN_WIN_RATE: float = 0.4

# ── Timing ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "120"))  # seconds (120s to respect Birdeye free tier)
DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8050"))

# ── Safety Filters ────────────────────────────────────────────────────────────
MAX_TOP5_HOLDER_RATIO: float = 0.40
DEV_WALLET_TIMEOUT_MIN: int = 10
SPIKE_THRESHOLD: float = 3.0   # 3x in 5 min = too late

# ── Birdeye API ───────────────────────────────────────────────────────────────
BIRDEYE_BASE_URL: str = "https://public-api.birdeye.so"
BIRDEYE_HEADERS: dict = {
    "X-API-KEY": BIRDEYE_API_KEY,
    "x-chain": "solana",
    "accept": "application/json",
}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE: str = "logs/runtime.log"
LOG_ROTATION: str = "10 MB"
LOG_LEVEL: str = "INFO"
