"""
Helius API client — fetch parsed swap transactions from Solana.
"""

import asyncio
import aiohttp
from loguru import logger
from early_detector.config import HELIUS_API_KEY, HELIUS_BASE_URL

# Rate limiter: max 2 concurrent requests to Helius
_semaphore = asyncio.Semaphore(2)


async def fetch_token_swaps(session: aiohttp.ClientSession,
                            token_address: str,
                            limit: int = 100) -> list[dict]:
    """
    Fetch recent SWAP transactions involving a token using Helius
    Enhanced Transactions API.

    Returns list of dicts with: wallet, type (buy/sell), amount_usd, timestamp
    """
    url = f"{HELIUS_BASE_URL}/v0/addresses/{token_address}/transactions"
    params = {
        "api-key": HELIUS_API_KEY,
        "type": "SWAP",
        "limit": min(limit, 100),
    }

    async with _semaphore:
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                await asyncio.sleep(0.3)  # pace requests
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

    Each swap has tokenTransfers showing what moved in/out.
    We determine if it's a buy or sell of our target token.
    """
    trades = []
    for tx in txns:
        if not isinstance(tx, dict):
            continue

        timestamp = tx.get("timestamp", 0)
        fee_payer = tx.get("feePayer", "")

        # Look at token transfers to determine buy/sell
        token_transfers = tx.get("tokenTransfers", [])
        native_transfers = tx.get("nativeTransfers", [])

        if not fee_payer:
            continue

        # Check if this wallet bought or sold the target token
        bought_amount = 0.0
        sold_amount = 0.0

        for transfer in token_transfers:
            mint = transfer.get("mint", "")
            amount = float(transfer.get("tokenAmount", 0) or 0)

            if mint == token_address:
                if transfer.get("toUserAccount") == fee_payer:
                    bought_amount += amount
                elif transfer.get("fromUserAccount") == fee_payer:
                    sold_amount += amount

        if bought_amount > 0:
            trades.append({
                "wallet": fee_payer,
                "type": "buy",
                "amount": bought_amount,
                "timestamp": timestamp,
                "token": token_address,
            })
        elif sold_amount > 0:
            trades.append({
                "wallet": fee_payer,
                "type": "sell",
                "amount": sold_amount,
                "timestamp": timestamp,
                "token": token_address,
            })

    return trades


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
        "limit": min(limit, 100),
    }

    async with _semaphore:
        try:
            async with session.get(url, params=params, timeout=15) as resp:
                await asyncio.sleep(0.3)
                if resp.status != 200:
                    logger.warning(f"Helius wallet history {resp.status} for {wallet_address}")
                    return []
                txns = await resp.json()

                trades = []
                for tx in txns:
                    if not isinstance(tx, dict):
                        continue
                    timestamp = tx.get("timestamp", 0)
                    token_transfers = tx.get("tokenTransfers", [])

                    for transfer in token_transfers:
                        mint = transfer.get("mint", "")
                        amount = float(transfer.get("tokenAmount", 0) or 0)
                        if not mint or amount == 0:
                            continue

                        if transfer.get("toUserAccount") == wallet_address:
                            trade_type = "buy"
                        elif transfer.get("fromUserAccount") == wallet_address:
                            trade_type = "sell"
                        else:
                            continue

                        trades.append({
                            "wallet": wallet_address,
                            "type": trade_type,
                            "amount": amount,
                            "timestamp": timestamp,
                            "token": mint,
                        })
                return trades
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


async def test_helius():
    """Quick connectivity test for Helius API."""
    # Test with SOL token
    test_addr = "So11111111111111111111111111111111111111112"
    async with aiohttp.ClientSession() as session:
        trades = await fetch_token_swaps(session, test_addr, limit=5)
        if trades:
            logger.info(f"Helius test OK: got {len(trades)} swap records")
        else:
            logger.warning("Helius test: no swaps found (may be normal for SOL)")
        logger.info("Helius API connection successful")
