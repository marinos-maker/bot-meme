
import asyncio
from early_detector.db import get_pool, close_pool
from loguru import logger

async def clear_old_signals():
    """Manually clear signals older than 1 hour or ALL signals."""
    pool = await get_pool()
    try:
        # Per pulizia totale (tutti i segnali esistenti):
        res = await pool.execute("DELETE FROM signals")
        logger.info(f"✅ Tabella signals svuotata: {res}")
        
        # Facoltativo: pialliamo anche le metriche vecchie per liberare spazio
        res_m = await pool.execute("DELETE FROM token_metrics_timeseries WHERE timestamp < NOW() - INTERVAL '4 hours'")
        logger.info(f"🧹 Pulite metriche vecchie (>4h): {res_m}")
        
    except Exception as e:
        logger.error(f"❌ Errore durante la pulizia: {e}")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(clear_old_signals())
