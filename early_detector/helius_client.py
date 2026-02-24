import aiohttp
from loguru import logger
from early_detector.config import HELIUS_API_KEY

HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"


async def get_token_largest_accounts(session: aiohttp.ClientSession, token_mint: str) -> list[dict]:
    """
    Fetch the largest token accounts via Helius RPC.
    NOTE: This only works for established (non-bonding-curve) SPL tokens.
    New Pump.fun tokens (~pump suffix) are NOT yet in SPL format and will fail.
    """
    if not HELIUS_API_KEY:
        return []

    # Pump.fun bonding-curve tokens are not standard SPL mints until they graduate.
    # Skip the call entirely to save credits — caller should default to 100%.
    if token_mint.endswith("pump"):
        return []

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenLargestAccounts",
        "params": [token_mint]
    }

    try:
        async with session.post(HELIUS_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                error = data.get("error")
                if error:
                    logger.debug(f"Helius getTokenLargestAccounts error for {token_mint[:8]}: {error.get('message')}")
                    return []
                return data.get("result", {}).get("value", [])
            else:
                logger.debug(f"Helius getTokenLargestAccounts HTTP {resp.status} for {token_mint[:8]}")
    except Exception as e:
        logger.debug(f"Helius getTokenLargestAccounts request error for {token_mint[:8]}: {e}")

    return []


async def get_asset(session: aiohttp.ClientSession, token_mint: str) -> dict:
    """
    Fetch Digital Asset metadata (creator, supply, etc.) via Helius DAS API.
    NOTE: New Pump.fun tokens may not be indexed yet — returns {} silently.
    """
    if not HELIUS_API_KEY:
        return {}

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAsset",
        "params": {"id": token_mint}
    }

    try:
        async with session.post(HELIUS_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                error = data.get("error")
                if error:
                    # Silently ignore "Asset Not Found" — token is too new to be indexed
                    if "RecordNotFound" not in str(error):
                        logger.debug(f"Helius getAsset error for {token_mint[:8]}: {error.get('message')}")
                    return {}
                return data.get("result", {})
            else:
                logger.debug(f"Helius getAsset HTTP {resp.status} for {token_mint[:8]}")
    except Exception as e:
        logger.debug(f"Helius getAsset request error for {token_mint[:8]}: {e}")

    return {}
