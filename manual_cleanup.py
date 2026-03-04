import asyncio
from early_detector.db import cleanup_old_data, get_pool

async def main():
    print("🚀 Starting manual DB cleanup (Aggressive: 2 days)...")
    deleted = await cleanup_old_data(days=2)
    print(f"✅ Cleanup finished. Removed {deleted} orphaned tokens.")
    
    # Check final counts
    pool = await get_pool()
    token_count = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    wallets_count = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    print(f"📊 Final state: Tokens: {token_count}, Wallets: {wallets_count}")

if __name__ == "__main__":
    asyncio.run(main())
