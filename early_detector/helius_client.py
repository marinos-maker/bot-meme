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


async def get_token_buyers(session: aiohttp.ClientSession, token_mint: str, limit: int = 20) -> list[dict]:
    """
    Fetch the first transactions for a token to identify early buyers.
    This is used for Insider Risk (Coordinated Entry) detection.
    """
    if not HELIUS_API_KEY:
        return []

    # getSignaturesForAddress to find earliest transactions
    payload_sigs = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [
            token_mint,
            {"limit": limit}
        ]
    }

    try:
        async with session.post(HELIUS_RPC_URL, json=payload_sigs, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            sigs = [s["signature"] for s in data.get("result", [])]
            
            if not sigs:
                return []

            # getTransactions to find who bought
            payload_txs = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransactions",
                "params": [sigs, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            
            async with session.post(HELIUS_RPC_URL, json=payload_txs, timeout=aiohttp.ClientTimeout(total=15)) as resp_tx:
                if resp_tx.status != 200:
                    return []
                tx_data = await resp_tx.json()
                transactions = tx_data.get("result", [])
                
                buyers = []
                for tx in transactions:
                    if not tx: continue
                    
                    # Very basic parse for Pump.fun or Raydium buys
                    # We extract the first account that is not the token mint or program
                    # This is a heuristic for 'trader'
                    try:
                        account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                        if not account_keys: continue
                        
                        # The first account in a standard transaction is usually the signer/payer (buyer)
                        signer = None
                        for acc in account_keys:
                            if acc.get("signer"):
                                signer = acc.get("pubkey")
                                break
                        
                        if signer:
                            timestamp = tx.get("blockTime")
                            buyers.append({
                                "wallet": signer,
                                "first_trade_time": timestamp,
                                "volume": 0.0 # Volume is harder to parse from raw tx without heavy lifting
                            })
                    except Exception:
                        continue
                
                return buyers
    except Exception as e:
        logger.debug(f"Helius get_token_buyers error for {token_mint[:8]}: {e}")

    return []
