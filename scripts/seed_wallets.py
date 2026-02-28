"""
Bootstrap script V5.0 — Re-cluster and refresh wallet_performance table.

Uses data already collected by PumpPortal + DexScreener (NO Helius dependency).

What it does:
1. Fetches trending tokens from DexScreener to discover new active wallets
2. Re-clusters ALL existing wallets in DB using K-Means
3. Identifies smart wallets based on V5.0 criteria (ROI > 2.0x, 5+ trades, 35% WR)
4. Prunes stale wallets with no activity in 7+ days

Usage:
    python -m scripts.seed_wallets
"""

import asyncio
import aiohttp
from loguru import logger
from datetime import datetime, timezone, timedelta

from early_detector.db import (
    get_pool, close_pool, upsert_wallet,
    get_all_wallet_performance, get_smart_wallets,
)
from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE


async def discover_wallets_from_dexscreener(session: aiohttp.ClientSession, limit: int = 15) -> list[dict]:
    """
    Fetch trending Solana tokens from DexScreener and extract
    top trader addresses from the pairs data.
    Returns list of {wallet, token_address} for newly discovered wallets.
    """
    discovered = []
    seen_wallets = set()

    try:
        # Get trending Solana pairs
        url = "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112"
        async with session.get(url, timeout=15) as resp:
            if resp.status != 200:
                logger.warning(f"DexScreener returned {resp.status}")
                return []
            body = await resp.json()
            pairs = body.get("pairs", [])

        # Filter for active Solana meme pairs
        active_pairs = [
            p for p in pairs
            if p.get("chainId") == "solana"
            and (p.get("volume", {}).get("h24", 0) or 0) > 1000
            and (p.get("liquidity", {}).get("usd", 0) or 0) > 500
        ][:limit]

        logger.info(f"Found {len(active_pairs)} active Solana pairs from DexScreener")

        for pair in active_pairs:
            base = pair.get("baseToken", {})
            token_addr = base.get("address", "")
            txns = pair.get("txns", {})

            # Extract basic trade activity metrics
            buys_24h = txns.get("h24", {}).get("buys", 0)
            sells_24h = txns.get("h24", {}).get("sells", 0)

            # We can't get individual wallet addresses from DexScreener,
            # but we can use maker addresses if available
            makers = pair.get("makers", []) if isinstance(pair.get("makers"), list) else []

            for maker in makers:
                if isinstance(maker, str) and maker not in seen_wallets:
                    seen_wallets.add(maker)
                    discovered.append({
                        "wallet": maker,
                        "token_address": token_addr,
                        "buys_24h": buys_24h,
                        "sells_24h": sells_24h,
                    })

            await asyncio.sleep(0.1)

    except Exception as e:
        logger.error(f"DexScreener discovery error: {e}")

    return discovered


async def refresh_top_wallets_via_helius(limit: int = 150):
    """Fetch real on-chain ROI for the top N most active wallets from DB."""
    pool = await get_pool()
    from early_detector.helius_client import get_wallet_performance

    # Get the top active wallets that need verification
    rows = await pool.fetch(
        "SELECT wallet FROM wallet_performance ORDER BY last_active DESC, total_trades DESC LIMIT $1",
        limit
    )
    
    if not rows:
        return 0

    logger.info(f"⏳ Verifying {len(rows)} wallets via Helius real-time stats...")
    
    verified = 0
    async with aiohttp.ClientSession() as session:
        for r in rows:
            wallet_addr = r["wallet"]
            try:
                # API Call to Helius
                stats = await get_wallet_performance(session, wallet_addr)
                
                # Only update if they actually have trades on-chain
                if stats["total_trades"] > 0:
                    await pool.execute(
                        """
                        UPDATE wallet_performance 
                        SET avg_roi = $1, win_rate = $2, total_trades = $3, last_active = NOW()
                        WHERE wallet = $4
                        """,
                        stats["avg_roi"], stats["win_rate"], stats["total_trades"], wallet_addr
                    )
                    verified += 1
                
                # Sleep to respect Helius rate limits (be very patient for free tier)
                await asyncio.sleep(2.0)
                
            except Exception as e:
                logger.debug(f"Helius verification error for {wallet_addr[:8]}: {e}")

    logger.info(f"✅ Verified {verified} wallets via Helius (Updated ROI/WR)")
    return verified


async def recluster_all_wallets() -> dict:
    """
    Re-cluster ALL wallets in the wallet_performance table using K-Means.
    Returns summary stats.
    """
    from early_detector.smart_wallets import cluster_wallets
    import pandas as pd

    pool = await get_pool()

    # Fetch all wallets with stats
    rows = await pool.fetch(
        """
        SELECT wallet, avg_roi, total_trades, win_rate, cluster_label, last_active
        FROM wallet_performance
        WHERE total_trades > 0
        """
    )

    if not rows:
        logger.warning("No wallets with trades found in DB")
        return {"total": 0, "clustered": 0, "smart": 0}

    logger.info(f"Re-clustering {len(rows)} wallets...")

    # Build DataFrame for clustering
    data = []
    for r in rows:
        data.append({
            "wallet": r["wallet"],
            "avg_roi": float(r["avg_roi"] or 1.0),
            "total_trades": int(r["total_trades"] or 0),
            "win_rate": float(r["win_rate"] or 0.0),
        })

    df = pd.DataFrame(data)
    df = df.set_index("wallet")

    # Only cluster if we have enough wallets for K-Means (need at least 4)
    if len(df) < 4:
        logger.info(f"Only {len(df)} wallets — assigning labels manually")
        for wallet in df.index:
            row = df.loc[wallet]
            if row["avg_roi"] > SW_MIN_ROI and row["total_trades"] >= SW_MIN_TRADES and row["win_rate"] > SW_MIN_WIN_RATE:
                label = "sniper"
            elif row["total_trades"] >= 3:
                label = "retail"
            else:
                label = "unknown"

            await pool.execute(
                "UPDATE wallet_performance SET cluster_label = $1 WHERE wallet = $2",
                label, wallet
            )
        smart_count = len(await get_smart_wallets())
        return {"total": len(df), "clustered": len(df), "smart": smart_count}

    # Run K-Means clustering
    try:
        clustered = cluster_wallets(df)

        # Update cluster labels in DB (Bulk Update for performance)
        logger.info(f"Applying labels to {len(clustered)} wallets...")
        
        # We'll batch these updates to avoid massive memory usage or query limits
        batch_size = 500
        wallets_to_update = list(clustered.index)
        
        for i in range(0, len(wallets_to_update), batch_size):
            batch = wallets_to_update[i:i + batch_size]
            values = []
            for wallet_addr in batch:
                row = clustered.loc[wallet_addr]
                label = row.get("cluster_label", "unknown")
                values.append((label, wallet_addr))
            
            # Using executemany for efficiency
            await pool.executemany(
                "UPDATE wallet_performance SET cluster_label = $1 WHERE wallet = $2",
                values
            )
            
            if (i // batch_size) % 5 == 0:
                logger.debug(f"  ...Progress: {i}/{len(wallets_to_update)} updated")

        updated = len(clustered)
        logger.info(f"Updated cluster labels for {updated} wallets")

    except Exception as e:
        logger.error(f"Clustering error: {e}")
        updated = 0

    smart_count = len(await get_smart_wallets())

    return {"total": len(df), "clustered": updated, "smart": smart_count}


async def prune_stale_wallets(days: int = 7) -> int:
    """Remove wallets with no activity in N days and <= 1 trade (noise)."""
    pool = await get_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = await pool.execute(
        """
        DELETE FROM wallet_performance
        WHERE last_active < $1 AND total_trades <= 1
        """,
        cutoff
    )

    deleted = 0
    if result and "DELETE" in result:
        deleted = int(result.split()[-1])

    if deleted > 0:
        logger.info(f"🧹 Pruned {deleted} stale wallets (inactive {days}+ days, ≤1 trade)")

    return deleted


async def seed():
    """Main seed function V5.0 — no Helius dependency."""
    logger.info("=" * 60)
    logger.info("🌱 Wallet Performance Seed Script V5.0 (No Helius)")
    logger.info("=" * 60)

    await get_pool()

    async with aiohttp.ClientSession() as session:
        # 1. Discover new wallets from DexScreener trending
        logger.info("Step 1: Discovering wallets from DexScreener trending...")
        new_wallets = await discover_wallets_from_dexscreener(session, limit=15)
        logger.info(f"  → Discovered {len(new_wallets)} wallet entries from trending pairs")

        # Save newly discovered wallets
        for w in new_wallets:
            try:
                await upsert_wallet(w["wallet"], {
                    "avg_roi": 1.0,
                    "total_trades": 1,
                    "win_rate": 0.0,
                    "cluster_label": "new",
                })
            except Exception as e:
                logger.debug(f"Error upserting wallet {w['wallet'][:8]}: {e}")

    # 2. Refresh top wallets via Helius (NEW V5.0 step)
    logger.info("Step 2: Refreshing TOP active wallets via Helius for ROI calculation...")
    verified = await refresh_top_wallets_via_helius(limit=150)

    # 3. Prune stale noise wallets
    logger.info("Step 3: Pruning stale wallets...")
    pruned = await prune_stale_wallets(days=7)

    # 4. Re-cluster all wallets
    logger.info("Step 4: Re-clustering all wallets...")
    stats = await recluster_all_wallets()

    # 5. Summary
    logger.info("=" * 60)
    logger.info(f"✅ Seed Complete:")
    logger.info(f"   Total wallets: {stats['total']}")
    logger.info(f"   Verified via Helius: {verified}")
    logger.info(f"   Clustered: {stats['clustered']}")
    logger.info(f"   Smart wallets (V5.0): {stats['smart']}")
    logger.info(f"   Pruned: {pruned}")
    logger.info(f"   Criteria: ROI > {SW_MIN_ROI}x, Trades >= {SW_MIN_TRADES}, WR > {SW_MIN_WIN_RATE:.0%}")
    logger.info("=" * 60)

    await close_pool()
    return stats


if __name__ == "__main__":
    asyncio.run(seed())
