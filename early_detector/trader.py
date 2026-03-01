"""
Trader — PumpPortal Lightning Transaction API for Solana meme coin trading.

V6.1: Updated to use PumpPortal Lightning API with API key.
Docs: https://pumpportal.fun/api/trade?api-key=your-api-key-here
"""

import asyncio
import aiohttp
from loguru import logger

from early_detector.config import (
    WALLET_PRIVATE_KEY, ALCHEMY_RPC_URL, SOL_MINT, SLIPPAGE_BPS, PUMPPORTAL_API_KEY
)
from early_detector.cache import cache

# PumpPortal Lightning Transaction API
PUMPPORTAL_TRADE_URL = f"https://pumpportal.fun/api/trade?api-key={PUMPPORTAL_API_KEY}" if PUMPPORTAL_API_KEY else None

# Public fallback
PUBLIC_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Rate limiter
_sem = asyncio.Semaphore(1)  # One trade at a time

def get_rpc_url() -> str:
    """Get the active RPC URL (Alchemy > fallback)."""
    return ALCHEMY_RPC_URL or PUBLIC_SOLANA_RPC

# ── Wallet Setup ─────────────────────────────────────────────────────────────

def get_keypair():
    """Load wallet keypair from private key in .env."""
    if not WALLET_PRIVATE_KEY:
        logger.error("WALLET_PRIVATE_KEY not set in .env")
        return None
    try:
        import base58 as b58
        from solders.keypair import Keypair
        key_bytes = b58.b58decode(WALLET_PRIVATE_KEY)
        return Keypair.from_bytes(key_bytes)
    except Exception as e:
        logger.error(f"Failed to load wallet keypair: {e}")
        return None


def get_wallet_address() -> str | None:
    """Get the public address of the configured wallet."""
    kp = get_keypair()
    return str(kp.pubkey()) if kp else None


# ── Balance Queries ──────────────────────────────────────────────────────────

async def get_sol_balance(session: aiohttp.ClientSession) -> float:
    """Get SOL balance of the wallet with fallback."""
    wallet = get_wallet_address()
    if not wallet:
        return 0.0

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [wallet]
    }
    
    # 1. Try Primary RPC
    try:
        async with session.post(get_rpc_url(), json=payload, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                if "result" in body:
                    return body["result"]["value"] / 1_000_000_000
    except Exception as e:
        logger.debug(f"Primary RPC balance check failed: {e}")

    # 2. Try Public Fallback (if primary was not public)
    if get_rpc_url() != PUBLIC_SOLANA_RPC:
        try:
            async with session.post(PUBLIC_SOLANA_RPC, json=payload, timeout=8) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if "result" in body:
                        return body["result"]["value"] / 1_000_000_000
        except Exception:
            pass

    return 0.0


async def get_token_balance(session: aiohttp.ClientSession, token_address: str) -> float:
    """Get SPL token balance of the wallet."""
    wallet = get_wallet_address()
    if not wallet:
        return 0.0

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet,
            {"mint": token_address},
            {"encoding": "jsonParsed"}
        ]
    }
    
    try:
        async with session.post(get_rpc_url(), json=payload, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                if "result" in body:
                    accounts = body["result"]["value"]
                    total = 0.0
                    for acc in accounts:
                        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        total += float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                    return total
    except Exception as e:
        logger.debug(f"Token balance check failed: {e}")

    return 0.0


# ── Trading ──────────────────────────────────────────────────────────────────

async def execute_buy(session: aiohttp.ClientSession,
                      token_address: str,
                      amount_sol: float,
                      slippage_bps: int = SLIPPAGE_BPS) -> dict:
    """
    Buy a token using PumpPortal Lightning Transaction API.
    V6.1: Uses /trade endpoint with API key for server-side signing.
    
    API Docs:
    - action: "buy" or "sell"
    - mint: contract address
    - amount: SOL or tokens to trade
    - denominatedInSol: "true" if amount is SOL, "false" if tokens
    - slippage: percent allowed
    - priorityFee: for transaction speed
    - pool: "pump", "raydium", "pump-amm", "launchlab", "raydium-cpmm", "bonk", or "auto"
    """
    if not PUMPPORTAL_API_KEY:
        return {"success": False, "error": "PUMPPORTAL_API_KEY non configurata nel .env"}

    if not WALLET_PRIVATE_KEY:
        return {"success": False, "error": "Wallet non configurato"}

    async with _sem:
        try:
            # Pre-trade balance check
            balance = await get_sol_balance(session)
            if balance < amount_sol + 0.005:  # amount + buffer for fees/rent
                msg = f"Saldo SOL insufficiente: hai {balance:.4f} SOL, desideri spendere {amount_sol} SOL"
                logger.warning(f"⚠️ {msg}")
                return {"success": False, "error": msg}

            slippage_pct = slippage_bps / 100.0
            
            # PumpPortal Lightning API request
            # Using form data as per docs
            data = {
                "action": "buy",
                "mint": token_address,
                "amount": str(amount_sol),  # Amount in SOL
                "denominatedInSol": "true",
                "slippage": str(slippage_pct),
                "priorityFee": "0.0001",
                "pool": "auto",  # Automatically select best pool
                "skipPreflight": "false",  # Simulate before sending
            }

            logger.info(f"🚀 BUY request: {amount_sol} SOL → {token_address[:8]}... (slippage={slippage_pct}%)")
            
            async with session.post(PUMPPORTAL_TRADE_URL, data=data, timeout=30) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    error = result.get("error", result.get("errors", f"HTTP {resp.status}"))
                    logger.error(f"PumpPortal BUY error: {error}")
                    return {"success": False, "error": str(error)}
                
                # Check for transaction signature
                tx_hash = result.get("signature") or result.get("txSignature")
                
                if tx_hash:
                    logger.info(f"🟢 BUY executed! TX: {tx_hash}")
                    
                    # Wait for confirmation and get token balance
                    amount_token = 0
                    for i in range(5):
                        await asyncio.sleep(3)
                        amount_token = await get_token_balance(session, token_address)
                        if amount_token > 0:
                            break
                    
                    price = (amount_sol / amount_token) if amount_token > 0 else 0
                    
                    return {
                        "success": True,
                        "tx_hash": tx_hash,
                        "amount_sol": amount_sol,
                        "amount_token": amount_token,
                        "price": price,
                    }
                else:
                    errors = result.get("errors", result)
                    logger.error(f"PumpPortal BUY failed: {errors}")
                    return {"success": False, "error": str(errors)}

        except Exception as e:
            logger.error(f"Buy execution error: {e}")
            return {"success": False, "error": str(e)}


async def execute_sell(session: aiohttp.ClientSession,
                       token_address: str,
                       amount_token: float | str | None = None,
                       slippage_bps: int = SLIPPAGE_BPS) -> dict:
    """
    Sell a token using PumpPortal Lightning Transaction API.
    V6.1: Uses /trade endpoint with API key for server-side signing.
    
    For selling:
    - amount can be a percentage like "100%" to sell all
    - denominatedInSol should be "false" when selling tokens
    """
    if not PUMPPORTAL_API_KEY:
        return {"success": False, "error": "PUMPPORTAL_API_KEY non configurata nel .env"}

    if not WALLET_PRIVATE_KEY:
        return {"success": False, "error": "Wallet non configurato"}

    # Handle "Sell All" with percentage
    if amount_token is None or amount_token == "100%":
        amount_to_sell = "100%"
    else:
        amount_to_sell = str(amount_token)

    async with _sem:
        try:
            slippage_pct = slippage_bps / 100.0
            
            # PumpPortal Lightning API request
            data = {
                "action": "sell",
                "mint": token_address,
                "amount": amount_to_sell,
                "denominatedInSol": "false",  # Selling tokens, not SOL
                "slippage": str(slippage_pct),
                "priorityFee": "0.0001",
                "pool": "auto",
                "skipPreflight": "false",
            }

            logger.info(f"🔴 SELL request: {amount_to_sell} tokens → {token_address[:8]}... (slippage={slippage_pct}%)")
            
            async with session.post(PUMPPORTAL_TRADE_URL, data=data, timeout=30) as resp:
                result = await resp.json()
                
                if resp.status != 200:
                    error = result.get("error", result.get("errors", f"HTTP {resp.status}"))
                    logger.error(f"PumpPortal SELL error: {error}")
                    return {"success": False, "error": str(error)}
                
                # Check for transaction signature
                tx_hash = result.get("signature") or result.get("txSignature")
                
                if tx_hash:
                    logger.info(f"🔴 SELL executed! TX: {tx_hash}")
                    return {
                        "success": True,
                        "tx_hash": tx_hash,
                        "amount_token": amount_to_sell,
                    }
                else:
                    errors = result.get("errors", result)
                    logger.error(f"PumpPortal SELL failed: {errors}")
                    return {"success": False, "error": str(errors)}

        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            return {"success": False, "error": str(e)}