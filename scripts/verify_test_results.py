import asyncio
from early_detector.db import get_pool

async def check_stats():
    pool = await get_pool()
    r = await pool.fetchrow("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE avg_roi != 1.0) as verified,
            AVG(avg_roi) FILTER (WHERE avg_roi != 1.0) as avg_roi_val,
            COUNT(*) FILTER (WHERE cluster_label = 'high_volume_noise') as noise_bots
        FROM wallet_performance 
        WHERE last_active > NOW() - INTERVAL '1 hour'
    """)
    
    print("\n=== TEST RESULTS (Last 60 min) ===")
    print(f"Wallets Processati: {r['total']}")
    print(f"Wallets Verificati (ROI != 1.0): {r['verified']}")
    print(f"ROI Medio Verificati: {r['avg_roi_val'] if r['avg_roi_val'] else 0:.2f}x")
    print(f"Bot di Rumore Identificati: {r['noise_bots']}")
    print("==================================\n")
    
    # Check 5 most recent
    recent = await pool.fetch("""
        SELECT wallet, avg_roi, total_trades, cluster_label 
        FROM wallet_performance 
        WHERE last_active > NOW() - INTERVAL '1 hour'
        ORDER BY last_active DESC LIMIT 5
    """)
    for row in recent:
        print(f"Wallet: {row['wallet'][:8]}... | ROI: {row['avg_roi']}x | Trades: {row['total_trades']} | Cluster: {row['cluster_label']}")

if __name__ == "__main__":
    asyncio.run(check_stats())
