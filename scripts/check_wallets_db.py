
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def check_wallets():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        count = await conn.fetchval('SELECT COUNT(*) FROM wallet_performance')
        print(f"Total wallets in DB: {count}")
        
        if count > 0:
            smart_count = await conn.fetchval('''
                SELECT COUNT(*) FROM wallet_performance
                WHERE avg_roi > 2.5 AND total_trades >= 15 AND win_rate > 0.4
            ''')
            print(f"Smart wallets (P95 criteria): {smart_count}")
            
            # Show a sample
            sample = await conn.fetch('SELECT * FROM wallet_performance ORDER BY avg_roi DESC LIMIT 5')
            for r in sample:
                print(f"Wallet: {r['wallet'][:8]}... | ROI: {r['avg_roi']:.2f} | Trades: {r['total_trades']} | WinRate: {r['win_rate']:.2f}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_wallets())
