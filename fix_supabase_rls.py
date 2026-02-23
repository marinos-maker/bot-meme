import asyncio
from early_detector.db import get_pool, close_pool

async def main():
    pool = await get_pool()
    tables = [
        "creator_performance",
        "market_regime",
        "signals",
        "token_metrics_timeseries",
        "tokens",
        "trades",
        "wallet_performance"
    ]
    
    print("🛡️ Attaching RLS Policies to Supabase tables...")
    for table in tables:
        try:
            # Rimuove le vecchie policy se esistono
            await pool.execute(f'DROP POLICY IF EXISTS "Service Role Full Access" ON {table}')
            
            # Crea una policy che autorizza l'accesso totale al Service Role
            # Questo zittisce l'errore Linter senza esporre i dati al pubblico (anon)
            await pool.execute(f"""
                CREATE POLICY "Service Role Full Access" 
                ON {table} 
                FOR ALL 
                TO service_role 
                USING (true) 
                WITH CHECK (true);
            """)
            print(f"✅ Policy created for: {table}")
        except Exception as e:
            print(f"❌ Error on {table}: {e}")

    await close_pool()

asyncio.run(main())
