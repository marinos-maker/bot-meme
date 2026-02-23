#!/usr/bin/env python3
"""
Script per analizzare un token specifico e capire perché non ha generato un alert.
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger

# Aggiungi il percorso del progetto
sys.path.insert(0, str(Path(__file__).parent))

from early_detector.db import get_pool
from early_detector.collector import fetch_token_metrics
from early_detector.signals import passes_trigger, passes_safety_filters
from early_detector.scoring import compute_instability, get_signal_threshold


async def analyze_token(token_address: str):
    """Analizza un token specifico per capire perché non ha generato un alert."""
    
    logger.info(f"🔍 Analizzando token: {token_address}")
    
    pool = await get_pool()
    
    # 1. Recupera i dati del token dal database
    logger.info("📊 Recuperando dati del token dal database...")
    
    token_data = await pool.fetchrow(
        """
        SELECT t.id, t.address, t.name, t.symbol, t.first_seen_at, t.narrative,
               m.price, m.marketcap, m.liquidity, m.holders,
               m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index,
               m.timestamp as last_metric_at, m.insider_psi, m.creator_risk_score
        FROM tokens t
        LEFT JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE t.address = $1
        ORDER BY m.timestamp DESC
        LIMIT 1
        """,
        token_address,
    )
    
    if not token_data:
        logger.error(f"❌ Token {token_address} non trovato nel database")
        return
    
    logger.info(f"✅ Token trovato: {token_data['name']} ({token_data['symbol']})")
    logger.info(f"   Prezzo: {token_data['price']}")
    logger.info(f"   Liquidity: ${token_data['liquidity']:,}")
    logger.info(f"   Market Cap: ${token_data['marketcap']:,}")
    logger.info(f"   Volume 5m: ${token_data['volume_5m']:,}")
    logger.info(f"   Instability Index: {token_data['instability_index']}")
    logger.info(f"   Timestamp: {token_data['last_metric_at']}")
    
    # 2. Calcola la velocity (turnover)
    liq = float(token_data['liquidity'] or 0)
    vol = float(token_data['volume_5m'] or 0)
    velocity = (vol / (liq + 1)) * 100 if liq > 0 else 0
    
    logger.info(f"   Velocity (Turnover): {velocity:.1f}%")
    
    # 3. Recupera tutti i token per calcolare il threshold
    logger.info("📈 Calcolando threshold dinamico...")
    
    all_tokens = await pool.fetch(
        """
        SELECT DISTINCT ON (t.address)
            t.address, t.name, t.symbol,
            m.price, m.marketcap, m.liquidity, 
            m.volume_5m, m.instability_index, m.timestamp
        FROM tokens t
        LEFT JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE m.timestamp > NOW() - INTERVAL '30 minutes'
        ORDER BY t.address, m.timestamp DESC
        """
    )
    
    if not all_tokens:
        logger.warning("⚠️ Nessun token trovato negli ultimi 30 minuti")
        return
    
    # Calcola l'Instability Index per tutti i token
    import math
    valid_tokens = []
    for r in all_tokens:
        liq = float(r["liquidity"] or 0)
        vol = float(r["volume_5m"] or 0)
        velocity = (vol / (liq + 1)) * 100 if liq > 0 else 0
        
        instability = float(r["instability_index"] or 0)
        
        if not math.isfinite(instability): instability = 0
        if not math.isfinite(liq): liq = 0
        if not math.isfinite(vol): vol = 0
        if not math.isfinite(velocity): velocity = 0
        
        valid_tokens.append({
            "address": r["address"],
            "instability": instability,
            "liquidity": liq,
            "volume": vol,
            "velocity": velocity
        })
    
    # Calcola il threshold (P90) manualmente
    import numpy as np
    instability_values = [token["instability"] for token in valid_tokens if token["instability"] > 0]
    
    if instability_values:
        threshold = np.percentile(instability_values, 90)
        logger.info(f"   Threshold (P90): {threshold:.4f}")
    else:
        threshold = 0.0001  # Valore di default se non ci sono valori validi
        logger.info(f"   Threshold (P90): {threshold:.4f} (default)")
    
    # 4. Verifica i criteri di trigger
    logger.info("🔍 Verificando criteri di trigger...")
    
    # Crea un dizionario con i dati del token per la funzione passes_trigger
    token_for_trigger = {
        "instability": float(token_data['instability_index'] or 0),
        "delta_instability": 0.0,  # Non disponibile, mettiamo 0
        "vol_shift": 1.0,  # Non disponibile, mettiamo 1
        "liquidity": float(token_data['liquidity'] or 0),
        "marketcap": float(token_data['marketcap'] or 0),
        "symbol": token_data['symbol'] or "???",
        "address": token_data['address']
    }
    
    # Verifica il trigger
    trigger_passed = passes_trigger(token_for_trigger, threshold)
    logger.info(f"   Trigger passed: {trigger_passed}")
    
    if not trigger_passed:
        logger.warning("❌ Token scartato dal trigger")
        
        # Analizza i singoli criteri
        ii = token_for_trigger["instability"]
        liq = token_for_trigger["liquidity"]
        mcap = token_for_trigger["marketcap"]
        
        logger.info(f"   Instability Index: {ii} (threshold: {threshold})")
        logger.info(f"   Liquidity: ${liq:,} (min: 2500)")
        logger.info(f"   Market Cap: ${mcap:,} (max: 5,000,000)")
        
        if ii < threshold:
            logger.warning(f"   ❌ Instability Index troppo basso ({ii} < {threshold})")
        
        if liq < 2500:
            logger.warning(f"   ❌ Liquidity troppo bassa (${liq:,} < $2,500)")
        
        if mcap > 5000000:
            logger.warning(f"   ❌ Market Cap troppo alto (${mcap:,} > $5,000,000)")
    
    # 5. Verifica i filtri di sicurezza
    logger.info("🛡️ Verificando filtri di sicurezza...")
    
    # Crea un dizionario con i dati del token per la funzione passes_safety_filters
    token_for_safety = {
        "mint_authority": None,  # Non disponibile
        "freeze_authority": None,  # Non disponibile
        "top10_ratio": None,  # Non disponibile
        "insider_psi": float(token_data['insider_psi'] or 0),
        "creator_risk_score": float(token_data['creator_risk_score'] or 0),
        "marketcap": float(token_data['marketcap'] or 0)
    }
    
    safety_passed = passes_safety_filters(token_for_safety)
    logger.info(f"   Safety filters passed: {safety_passed}")
    
    if not safety_passed:
        logger.warning("❌ Token scartato dai filtri di sicurezza")
    
    # 6. Analisi completa
    logger.info("📊 Analisi completa:")
    logger.info(f"   Token: {token_data['name']} ({token_data['symbol']})")
    logger.info(f"   Address: {token_data['address']}")
    logger.info(f"   Instability Index: {token_for_trigger['instability']:.4f}")
    logger.info(f"   Liquidity: ${token_for_trigger['liquidity']:,}")
    logger.info(f"   Market Cap: ${token_for_trigger['marketcap']:,}")
    logger.info(f"   Velocity: {velocity:.1f}%")
    logger.info(f"   Threshold: {threshold:.4f}")
    logger.info(f"   Trigger passed: {trigger_passed}")
    logger.info(f"   Safety passed: {safety_passed}")
    logger.info(f"   Overall alert: {trigger_passed and safety_passed}")
    
    if trigger_passed and safety_passed:
        logger.info("🎉 Questo token avrebbe generato un alert!")
    else:
        logger.info("❌ Questo token non avrebbe generato un alert")


async def main():
    """Funzione principale."""
    if len(sys.argv) != 2:
        print("Uso: python analyze_token.py <indirizzo_token>")
        print("Esempio: python analyze_token.py G47EFdz7yBb7vyi4Ghui3xYE4aMF6mSqabbvwLDnpump")
        sys.exit(1)
    
    token_address = sys.argv[1]
    
    # Setup logging
    logger.add("logs/analyze_token.log", rotation="10 MB", level="INFO",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    
    await analyze_token(token_address)


if __name__ == "__main__":
    asyncio.run(main())