"""
Trader — Jupiter V6 Swap integration for Solana meme coin trading.

Handles: BUY (SOL → Token), SELL (Token → SOL), balance queries.
"""

import asyncio
import base64
import aiohttp
from loguru import logger

from solders.keypair import Keypair  # type: ignore
from solders.transaction import VersionedTransaction  # type: ignore

from early_detector.config import (
    WALLET_PRIVATE_KEY, HELIUS_RPC_URL, SOL_MINT, SLIPPAGE_BPS, PUMPPORTAL_API_KEY
)
from early_detector.cache import cache

# PumpPortal Lightning API
PUMPPORTAL_TRADE_URL = "https://pumpportal.fun/api/trade"

# Rate limiter
_sem = asyncio.Semaphore(1)  # One trade at a time

# ── Wallet Setup ─────────────────────────────────────────────────────────────

def get_keypair() -> Keypair | None:
    """Load wallet keypair from private key in .env."""
    if not WALLET_PRIVATE_KEY:
        logger.error("WALLET_PRIVATE_KEY not set in .env")
        return None
    try:
        import base58 as b58
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
    """Get SOL balance of the wallet with multi-tier fallback."""
    wallet = get_wallet_address()
    if not wallet:
        return 0.0

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [wallet]
    }
    
    # 1. Try Helius
    try:
        async with session.post(HELIUS_RPC_URL, json=payload, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                if "result" in body:
                    return body["result"]["value"] / 1_000_000_000
    except Exception:
        pass

    # 2. Try Alchemy
    from early_detector.config import ALCHEMY_RPC_URL
    if ALCHEMY_RPC_URL:
        try:
            async with session.post(ALCHEMY_RPC_URL, json=payload, timeout=8) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if "result" in body:
                        return body["result"]["value"] / 1_000_000_000
        except Exception:
            pass

    # 3. Try dRPC
    from early_detector.config import DRPC_RPC_URL
    if DRPC_RPC_URL:
        try:
            headers = {"Content-Type": "application/json"}
            async with session.post(DRPC_RPC_URL, json=payload, timeout=8, headers=headers) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if "result" in body:
                        return body["result"]["value"] / 1_000_000_000
        except Exception:
            pass

    # 3. Final Fallback: Public RPC
    try:
        async with session.post("https://api.mainnet-beta.solana.com", json=payload, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                if "result" in body:
                    return body["result"]["value"] / 1_000_000_000
    except Exception:
        pass

    return 0.0


async def get_token_balance(session: aiohttp.ClientSession, token_address: str) -> float:
    """Get SPL token balance of the wallet with multi-tier fallback."""
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
    
    # 1. Try Helius
    try:
        async with session.post(HELIUS_RPC_URL, json=payload, timeout=8) as resp:
            if resp.status == 200:
                body = await resp.json()
                if "result" in body:
                    accounts = body["result"]["value"]
                    total = 0.0
                    for acc in accounts:
                        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        total += float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                    return total
    except Exception:
        pass

    # 2. Try Alchemy
    from early_detector.config import ALCHEMY_RPC_URL
    if ALCHEMY_RPC_URL:
        try:
            async with session.post(ALCHEMY_RPC_URL, json=payload, timeout=8) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if "result" in body:
                        accounts = body["result"]["value"]
                        total = 0.0
                        for acc in accounts:
                            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                            total += float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
                        return total
        except Exception:
            pass

    return 0.0


# ── Trading ──────────────────────────────────────────────────────────────────

async def execute_buy(session: aiohttp.ClientSession,
                      token_address: str,
                      amount_sol: float,
                      slippage_bps: int = SLIPPAGE_BPS) -> dict:
    """
    Buy a token using PumpPortal Lightning API.
    
    Returns: {"success": bool, "tx_hash": str, "amount_token": float, "price": float, "error": str}
    """
    if not WALLET_PRIVATE_KEY:
        return {"success": False, "error": "Wallet non configurato"}

    async with _sem:
        try:
            # Prepare PumpPortal request
            # slippage_bps 100 = 1%
            slippage_pct = slippage_bps / 100.0
            
            url = f"{PUMPPORTAL_TRADE_URL}?api-key={PUMPPORTAL_API_KEY}"
            payload = {
                "action": "buy",
                "mint": token_address,
                "amount": amount_sol,
                "denominatedInSol": "true",
                "slippage": slippage_pct,
                "priorityFee": 0.0001,
                "pool": "auto",
                "privateKey": WALLET_PRIVATE_KEY
            }

            logger.info(f"🚀 Sending BUY request to PumpPortal for {token_address} ({amount_sol} SOL)...")
            
            async with session.post(url, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"PumpPortal API error {resp.status}: {error_text}")
                    return {"success": False, "error": f"API Error {resp.status}"}
                
                data = await resp.json()
            
            if "signature" in data:
                tx_hash = data["signature"]
                logger.info(f"🟢 BUY sent via PumpPortal! TX: {tx_hash}. Verifying balance...")
                
                # Wait up to 15 seconds for confirmation and balance update
                amount_token = 0
                for i in range(5):
                    await asyncio.sleep(3) # Wait 3 sec
                    amount_token = await get_token_balance(session, token_address)
                    if amount_token > 0:
                        break
                
                # If we still have 0, maybe it failed or is very slow
                price = (amount_sol / amount_token) if amount_token > 0 else 0
                
                return {
                    "success": True if amount_token > 0 else False,
                    "tx_hash": tx_hash,
                    "amount_sol": amount_sol,
                    "amount_token": amount_token,
                    "price": price,
                    "error": "Transazione inviata ma saldo non aggiornato (possibile fallimento)" if amount_token == 0 else ""
                }
            else:
                err = data.get("errors") or data.get("error") or "Unknown PumpPortal error"
                logger.error(f"PumpPortal Trade Failure: {err}")
                return {"success": False, "error": str(err)}

        except Exception as e:
            logger.error(f"Buy execution error: {e}")
            return {"success": False, "error": str(e)}


async def execute_sell(session: aiohttp.ClientSession,
                       token_address: str,
                       amount_token: float | str | None = None,
                       slippage_bps: int = SLIPPAGE_BPS) -> dict:
    """
    Sell a token using PumpPortal Lightning API.
    If amount_token is None, sells 100%.
    
    Returns: {"success": bool, "tx_hash": str, "amount_sol": float, "price": float, "error": str}
    """
    if not WALLET_PRIVATE_KEY:
        return {"success": False, "error": "Wallet non configurato"}

    # Handle "Sell All"
    if amount_token is None:
        amount_to_sell = "100%"
        denominated_in_sol = "false"
    else:
        amount_to_sell = amount_token
        denominated_in_sol = "false"

    async with _sem:
        try:
            slippage_pct = slippage_bps / 100.0
            url = f"{PUMPPORTAL_TRADE_URL}?api-key={PUMPPORTAL_API_KEY}"
            
            payload = {
                "action": "sell",
                "mint": token_address,
                "amount": amount_to_sell,
                "denominatedInSol": denominated_in_sol,
                "slippage": slippage_pct,
                "priorityFee": 0.0001,
                "pool": "auto",
                "privateKey": WALLET_PRIVATE_KEY
            }

            logger.info(f"🚀 Sending SELL request to PumpPortal for {token_address}...")

            async with session.post(url, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"PumpPortal API error {resp.status}: {error_text}")
                    return {"success": False, "error": f"API Error {resp.status}"}
                
                data = await resp.json()

            if "signature" in data:
                tx_hash = data["signature"]
                logger.info(f"🔴 SELL executed via PumpPortal! TX: {tx_hash}")
                return {
                    "success": True,
                    "tx_hash": tx_hash,
                    "amount_sol": 0,
                    "amount_token": 0,
                }
            else:
                err = data.get("errors") or data.get("error") or "Unknown PumpPortal error"
                logger.error(f"PumpPortal Trade Failure: {err}")
                return {"success": False, "error": str(err)}

        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            return {"success": False, "error": str(e)}
