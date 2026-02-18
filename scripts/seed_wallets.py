"""
Bootstrap script — populate wallet_performance table with historical data.

Usage:
    python -m scripts.seed_wallets
"""

import asyncio
import aiohttp
import pandas as pd
from loguru import logger

from early_detector.config import DEXSCREENER_API_URL
from early_detector.db import get_pool, close_pool, upsert_wallet, get_pool
from early_detector.helius_client import fetch_token_swaps, compute_wallet_performance
from early_detector.smart_wallets import cluster_wallets


async def get_trending_tokens(session: aiohttp.ClientSession,
                              limit: int = 20) -> list[str]:
    """Fetch trending Solana meme token addresses from DexScreener + DB."""
    seen = set()
    addresses = []

    # Source 1: DexScreener top Solana pairs
    url = "https://api.dexscreener.com/latest/dex/pairs/solana"
    try:
        # Get pairs for well-known meme coins on Solana
        for query_token in [
            "So11111111111111111111111111111111111111112",  # SOL pairs
        ]:
            search_url = f"https://api.dexscreener.com/latest/dex/tokens/{query_token}"
            async with session.get(search_url, timeout=15) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    for p in body.get("pairs", []):
                        if p.get("chainId") != "solana":
                            continue
                        addr = p.get("baseToken", {}).get("address")
                        if addr and addr not in seen and addr != query_token:
                            seen.add(addr)
                            addresses.append(addr)
                        if len(addresses) >= limit:
                            break
            await asyncio.sleep(0.3)
    except Exception as e:
        logger.error(f"DexScreener trending error: {e}")

    # Source 2: tokens already being tracked in our DB
    try:
        from early_detector.db import get_tracked_tokens
        db_tokens = await get_tracked_tokens(limit=limit)
        for addr in db_tokens:
            if addr not in seen:
                seen.add(addr)
                addresses.append(addr)
    except Exception as e:
        logger.debug(f"Could not fetch DB tokens: {e}")

    return addresses[:limit]


async def seed():
    """Main seed function — fetch trades and populate wallet_performance."""
    logger.info("=" * 60)
    logger.info("🌱 Wallet Performance Seed Script")
    logger.info("=" * 60)

    # Ensure DB pool
    await get_pool()

    async with aiohttp.ClientSession() as session:
        # 1. Get trending tokens
        logger.info("Fetching trending Solana meme tokens from DexScreener...")
        tokens = await get_trending_tokens(session, limit=20)
        logger.info(f"Found {len(tokens)} trending tokens")

        if not tokens:
            logger.error("No tokens found — cannot seed wallets")
            await close_pool()
            return

        # 2. Fetch swap transactions for each token
        all_trades = []
        for i, token_addr in enumerate(tokens, 1):
            logger.info(f"  [{i}/{len(tokens)}] Fetching swaps for {token_addr[:8]}...")
            trades = await fetch_token_swaps(session, token_addr, limit=100)
            all_trades.extend(trades)
            logger.debug(f"    → {len(trades)} trades")
            await asyncio.sleep(0.2)  # gentle pacing

        logger.info(f"Total trades collected: {len(all_trades)}")

        if not all_trades:
            logger.warning("No trades found — check Helius API key")
            await close_pool()
            return

        # 3. Compute wallet performance statistics
        logger.info("Computing wallet performance stats...")
        wallet_stats = compute_wallet_performance(all_trades)
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
            (clustered["avg_roi"] > 2.5)
            & (clustered["total_trades"] >= 15)
            & (clustered["win_rate"] > 0.4)
        ]
        logger.info(f"🧠 Of these, {len(smart)} qualify as 'smart wallets'")
        logger.info("=" * 60)

    await close_pool()


if __name__ == "__main__":
    asyncio.run(seed())
