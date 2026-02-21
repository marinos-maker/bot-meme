"""
AI Analyst — Uses Gemini LLM to interpret token signals and metrics.
"""

import json
from datetime import datetime
from loguru import logger
from early_detector.config import GOOGLE_API_KEY

# Try using the new google-genai library if available, otherwise fallback (though this file is updated to use new syntax)
try:
    from google import genai
    from google.genai import types
    HAS_NEW_GENAI = True
except ImportError:
    HAS_NEW_GENAI = False
    import google.generativeai as genai_old

# Configure Gemini for old library (deprecated)
if not HAS_NEW_GENAI and GOOGLE_API_KEY:
    try:
        genai_old.configure(api_key=GOOGLE_API_KEY)
    except Exception as e:
        logger.warning(f"Failed to configure old genai: {e}")

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
        insider_psi = current.get('insider_psi') or 0.0
        creator_risk = current.get('creator_risk_score') or 0.0
        narrative = current.get('narrative') or 'Unknown'
        mint_auth = current.get('mint_authority')
        freeze_auth = current.get('freeze_authority')
        top10 = current.get('top10_ratio') or 0.0
        
        h_growth = 0
        if len(history) > 1:
            prev_h = history[1].get("holders") or history[0].get("holders") or 0
            curr_h = holders
            if prev_h > 0:
                h_growth = ((curr_h - prev_h) / prev_h) * 100

        # 2. Build Prompt
        prompt = f"""
        Analyze this Solana Meme Coin signal. Be critical, concise, and act like a professional degen trader.
        RESPONSE MUST BE IN ENGLISH.
        
        TOKEN DATA:
        - Symbol: {symbol}
        - Address: {address}
        - Price: ${price:.12f}
        - Market Cap: ${mcap:,.0f}
        - Liquidity: ${liq:,.0f}
        - Holders: {holders} (Growth: {h_growth:+.2f}% since last cycle)
        - Top 10 Holders Ratio: {top10:.1f}%
        - 5m Volume: ${vol_5m:,.0f}
        - 5m Buys/Sells: {buys_5m}/{sells_5m}
        - Instability Index: {instability:.3f}
        - Insider Risk (PSI): {insider_psi:.2f}
        - Creator Risk: {creator_risk:.2f}
        - Mint Authority: {"ENABLED (RUG RISK!)" if mint_auth else "Revoked (Safe)"}
        - Freeze Authority: {"ENABLED (SCAM RISK!)" if freeze_auth else "Revoked (Safe)"}
        - Narrative: {narrative}
        
        LIQUIDITY/MCAP RATIO: {liq / (mcap + 1e-9):.2f}
        
        CRITICAL: If Mint Authority or Freeze Authority is ENABLED, the verdict MUST be AVOID.
        If Top 10 Holders Ratio > 40%, be extremely cautious.
        Based on these metrics, give a structured verdict.
        High Insider Risk (>0.7) or high Creator Risk (>0.7) must be a strong red flag.
        Return ONLY a JSON object with this exact structure (no markdown formatting, no backticks, just raw JSON).
        The "summary" and "risks" fields MUST be in ENGLISH:
        {{
            "verdict": "BUY" | "WAIT" | "AVOID",
            "rating": (int 0-10),
            "risk_level": "HIGH" | "MEDIUM" | "LOW",
            "summary": "Concise explanation of the verdict IN ENGLISH (max 200 chars)",
            "risks": ["Risk factor 1", "Risk factor 2", "Risk factor 3"]
        }}
        """

        # 3. Request Analysis
        response_text = ""
        
        # Use available models (Gemini 2.0 Flash is preferred, 1.5 as fallback)
        models_to_try = [
            'gemini-2.0-flash', 
            'gemini-1.5-flash', 
            'gemini-1.5-flash-8b', 
            'gemini-flash-latest'
        ]
        
        if HAS_NEW_GENAI:
            client = genai.Client(api_key=GOOGLE_API_KEY)
            for model_name in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    if response and response.text:
                        response_text = response.text
                        break
                except Exception as e:
                    err_msg = str(e).upper()
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        logger.warning(f"Gemini 429 on {model_name}, quota reached.")
                        # If the first model (usually fastest) is exhausted, wait a tiny bit
                        import asyncio
                        await asyncio.sleep(1)
                    else:
                        logger.warning(f"Failed with {model_name} (new genai): {e}")
                    continue
        else:
            # Fallback to old library
            for model_name in models_to_try:
                try:
                    model = genai_old.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    if response and response.text:
                        response_text = response.text
                        break
                except Exception as e:
                    logger.warning(f"Failed with {model_name} (old genai): {e}")
                    continue

        if not response_text:
            return {
                "verdict": "WAIT",
                "rating": 0,
                "risk_level": "UNKNOWN",
                "summary": "AI is temporarily overloaded or credits exhausted. Try again in 1 minute.",
                "risks": ["AI Quota Limiting (429)"]
            }
        
        # 4. Parse JSON from response text (Robust)
        text = response_text.strip()
        
        # Strip markdown code blocks if present
        if "```" in text:
            # find first { and last }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                text = text[start:end+1]
        
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Last ditch effort: regex for json object
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                raise ValueError(f"Could not parse JSON from AI response: {text[:50]}...")
                
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
