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
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig

from early_detector.config import (
    WALLET_PRIVATE_KEY, ALCHEMY_RPC_URL, SOL_MINT, SLIPPAGE_BPS, PUMPPORTAL_API_KEY
)
from early_detector.cache import cache

# PumpPortal Lightning API (LOCAL version for signing on client)
PUMPPORTAL_TRADE_URL = "https://pumpportal.fun/api/trade-local"

# Public fallback
PUBLIC_SOLANA_RPC = "https://api.mainnet-beta.solana.com"

# Rate limiter
_sem = asyncio.Semaphore(1)  # One trade at a time

def get_rpc_url() -> str:
    """Get the active RPC URL (Alchemy > fallback)."""
    return ALCHEMY_RPC_URL or PUBLIC_SOLANA_RPC

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
    Buy a token using PumpPortal Lightning API (LOCAL signing).
    """
    if not WALLET_PRIVATE_KEY:
        return {"success": False, "error": "Wallet non configurato"}

    async with _sem:
        try:
            # V4.7: Pre-trade balance check
            balance = await get_sol_balance(session)
            if balance < amount_sol + 0.005: # amount + buffer for fees/rent
                msg = f"Saldo SOL insufficiente: hai {balance:.4f} SOL, desideri spendere {amount_sol} SOL. (Buffer richiesto per fees/rent: 0.005 SOL)"
                logger.warning(f"⚠️ {msg}")
                return {"success": False, "error": msg}

            slippage_pct = slippage_bps / 100.0
            
            # Prepare PumpPortal request (trade-local)
            publicKey = get_wallet_address()
            if not publicKey:
                return {"success": False, "error": "Public key non trovata"}

            # Improved pool selection for PumpPortal
            payload = {
                "publicKey": publicKey,
                "action": "buy",
                "mint": token_address,
                "amount": float(amount_sol),
                "denominatedInSol": True,
                "slippage": float(slippage_pct),
                "priorityFee": 0.0001,
                "pool": "auto"
            }

            # 1. Fetch transaction from PumpPortal
            logger.info(f"🚀 Fetching BUY transaction from PumpPortal (auto) for {token_address} (Balance: {balance:.4f} SOL)...")
            logger.info(f"Payload: {payload}")
            
            async with session.post(PUMPPORTAL_TRADE_URL, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"PumpPortal API error {resp.status}: {error_text}")
                    return {"success": False, "error": f"API Error {resp.status}: {error_text}"}
                
                tx_raw = await resp.read()

            # 2. Sign and Send Transaction
            kp = get_keypair()
            if not kp:
                return {"success": False, "error": "Incapace di caricare il keypair"}

            tx_hash = None
            try:
                # Deserialize, sign and prepare payload
                tx = VersionedTransaction(VersionedTransaction.from_bytes(tx_raw).message, [kp])
                
                commitment = CommitmentLevel.Confirmed
                config = RpcSendTransactionConfig(preflight_commitment=commitment)
                send_tx_payload = SendVersionedTransaction(tx, config).to_json()
                
                # Send to RPC
                async with session.post(get_rpc_url(), headers={"Content-Type": "application/json"}, data=send_tx_payload) as rpc_resp:
                    rpc_data = await rpc_resp.json()
                    if rpc_resp.status != 200 or "result" not in rpc_data:
                        err = rpc_data.get("error", "Unknown RPC error")
                        logger.error(f"RPC Transaction Error: {err}")
                        return {"success": False, "error": f"RPC Error: {err}"}
                    
                    tx_hash = rpc_data["result"]
            except Exception as sign_err:
                logger.error(f"Signing/Sending error: {sign_err}")
                return {"success": False, "error": f"Signing error: {sign_err}"}
            
            if tx_hash:
                logger.info(f"🟢 BUY hash received! TX: {tx_hash}. Verifying balance...")
                
                # Wait up to 15 seconds for confirmation and balance update
                amount_token = 0
                for i in range(5):
                    await asyncio.sleep(3) # Wait 3 sec
                    amount_token = await get_token_balance(session, token_address)
                    if amount_token > 0:
                        break
                
                price = (amount_sol / amount_token) if amount_token > 0 else 0
                
                return {
                    "success": True if amount_token > 0 else False,
                    "tx_hash": tx_hash,
                    "amount_sol": amount_sol,
                    "amount_token": amount_token,
                    "price": price,
                    "error": "Transazione inviata ma saldo non aggiornato (possibile fallimento)" if amount_token == 0 else ""
                }
            
            return {"success": False, "error": "Incapace di ottenere tx hash"}

        except Exception as e:
            logger.error(f"Buy execution error: {e}")
            return {"success": False, "error": str(e)}


async def execute_sell(session: aiohttp.ClientSession,
                       token_address: str,
                       amount_token: float | str | None = None,
                       slippage_bps: int = SLIPPAGE_BPS) -> dict:
    """
    Sell a token using PumpPortal Lightning API (LOCAL signing).
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
            publicKey = get_wallet_address()
            if not publicKey:
                return {"success": False, "error": "Public key non trovata"}

            # Improved pool selection for PumpPortal
            payload = {
                "publicKey": publicKey,
                "action": "sell",
                "mint": token_address,
                "amount": amount_to_sell,
                "denominatedInSol": False,
                "slippage": float(slippage_pct),
                "priorityFee": 0.0001,
                "pool": "auto"
            }

            # 1. Fetch transaction from PumpPortal
            logger.info(f"🚀 Fetching SELL transaction from PumpPortal (auto) for {token_address}...")
            logger.info(f"Payload: {payload}")
            
            async with session.post(PUMPPORTAL_TRADE_URL, json=payload, timeout=20) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"PumpPortal API error {resp.status}: {error_text}")
                    return {"success": False, "error": f"API Error {resp.status}: {error_text}"}
                
                tx_raw = await resp.read()

            # 2. Sign and Send Transaction
            kp = get_keypair()
            if not kp:
                return {"success": False, "error": "Incapace di caricare il keypair"}

            tx_hash = None
            try:
                # Deserialize, sign and prepare payload
                tx = VersionedTransaction(VersionedTransaction.from_bytes(tx_raw).message, [kp])
                
                commitment = CommitmentLevel.Confirmed
                config = RpcSendTransactionConfig(preflight_commitment=commitment)
                send_tx_payload = SendVersionedTransaction(tx, config).to_json()
                
                # Send to RPC
                async with session.post(get_rpc_url(), headers={"Content-Type": "application/json"}, data=send_tx_payload) as rpc_resp:
                    rpc_data = await rpc_resp.json()
                    if rpc_resp.status != 200 or "result" not in rpc_data:
                        err = rpc_data.get("error", "Unknown RPC error")
                        logger.error(f"RPC Transaction Error: {err}")
                        return {"success": False, "error": f"RPC Error: {err}"}
                    
                    tx_hash = rpc_data["result"]
            except Exception as sign_err:
                logger.error(f"Signing/Sending error: {sign_err}")
                return {"success": False, "error": f"Signing error: {sign_err}"}

            if tx_hash:
                logger.info(f"🔴 SELL executed via local signing! TX: {tx_hash}")
                return {
                    "success": True,
                    "tx_hash": tx_hash,
                    "amount_sol": 0,
                    "amount_token": 0,
                }
            
            return {"success": False, "error": "Incapace di ottenere tx hash"}

        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            return {"success": False, "error": str(e)}
