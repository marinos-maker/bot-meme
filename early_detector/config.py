"""
Configuration module — loads environment variables and defines constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
SUPABASE_DB_URL: str = os.getenv("SUPABASE_DB_URL", "")
DATA_DIR: str = os.getenv("DATA_DIR", ".")

# ── API Keys ──────────────────────────────────────────────────────────────────
DEXSCREENER_API_URL: str = os.getenv(
    "DEXSCREENER_API_URL", "https://api.dexscreener.com/latest"
)
PUMPPORTAL_API_KEY: str = os.getenv("PUMPPORTAL_API_KEY", "")

# AI APIs
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
AI_MODEL_NAME: str = os.getenv("AI_MODEL_NAME", "z-ai/glm-4.5-air:free")

WALLET_PUBLIC_KEY: str = os.getenv("WALLET_PUBLIC_KEY", "")
ALCHEMY_RPC_URL: str = os.getenv("ALCHEMY_RPC_URL", "")

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Trading Filters ──────────────────────────────────────────────────────────
LIQUIDITY_MIN: float = float(os.getenv("LIQUIDITY_MIN", "1000"))  # Reduced for early detection
MCAP_MAX: float = float(os.getenv("MCAP_MAX", "10000000"))
TOP10_MAX_RATIO: float = float(os.getenv("TOP10_MAX_RATIO", "0.60"))  # More flexible for meme coins

# ── Scoring ───────────────────────────────────────────────────────────────────
SIGNAL_PERCENTILE: float = float(os.getenv("SIGNAL_PERCENTILE", "0.60"))  # More aggressive threshold

# ── Instability Index Weights (default, can be overridden by optimizer) ──────
WEIGHT_SA: float = 2.0        # Stealth Accumulation
WEIGHT_HOLDER: float = 1.5    # Holder Acceleration
WEIGHT_VS: float = 1.5        # Volatility Shift
WEIGHT_SWR: float = 2.0       # Smart Wallet Rotation
WEIGHT_VI: float = 2.0        # Volume Intensity (Turnover)
WEIGHT_SELL: float = 2.0      # Sell Pressure (subtracted)

# ── Smart Wallet Thresholds ───────────────────────────────────────────────────
# Opzione C: Criteri più flessibili per identificare più smart wallet
SW_MIN_ROI: float = 1.0      # Da 1.1 a 1.0 (ROI > 1.0x)
SW_MIN_TRADES: int = 1       # Da 2 a 1 (Trade >= 1)
SW_MIN_WIN_RATE: float = 0.25 # Mantenere 25%

# ── Timing ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL: int = int(os.getenv("SCAN_INTERVAL", "15"))  # Reduced for V4.0 latency
DASHBOARD_PORT: int = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", "8050")))

# ── Safety Filters ────────────────────────────────────────────────────────────
MAX_TOP5_HOLDER_RATIO: float = 0.40
DEV_WALLET_TIMEOUT_MIN: int = 10
SPIKE_THRESHOLD: float = 5.0   # 5x in 5 min = too late

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE: str = "logs/runtime.log"
LOG_ROTATION: str = "10 MB"
LOG_LEVEL: str = "INFO"

# ── Trading (V5.0) ───────────────────────────────────────────────────────────
WALLET_PRIVATE_KEY: str = os.getenv("WALLET_PRIVATE_KEY", "")
TRADE_AMOUNT_SOL: float = float(os.getenv("TRADE_AMOUNT_SOL", "0.1"))
DEFAULT_TP_PCT: float = float(os.getenv("DEFAULT_TP_PCT", "50"))
DEFAULT_SL_PCT: float = float(os.getenv("DEFAULT_SL_PCT", "30"))
SLIPPAGE_BPS: int = int(os.getenv("SLIPPAGE_BPS", "200"))  # 200 = 2%
AUTO_TRADE_ENABLED: bool = os.getenv("AUTO_TRADE_ENABLED", "true").lower() == "true"
SOL_MINT: str = "So11111111111111111111111111111111111111112"

