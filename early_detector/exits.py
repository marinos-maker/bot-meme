"""
3-Layer Dynamic Exit Logic (V4.0).
Provides multi-stage exit strategy for meme coin trading.
"""

from loguru import logger

class ExitStrategy:
    """
    Implements:
    - -15% Hard Stop
    - +40% Take Profit (50% sell)
    - 20% Trailing Stop for the rest
    """
    
    STOP_LOSS_RATIO = 0.15
    TP_1_RATIO = 0.40
    TRAILING_RATIO = 0.20
    
    @staticmethod
    def calculate_levels(entry_price: float) -> dict:
        """
        Calculate price levels for the 3-layer exit strategy.
        """
        if entry_price <= 0:
            return {}
            
        return {
            "hard_stop": entry_price * (1 - ExitStrategy.STOP_LOSS_RATIO),
            "tp_1": entry_price * (1 + ExitStrategy.TP_1_RATIO),
            "trailing_trigger": entry_price * (1 + ExitStrategy.TP_1_RATIO), # Trailing starts after TP1
            "trailing_distance": ExitStrategy.TRAILING_RATIO
        }
        
    @staticmethod
    def get_exit_advice(current_price: float, entry_price: float, 
                        is_halved: bool = False, max_price: float = 0.0) -> str:
        """
        Returns advice: 'HOLD', 'HALF-SELL', 'EXIT', 'TRAILING-STOP'.
        """
        levels = ExitStrategy.calculate_levels(entry_price)
        if not levels:
            return "HOLD"
            
        if current_price <= levels["hard_stop"]:
            return "EXIT (Stop Loss)"
            
        if not is_halved and current_price >= levels["tp_1"]:
            return "HALF-SELL (+40% TP)"
            
        if is_halved:
            # Trailing stop logic: exit if price falls 20% from peak
            peak = max(max_price, current_price)
            if current_price <= peak * (1 - ExitStrategy.TRAILING_RATIO):
                return "EXIT (Trailing Stop)"
                
        return "HOLD"
