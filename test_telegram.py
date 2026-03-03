import asyncio
import aiohttp
import os
from dotenv import load_dotenv

async def test_telegram():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    print(f"Testing Telegram with Token: {token[:10]}... and Chat ID: {chat_id}")
    
    if not token or not chat_id:
        print("ERROR: Missing Token or Chat ID in .env")
        return

    text = "🚀 <b>Bot Test</b>\nIl collegamento a Telegram funziona correttamente!"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    print("SUCCESS: Message sent to Telegram!")
                else:
                    print(f"FAILED: Telegram error {resp.status}")
                    print(await resp.text())
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_telegram())
