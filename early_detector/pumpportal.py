
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
            async with websockets.connect(uri) as websocket:
                logger.info("🔌 Connected to PumpPortal Websocket")
                
                # 1. Subscribe to new tokens (instant discovery)
                await websocket.send(json.dumps({
                    "method": "subscribeNewToken",
                }))
                
                # 2. Subscribe to migrations (bullish signal for raydium)
                await websocket.send(json.dumps({
                    "method": "subscribeMigration",
                }))

                # 3. Subscribe to ALL trades for real-time wallet tracking (V4.1)
                await websocket.send(json.dumps({
                    "method": "subscribeAllTrades",
                }))

                # 3. Subscribe to smart wallet trades (Copy Trading potential)
                if smart_wallets:
                    logger.info(f"📋 PumpPortal: Subscribing to trades for {len(smart_wallets)} smart wallets")
                    await websocket.send(json.dumps({
                        "method": "subscribeAccountTrade",
                        "keys": smart_wallets
                    }))
                
                # Reset retry delay on successful connection
                retry_delay = 5
                last_subscribed_wallets = list(smart_wallets)
                
                # Local cache of known wallets from DB for fast lookups
                pool = await get_pool()
                rows = await pool.fetch("SELECT wallet FROM wallet_performance")
                known_wallets = set(r["wallet"] for r in rows)
                logger.info(f"Loaded {len(known_wallets)} known wallets for real-time tracking")

                last_known_wallets_refresh = asyncio.get_event_loop().time()
                
                # Use a small timeout for recv/iterator to allow periodic check of wallet list changes
                while True:
                    try:
                        # 1. Periodically refresh known_wallets from DB (every 2 mins)
                        if asyncio.get_event_loop().time() - last_known_wallets_refresh > 120:
                            rows = await pool.fetch("SELECT wallet FROM wallet_performance")
                            known_wallets = set(r["wallet"] for r in rows)
                            last_known_wallets_refresh = asyncio.get_event_loop().time()
                            logger.debug("Refreshed known_wallets cache")

                        # 2. Check if smart wallets list has changed to re-subscribe
                        if list(smart_wallets) != last_subscribed_wallets:
                            logger.info(f"🔄 Smart wallets updated. Re-subscribing PumpPortal...")
                            await websocket.send(json.dumps({
                                "method": "subscribeAccountTrade",
                                "keys": smart_wallets
                            }))
                            last_subscribed_wallets = list(smart_wallets)

                        # Wait for a message with a timeout
                        message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                        data = json.loads(message)
                        
                        tx_type = data.get("txType")
                        if tx_type:
                             # logger.debug(f"PumpPortal MSG: {tx_type}")
                             pass

                        # Handle Trades (All or Smart)
                        if "traderPublicKey" in data and tx_type in ["buy", "sell"]:
                            trader = data["traderPublicKey"]
                            mint = data.get("mint")
                            
                            # Real-time activity update for ANY wallet we see on Pump (discovery)
                            if trader in known_wallets:
                                # logger.debug(f"✨ Real-time activity: Touching known wallet {trader[:8]}...")
                                await touch_wallet(trader)
                            else:
                                # New wallet discovery!
                                # Add to DB with empty stats so the profiler can pick it up later
                                try:
                                    await upsert_wallet(trader, {
                                        "avg_roi": 1.0,
                                        "total_trades": 0,
                                        "win_rate": 0.0,
                                        "cluster_label": "new"
                                    })
                                    known_wallets.add(trader)
                                    # logger.debug(f"🔍 Discovered new wallet: {trader[:8]}")
                                except Exception:
                                    pass
                                
                            # If it's a trade for a token we track, queue it for processing
                            # (Optional: only if volume is interesting)
                            pass

                        # ── Unified Wallet Activity Logic ──
                        trader = data.get("traderPublicKey")
                        if trader:
                            if trader in known_wallets:
                                logger.debug(f"✨ Touching wallet {trader[:8]}...")
                                await touch_wallet(trader)
                            else:
                                try:
                                    logger.debug(f"🔍 Discovering NEW wallet {trader[:8]}...")
                                    await upsert_wallet(trader, {
                                        "avg_roi": 1.0, "total_trades": 0, "win_rate": 0.0, "cluster_label": "new"
                                    })
                                    known_wallets.add(trader)
                                except Exception as e: 
                                    logger.error(f"Failed to upsert wallet: {e}")

                        # Case A: New token creation
                        if data.get("txType") == "create" and "mint" in data:
                            mint = data["mint"]
                            name = data.get("name", "Unknown").replace("\x00", "")
                            symbol = data.get("symbol", "???").replace("\x00", "")
                            logger.info(f"🆕 PumpPortal: New Token {symbol} ({mint[:6]}...)")
                            await upsert_token(mint, name, symbol, narrative="GENERIC")
                            # Removed direct put to allow discovery_worker to batch for cross-sectional scoring
                            # await token_queue.put([{"address": mint, "name": name, "symbol": symbol}])
                        
                        # Case B/C: Buy, Sell, Migration
                        elif data.get("txType") in ["buy", "sell", "migration"] and "mint" in data:
                            mint = data["mint"]
                            tx_type = data.get("txType")
                            if trader and trader in smart_wallets:
                                logger.info(f"🎯 PumpPortal: Smart Wallet {trader[:6]}... {tx_type.upper()} on {mint[:6]}...")
                            # Removed direct put to allow discovery_worker to batch for cross-sectional scoring
                            # await token_queue.put([{"address": mint}])
                            
                    except asyncio.TimeoutError:
                        # Just a heartbeat/check for wallet updates
                        continue
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.error(f"Error handling PumpPortal message: {e}")
                        break # Exit inner loop to reconnect

        except (websockets.ConnectionClosed, websockets.InvalidURI, Exception) as e:
            logger.warning(f"PumpPortal Websocket disconnected: {e}. Retrying in {retry_delay}s...")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
