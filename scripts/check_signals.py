import asyncio
import asyncpg
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv()

async def main():
    db = await asyncpg.connect(dsn=os.getenv("SUPABASE_DB_URL"))

    print("=== ULTIMI 10 SEGNALI nel DB ===")
    rows = await db.fetch("""
        SELECT s.id, s.timestamp, s.degen_score, s.confidence, s.instability_index,
               t.symbol, t.address
        FROM signals s
        JOIN tokens t ON t.id = s.token_id
        ORDER BY s.timestamp DESC
        LIMIT 10
    """)
    if not rows:
        print("  [NESSUN SEGNALE TROVATO]")
    for r in rows:
        ts = r["timestamp"].strftime("%H:%M:%S") if r["timestamp"] else "?"
        sym = (r["symbol"] or "???")[:10]
        score = r["degen_score"]
        conf = float(r["confidence"] or 0)
        ii = float(r["instability_index"] or 0)
        addr = r["address"][:12]
        print(f"  {ts} | {sym:10} | score={score:3} | conf={conf:.2f} | II={ii:.2f} | {addr}...")

    print()
    print("=== TOTALE SEGNALI nel DB ===")
    total = await db.fetchval("SELECT COUNT(*) FROM signals")
    print(f"  Totale: {total}")

    print()
    print("=== SEGNALI NELLE ULTIME 2 ORE ===")
    recent = await db.fetchval("""
        SELECT COUNT(*) FROM signals
        WHERE timestamp > NOW() - INTERVAL '2 hours'
    """)
    print(f"  Ultimi 2h: {recent}")

    await db.close()

asyncio.run(main())
