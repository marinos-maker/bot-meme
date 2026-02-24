import aiohttp
import asyncio
from loguru import logger
from early_detector.config import HELIUS_API_KEY

async def get_token_largest_accounts(session: aiohttp.ClientSession, token_mint: str) -> list[dict]:
    """Fetch the largest token accounts (Holders) via Helius RPC. Helps calculate Top 10 Ratio."""
    if not HELIUS_API_KEY:
        return []
        
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [token_mint]
    }
    
    try:
        async with session.post(url, json=payload, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("result", {}).get("value", [])
            else:
                logger.debug(f"Helius RPC getTokenLargestAccounts failed: {resp.status}")
    except Exception as e:
        logger.debug(f"Helius RPC request error for {token_mint[:8]}: {e}")
        
    return []

async def get_asset(session: aiohttp.ClientSession, token_mint: str) -> dict:
    """Fetch Digital Asset metadata, including the creator, via Helius DAS API."""
    if not HELIUS_API_KEY:
        return {}
        
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAsset",
        "params": {
            "id": token_mint
        }
    }
    
    try:
        async with session.post(url, json=payload, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("result", {})
            else:
                logger.debug(f"Helius DAS getAsset failed: {resp.status}")
    except Exception as e:
        logger.debug(f"Helius DAS request error for {token_mint[:8]}: {e}")
        
    return {}
