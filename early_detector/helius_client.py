import aiohttp
import asyncio
import time
from loguru import logger
from early_detector.config import HELIUS_API_KEY, ALCHEMY_RPC_URL, VALIDATION_CLOUD_RPC_URL, EXTRA_RPC_URLS

HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else ""

# List of RPCs for rotating fallback - VALIDATION CLOUD FIRST (most reliable)
extra_list = [u.strip() for u in EXTRA_RPC_URLS.split(",") if u.strip()]
RPC_POOL = [url for url in [VALIDATION_CLOUD_RPC_URL, ALCHEMY_RPC_URL] if url] + extra_list
SOLANA_RPC_URL = RPC_POOL[0] if RPC_POOL else None

# V5.1: Circuit breaker for rate limits - Global state
_RPC_DISABLED_UNTIL: dict[str, float] = {}  # url -> disabled_until timestamp
_RPC_INDEX = 0
_RATE_LIMIT_COOLDOWN = 60.0  # seconds to disable an RPC after rate limit

def _is_rpc_disabled(url: str) -> bool:
    """Check if an RPC is temporarily disabled due to rate limiting."""
    disabled_until = _RPC_DISABLED_UNTIL.get(url, 0.0)
    return time.time() < disabled_until

def _disable_rpc(url: str, duration: float = _RATE_LIMIT_COOLDOWN) -> None:
    """Temporarily disable an RPC due to rate limiting."""
    _RPC_DISABLED_UNTIL[url] = time.time() + duration
    logger.warning(f"🚫 RPC rate limited, disabled for {duration}s: {url[:50]}...")

def _get_next_available_rpc() -> str | None:
    """Get the next available RPC from the pool, skipping disabled ones."""
    global _RPC_INDEX
    if not RPC_POOL:
        return None
    
    # Try to find an available RPC
    for _ in range(len(RPC_POOL)):
        url = RPC_POOL[_RPC_INDEX % len(RPC_POOL)]
        _RPC_INDEX += 1
        if not _is_rpc_disabled(url):
            return url
    
    # All RPCs are disabled - reset and return first one anyway
    logger.warning("⚠️ All RPCs are rate limited, resetting...")
    _RPC_DISABLED_UNTIL.clear()
    return RPC_POOL[0] if RPC_POOL else None


async def get_token_largest_accounts(session: aiohttp.ClientSession, token_mint: str) -> list[dict]:
    """
    Fetch the largest token accounts via Validation Cloud RPC (primary) or Helius fallback.
    NOTE: This only works for established (non-bonding-curve) SPL tokens.
    New Pump.fun tokens (~pump suffix) are NOT yet in SPL format and will fail.
    """
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

    # Try Validation Cloud RPC first (most reliable, no rate limits)
    rpc_url = _get_next_available_rpc()
    if not rpc_url:
        return []

    try:
        async with session.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                error = data.get("error")
                if error:
                    logger.debug(f"RPC getTokenLargestAccounts error for {token_mint[:8]}: {error.get('message')}")
                    return []
                return data.get("result", {}).get("value", [])
            elif resp.status == 429:
                _disable_rpc(rpc_url)
                logger.debug(f"RPC rate limited for {token_mint[:8]}, rotating...")
            else:
                logger.debug(f"RPC getTokenLargestAccounts HTTP {resp.status} for {token_mint[:8]}")
    except Exception as e:
        logger.debug(f"RPC getTokenLargestAccounts request error for {token_mint[:8]}: {e}")

    return []


async def get_asset(session: aiohttp.ClientSession, token_mint: str) -> dict:
    """
    Fetch Digital Asset metadata (creator, supply, etc.) via Helius DAS API.
    NOTE: New Pump.fun tokens may not be indexed yet — returns {} silently.
    V5.1: Skip for pump tokens (too new) to save API credits.
    """
    # Pump tokens are too new to be indexed by DAS - skip entirely
    if token_mint.endswith("pump"):
        return {}
    
    if not HELIUS_API_KEY:
        return {}

    # Check if Helius is rate-limited
    if HELIUS_RPC_URL and _is_rpc_disabled(HELIUS_RPC_URL):
        logger.debug(f"Helius rate limited, skipping getAsset for {token_mint[:8]}")
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
            elif resp.status == 429:
                _disable_rpc(HELIUS_RPC_URL, duration=300.0)  # Disable Helius for 5 min on rate limit
                logger.warning(f"Helius rate limited on getAsset for {token_mint[:8]}")
            else:
                logger.debug(f"Helius getAsset HTTP {resp.status} for {token_mint[:8]}")
    except Exception as e:
        logger.debug(f"Helius getAsset request error for {token_mint[:8]}: {e}")

    return {}


async def get_token_buyers(session: aiohttp.ClientSession, token_mint: str, limit: int = 20) -> list[dict]:
    """
    Fetch the first transactions for a token to identify early buyers.
    This is used for Insider Risk (Coordinated Entry) detection.
    V5.1: Uses Validation Cloud RPC instead of Helius for reliability.
    """
    # Get available RPC from pool
    rpc_url = _get_next_available_rpc()
    if not rpc_url:
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
        async with session.post(rpc_url, json=payload_sigs, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 429:
                _disable_rpc(rpc_url)
                return []
            if resp.status != 200:
                return []
            data = await resp.json()
            sigs = [s["signature"] for s in data.get("result", [])]
            
            if not sigs:
                return []

            # getTransactions to find who bought
            payload_txs = [
                {
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                }
                for i, sig in enumerate(sigs[:10])  # Limit to 10 transactions
            ]
            
            async with session.post(rpc_url, json=payload_txs, timeout=aiohttp.ClientTimeout(total=15)) as resp_tx:
                if resp_tx.status == 429:
                    _disable_rpc(rpc_url)
                    return []
                if resp_tx.status != 200:
                    return []
                tx_data = await resp_tx.json()
                
                # Handle batch response
                transactions = tx_data if isinstance(tx_data, list) else [tx_data]
                
                buyers = []
                for tx_res in transactions:
                    tx = tx_res.get("result") if isinstance(tx_res, dict) else tx_res
                    if not tx: continue
                    
                    try:
                        account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                        if not account_keys: continue
                        
                        # Find the signer/payer (buyer)
                        signer = None
                        for acc in account_keys:
                            if isinstance(acc, dict) and acc.get("signer"):
                                signer = acc.get("pubkey")
                                break
                        
                        if signer:
                            timestamp = tx.get("blockTime")
                            buyers.append({
                                "wallet": signer,
                                "first_trade_time": timestamp,
                                "volume": 0.0
                            })
                    except Exception:
                        continue
                
                return buyers
    except Exception as e:
        logger.debug(f"RPC get_token_buyers error for {token_mint[:8]}: {e}")

    return []


async def get_wallet_performance(session: aiohttp.ClientSession, wallet_addr: str, limit: int = 50) -> dict:
    """
    Fetch recent history via Validation Cloud RPC (primary) with Helius Enhanced API as fallback.
    V5.1: Prioritizes Validation Cloud for reliability.
    """
    # Try Helius Enhanced API only if not rate-limited
    helius_enhanced_url = f"https://api.helius.xyz/v0/addresses/{wallet_addr}/transactions?api-key={HELIUS_API_KEY}" if HELIUS_API_KEY else ""
    
    if helius_enhanced_url and not _is_rpc_disabled(helius_enhanced_url):
        max_retries = 2
        retry_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                async with session.get(helius_enhanced_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list):
                            return _parse_helius_trades(data, wallet_addr)
                    
                    if resp.status == 429:
                        logger.debug(f"Helius 429 for {wallet_addr[:8]} (Attempt {attempt+1}/{max_retries})")
                        if attempt == max_retries - 1:
                            _disable_rpc(helius_enhanced_url, duration=300.0)
                            logger.warning("Helius rate limit reached. Using RPC fallback.")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    
                    break
            except Exception as e:
                logger.debug(f"Helius request error for {wallet_addr[:8]}: {e}")
                break
    
    # --- FALLBACK: MANUAL RPC PARSING (VALIDATION CLOUD / ALCHEMY) ---
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
