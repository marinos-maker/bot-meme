"""
Data collector — async fetchers for DexScreener, Jupiter, and basic metrics.
"""

import asyncio
import aiohttp
from loguru import logger
from early_detector.config import (
    DEXSCREENER_API_URL, PUMPPORTAL_API_KEY
)
from early_detector.helius_client import get_token_largest_accounts, get_asset, get_token_buyers
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

# ── Helius RPC (Holders & Metadata) ───────────────────────────────────────────

async def fetch_helius_metrics(session: aiohttp.ClientSession, token_address: str) -> dict:
    """
    Fetch Top10 Holders Ratio and Creator info using Helius RPC.
    
    For Pump.fun bonding-curve tokens (.endswith 'pump'):
    - Top10 is naturally 100% (bonding curve holds all supply) — no API call needed.
    - getAsset is attempted but may return {} if the token is too new to be indexed.
    
    For graduated/established tokens:
    - getTokenLargestAccounts is used to compute real Top10 ratio.
    - getAsset is used for creator information.
    """
    res = {}

    if token_address.endswith("pump"):
        # Bonding curve tokens: the pump bonding curve contract holds ~100% of supply.
        # This is NORMAL and expected — no need to waste a Helius credit querying it.
        res["top10_ratio"] = 100.0
        logger.debug(f"Helius: {token_address[:8]} is a pump BC token → top10_ratio=100% (expected)")
    else:
        # Graduated / established token — query real holder distribution
        try:
            accounts = await get_token_largest_accounts(session, token_address)
            if accounts:
                top_10 = sum(float(acc.get("amount", 0)) for acc in accounts[:10])
                total_supply = sum(float(acc.get("amount", 0)) for acc in accounts)
                if total_supply > 0:
                    res["top10_ratio"] = min((top_10 / total_supply) * 100, 100.0)
                    logger.debug(f"Helius: {token_address[:8]} top10_ratio={res['top10_ratio']:.1f}%")
        except Exception as e:
            logger.debug(f"Helius holders error for {token_address[:8]}: {e}")

    # Always try getAsset for creator info (silently skipped if token not indexed yet)
    try:
        asset = await get_asset(session, token_address)
        if asset:
            creators = asset.get("creators", [])
            if creators:
                res["creator"] = creators[0].get("address")
            else:
                res["creator"] = asset.get("token_info", {}).get("update_authority")
            if res.get("creator"):
                logger.debug(f"Helius: {token_address[:8]} creator={res['creator'][:8]}...")
    except Exception as e:
        logger.debug(f"Helius DAS meta error for {token_address[:8]}: {e}")

    # V4.8: Fetch recent buyers for Insider Risk detection
    try:
        buyers = await get_token_buyers(session, token_address, limit=15)
        if buyers:
            res["buyers_data"] = buyers
            logger.debug(f"Helius: {token_address[:8]} fetched {len(buyers)} early buyers")
    except Exception as e:
        logger.debug(f"Helius buyers fetch error for {token_address[:8]}: {e}")

    return res

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
            
            socials = pair.get("info", {}).get("socials", [])
            has_twitter = any(s.get("type") == "twitter" for s in socials)
            
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
                "has_twitter": has_twitter,
            }
    except Exception as e:
        logger.error(f"DexScreener fetch error for {token_address}: {e}")
        return None


# ── Pump.fun (Authentic Holders/Meta) ──────────────────────────────────────────

async def fetch_pump_fun_metrics(session: aiohttp.ClientSession, token_address: str) -> dict | None:
    """Fetch real coin data from Pump.fun API, including holder count."""
    if not token_address.endswith("pump"):
        return None
        
    url = f"https://frontend-api.pump.fun/coins/{token_address}"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Pump.fun API returns a rich object. We extract what we need.
                return {
                    "holders": int(data.get("holder_count") or 0),
                    "is_complete": data.get("complete", False),
                    "virtual_token_reserves": float(data.get("virtual_token_reserves") or 0),
                    "virtual_sol_reserves": float(data.get("virtual_sol_reserves") or 0),
                    "market_cap": float(data.get("usd_market_cap") or 0),
                    "description": data.get("description", ""),
                    "twitter": data.get("twitter"),
                    "telegram": data.get("telegram"),
                    "website": data.get("website"),
                    "reply_count": data.get("reply_count", 0),
                    "last_reply": data.get("last_reply"),
                }
    except Exception as e:
        logger.debug(f"Pump.fun API error for {token_address[:8]}: {e}")
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
            # V5.0: Conservative virtual liquidity estimate (20% of MCap, capped at $2000)
            # Flagged as synthetic so safety filters know this is NOT real on-chain liquidity
            virtual_liq = min(mcap * 0.20, 2000.0)
            metrics["liquidity"] = virtual_liq
            metrics["liquidity_is_virtual"] = True
            logger.debug(f"Applied VIRTUAL liquidity for {token_address[:8]}: ${virtual_liq:,.0f} (flagged as synthetic)")
        else:
            metrics["liquidity_is_virtual"] = False
            
        # V4.8: Add real-time Pump.fun holder and social enrichment
        pump_meta = await fetch_pump_fun_metrics(session, token_address)
        if pump_meta:
            metrics["holders"] = pump_meta.get("holders", metrics.get("holders", 0))
            if pump_meta.get("is_complete"):
                metrics["bonding_is_complete"] = True
            
            # Use USD Market Cap from Pump.fun if DexScreener is lagging
            if metrics.get("marketcap", 0) < 5000 and pump_meta.get("market_cap", 0) > 0:
                metrics["marketcap"] = pump_meta["market_cap"]

            if pump_meta.get("twitter"):
                metrics["has_twitter"] = True
            logger.debug(f"Pump.fun enrichment for {token_address[:8]}: holders={metrics['holders']}, complete={metrics.get('bonding_is_complete')}")

    # Integrate Helius metrics if available ONLY FOR VIABLE TOKENS
    # (to save the 1,000,000 requests/month limit)
    h_metrics = {}
    if metrics.get("price", 0) > 0 and metrics.get("liquidity", 0) > 200:
        h_metrics = await fetch_helius_metrics(session, token_address)
        if h_metrics:
            if "top10_ratio" in h_metrics:
                metrics["top10_ratio"] = h_metrics["top10_ratio"]
            if "creator" in h_metrics:
                metrics["creator_address"] = h_metrics["creator"]
            if "buyers_data" in h_metrics:
                metrics["buyers_data"] = h_metrics["buyers_data"]

    # Initialize missing fields that were previously provided by Helius/Birdeye
    # to avoid crashes in feature calculation
    for field in ["holders", "top10_ratio", "mint_authority", "freeze_authority", 
                  "creator_risk_score", "unique_buyers_50tx", "insider_psi", "has_twitter"]:
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
