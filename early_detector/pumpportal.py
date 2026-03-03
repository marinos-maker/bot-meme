
import asyncio
import websockets
import json
import aiohttp
from loguru import logger
from early_detector.config import PUMPPORTAL_API_KEY
from early_detector.db import upsert_token, touch_wallet, get_pool, upsert_wallet, upsert_creator_stats


async def fetch_pumpportal_token_data(session: aiohttp.ClientSession, token_address: str) -> dict | None:
    """
    Fetch bonding curve data from Pump.fun API.
    V6.0.1: Use pump.fun backend API with proper headers to avoid 530 errors.
    """
    if not token_address.endswith("pump"):
        return None
        
    try:
        # Try the main pump.fun API endpoint with proper headers
        url = f"https://pump.fun/api/coins/{token_address}"
        headers = {
            "Accept": "application/json",
            "Origin": "https://pump.fun",
            "Referer": "https://pump.fun/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        async with session.get(url, headers=headers, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                # Extract bonding curve specific data
                virtual_sol_reserves = float(data.get("virtual_sol_reserves", 0) or 0)
                virtual_token_reserves = float(data.get("virtual_token_reserves", 0) or 0)
                is_complete = data.get("complete", False)
                
                # Calculate bonding progress
                # V6.1 FIX: Correct bonding curve calculation
                # Pump.fun bonding curve starts at ~30 SOL and graduates at ~85 SOL
                START_SOL = 30.0      # Bonding curve starts at ~30 SOL
                GRADUATION_SOL = 85.0  # Pump.fun graduates at ~85 SOL
                bonding_pct = 0.0
                
                if virtual_sol_reserves > 0:
                    if is_complete and virtual_sol_reserves >= GRADUATION_SOL:
                        bonding_pct = 100.0
                    elif virtual_sol_reserves >= GRADUATION_SOL:
                        bonding_pct = 100.0
                    else:
                        # Correct formula: (current - start) / (end - start)
                        bonding_pct = max(0.0, min(((virtual_sol_reserves - START_SOL) / (GRADUATION_SOL - START_SOL)) * 100, 99.0))
                
                return {
                    "virtual_sol_reserves": virtual_sol_reserves,
                    "virtual_token_reserves": virtual_token_reserves,
                    "bonding_pct": bonding_pct,
                    "bonding_is_complete": is_complete and virtual_sol_reserves >= GRADUATION_SOL,
                    "market_cap": float(data.get("usd_market_cap", 0) or 0),
                    "holders": int(data.get("holder_count", 0) or 0),
                    "price_sol": float(data.get("sol_amount", 0) or 0),
                }
            else:
                logger.debug(f"Pump.fun API returned {resp.status} for {token_address[:8]}")
                return None
                
    except Exception as e:
        logger.debug(f"Pump.fun fetch error for {token_address[:8]}: {e}")
        return None


async def pumpportal_worker(token_queue: asyncio.Queue, smart_wallets: list[str]) -> None:
    """
    Worker that connects to PumpPortal Websocket.
    Discovered tokens and smart wallet trades are immediately sent to the processing queue.
    V6.0: Now uses API key for enhanced data access.
    """
    # Build URI with API key if available
    if PUMPPORTAL_API_KEY:
        uri = f"wss://pumpportal.fun/api/data?api-key={PUMPPORTAL_API_KEY}"
        logger.info("📡 PumpPortal worker starting with API key (enhanced data access)...")
    else:
        uri = "wss://pumpportal.fun/api/data"
        logger.info("📡 PumpPortal worker starting (limited access - no API key)...")
    
    retry_delay = 5
    
    while True:
        try:
            # V4.6: Enhanced stability with optimized keepalive settings
            async with websockets.connect(
                uri, 
                ping_interval=30,      # Ping every 30s (less frequent to reduce load)
                ping_timeout=10,       # Wait 10s for pong (more responsive to timeouts)
                close_timeout=5,
                max_size=2**20,        # 1MB max message size
                max_queue=1000         # Limit message queue size
            ) as websocket:
                logger.info("🔌 Connected to PumpPortal Websocket")
                
                # 1. Subscribe to new tokens (instant discovery)
                await websocket.send(json.dumps({
                    "method": "subscribeNewToken",
                }))
                
                # 2. Subscribe to migrations (bullish signal for raydium)
                await websocket.send(json.dumps({
                    "method": "subscribeMigration",
                }))

                # 3. Subscribe to smart wallet trades (Copy Trading potential)
                if smart_wallets:
                    logger.info(f"📋 PumpPortal: Subscribing to trades for {len(smart_wallets)} smart wallets")
                    await websocket.send(json.dumps({
                        "method": "subscribeAccountTrade",
                        "keys": smart_wallets
                    }))
                
                # 4. Subscribe to trades for recently active tokens (V4.2)
                from early_detector.db import get_tracked_tokens
                tracked_tokens = await get_tracked_tokens(limit=100)
                if tracked_tokens:
                    logger.info(f"📋 PumpPortal: Subscribing to trades for {len(tracked_tokens)} active tokens")
                    await websocket.send(json.dumps({
                        "method": "subscribeTokenTrade",
                        "keys": tracked_tokens
                    }))

                # Reset retry delay on successful connection
                retry_delay = 5
                last_subscribed_wallets = list(smart_wallets)
                last_subscribed_tokens = list(tracked_tokens)
                last_token_refresh = asyncio.get_event_loop().time()
                
                # Local state for real-time tracking
                pool = await get_pool()
                rows = await pool.fetch("SELECT wallet FROM wallet_performance")
                known_wallets = set(r["wallet"] for r in rows)
                last_known_wallets_refresh = asyncio.get_event_loop().time()
                
                recently_queued = set()
                last_queued_clear = asyncio.get_event_loop().time()
                
                logger.info(f"Loaded {len(known_wallets)} known wallets for real-time tracking")

                while True:
                    try:
                        # 0. Clear recently_queued every 10s (Reduced from 60s for V4.7 real-time responsiveness)
                        if asyncio.get_event_loop().time() - last_queued_clear > 10:
                            recently_queued.clear()
                            last_queued_clear = asyncio.get_event_loop().time()

                        # 1. Periodically refresh known_wallets from DB (every 5 mins)
                        if asyncio.get_event_loop().time() - last_known_wallets_refresh > 300:
                            rows = await pool.fetch("SELECT wallet FROM wallet_performance")
                            known_wallets = set(r["wallet"] for r in rows)
                            last_known_wallets_refresh = asyncio.get_event_loop().time()

                        # 2. Check if smart wallets list has changed to re-subscribe
                        if list(smart_wallets) != last_subscribed_wallets:
                            logger.info(f"🔄 Smart wallets updated. Re-subscribing PumpPortal...")
                            await websocket.send(json.dumps({"method": "subscribeAccountTrade", "keys": smart_wallets}))
                            last_subscribed_wallets = list(smart_wallets)

                        # 2b. Periodically refresh tracked tokens (every 5 mins)
                        if asyncio.get_event_loop().time() - last_token_refresh > 300:
                            tracked_tokens = await get_tracked_tokens(limit=100)
                            if list(tracked_tokens) != last_subscribed_tokens:
                                logger.info(f"🔄 Active tokens updated. Subscribing to trades for {len(tracked_tokens)} tokens...")
                                await websocket.send(json.dumps({"method": "subscribeTokenTrade", "keys": tracked_tokens}))
                                last_subscribed_tokens = list(tracked_tokens)
                            last_token_refresh = asyncio.get_event_loop().time()

                        # 3. Handle incoming message
                        # Increased timeout for recv to 10s to reduce unnecessary loop churn
                        message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                        data = json.loads(message)
                        
                        tx_type = data.get("txType")
                        mint = data.get("mint")
                        trader = data.get("traderPublicKey") or data.get("userPublicKey") # Fallback for different msg types

# A. New Token Discovery
                        if tx_type == "create" and mint:
                            # Get name/symbol from PumpPortal with fallback
                            name = data.get("name", "Unknown").replace("\x00", "")
                            symbol = data.get("symbol", "???").replace("\x00", "")
                            
                            # If name/symbol is still default, generate better ones
                            if name == "Unknown" or name == "???":
                                name = f"Token #{mint[:8]}"
                            if symbol == "???" or symbol == "Unknown":
                                symbol = f"TOK{mint[:4]}"
                            
                            # V6.1: Extract bonding curve data from creation event
                            # New tokens start with ~0.25 SOL in the bonding curve
                            initial_sol = float(data.get("sol_amount", 0) or 0)
                            virtual_sol_reserves = float(data.get("virtual_sol_reserves", 0) or 0)
                            
                            logger.info(f"🆕 PumpPortal: New Token {symbol} ({mint[:6]}...) by {trader[:6]}... (initial_sol={initial_sol:.4f})")
                            await upsert_token(mint, name, symbol, narrative="GENERIC", creator_address=trader)
                            
                            # Increment tokens launched by this creator
                            if trader:
                                await upsert_creator_stats(trader, {"total_tokens": 1})
                            
                            # ── SNIPER LOGIC (V6.0) ──
                            from early_detector.config import SNIPER_ENABLED, SNIPER_AMOUNT_SOL, SLIPPAGE_BPS, DEFAULT_TP_PCT, DEFAULT_SL_PCT
                            if SNIPER_ENABLED and trader:
                                from early_detector.db import check_suspicious_wallet, insert_trade
                                from early_detector.trader import execute_buy, get_sol_balance
                                
                                # 1. Check if creator is suspicious
                                risk = await check_suspicious_wallet(trader)
                                if risk["is_suspicious"]:
                                    logger.warning(f"🚫 Sniper: Skipping {symbol} - Creator {trader[:8]}... is SUSPICIOUS: {risk['reason']}")
                                else:
                                    # Use a dedicated session for the snipe to avoid interfering with the main worker
                                    async with aiohttp.ClientSession() as snipe_session:
                                        # 2. Check balance
                                        balance = await get_sol_balance(snipe_session)
                                        if balance >= SNIPER_AMOUNT_SOL:
                                            logger.info(f"🎯 SNIPER: Buying {symbol} ({mint[:8]}) - Creator reputation clean.")
                                            
                                            # Execute immediate buy
                                            result = await execute_buy(snipe_session, mint, SNIPER_AMOUNT_SOL, SLIPPAGE_BPS)
                                            
                                            if result["success"]:
                                                logger.info(f"🚀 SNIPER SUCCESS: Bought {result.get('amount_token', 0):.0f} {symbol} for {SNIPER_AMOUNT_SOL} SOL")
                                                
                                                # Send Telegram Notification for Sniper
                                                from early_detector.signals import send_sniper_alert
                                                asyncio.create_task(send_sniper_alert(
                                                    address=mint,
                                                    symbol=symbol,
                                                    name=name,
                                                    amount_sol=SNIPER_AMOUNT_SOL,
                                                    tx_hash=result.get("tx_hash", ""),
                                                    risk_reason="Creator reputation clean"
                                                ))

                                                await insert_trade(
                                                    token_address=mint,
                                                    side="BUY",
                                                    amount_sol=SNIPER_AMOUNT_SOL,
                                                    amount_token=result.get("amount_token", 0),
                                                    price_entry=result.get("price", 0),
                                                    tp_pct=DEFAULT_TP_PCT,
                                                    sl_pct=DEFAULT_SL_PCT,
                                                    tx_hash=result.get("tx_hash", "")
                                                )
                                            else:
                                                logger.error(f"❌ SNIPER FAILED: {result.get('error')}")
                                        else:
                                            logger.warning(f"⚠️ Sniper: Insufficient balance ({balance:.4f} SOL)")
                        
                        # B. Trade Activity & Wallet Tracking
                        if trader and tx_type in ["buy", "sell", "migration"]:
                            is_trade = tx_type in ["buy", "sell"]
                            
                            # 1. Update wallet activity
                            from early_detector.db import increment_wallet_trades
                            if trader in known_wallets:
                                if is_trade:
                                    await increment_wallet_trades(trader, cluster="retail")
                                else:
                                    await touch_wallet(trader)
                            else:
                                try:
                                    # Create new entry for previously unknown wallet
                                    await increment_wallet_trades(trader, cluster="new")
                                    known_wallets.add(trader)
                                    
                                    # Sniper V6.0: If a smart wallet buys a token early, consider it a 'Smart Snipe'
                                    if is_trade and tx_type == "buy" and trader in smart_wallets:
                                        # This could trigger another type of snipe (Copy-Trading)
                                        # For now, we just log it as a strong signal
                                        logger.info(f"🔥 Smart Wallet {trader[:8]} is SNIPING {mint[:8]}! High conviction.")
                                        
                                except Exception as e:
                                    logger.error(f"Error upserting wallet {trader[:8]}: {e}")

                            # 2. Re-queue token for REAL-TIME metrics if it has volume
                            if mint and mint not in recently_queued:
                                if trader in smart_wallets:
                                    logger.info(f"🎯 Smart Wallet action on {mint[:6]}... Re-queuing for metrics.")
                                
                                # Send to processors for a fresh scan
                                await token_queue.put([{"address": mint}])
                                recently_queued.add(mint)
                                
                    except asyncio.TimeoutError:
                        continue 
                    except websockets.ConnectionClosedError as e:
                        if e.code == 1011:  # Internal Error
                            logger.warning(f"⚠️ PumpPortal connection lost (Internal Error 1011): {e}. This may indicate server overload.")
                        else:
                            logger.warning(f"⚠️ PumpPortal connection lost (Code {e.code}): {e}")
                        break
                    except websockets.ConnectionClosed as e:
                        logger.warning(f"⚠️ PumpPortal connection closed: {e}")
                        break
                    except json.JSONDecodeError: 
                        continue
                    except Exception as e:
                        logger.error(f"Error handling PumpPortal message: {e}")
                        break 

        except Exception as e:
            logger.warning(f"PumpPortal Websocket disconnected: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            # Implement jitter to avoid thundering herd on server restart
            jitter = asyncio.get_event_loop().time() % 5
            retry_delay = min(retry_delay * 1.5, 120) + jitter
