"""
Creator Monitor — Periodic background worker to evaluate creator history (Rug Ratio & Lifespan).
"""

import asyncio
import aiohttp
from loguru import logger
from early_detector.db import get_creators_to_analyze, get_creator_tokens, upsert_creator_stats
from early_detector.collector import fetch_dexscreener_pair

# Esegue l'analisi ogni 6 ore (in secondi)
CHECK_INTERVAL_SECONDS = 21600

async def creator_performance_job(session: aiohttp.ClientSession) -> None:
    """Worker periodico per calcolare rug_ratio e avg_lifespan dei creatori."""
    # Attende un po' di tempo prima del primo avvio per dare priorità ad altri task all'avvio
    await asyncio.sleep(60)
    
    while True:
        try:
            logger.info("🔍 Avvio scansione performance dei creatori (Rug Ratio & Lifespan)...")
            
            creators = await get_creators_to_analyze()
            logger.info(f"Trovati {len(creators)} creatori da analizzare.")
            
            if not creators:
                # Nessun creatore da analizzare, attende il prossimo ciclo
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue
                
            for creator in creators:
                tokens = await get_creator_tokens(creator)
                
                if not tokens:
                    continue
                
                rugged_count = 0
                total_evaluated = 0
                lifespans = []
                
                for tk in tokens:
                    address = tk["address"]
                    hours_since_creation = float(tk.get("hours_since_creation", 0) or 0)
                    
                    # Verifica le metriche attuali su DexScreener
                    metrics = await fetch_dexscreener_pair(session, address)
                    
                    if metrics:
                        liquidity = metrics.get("liquidity") or 0
                        marketcap = metrics.get("marketcap") or 0
                        price = metrics.get("price") or 0
                        
                        # Definiamo "Rug Pull":
                        # 1. Liquidità < $1000
                        # 2. Market Cap crollato < $5000 o prezzo nullo
                        is_rugged = (liquidity < 1000 or marketcap < 5000 or price == 0)
                        
                        if is_rugged:
                            rugged_count += 1
                            # Se è "rugged", ha avuto vita breve (consideriamo 0 per abbassare la media severamente)
                            lifespans.append(0.0)
                        else:
                            # Token ancora vivo (e sano)
                            lifespans.append(hours_since_creation)
                        
                        total_evaluated += 1
                        
                        # Piccola pausa per non intasare l'API di DexScreener o farci bannare
                        await asyncio.sleep(0.5)
                
                # Calcola le metriche finali per questo creatore
                if total_evaluated > 0:
                    rug_ratio = round(rugged_count / total_evaluated, 2)
                    avg_lifespan = 0.0
                    if lifespans:
                        avg_lifespan = round(sum(lifespans) / len(lifespans), 2)
                    
                    # Aggiorna il DB solo sostituendo rug_ratio e avg_lifespan
                    # Passiamo "total_tokens": 0 per non incrementare falsamente il conteggio dei token pre-esistenti
                    await upsert_creator_stats(creator, {
                        "rug_ratio": rug_ratio,
                        "avg_lifespan": avg_lifespan,
                        "total_tokens": 0 
                    })
                    
                    if rug_ratio > 0.6:
                        logger.debug(f"🚨 Sviluppatore {creator[:6]} individuato come alto rischio! Rug: {rug_ratio*100}%, V. media: {avg_lifespan}h")
                    elif rug_ratio == 0.0 and total_evaluated >= 2:
                        logger.info(f"💎 Sviluppatore {creator[:6]} solido! {total_evaluated} token vivi.")
            
            logger.info("✅ Scansione creator conclusa. Pausa fino al prossimo ciclo...")
        
        except Exception as e:
            logger.error(f"Errore nel calcolo del creator performance: {e}")
        
        # Esegue il job ciclicamente
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
