"""
Quantitative Diary (V4.0).
Logs detailed signal context for later re-calibration and analysis.
"""

import json
import os
from datetime import datetime
from loguru import logger
from early_detector.config import DATA_DIR

DIARY_FILE = os.path.join(DATA_DIR or ".", "quant_diary.jsonl")

def log_trade_signal(signal_data: dict, market_regime: str):
    """
    Log a signal to the quantitative diary.
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "token_id": signal_data.get("token_id"),
        "symbol": signal_data.get("symbol"),
        "ii": signal_data.get("instability_index"),
        "p_insider": signal_data.get("insider_psi"),
        "liquidity": signal_data.get("liquidity"),
        "mcap": signal_data.get("marketcap"),
        "regime": market_regime,
        "kelly_size": signal_data.get("kelly_size"),
        "hard_stop": signal_data.get("hard_stop"),
        "tp_1": signal_data.get("tp_1"),
        "outcome": "PENDING"
    }
    
    try:
        with open(DIARY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Failed to log to quant diary: {e}")

def update_signal_outcome(token_id: str, outcome: float):
    """
    Update the outcome (ROI multiplier) of a logged signal.
    """
    # This would involve reading the JSONL, finding the token, and updating.
    # For now, we'll implement a simpler append-only logger for performance.
    pass
