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

# In-memory cache to avoid duplicate expensive AI calls
# { address: (timestamp, result_dict) }
AI_CACHE = {}
CACHE_TTL = 600 # 10 minutes

async def analyze_token_signal(token_data: dict, history: list) -> dict:
    """
    Asks Gemini to analyze a token based on current metrics and history.
    Includes caching to preserve quota.
    """
    if not GOOGLE_API_KEY:
        return {
            "rating": 0,
            "verdict": "AI Disabled (Missing API Key)",
            "summary": "Please add GOOGLE_API_KEY to your .env file.",
            "risks": []
        }

    address = token_data.get('address') or 'Unknown'
    
    # ── Check Cache ──
    now = datetime.now().timestamp()
    if address in AI_CACHE:
        ts, cached_result = AI_CACHE[address]
        if now - ts < CACHE_TTL:
            logger.info(f"🧠 AI: Using cached result for {address[:8]}...")
            return cached_result

    try:
        # 1. Prepare data for prompt with defaults for None values
        current = token_data
        symbol = current.get('symbol') or '???'
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
        Act as a professional Crypto Alpha Analyst and Degen Trader. 
        Analyze this Solana Meme Coin signal with extreme prejudice. 
        Detect potential rug-pulls, wash-trading, and coordinated degen entries.

        TOKEN METRICS:
        - Symbol: {symbol}
        - Address: {address}
        - Price: ${price:.12f}
        - Market Cap: ${mcap:,.0f}
        - Liquidity: ${liq:,.0f}
        - Liquidity/MCap Ratio: {liq / (mcap + 1e-9):.3f}
        - Holders: {holders} (20m Growth: {h_growth:+.1f}%)
        - Top 10 Holder Concentration: {top10:.1f}%
        - 5m Volume: ${vol_5m:,.0f}
        - 5m Buy/Sell Ratio: {buys_5m/(sells_5m+1):.2f} ({buys_5m} buys / {sells_5m} sells)
        - Instability Index (II): {instability:.3f}
        - Insider Probability (PSI): {insider_psi:.2f}
        - Creator Reputation Risk: {creator_risk:.2f}
        - Authorities: Mint: {"⚠️ ENABLED" if mint_auth else "✅ Revoked"}, Freeze: {"⚠️ ENABLED" if freeze_auth else "✅ Revoked"}
        - Narrative: {narrative}
        
        CRITICAL RULES:
        1. If Mint or Freeze is ENABLED, Verdict MUST be AVOID.
        2. If Top 10 > 50%, be extremely critical.
        3. If Insider PSI > 0.7, assume it's a cabal/scam.
        
        Return ONLY a JSON object (no markdown, no backticks):
        {{
            "verdict": "BUY" | "WAIT" | "AVOID",
            "degen_score": (int 0-100),
            "rating": (int 0-10),
            "risk_level": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
            "summary": "One sentence punchy degen summary IN ENGLISH",
            "analysis": {{
                "bull_case": "Why this could 10x",
                "bear_case": "Why this will rug/dump",
                "narrative_strength": (int 0-10)
            }},
            "risks": ["Risk 1", "Risk 2", "Risk 3"]
        }}
        """

        # 3. Request Analysis
        response_text = ""
        
        # Use available models (Gemini 2.0 Flash is preferred, 1.5 as fallback)
        models_to_try = [
            'gemini-2.0-flash', 
            'gemini-2.0-flash-lite-preview-02-05',
            'gemini-1.5-flash', 
            'gemini-1.5-pro'
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
                        logger.warning(f"Gemini 429 on {model_name}, quota reached. Waiting 2s...")
                        import asyncio
                        await asyncio.sleep(2)
                    elif "404" in err_msg or "NOT_FOUND" in err_msg:
                        logger.warning(f"Model {model_name} not found, skipping...")
                    else:
                        logger.warning(f"Failed with {model_name} (new genai): {e}")
                    continue
        else:
            # Fallback to old library
            for model_name in models_to_try:
                try:
                    model = genai_old.GenerativeModel(model_name or 'gemini-1.5-flash')
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
                "degen_score": 0,
                "rating": 0,
                "risk_level": "UNKNOWN",
                "summary": "AI is temporarily overloaded or credits exhausted. Try again in 1 minute.",
                "risks": ["AI Quota Limiting (429)"]
            }
        
        # 4. Parse JSON from response text (Robust)
        text = response_text.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                text = text[start:end+1]
        
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
            else:
                raise ValueError(f"Could not parse JSON from AI response: {text[:50]}...")
                
        # ── Normalize Output (V4.5) ──
        # Ensure degen_score exists, or derive it from rating
        rating = result.get("rating", 0)
        if "degen_score" not in result:
            result["degen_score"] = int(rating * 10)
        
        # Ensure other critical fields exist
        if "verdict" not in result: result["verdict"] = "WAIT"
        if "summary" not in result: result["summary"] = "No summary provided by AI."
        if "risks" not in result: result["risks"] = []

        # ── Update Cache ──
        AI_CACHE[address] = (datetime.now().timestamp(), result)

        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"AI Analyst error: {e}")
        
        # Determine if it's a rate limit error
        is_quota = "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg
        
        return {
            "verdict": "WAIT" if is_quota else "ERROR",
            "degen_score": 0,
            "rating": 0,
            "risk_level": "CRITICAL" if not is_quota else "MEDIUM",
            "summary": "AI Quota Exceeded. Please wait 60s." if is_quota else f"Error: {error_msg[:50]}",
            "risks": ["Rate Limit Reached" if is_quota else "Internal Analysis Error"]
        }
