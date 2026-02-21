
import numpy as np
from loguru import logger

class AlphaEngine:
    """
    Hedge-fund grade mathematical models for risk and scoring.
    """

    @staticmethod
    def calculate_bayesian_confidence(prior: float, likelihoods: list[float]) -> float:
        """
        Updates signal confidence using Bayesian inference.
        P(H|D) = (P(D|H) * P(H)) / P(D)
        
        Args:
            prior: The initial confidence (0-1).
            likelihoods: A list of likelihood ratios (P(D|Signal) / P(D|NoSignal)).
                        > 1.0 increases confidence, < 1.0 decreases it.
        """
        if not likelihoods:
            return prior
            
        # Cumulative product of likelihoods
        final_odds = (prior / (1 - prior + 1e-9)) * np.prod(likelihoods)
        
        # Convert back to probability
        posterior = final_odds / (1 + final_odds)
        return float(np.clip(posterior, 0.01, 0.99))

    @staticmethod
    def calculate_kelly_size(win_prob: float, avg_win_multiplier: float, 
                             avg_loss_multiplier: float = 0.15,
                             fractional_kelly: float = 0.25) -> float:
        """
        Calculates optimal position size using the Refined V4.0 Formula.
        E = win_rate * avg_win - loss_rate * avg_loss
        f* = k * (E / avg_loss)
        
        Args:
            win_prob: Probability of winning (0-1).
            avg_win_multiplier: Average profit (e.g. 0.4 for 40% gain).
            avg_loss_multiplier: Average loss (e.g. 0.15 for 15% loss).
            fractional_kelly: Safety multiplier (k = 0.25 default).
        """
        p = win_prob
        q = 1 - p
        w = avg_win_multiplier
        l = avg_loss_multiplier
        
        if l <= 0:
            return 0.0
            
        expectancy = (p * w) - (q * l)
        
        if expectancy <= 0:
            return 0.0
            
        kelly = expectancy / l
        
        # Apply fractional Kelly and clip to 0-100%
        final_size = kelly * fractional_kelly
        return float(np.clip(final_size, 0.0, 1.0))

    @staticmethod
    def run_monte_carlo_sim(win_rate: float, avg_win: float, avg_loss: float, 
                            num_trades: int = 100, num_sims: int = 1000) -> dict:
        """
        Simulates risk of ruin and drawdown using Monte Carlo.
        """
        all_equity_curves = []
        
        for _ in range(num_sims):
            balance = 1.0
            curve = [balance]
            for _ in range(num_trades):
                if np.random.random() < win_rate:
                    balance *= (1 + avg_win)
                else:
                    balance *= (1 - avg_loss)
                curve.append(balance)
            all_equity_curves.append(curve)
            
        curves = np.array(all_equity_curves)
        final_balances = curves[:, -1]
        
        # Calculate Drawdown
        peaks = np.maximum.accumulate(curves, axis=1)
        drawdowns = (peaks - curves) / peaks
        max_drawdowns = np.max(drawdowns, axis=1)
        
        return {
            "expected_return": float(np.mean(final_balances) - 1),
            "median_return": float(np.median(final_balances) - 1),
            "max_drawdown_avg": float(np.mean(max_drawdowns)),
            "risk_of_ruin": float(np.mean(final_balances < 0.2)) # 80% loss
        }
