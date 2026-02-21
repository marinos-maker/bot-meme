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
    HELIUS_BASE_URL, HELIUS_RPC_URL, PUMPPORTAL_API_KEY
)
from early_detector.helius_client import (
    check_token_security, fetch_top_holders_rpc, fetch_token_swaps,
    _is_helius_rpc_open, _break_helius_rpc, get_buyers_stats,
    fetch_creator_history, fetch_token_supply_rpc
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

# Rate limiter: max 2 concurrent requests to Birdeye
_semaphore = asyncio.Semaphore(2)
_birdeye_circuit_broken_until = 0

def _is_birdeye_circuit_open():
    import time
    return time.time() < _birdeye_circuit_broken_until

def _break_birdeye_circuit(seconds=60):
    global _birdeye_circuit_broken_until
    import time
    _birdeye_circuit_broken_until = time.time() + seconds
    logger.warning(f"🚫 Birdeye circuit broken for {seconds}s due to credit exhaustion")


# ── Birdeye ───────────────────────────────────────────────────────────────────

async def fetch_token_overview(session: aiohttp.ClientSession,
                               token_address: str) -> dict | None:
    """Fetch token overview from Birdeye with exponential backoff and caching."""
    # 0. Circuit breaker check FIRST
    if _is_birdeye_circuit_open():
        return None

    # 1. Check Cache (5 minute TTL to save compute units)
    cached = cache.get(f"birdeye:{token_address}")
    if cached:
        return cached

    url = f"{BIRDEYE_BASE_URL}/defi/token_overview"
    params = {"address": token_address}
    
    try:
        async with _semaphore:
            async with session.get(url, headers=BIRDEYE_HEADERS,
                                   params=params, timeout=10) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    d = body.get("data", {})
                    if not d:
                        return None
                    
                    result = {
                        "name": d.get("name"),
                        "symbol": d.get("symbol"),
                        "price": d.get("price"),
                        "marketcap": d.get("mc"),
                        "liquidity": d.get("liquidity"),
                        "holders": d.get("holder"),
                        "volume_5m": d.get("v5mUSD"),
                        "volume_1h": d.get("v1hUSD"),
                        "buys_5m": d.get("buy5m"),
                        "sells_5m": d.get("sell5m"),
                        "top10_ratio": None,
                    }
                    cache.set(f"birdeye:{token_address}", result, ttl_seconds=300)
                    return result
                
                if resp.status in [400, 401, 403, 429]:
                    _break_birdeye_circuit(300)  # 5 min silence
                    return None
                
                return None
    except Exception as e:
        logger.error(f"Birdeye fetch error: {e}")
        return None



async def fetch_new_tokens(session: aiohttp.ClientSession,
                           limit: int = 50) -> list[dict]:
    """Fetch recently created tokens using GeckoTerminal as primary and Birdeye as fallback."""
    # 1. Primary: GeckoTerminal (Unbeatable for new pools discovery)
    gecko_tokens = await fetch_new_tokens_gecko(session)
    if gecko_tokens:
        logger.info(f"GeckoTerminal: Discovered {len(gecko_tokens)} new pools")
        return gecko_tokens
    
    # 2. Fallback to Birdeye only if Gecko fails
    logger.info("Falling back to Birdeye for discovery...")
    # ... rest of existing birdeye logic ...
    cached_list = cache.get("birdeye:new_tokens_list")
    if cached_list:
        return cached_list

    # 2. Check circuit breaker for this specific endpoint
    breaker_key = "birdeye:new_tokens_breaker"
    if cache.get(breaker_key):
        # Quietly return empty while circuit is open
        return []

    url = f"{BIRDEYE_BASE_URL}/defi/tokenlist"
    params = {
        "sort_by": "v1hUSD",
        "sort_type": "desc",
        "offset": 0,
        "limit": limit
    }
    
    try:
        async with _semaphore:
            async with session.get(url, headers=BIRDEYE_HEADERS,
                                   params=params, timeout=15) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    tokens = body.get("data", {}).get("tokens", [])
                    result = [
                        {
                            "address": t.get("address"),
                            "name": t.get("name"),
                            "symbol": t.get("symbol"),
                        }
                        for t in tokens
                        if t.get("address")
                    ]
                    # Cache for 30 minutes - Helius is our real-time source now
                    cache.set("birdeye:new_tokens_list", result, ttl_seconds=1800)
                    return result
                
                if resp.status in [400, 401, 403, 429]:
                    logger.warning(f"Birdeye tokenlist limited/rejected ({resp.status}). Silencing discovery for 5m.")
                    # Open breaker for 5 minutes
                    cache.set(breaker_key, True, ttl_seconds=300)
                    return []
                    
                logger.warning(f"Birdeye tokenlist status {resp.status}")
                return []
    except Exception as e:
        logger.error(f"Birdeye tokenlist error: {e}")
        return []


# ── GeckoTerminal (Permissive Discovery) ──────────────────────────────────────

async def fetch_new_tokens_gecko(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch recently created pools from GeckoTerminal (Very permissive)."""
    url = f"{GECKOTERMINAL_API_URL}/networks/solana/new_pools"
    try:
        async with session.get(url, timeout=12) as resp:
            if resp.status == 200:
                body = await resp.json()
                data = body.get("data", [])
                tokens = []
                for pool in data:
                    rels = pool.get("relationships", {})
                    base_token = rels.get("base_token", {}).get("data", {}).get("id", "")
                    if base_token.startswith("solana_"):
                        addr = base_token.replace("solana_", "")
                        attr = pool.get("attributes", {})
                        tokens.append({
                            "address": addr,
                            "name": attr.get("name", "Unknown").split(" / ")[0],
                            "symbol": "", # Geckoterminal pool name usually has it
                        })
                return tokens
            logger.warning(f"GeckoTerminal status {resp.status}")
            return []
    except Exception as e:
        logger.error(f"GeckoTerminal error: {e}")
        return []


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


async def fetch_top_holders(session: aiohttp.ClientSession,
                            token_address: str, top_n: int = 10) -> float | None:
    """Fetch top N holder concentration ratio from Birdeye."""
    if _is_birdeye_circuit_open():
        return None
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
    Fetch metrics from DexScreener first (no strict rate limit);
    fallback to Birdeye on failure. Enriches with top holder ratio.
    """
    # DexScreener as primary (no strict rate limit)
    metrics = await fetch_dexscreener_pair(session, token_address)

    # Fallback to Jupiter for price if DexScreener fails
    if metrics is None or not metrics.get("price"):
        j_price = await fetch_jupiter_price(session, token_address)
        if j_price:
            if metrics is None:
                metrics = {"price": j_price, "address": token_address}
            else:
                metrics["price"] = j_price

    # Fallback to Birdeye for holders or missing liquidity
    if metrics:
        if metrics.get("holders") is None:
            metrics["holders"] = 0
            
    overview = None
    # We always want holders if missing, but we must protect Birdeye credits
    birdeye_token_cooldown = f"birdeye_cooldown:{token_address}"
    
    if not _is_birdeye_circuit_open() and not cache.get(birdeye_token_cooldown):
        # We call Birdeye if:
        # 1. We have no metrics yet
        # 2. Liquidity is missing (often the case for very new tokens on DexScreener)
        # 3. Holders are missing (DexScreener never provides them)
        if metrics is None or not metrics.get("liquidity") or metrics.get("holders") is None:
            logger.debug(f"Fetching enrichment from Birdeye for {token_address}")
            overview = await fetch_token_overview(session, token_address)
            if overview:
                # Cache that we checked Birdeye for this token recently
                cache.set(birdeye_token_cooldown, True, ttl_seconds=600) # 10 min cooldown
                if metrics is None:
                    metrics = overview
                else:
                    # Merge data from Birdeye into existing metrics
                    for k, v in overview.items():
                        if v is not None and (metrics.get(k) is None or metrics.get(k) == 0):
                            metrics[k] = v

    if metrics is None:
        # If we reach here and metrics is None, it means DexScreener AND Jupiter failed.
        # We initialize a minimal dict so RPC enrichements can still happen (V4.2 Robustness)
        metrics = {
            "address": token_address,
            "price": 0.0,
            "liquidity": 0.0,
            "marketcap": 0.0,
            "holders": 0,
            "volume_1h": 0.0
        }

    # Enrich with holders data from overview if available
    if overview:
        if overview.get("holders"):
            metrics["holders"] = overview.get("holders")
        if overview.get("top10_ratio"):
            metrics["top10_ratio"] = overview.get("top10_ratio")
    
    # ── Heavy Enrichments (with Graceful Failure) ──
    try:
        # Still call fetch_top_holders ONLY if ratio is still missing
        if metrics.get("top10_ratio") is None:
            cached_ratio = cache.get(f"holders_ratio:{token_address}")
            if cached_ratio is not None:
                metrics["top10_ratio"] = cached_ratio
            else:
                top10 = await fetch_top_holders(session, token_address)
                if top10 is not None:
                    metrics["top10_ratio"] = top10
                    cache.set(f"holders_ratio:{token_address}", top10, ttl_seconds=600)
                else:
                    # FINAL FALLBACK: Helius RPC (Expensive but reliable)
                    if not _is_helius_rpc_open():
                        top10_rpc = await fetch_top_holders_rpc(session, token_address)
                        if top10_rpc is not None:
                            metrics["top10_ratio"] = top10_rpc
                            cache.set(f"holders_ratio:{token_address}", top10_rpc, ttl_seconds=600)
    except Exception as e:
        logger.debug(f"Holder enrichment failed for {token_address}: {e}")

    try:
        # Enrich with Security Checks via Helius RPC
        if not _is_helius_rpc_open():
            security = await check_token_security(session, token_address)
            metrics["mint_authority"] = security.get("mint_authority")
            metrics["freeze_authority"] = security.get("freeze_authority")
            metrics["helius_name"] = security.get("name")
            metrics["helius_symbol"] = security.get("symbol")
            creator = security.get("creator")
            if creator:
                metrics["creator_address"] = creator
                metrics["creator_risk_score"] = await fetch_creator_history(session, creator)
    except Exception as e:
        logger.debug(f"Security check failed for {token_address}: {e}")

    try:
        # Enrich with Unique Buyers (simulated real-time stealth accumulation)
        if not _is_helius_rpc_open():
            buyers_data = await get_buyers_stats(session, token_address, limit=50)
            metrics["unique_buyers_50tx"] = buyers_data["count"]
            metrics["buyers_data"] = buyers_data["buyers"]  # Pass full list for Insider Scoring
    except Exception as e:
        logger.debug(f"Buyer stats failed for {token_address}: {e}")

    # ── FINAL FALLBACK: Dex metadata if still nameless ──
    if not metrics.get("name") and not metrics.get("helius_name"):
        dex_meta = await fetch_dex_metadata(session, token_address)
        if dex_meta:
            metrics["dex_name"] = dex_meta.get("name")
            metrics["dex_symbol"] = dex_meta.get("symbol")

    # Estimate Marketcap from Supply if missing but price exists
    if metrics.get("price") and (not metrics.get("marketcap") or metrics.get("marketcap") == 0):
        try:
            supply = await fetch_token_supply_rpc(session, token_address)
            if supply:
                metrics["marketcap"] = metrics["price"] * supply
        except:
            pass

    # ── CRITICAL V4.4: Fix $0 Liquidity for Pump Tokens ──
    # DexScreener/Birdeye often report 0 liquidity for extremely new tokens.
    # We estimate it based on bonding curve mechanics (Virtual Liq ≈ 18% of Mccap).
    if (not metrics.get("liquidity") or metrics.get("liquidity") == 0) and token_address.endswith("pump"):
        mcap = metrics.get("marketcap") or 0
        if mcap > 0:
            metrics["liquidity"] = mcap * 0.18
            logger.debug(f"Estimated liquidity for Pump token {token_address[:8]}: ${metrics['liquidity']:.0f}")

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
