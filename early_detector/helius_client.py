"""
Helius API client — fetch parsed swap transactions and token security info from Solana.
"""

import asyncio
import aiohttp
import json
from loguru import logger
from early_detector.config import HELIUS_API_KEY, HELIUS_BASE_URL, HELIUS_RPC_URL
from early_detector.cache import cache

# Rate limiter: max 5 concurrent requests to Helius (RPC + API)
_semaphore = asyncio.Semaphore(5)


async def fetch_token_swaps(session: aiohttp.ClientSession,
                            token_address: str,
                            limit: int = 100) -> list[dict]:
    """
    Fetch recent SWAP transactions involving a token using Helius
    Enhanced Transactions API.

    Returns list of dicts with: wallet, type (buy/sell), amount_usd, timestamp
    """
    # Use the v0 API for parsed transactions
    url = f"{HELIUS_BASE_URL}/v0/addresses/{token_address}/transactions"
    params = {
        "api-key": HELIUS_API_KEY,
        "type": "SWAP",
        "limit": str(min(limit, 100)),
    }

    async with _semaphore:
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"Helius swaps {resp.status} for {token_address}")
                    return []
                txns = await resp.json()
                return _parse_swap_transactions(txns, token_address)
        except Exception as e:
            logger.error(f"Helius fetch error for {token_address}: {e}")
            return []


def _parse_swap_transactions(txns: list, token_address: str) -> list[dict]:
    """
    Parse Helius Enhanced Transaction responses into trade records.
    Identify Unique Buyers and SWR data points.
    """
    trades = []
    if not isinstance(txns, list):
        return []

    for tx in txns:
        if not isinstance(tx, dict):
            continue

        timestamp = tx.get("timestamp", 0)
        fee_payer = tx.get("feePayer", "")
        
        # Enhanced transaction parsing
        description = tx.get("description", "")
        token_transfers = tx.get("tokenTransfers", [])
        
        # Infer trade type from transfers if description is ambiguous
        bought_amount = 0.0
        sold_amount = 0.0
        
        # Check transfers relative to the fee payer (likely the trader)
        for transfer in token_transfers:
            mint = transfer.get("mint")
            amount = float(transfer.get("tokenAmount", 0) or 0)
            
            if mint == token_address:
                if transfer.get("toUserAccount") == fee_payer:
                    bought_amount += amount
                elif transfer.get("fromUserAccount") == fee_payer:
                    sold_amount += amount

        # Determine trade direction
        trade_type = "unknown"
        if bought_amount > 0 and sold_amount == 0:
            trade_type = "buy"
            amount = bought_amount
        elif sold_amount > 0 and bought_amount == 0:
            trade_type = "sell"
            amount = sold_amount
        else:
            continue

        trades.append({
            "wallet": fee_payer,
            "type": trade_type,
            "amount": amount,
            "timestamp": timestamp,
            "token": token_address,
            "tx_signature": tx.get("signature", "")
        })

    return trades


async def check_token_security(session: aiohttp.ClientSession, token_address: str) -> dict:
    """
    Check token security (Mint Authority, Freeze Authority) using Helius RPC `getAsset`.
    Returns a dict with flags.
    """
    # 1. Check Cache
    cached = cache.get(f"security:{token_address}")
    if cached:
        return cached

    payload = {
        "jsonrpc": "2.0",
        "id": "security-check",
        "method": "getAsset",
        "params": {
# ... (rest of function)
            "id": token_address
        }
    }

    async with _semaphore:
        try:
            async with session.post(HELIUS_RPC_URL, json=payload, timeout=5) as resp:
                if resp.status != 200:
                    logger.warning(f"RPC getAsset failed: {resp.status}")
                    return {"mint_authority": None, "freeze_authority": None, "is_safe": False}
                
                body = await resp.json()
                if "error" in body:
                    logger.warning(f"RPC error for {token_address}: {body['error']}")
                    return {"mint_authority": None, "freeze_authority": None, "is_safe": False}
                
                result = body.get("result", {})
                
                # Check authorities
                authorities = result.get("authorities", [])
                mint_auth = None
                freeze_auth = None
                
                # DAS API structure for authorities
                for auth in authorities:
                    scopes = auth.get("scopes", [])
                    if "mint" in scopes:
                        mint_auth = auth.get("address")
                    if "freeze" in scopes:
                        freeze_auth = auth.get("address")

                # Alternative: check ownership/supply details if authorities not explicit in DAS
                # Fallback to standard `getAccountInfo` if DAS `getAsset` is ambiguous (simplified here)
                
                # Creators
                creators = result.get("creators", [])
                creator_addr = creators[0].get("address") if creators else None

                # LP Lock Check (Simplified)
                # specific checks for LP burn require finding the LP mint address first.
                # For now, we rely on Mint + Freeze authority being revoked as a strong signal.
                # In V3, we would analyze the Raydium Pool account owner.
                
                # Logic: Safe if Mint and Freeze are None (revoked)
                authorities_revoked = (mint_auth is None) and (freeze_auth is None)
                
                result_dict = {
                    "mint_authority": mint_auth,
                    "freeze_authority": freeze_auth,
                    "is_safe": authorities_revoked,
                    "creator": creator_addr
                }
                
                # Cache result for 10 minutes
                cache.set(f"security:{token_address}", result_dict, ttl_seconds=600)
                
                return result_dict
                
        except Exception as e:
            logger.error(f"Security check error for {token_address}: {e}")
            return {"mint_authority": "Unknown", "freeze_authority": "Unknown", "is_safe": False}


async def get_buyers_stats(session: aiohttp.ClientSession, token_address: str, limit: int = 100) -> dict:
    """
    Get stats of unique wallets that bought in the last N transactions.
    Returns:
        {
            "count": int,
            "buyers": list[dict]  # [{"wallet": str, "first_trade_time": int}, ...]
        }
    """
    trades = await fetch_token_swaps(session, token_address, limit=limit)
    
    # Filter for buys
    buy_trades = [t for t in trades if t["type"] == "buy"]
    
    # Group by wallet to find first trade time and total volume per wallet
    buyer_map = {}
    for t in buy_trades:
        w = t["wallet"]
        ts = t["timestamp"]
        vol = t.get("amount", 0) # Assumes normalized amount (e.g. in SOL or USD)
        
        if w not in buyer_map:
            buyer_map[w] = {"first_trade": ts, "volume": vol}
        else:
            buyer_map[w]["first_trade"] = min(buyer_map[w]["first_trade"], ts)
            buyer_map[w]["volume"] += vol
            
    buyers_list = [
        {"wallet": w, "first_trade_time": d["first_trade"], "volume": d["volume"]}
        for w, d in buyer_map.items()
    ]
    
    return {
        "count": len(buyer_map),
        "buyers": buyers_list
    }



async def fetch_wallet_history(session: aiohttp.ClientSession,
                               wallet_address: str,
                               limit: int = 50) -> list[dict]:
    """
    Fetch recent SWAP transactions for a specific wallet.
    Returns parsed trade records.
    """
    url = f"{HELIUS_BASE_URL}/v0/addresses/{wallet_address}/transactions"
    params = {
        "api-key": HELIUS_API_KEY,
        "type": "SWAP",
        "limit": str(min(limit, 100)),
    }

    async with _semaphore:
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                await asyncio.sleep(0.3)
                if resp.status != 200:
                    logger.warning(f"Helius wallet history {resp.status} for {wallet_address}")
                    return []
                txns = await resp.json()
                # Reuse the parser
                return _parse_swap_transactions(txns, "ANY") # Token address not strict here
        except Exception as e:
            logger.error(f"Helius wallet history error for {wallet_address}: {e}")
            return []


def compute_wallet_performance(trades: list[dict]) -> dict[str, dict]:
    """
    Compute performance stats for each wallet from trade records.

    Groups trades by wallet, then by token. For each token, matches
    buys and sells to estimate ROI. Returns dict of wallet -> stats.
    """
    from collections import defaultdict

    # Group trades by wallet -> token -> [trades]
    wallet_tokens = defaultdict(lambda: defaultdict(list))
    for t in trades:
        wallet_tokens[t["wallet"]][t["token"]].append(t)

    wallet_stats = {}

    for wallet, tokens in wallet_tokens.items():
        total_trades = 0
        wins = 0
        rois = []

        for token, token_trades in tokens.items():
            buys = [t for t in token_trades if t["type"] == "buy"]
            sells = [t for t in token_trades if t["type"] == "sell"]

            if not buys:
                continue

            total_trades += len(buys)
            avg_buy_amount = sum(t["amount"] for t in buys) / len(buys)

            if sells:
                avg_sell_amount = sum(t["amount"] for t in sells) / len(sells)
                # ROI approximation: sell amount / buy amount
                roi = avg_sell_amount / (avg_buy_amount + 1e-9)
                rois.append(roi)
                if roi > 1.0:
                    wins += len(sells)
            else:
                # Still holding — count as neutral
                rois.append(1.0)

        if total_trades == 0:
            continue

        avg_roi = sum(rois) / len(rois) if rois else 1.0
        win_rate = wins / total_trades if total_trades > 0 else 0.0

        wallet_stats[wallet] = {
            "avg_roi": avg_roi,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "cluster_label": "unknown",  # will be set by clustering
        }

    return wallet_stats


async def test_helius_connection():
    """Quick connectivity test."""
    test_addr = "So11111111111111111111111111111111111111112" # SOL
    async with aiohttp.ClientSession() as session:
        # Test 1: Swaps
        swaps = await fetch_token_swaps(session, test_addr, limit=5)
        logger.info(f"Helius Swaps Test: {len(swaps)} records found")
        
        # Test 2: Security (RPC)
        security = await check_token_security(session, test_addr)
        logger.info(f"Helius Security Test: {security}")


async def fetch_creator_history(session: aiohttp.ClientSession, creator_address: str) -> float:
    """
    Analyze risk of a creator wallet.
    Fetch all tokens created by this address.
    Risk Score = (Rugged Tokens / Total Tokens)
    
    returns: float 0.0 (Safe) to 1.0 (High Risk)
    """
    # 1. Check Cache
    cached = cache.get(f"creator:{creator_address}")
    if cached is not None:
        return cached

    # Helius DAS API: Get assets by creator
    url = HELIUS_RPC_URL
    payload = {
        "jsonrpc": "2.0",
        "id": "creator-check",
        "method": "getAssetsByCreator",
        "params": {
            "creatorAddress": creator_address,
            "onlyVerified": True,
            "page": 1,
            "limit": 50
        }
    }
    
    async with _semaphore:
        try:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    cache.set(f"creator:{creator_address}", 0.5, ttl_seconds=3600) # shorter TTL for errors
                    return 0.5 # Unknown risk
                
                body = await resp.json()
                items = body.get("result", {}).get("items", [])
                
                if not items:
                    cache.set(f"creator:{creator_address}", 0.0, ttl_seconds=86400)
                    return 0.0 # No history = Neutral/Safe-ish (Fresh wallet logic handles the rest)
                
                total = len(items)
                rugged = 0
                
                # Heuristic: Check if previous tokens are "dead"
                # Ideally we'd check their price/volume, but that requires N API calls.
                # Proxy: Check if they have "Mutable" metadata enabled (often used for rugs) OR 
                # if we can get a batch status.
                # For this iteration, we use a simpler heuristic: 
                # If they created MANY tokens (>5) in a short time, it's a serial pump-and-dumper.
                
                # Advanced: We could check if Mint Authority is still enabled for them.
                for item in items:
                    # simplistic "bad actor" check from metadata headers if available
                    # Real "rugged" check needs price history.
                    # For now, we penalize high velocity: serial creators are risky.
                    pass
                
                # Serial Creator Penalty
                # If a wallet has created > 10 tokens, assume farm/spam/scam unless proved otherwise
                risk = 0.1
                if total > 10:
                    risk = 0.8
                elif total > 5:
                    risk = 0.5
                
                cache.set(f"creator:{creator_address}", risk, ttl_seconds=86400)
                return risk

        except Exception as e:
            logger.error(f"Creator check error: {e}")
            return 0.0

