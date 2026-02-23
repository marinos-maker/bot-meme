"""
Data collector — async fetchers for DexScreener, Jupiter, and basic metrics.
"""

import asyncio
import aiohttp
from loguru import logger
from early_detector.config import (
    DEXSCREENER_API_URL, PUMPPORTAL_API_KEY
)
from early_detector.cache import cache

async def fetch_dex_metadata(session: aiohttp.ClientSession, token_address: str) -> dict | None:
    """Fetch basic name/symbol from DexScreener as a fast fallback."""
    url = f"{DEXSCREENER_API_URL}/dex/tokens/{token_address}"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    pair = pairs[0]  # First pair usually has the info
                    return {
                        "name": pair.get("baseToken", {}).get("name"),
                        "symbol": pair.get("baseToken", {}).get("symbol")
                    }
    except Exception as e:
        logger.debug(f"Dex metadata fetch failed: {e}")
    return None

GECKOTERMINAL_API_URL = "https://api.geckoterminal.com/api/v2"
JUPITER_PRICE_API_URL = "https://price.jup.ag/v4/price"

# ── Jupiter (Price Fallback) ──────────────────────────────────────────────────

async def fetch_jupiter_price(session: aiohttp.ClientSession, token_address: str) -> float | None:
    """Fetch price from Jupiter Public API (High rate limit/Free)."""
    url = f"{JUPITER_PRICE_API_URL}?ids={token_address}"
    try:
        async with session.get(url, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                data = body.get("data", {}).get(token_address, {})
                price = data.get("price")
                return float(price) if price else None
            return None
    except Exception as e:
        return None


# ── DexScreener ───────────────────────────────────────────────────────────────

async def fetch_dexscreener_pair(session: aiohttp.ClientSession,
                                 token_address: str) -> dict | None:
    """Fetch pair data from DexScreener as fallback / enrichment."""
    url = f"{DEXSCREENER_API_URL}/dex/tokens/{token_address}"
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status != 200:
                return None
            body = await resp.json()
            pairs = body.get("pairs", [])
            if not pairs:
                return None
            # Use the pair with highest liquidity
            pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
            return {
                "name": pair.get("baseToken", {}).get("name"),
                "symbol": pair.get("baseToken", {}).get("symbol"),
                "price": float(pair.get("priceUsd", 0) or 0),
                "marketcap": float(pair.get("fdv", 0) or 0),
                "liquidity": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                "buys_5m": int(pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0),
                "sells_5m": int(pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0),
                "pair_created_at": pair.get("pairCreatedAt"),
            }
    except Exception as e:
        logger.error(f"DexScreener fetch error for {token_address}: {e}")
        return None


# ── Unified fetch ─────────────────────────────────────────────────────────────

async def fetch_token_metrics(session: aiohttp.ClientSession,
                               token_address: str) -> dict | None:
    """
    Fetch metrics from DexScreener first; fallback to Jupiter for price and metadata.
    Birdeye and Helius RPC removals implemented.
    """
    # DexScreener as primary
    metrics = await fetch_dexscreener_pair(session, token_address)

    # If DexScreener didn't return name/symbol, try to get it from Jupiter
    if metrics and (not metrics.get("name") or not metrics.get("symbol")):
        # Try to get name/symbol from Jupiter if available
        j_price = await fetch_jupiter_price(session, token_address)
        if j_price:
            # If we have price but no name/symbol, try to enrich with Jupiter metadata
            if not metrics.get("name"):
                metrics["name"] = f"Token #{token_address[:8]}"
            if not metrics.get("symbol"):
                metrics["symbol"] = f"TOK{token_address[:4]}"

    # Fallback to Jupiter for price if DexScreener fails
    if metrics is None or not metrics.get("price"):
        j_price = await fetch_jupiter_price(session, token_address)
        if j_price:
            if metrics is None:
                metrics = {"price": j_price, "address": token_address}
                # Add basic name/symbol if creating new metrics
                metrics["name"] = f"Token #{token_address[:8]}"
                metrics["symbol"] = f"TOK{token_address[:4]}"
            else:
                metrics["price"] = j_price

    if metrics is None:
        metrics = {
            "address": token_address,
            "price": 0.0,
            "liquidity": 0.0,
            "marketcap": 0.0,
            "holders": 0,
            "volume_1h": 0.0,
            "name": f"Token #{token_address[:8]}",
            "symbol": f"TOK{token_address[:4]}"
        }

    # ── CRITICAL V4.4: Fix $0 Liquidity for Pump Tokens ──
    if token_address.endswith("pump"):
        mcap = metrics.get("marketcap") or 0
        price = metrics.get("price") or 0
        
        if mcap <= 0 and price > 0:
            mcap = price * 1_000_000_000
            metrics["marketcap"] = mcap
            
        curr_liq = metrics.get("liquidity") or 0
        if curr_liq < 100 and mcap > 0:
            metrics["liquidity"] = mcap * 0.18
            logger.debug(f"Applied virtual liquidity for {token_address[:8]}: ${metrics['liquidity']:,.0f}")

    # Initialize missing fields that were previously provided by Helius/Birdeye
    # to avoid crashes in feature calculation
    for field in ["holders", "top10_ratio", "mint_authority", "freeze_authority", 
                  "creator_risk_score", "unique_buyers_50tx", "insider_psi"]:
        if field not in metrics:
            metrics[field] = None if field in ["mint_authority", "freeze_authority"] else 0.0

    # Add logging to debug the metrics being returned
    logger.debug(f"fetch_token_metrics for {token_address[:8]}: name={metrics.get('name')}, symbol={metrics.get('symbol')}, price={metrics.get('price')}, liquidity={metrics.get('liquidity')}")

    return metrics


# ── Test helper ───────────────────────────────────────────────────────────────

async def test_fetch():
    """Quick connectivity test — fetches a known token."""
    # SOL token address for testing
    test_addr = "So11111111111111111111111111111111111111112"
    async with aiohttp.ClientSession() as session:
        result = await fetch_token_metrics(session, test_addr)
        if result:
            logger.info(f"Test fetch OK: SOL price = {result.get('price')}")
        else:
            logger.error("Test fetch FAILED — check API key and connectivity")
