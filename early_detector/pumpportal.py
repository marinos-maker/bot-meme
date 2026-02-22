
import asyncio
import websockets
import json
from loguru import logger
from early_detector.db import upsert_token, touch_wallet, get_pool, upsert_wallet

async def pumpportal_worker(token_queue: asyncio.Queue, smart_wallets: list[str]) -> None:
    """
    Worker that connects to PumpPortal Websocket.
    Discovered tokens and smart wallet trades are immediately sent to the processing queue.
    """
    uri = "wss://pumpportal.fun/api/data"
    logger.info("📡 PumpPortal worker starting...")
    
    retry_delay = 5
    
    while True:
        try:
            # V4.6: Increased stability with keepalive settings
            async with websockets.connect(
                uri, 
                ping_interval=20,      # Ping more frequently (every 20s)
                ping_timeout=20,       # Wait longer for pong (20s)
                close_timeout=5
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
                        # 0. Clear recently_queued every 60s
                        if asyncio.get_event_loop().time() - last_queued_clear > 60:
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
                            
                            logger.info(f"🆕 PumpPortal: New Token {symbol} ({mint[:6]}...)")
                            await upsert_token(mint, name, symbol, narrative="GENERIC")
                        
                        # B. Trade Activity & Wallet Tracking
                        if trader and tx_type in ["buy", "sell", "migration"]:
                            is_trade = tx_type in ["buy", "sell"]
                            
                            # 1. Update wallet activity
                            if trader in known_wallets:
                                if is_trade:
                                    await upsert_wallet(trader, {"avg_roi": 1.0, "total_trades": 1, "win_rate": 0.0, "cluster_label": "retail"})
                                else:
                                    await touch_wallet(trader)
                            else:
                                try:
                                    # Create new entry for previously unknown wallet
                                    await upsert_wallet(trader, {"avg_roi": 1.0, "total_trades": 1 if is_trade else 0, "win_rate": 0.0, "cluster_label": "new"})
                                    known_wallets.add(trader)
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
                    except (websockets.ConnectionClosed, websockets.ConnectionClosedError) as e:
                        logger.warning(f"⚠️ PumpPortal connection lost in recv: {e}")
                        break
                    except json.JSONDecodeError: 
                        continue
                    except Exception as e:
                        logger.error(f"Error handling PumpPortal message: {e}")
                        break 

        except Exception as e:
            logger.warning(f"PumpPortal Websocket disconnected: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
