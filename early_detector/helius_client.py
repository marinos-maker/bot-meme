import aiohttp
import asyncio
from loguru import logger
from early_detector.config import HELIUS_API_KEY, ALCHEMY_RPC_URL, VALIDATION_CLOUD_RPC_URL, EXTRA_RPC_URLS

HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
# List of RPCs for rotating fallback
extra_list = [u.strip() for u in EXTRA_RPC_URLS.split(",") if u.strip()]
RPC_POOL = [url for url in [VALIDATION_CLOUD_RPC_URL, ALCHEMY_RPC_URL, HELIUS_RPC_URL] if url] + extra_list
SOLANA_RPC_URL = RPC_POOL[0] if RPC_POOL else None

# V5.0: Circuit breaker for Helius credits/rate limits
_HELIUS_DISABLED_UNTIL = 0.0
_RPC_INDEX = 0 


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


async def get_wallet_performance(session: aiohttp.ClientSession, wallet_addr: str, limit: int = 50) -> dict:
    """
    Fetch recent history via Helius Enhanced Transaction API 
    (Fallback to manual RPC parsing if Helius is credit-limited).
    """
    global _HELIUS_DISABLED_UNTIL
    now = asyncio.get_event_loop().time()

    if HELIUS_API_KEY and now > _HELIUS_DISABLED_UNTIL:
        url = f"https://api.helius.xyz/v0/addresses/{wallet_addr}/transactions?api-key={HELIUS_API_KEY}"
        
        # V5.0: Retry logic for Helius (Free tier is very sensitive)
        max_retries = 2
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list):
                            return _parse_helius_trades(data, wallet_addr)
                    
                    if resp.status == 429:
                        logger.debug(f"Helius 429 for {wallet_addr[:8]} (Attempt {attempt+1}/{max_retries})")
                        if attempt == max_retries - 1:
                            # Helius is consistently blocking us - disable for 5 minutes
                            _HELIUS_DISABLED_UNTIL = now + 300.0
                            logger.warning("Helius rate limit reached. Disabling Helius for 5 min, using RPC fallback.")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    # If other error (e.g. 500, 401), break to fallback
                    break
            except Exception as e:
                logger.debug(f"Helius request error for {wallet_addr[:8]}: {e}")
                break
            
    # --- FALLBACK: MANUAL RPC PARSING (ALCHEMY/GENERIC) ---
    # This is much more reliable as it uses Standard RPC credits (300M on Alchemy)
    logger.debug(f"Helius failed/limited for {wallet_addr[:8]}. Using RPC fallback...")
    return await get_wallet_performance_rpc(session, wallet_addr, limit=limit)


def _parse_helius_trades(data: list, wallet_addr: str) -> dict:
    """Helper to parse Helius Enhanced API response into ROI stats."""
    from early_detector.config import SOL_MINT
    trades = []
    
    for tx in data:
        try:
            native_transfers = tx.get("nativeTransfers", [])
            token_transfers = tx.get("tokenTransfers", [])
            
            sol_change = 0.0
            other_token_involved = False
            
            # 1. Native SOL transfers
            for nt in native_transfers:
                if nt.get("fromUserAccount") == wallet_addr:
                    sol_change -= float(nt.get("amount", 0)) / 1e9
                if nt.get("toUserAccount") == wallet_addr:
                    sol_change += float(nt.get("amount", 0)) / 1e9
            
            # 2. Token transfers (checking for WSOL as SOL, and others as tokens)
            for tt in token_transfers:
                if tt.get("fromUserAccount") == wallet_addr or tt.get("toUserAccount") == wallet_addr:
                    mint = tt.get("mint")
                    amount = float(tt.get("tokenAmount", 0))
                    
                    if mint == SOL_MINT: # WSOL
                        if tt.get("fromUserAccount") == wallet_addr:
                            sol_change -= amount
                        else:
                            sol_change += amount
                    else:
                        other_token_involved = True
            
            if abs(sol_change) > 0.005 and other_token_involved:
                trades.append(sol_change)
        except Exception:
            continue
            
    return _summarize_trades(trades)


async def get_wallet_performance_rpc(session: aiohttp.ClientSession, wallet_addr: str, limit: int = 20) -> dict:
    """Manual ROI calculation via rotating Solana RPC pool."""
    global _RPC_INDEX
    if not RPC_POOL:
        return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

    # Use the current RPC
    current_rpc = RPC_POOL[_RPC_INDEX % len(RPC_POOL)]
    
    try:
        # 1. Get signatures
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [wallet_addr, {"limit": limit}]
        }
        
        async with session.post(current_rpc, json=payload, timeout=10) as resp:
            if resp.status == 429:
                # Rotate RPC on limit
                _RPC_INDEX += 1
                logger.warning(f"RPC {current_rpc[:30]}... limited. Rotating to next...")
                return await get_wallet_performance_rpc(session, wallet_addr, limit)
                
            res = await resp.json()
            sigs = [s["signature"] for s in res.get("result", []) if s.get("signature")]
            
        if not sigs:
            return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

        trades = []
        # Process transactions in batches of 5 for stability on free tier
        batch_size = 5
        for i in range(0, len(sigs), batch_size):
            batch_sigs = sigs[i:i + batch_size]
            batch_payload = [
                {
                    "jsonrpc": "2.0",
                    "id": j,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                }
                for j, sig in enumerate(batch_sigs)
            ]
            
            # Sub-retry logic for Alchemy 429s
            for r_attempt in range(3):
                try:
                    async with session.post(current_rpc, json=batch_payload, timeout=15) as resp:
                        if resp.status == 429:
                            # Rotate and retry
                            _RPC_INDEX += 1
                            new_rpc = RPC_POOL[_RPC_INDEX % len(RPC_POOL)]
                            logger.debug(f"RPC rotate: {current_rpc[:20]} -> {new_rpc[:20]}")
                            return await get_wallet_performance_rpc(session, wallet_addr, limit)
                            
                        if resp.status != 200:
                            break

                        batch_txs = await resp.json()
                        
                        # Handling both list response (batch) or single object
                        if not isinstance(batch_txs, list):
                            batch_txs = [batch_txs]
                        
                        for tx_res in batch_txs:
                            tx = tx_res.get("result")
                            if not tx: continue

                            meta = tx.get("meta", {})
                            keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                            user_idx = -1
                            for idx, key in enumerate(keys):
                                pk = key.get("pubkey") if isinstance(key, dict) else key
                                if pk == wallet_addr:
                                    user_idx = idx
                                    break
                            
                            if user_idx == -1: continue
                            
                            sol_change = (meta.get("postBalances", [])[user_idx] - meta.get("preBalances", [])[user_idx]) / 1e9
                            token_involved = any(tb.get("owner") == wallet_addr for tb in meta.get("preTokenBalances", [])) or \
                                             any(tb.get("owner") == wallet_addr for tb in meta.get("postTokenBalances", []))
                            
                            if abs(sol_change) > 0.005 and token_involved:
                                trades.append(sol_change)
                        break # Success
                except Exception as e:
                    if "unexpected mimetype" in str(e) or "429" in str(e):
                        await asyncio.sleep(2.0)
                        continue
                    break
            
            await asyncio.sleep(0.1) 

        return _summarize_trades(trades)

    except Exception as e:
        logger.debug(f"RPC performance error for {wallet_addr[:8]}: {e}")
        return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}


def _summarize_trades(trades: list) -> dict:
    """Helper to calculate final ROI/WR from a list of SOL changes."""
    if not trades:
        return {"avg_roi": 1.0, "win_rate": 0.0, "total_trades": 0}

    wins = len([t for t in trades if t > 0])
    total = len(trades)
    net_sol = sum(trades)
    
    neg_flows = [t for t in trades if t < 0]
    total_invested = abs(sum(neg_flows)) if neg_flows else 0.01
    avg_roi = 1.0 + (net_sol / total_invested)
    
    return {
        "avg_roi": round(avg_roi, 2),
        "win_rate": round(wins / total, 3),
        "total_trades": total
    }
