import asyncio
import asyncpg
import os
from dotenv import load_dotenv

async def find_peaceman():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"))
    
    # Cerchiamo PEACEMAN (o simboli simili)
    row = await conn.fetchrow("SELECT * FROM tokens WHERE symbol ILIKE '%PEACEMAN%' OR address = 'So11111111111111111111111111111111111111112' LIMIT 1")
    # Se non lo trovi per simbolo, prova a cercarlo per gli ultimi inseriti
    if not row:
        print("PEACEMAN non trovato per simbolo, cerco ultimi token inseriti...")
        row = await conn.fetchrow("SELECT * FROM tokens ORDER BY created_at DESC LIMIT 1")

    if row:
        print(f"Token: {row['symbol']} ({row['address']})")
        token_id = row['id']
        
        # Vediamo le metriche
        metrics = await conn.fetch("SELECT * FROM token_metrics_timeseries WHERE token_id = $1 ORDER BY timestamp DESC LIMIT 3", token_id)
        for m in metrics:
            print(f"Stats: Time: {m['timestamp']}, Mcap: {m['marketcap']}, Liq: {m['liquidity']}, II: {m['instability_index']}")
            
        # Vediamo se ci sono stati tentativi di segnale (controllando i log o la tabella signals)
        signal = await conn.fetchrow("SELECT * FROM signals WHERE token_id = $1", token_id)
        if signal:
            print(f"Segnale ESISTENTE: Score {signal['degen_score']} at {signal['timestamp']}")
        else:
            print("Nessun segnale trovato in DB.")
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(find_peaceman())
