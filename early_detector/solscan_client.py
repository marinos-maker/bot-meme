import aiohttp
import asyncio
from loguru import logger
import os
from early_detector.config import SOLSCAN_API_KEY, SOL_MINT

SOLSCAN_BASE_URL = "https://pro-api.solscan.io/v2.0"

async def get_wallet_performance_solscan(session: aiohttp.ClientSession, wallet_addr: str, limit: int = 50) -> dict:
    """
    Fetch wallet swap history via Solscan Pro API v2
    and calculate ROI based on SOL/WSOL flow.
    """
    if not SOLSCAN_API_KEY:
        return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

    url = f"{SOLSCAN_BASE_URL}/account/transfer"
    params = {
        "address": wallet_addr,
        "page": 1,
        "page_size": limit,
        "sort_by": "block_time",
        "sort_order": "desc",
        "remove_spam": "true"
    }
    headers = {"token": SOLSCAN_API_KEY}

    try:
        async with session.get(url, params=params, headers=headers, timeout=15) as resp:
            if resp.status == 429:
                logger.debug(f"Solscan Rate Limit for {wallet_addr[:8]}")
                return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}
            
            if resp.status != 200:
                logger.debug(f"Solscan error for {wallet_addr[:8]}: HTTP {resp.status}")
                return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}
            
            body = await resp.json()
            data = body.get("data", [])
            if not data:
                return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

            # Group transfers by transaction hash to identify "swaps"
            tx_groups = {}
            for item in data:
                tx_hash = item.get("trans_id")
                if not tx_hash: continue
                if tx_hash not in tx_groups:
                    tx_groups[tx_hash] = []
                tx_groups[tx_hash].append(item)

            trades = []
            for tx_hash, transfers in tx_groups.items():
                sol_change = 0.0
                other_token = False
                
                for t in transfers:
                    mint = t.get("token_address")
                    amount = float(t.get("amount", 0)) / (10**t.get("token_decimals", 0))
                    flow = t.get("flow") # "in" or "out"
                    
                    if mint == SOL_MINT or mint == "So11111111111111111111111111111111111111112":
                        if flow == "out":
                            sol_change -= amount
                        else:
                            sol_change += amount
                    else:
                        other_token = True
                
                # If it's a trade (SOL change + other token change)
                if abs(sol_change) > 0.005 and other_token:
                    trades.append(sol_change)

            if not trades:
                return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

            wins = len([t for t in trades if t > 0])
            total = len(trades)
            net_sol = sum(trades)
            
            neg_flows = [t for t in trades if t < 0]
            total_invested = abs(sum(neg_flows)) if neg_flows else 0.01
            avg_roi = 1.0 + (net_sol / total_invested)
            win_rate = wins / total
            
            return {
                "avg_roi": round(avg_roi, 2),
                "win_rate": round(win_rate, 3),
                "total_trades": total
            }

    except Exception as e:
        logger.debug(f"Solscan request error for {wallet_addr[:8]}: {e}")
    
    return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}
