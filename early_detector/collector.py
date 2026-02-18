"""
Data collector — async fetchers for Birdeye, DexScreener, and new token discovery.
"""

import asyncio
import aiohttp
from loguru import logger
from early_detector.config import (
    BIRDEYE_BASE_URL,
    BIRDEYE_HEADERS,
    DEXSCREENER_API_URL,
)
from early_detector.helius_client import check_token_security, get_real_unique_buyers

# Rate limiter: max 2 concurrent requests to Birdeye (free tier is limited)
_semaphore = asyncio.Semaphore(2)


# ── Birdeye ───────────────────────────────────────────────────────────────────

async def fetch_token_overview(session: aiohttp.ClientSession,
                               token_address: str) -> dict | None:
    """Fetch token overview from Birdeye (price, mcap, liquidity, holders)."""
    url = f"{BIRDEYE_BASE_URL}/defi/token_overview"
    params = {"address": token_address}
    async with _semaphore:
        try:
            async with session.get(url, headers=BIRDEYE_HEADERS,
                                   params=params, timeout=10) as resp:
                await asyncio.sleep(0.5)  # pace requests for free tier
                if resp.status != 200:
                    logger.warning(f"Birdeye overview {resp.status} for {token_address}")
                    return None
                body = await resp.json()
                d = body.get("data", {})
                return {
                    "price": d.get("price"),
                    "marketcap": d.get("mc"),
                    "liquidity": d.get("liquidity"),
                    "holders": d.get("holder"),
                    "volume_5m": d.get("v5mUSD"),
                    "volume_1h": d.get("v1hUSD"),
                    "buys_5m": d.get("buy5m"),
                    "sells_5m": d.get("sell5m"),
                    "top10_ratio": None,  # enriched separately
                }
        except Exception as e:
            logger.error(f"Birdeye fetch error for {token_address}: {e}")
            return None


async def fetch_new_tokens(session: aiohttp.ClientSession,
                           limit: int = 50) -> list[dict]:
    """Fetch recently created tokens from Birdeye."""
    url = f"{BIRDEYE_BASE_URL}/defi/tokenlist"
    params = {
        "sort_by": "v24hChangePercent",
        "sort_type": "desc",
        "offset": 0,
        "limit": limit,
        "min_liquidity": 100,
    }
    async with _semaphore:
        try:
            async with session.get(url, headers=BIRDEYE_HEADERS,
                                   params=params, timeout=15) as resp:
                await asyncio.sleep(0.5)  # pace requests for free tier
                if resp.status != 200:
                    logger.warning(f"Birdeye tokenlist status {resp.status}")
                    return []
                body = await resp.json()
                tokens = body.get("data", {}).get("tokens", [])
                return [
                    {
                        "address": t.get("address"),
                        "name": t.get("name"),
                        "symbol": t.get("symbol"),
                    }
                    for t in tokens
                    if t.get("address")
                ]
        except Exception as e:
            logger.error(f"Birdeye tokenlist error: {e}")
            return []


async def fetch_top_holders(session: aiohttp.ClientSession,
                            token_address: str, top_n: int = 10) -> float | None:
    """Fetch top N holder concentration ratio from Birdeye."""
    url = f"{BIRDEYE_BASE_URL}/defi/token_holder"
    params = {"address": token_address, "limit": top_n}
    async with _semaphore:
        try:
            async with session.get(url, headers=BIRDEYE_HEADERS,
                                   params=params, timeout=10) as resp:
                await asyncio.sleep(0.5)  # pace requests for free tier
                if resp.status != 200:
                    return None
                body = await resp.json()
                holders = body.get("data", {}).get("items", [])
                total_pct = sum(h.get("percentage", 0) for h in holders[:top_n])
                return total_pct
        except Exception as e:
            logger.error(f"Birdeye holder error for {token_address}: {e}")
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
                "price": float(pair.get("priceUsd", 0) or 0),
                "marketcap": float(pair.get("fdv", 0) or 0),
                "liquidity": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                "volume_5m": float(pair.get("volume", {}).get("m5", 0) or 0),
                "volume_1h": float(pair.get("volume", {}).get("h1", 0) or 0),
                "buys_5m": int(pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0),
                "sells_5m": int(pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0),
            }
    except Exception as e:
        logger.error(f"DexScreener fetch error for {token_address}: {e}")
        return None


# ── Unified fetch ─────────────────────────────────────────────────────────────

async def fetch_token_metrics(session: aiohttp.ClientSession,
                              token_address: str) -> dict | None:
    """
    Fetch metrics from DexScreener first (no strict rate limit);
    fallback to Birdeye on failure. Enriches with top holder ratio.
    """
    # DexScreener as primary (no strict rate limit)
    metrics = await fetch_dexscreener_pair(session, token_address)

    # Fallback to Birdeye if DexScreener fails
    if metrics is None:
        logger.debug(f"Falling back to Birdeye for {token_address}")
        metrics = await fetch_token_overview(session, token_address)

    if metrics is None:
        return None

    # Enrich with top holder ratio (Birdeye only)
    top10 = await fetch_top_holders(session, token_address)
    if top10 is not None:
        metrics["top10_ratio"] = top10

    # Enrich with Security Checks via Helius RPC
    security = await check_token_security(session, token_address)
    metrics["mint_authority"] = security.get("mint_authority")
    metrics["freeze_authority"] = security.get("freeze_authority")

    # Enrich with Unique Buyers (simulated real-time stealth accumulation)
    unique_buyers = await get_real_unique_buyers(session, token_address, limit=50)
    metrics["unique_buyers_50tx"] = unique_buyers

    return metrics


# ── Test helper ───────────────────────────────────────────────────────────────

async def test_fetch():
    """Quick connectivity test — fetches a known token."""
    # SOL token address for testing
    test_addr = "So11111111111111111111111111111111111111112"
    async with aiohttp.ClientSession() as session:
        result = await fetch_token_overview(session, test_addr)
        if result:
            logger.info(f"Test fetch OK: SOL price = {result.get('price')}")
        else:
            logger.error("Test fetch FAILED — check API key and connectivity")
