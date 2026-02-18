"""
AI Analyst — Uses Gemini LLM to interpret token signals and metrics.
"""

import json
from datetime import datetime
import google.generativeai as genai
from loguru import logger
from early_detector.config import GOOGLE_API_KEY

# Configure Gemini
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
else:
    logger.warning("GOOGLE_API_KEY not found. AI Analyst will be disabled.")


async def analyze_token_signal(token_data: dict, history: list) -> dict:
    """
    Asks Gemini to analyze a token based on current metrics and history.
    """
    if not GOOGLE_API_KEY:
        return {
            "rating": 0,
            "verdict": "AI Disabled (Missing API Key)",
            "summary": "Please add GOOGLE_API_KEY to your .env file.",
            "risks": []
        }

    try:
        # 1. Prepare data for prompt with defaults for None values
        current = token_data
        symbol = current.get('symbol') or '???'
        address = current.get('address') or 'Unknown'
        price = current.get('price') or 0.0
        mcap = current.get('marketcap') or 0.0
        liq = current.get('liquidity') or 0.0
        holders = current.get('holders') or 0
        vol_5m = current.get('volume_5m') or 0.0
        buys_5m = current.get('buys_5m') or 0
        sells_5m = current.get('sells_5m') or 0
        instability = current.get('instability_index') or 0.0
        
        h_growth = 0
        if len(history) > 1:
            prev_h = history[1].get("holders") or history[0].get("holders") or 0
            curr_h = holders
            if prev_h > 0:
                h_growth = ((curr_h - prev_h) / prev_h) * 100

        # 2. Build Prompt
        prompt = f"""
        Analyze this Solana Meme Coin signal. Be critical, concise, and act as a pro degen trader.
        
        TOKEN DATA:
        - Symbol: {symbol}
        - Address: {address}
        - Price: ${price:.8f}
        - Market Cap: ${mcap:,.0f}
        - Liquidity: ${liq:,.0f}
        - Holders: {holders} (Growth: {h_growth:+.2f}% since last cycle)
        - 5m Volume: ${vol_5m:,.0f}
        - 5m Buys/Sells: {buys_5m}/{sells_5m}
        - Instability Index: {instability:.3f}
        
        LIQUIDITY/MCAP RATIO: {liq / (mcap + 1e-9):.2f}
        
        Based on these metrics, give me a structured verdict. 
        Return ONLY a JSON object with this exact structure (no markdown formatting, no backticks, just raw JSON):
        {{
            "rating": (int 0-10),
            "verdict": (BUY, AVOID, or WAIT),
            "summary": (max 150 characters explanation),
            "risks": [list of 2-3 main risks]
        }}
        """

        # 3. Try 1.5 Flash first, then fallback to Pro
        response = None
        for model_name in ['gemini-1.5-flash', 'gemini-pro']:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response:
                    break
            except Exception as e:
                logger.warning(f"Failed with {model_name}: {e}")
                continue

        if not response:
            raise Exception("All Gemini models failed")
        
        # 4. Parse JSON from response text
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        result = json.loads(text)
        return result

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            return {
                "rating": 0,
                "verdict": "WAIT",
                "summary": "AI Quota Exceeded. Please wait 60 seconds and try again.",
                "risks": ["Rate Limit Reached"]
            }
        
        logger.error(f"AI Analyst error: {e}")
        return {
            "rating": 0,
            "verdict": "ERROR",
            "summary": "Could not generate AI analysis at this time.",
            "risks": ["Internal Error", error_msg[:100]]
        }
