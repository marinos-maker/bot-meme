"""
Alternative Seed Script — populate wallet_performance table using Birdeye API instead of Helius.

Usage:
    python -m scripts.seed_wallets_alt
"""

import asyncio
import aiohttp
import pandas as pd
from loguru import logger

from early_detector.config import BIRDEYE_API_KEY
from early_detector.db import get_pool, close_pool, upsert_wallet, get_pool
from early_detector.smart_wallets import cluster_wallets


async def get_trending_tokens_birdeye(session: aiohttp.ClientSession,
                                      limit: int = 20) -> list[str]:
    """Fetch trending Solana meme token addresses from Birdeye."""
    if not BIRDEYE_API_KEY:
        logger.error("BIRDEYE_API_KEY not configured")
        return []

    try:
        url = "https://public-api.birdeye.so/defi/tokenlist"
        params = {
            "sort_by": "volume_24h",
            "sort_type": "desc",
            "offset": 0,
            "limit": 100,
            "chain": "solana"
        }
        headers = {"X-API-Key": BIRDEYE_API_KEY, "x-chain": "solana"}
        
        async with session.get(url, params=params, headers=headers, timeout=15) as resp:
            if resp.status != 200:
                logger.error(f"Birdeye token list error: {resp.status}")
                return []
            
            data = await resp.json()
            tokens = data.get("data", {}).get("items", [])
            
            # Filter for meme coins and high volume
            meme_tokens = []
            for token in tokens:
                symbol = token.get("symbol", "").upper()
                name = token.get("name", "").upper()
                volume_24h = token.get("volume_24h", 0)
                
                # Basic meme coin filters
                meme_keywords = ["MEME", "PEPE", "DOGE", "SHIB", "WIF", "BONK", "FLOKI", "MOON", "CAT", "DOG"]
                is_meme = any(keyword in symbol or keyword in name for keyword in meme_keywords)
                
                if is_meme and volume_24h > 10000:  # High volume meme coins
                    address = token.get("address")
                    if address:
                        meme_tokens.append(address)
                        if len(meme_tokens) >= limit:
                            break
            
            logger.info(f"Found {len(meme_tokens)} trending meme tokens from Birdeye")
            return meme_tokens
            
    except Exception as e:
        logger.error(f"Birdeye trending tokens error: {e}")
        return []


async def get_token_trades_birdeye(session: aiohttp.ClientSession, token_addr: str, limit: int = 100) -> list[dict]:
    """Fetch recent trades for a token using Birdeye API."""
    if not BIRDEYE_API_KEY:
        return []

    try:
        url = "https://public-api.birdeye.so/v1/trades"
        params = {
            "address": token_addr,
            "limit": limit,
            "offset": 0
        }
        headers = {"X-API-Key": BIRDEYE_API_KEY, "x-chain": "solana"}
        
        async with session.get(url, params=params, headers=headers, timeout=15) as resp:
            if resp.status != 200:
                logger.debug(f"Birdeye trades error for {token_addr}: {resp.status}")
                return []
            
            data = await resp.json()
            trades = data.get("data", {}).get("items", [])
            
            # Convert Birdeye trades to our format
            converted_trades = []
            for trade in trades:
                try:
                    converted_trades.append({
                        "wallet": trade.get("wallet"),
                        "token": token_addr,
                        "amount_token": float(trade.get("amount_token", 0)),
                        "amount_usd": float(trade.get("amount_usd", 0)),
                        "price_usd": float(trade.get("price_usd", 0)),
                        "side": trade.get("side"),  # "buy" or "sell"
                        "timestamp": trade.get("timestamp")
                    })
                except (ValueError, TypeError):
                    continue
            
            return converted_trades
            
    except Exception as e:
        logger.debug(f"Birdeye trades fetch error for {token_addr}: {e}")
        return []


def compute_wallet_performance_alt(trades: list[dict]) -> dict:
    """Compute wallet performance statistics from trades (simplified version)."""
    wallet_stats = {}
    
    for trade in trades:
        wallet = trade.get("wallet")
        if not wallet:
            continue
            
        if wallet not in wallet_stats:
            wallet_stats[wallet] = {
                "total_trades": 0,
                "total_invested": 0.0,
                "total_returned": 0.0,
                "wins": 0,
                "losses": 0
            }
        
        stats = wallet_stats[wallet]
        stats["total_trades"] += 1
        
        if trade["side"] == "buy":
            stats["total_invested"] += trade["amount_usd"]
        elif trade["side"] == "sell":
            stats["total_returned"] += trade["amount_usd"]
    
    # Calculate ROI and win rate (simplified)
    for wallet, stats in wallet_stats.items():
        if stats["total_invested"] > 0:
            roi = (stats["total_returned"] - stats["total_invested"]) / stats["total_invested"]
            stats["avg_roi"] = max(roi, -1.0)  # Cap losses at -100%
        else:
            stats["avg_roi"] = 0.0
        
        # Simplified win rate based on ROI
        if stats["avg_roi"] > 0.1:  # 10% profit considered a win
            stats["wins"] = 1
            stats["losses"] = 0
        elif stats["avg_roi"] < -0.1:  # 10% loss considered a loss
            stats["wins"] = 0
            stats["losses"] = 1
        else:
            stats["wins"] = 0
            stats["losses"] = 0
        
        total_outcomes = stats["wins"] + stats["losses"]
        stats["win_rate"] = stats["wins"] / total_outcomes if total_outcomes > 0 else 0.0
    
    return wallet_stats


async def seed_alt():
    """Main seed function using Birdeye API — fetch trades and populate wallet_performance."""
    logger.info("=" * 60)
    logger.info("🌱 Alternative Wallet Performance Seed Script (Birdeye)")
    logger.info("=" * 60)

    # Ensure DB pool
    await get_pool()

    async with aiohttp.ClientSession() as session:
        # 1. Get trending tokens from Birdeye
        logger.info("Fetching trending Solana meme tokens from Birdeye...")
        tokens = await get_trending_tokens_birdeye(session, limit=20)
        logger.info(f"Found {len(tokens)} trending tokens")

        if not tokens:
            logger.error("No tokens found — check BIRDEYE_API_KEY")
            await close_pool()
            return

        # 2. Fetch trade data for each token
        all_trades = []
        for i, token_addr in enumerate(tokens, 1):
            logger.info(f"  [{i}/{len(tokens)}] Fetching trades for {token_addr[:8]}...")
            trades = await get_token_trades_birdeye(session, token_addr, limit=50)
            all_trades.extend(trades)
            logger.debug(f"    → {len(trades)} trades")
            await asyncio.sleep(0.2)  # gentle pacing

        logger.info(f"Total trades collected: {len(all_trades)}")

        if not all_trades:
            logger.warning("No trades found — check Birdeye API key and token addresses")
            await close_pool()
            return

        # 3. Compute wallet performance statistics
        logger.info("Computing wallet performance stats...")
        wallet_stats = compute_wallet_performance_alt(all_trades)
        logger.info(f"Computed stats for {len(wallet_stats)} wallets")

        if not wallet_stats:
            logger.warning("No wallet stats computed")
            await close_pool()
            return

        # 4. Cluster wallets
        logger.info("Clustering wallets...")
        stats_df = pd.DataFrame.from_dict(wallet_stats, orient="index")
        stats_df.index.name = "wallet"
        clustered = cluster_wallets(stats_df)

        # 5. Save to database
        logger.info("Saving to wallet_performance table...")
        saved = 0
        for wallet_addr in clustered.index:
            row = clustered.loc[wallet_addr]
            await upsert_wallet(wallet_addr, {
                "avg_roi": float(row["avg_roi"]),
                "total_trades": int(row["total_trades"]),
                "win_rate": float(row["win_rate"]),
                "cluster_label": row.get("cluster_label", "unknown"),
            })
            saved += 1

        logger.info(f"✅ Saved {saved} wallets to wallet_performance")

        # 6. Summary
        smart = clustered[
            (clustered["avg_roi"] > 1.5)  # Lower threshold for Birdeye data
            & (clustered["total_trades"] >= 5)  # Lower threshold for Birdeye data
            & (clustered["win_rate"] > 0.3)  # Lower threshold for Birdeye data
        ]
        logger.info(f"🧠 Of these, {len(smart)} qualify as 'smart wallets' (Birdeye criteria)")
        logger.info("=" * 60)

    await close_pool()


if __name__ == "__main__":
    asyncio.run(seed_alt())