"""
AI Analyst — Uses Gemini LLM to interpret token signals and metrics.
"""

import asyncio
import json
from datetime import datetime
from loguru import logger
from duckduckgo_search import DDGS
from early_detector.config import GOOGLE_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL, AI_MODEL_NAME

# Setup OpenAI
try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

if HAS_OPENAI and OPENAI_API_KEY:
    openai_client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        timeout=15.0,  # Prevent 5-minute freeze if API is down
        max_retries=1
    )
else:
    openai_client = None

# Try using the new google-genai library if available, otherwise fallback
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

async def get_social_sentiment(symbol: str, name: str) -> str:
    """Uses DuckDuckGo to scrape recent Twitter snippets matching the token symbol."""
    try:
        def do_search():
            query = f'site:twitter.com "{symbol}" crypto OR solana OR "{name}"'
            try:
                # DDGS can sometimes fail or be heavily rate limited
                results = DDGS().text(query, max_results=3)
                if not results:
                    return "No distinct social sentiment found on X."
                return " | ".join([r.get("body", "") for r in results])
            except:
                return "Search ratelimited."
        
        # Run synchronous web scraper in thread pool
        snippets = await asyncio.to_thread(do_search)
        return snippets
    except Exception as e:
        logger.debug(f"Social search skipped/failed: {e}")
        return "Search failed or unavailable."

async def analyze_token_signal(token_data: dict, history: list) -> dict:
    """
    Asks Gemini to analyze a token based on current metrics and history.
    Includes caching to avoid duplicate expensive AI calls.
    Falls back to quantitative scoring when AI is unavailable.
    """
    if not GOOGLE_API_KEY and not OPENAI_API_KEY:
        logger.warning("🧠 AI: Config keys absent, using quantitative fallback")
        return calculate_quantitative_score(token_data, history)

    address = token_data.get('address') or 'Unknown'
    
    # Caching disabled: if it reaches here, it must be analyzed again because the quantitative engine fired again.
    # now = datetime.now().timestamp()
    # if address in AI_CACHE:
    #     ts, cached_result = AI_CACHE[address]
    #     if now - ts < CACHE_TTL:
    #         logger.info(f"🧠 AI: Using cached result for {address[:8]}...")
    #         return cached_result

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
        has_twitter = current.get('has_twitter')
        
        h_growth = 0
        if len(history) > 1:
            prev_h = history[1].get("holders") or history[0].get("holders") or 0
            curr_h = holders
            if prev_h > 0:
                h_growth = ((curr_h - prev_h) / prev_h) * 100

        logger.info(f"🔍 AI: Running background web search for {symbol} on X...")
        twitter_snippets = await get_social_sentiment(symbol, current.get('name') or '')

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
        - Official Socials Provided: {"✅ YES" if has_twitter else "❌ NO (Ghost Token / Sus)"}
        - Recent Live Web Sentiment (Twitter/X): "{twitter_snippets}"
        - Narrative: {narrative}
        
        CRITICAL RULES:
        1. If Mint or Freeze is ENABLED, Verdict MUST be AVOID.
        2. If 'Official Socials Provided' is NO and 'Creator Reputation Risk' > 0.6, penalize score severely.
        3. If 'Live Web Sentiment' looks overly bot-spammed, warn about it.
        4. If Top 10 > 50%, be extremely critical.
        5. You MUST explicitly mention the presence or absence of Twitter Socials / Web Sentiment in your 'risks' or 'summary', no matter how bad the other metrics are.
        
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
        
        if openai_client:
            try:
                # Use OpenAI SDK (e.g., for OpenRouter / Z.AI)
                response = await openai_client.chat.completions.create(
                    model=AI_MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "You are a professional Crypto Alpha Analyst."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.6,
                    max_tokens=500
                )
                if response.choices and response.choices[0].message.content:
                    response_text = response.choices[0].message.content
            except Exception as e:
                err_msg = str(e).upper()
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "RATE_LIMIT" in err_msg:
                    logger.warning(f"OpenAI API 429 quota reached. Waiting 2s...")
                    import asyncio
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Failed with OpenAI API ({AI_MODEL_NAME}): {e}")
        else:
            # Use Google Gemini as fallback
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
        logger.error(f"🧠 AI Analysis error for {address[:8]}: {error_msg}")
        
        # Determine if it's a rate limit error
        is_quota = "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg
        
        # Fallback to quantitative scoring when AI fails
        logger.warning(f"🧠 AI: Analysis failed ({'quota' if is_quota else 'error'}), using quantitative fallback")
        return calculate_quantitative_score(token_data, history)


def calculate_quantitative_score(token_data: dict, history: list) -> dict:
    """
    Calculate a quantitative score based on token metrics when AI is unavailable.
    This provides a fallback scoring system based on mathematical analysis.
    """
    import math
    
    # Extract metrics with defaults
    price = float(token_data.get('price') or 0.0)
    mcap = float(token_data.get('marketcap') or 0.0)
    liq = float(token_data.get('liquidity') or 0.0)
    holders = int(token_data.get('holders') or 0)
    vol_5m = float(token_data.get('volume_5m') or 0.0)
    buys_5m = int(token_data.get('buys_5m') or 0)
    sells_5m = int(token_data.get('sells_5m') or 0)
    instability = float(token_data.get('instability_index') or 0.0)
    insider_psi = float(token_data.get('insider_psi') or 0.0)
    creator_risk = float(token_data.get('creator_risk_score') or 0.0)
    top10 = float(token_data.get('top10_ratio') or 0.0)
    mint_auth = token_data.get('mint_authority')
    freeze_auth = token_data.get('freeze_authority')
    symbol = token_data.get('symbol') or '???'
    address = token_data.get('address') or 'Unknown'
    
    # Calculate derived metrics
    liq_mcap_ratio = liq / (mcap + 1e-9)
    buy_sell_ratio = buys_5m / (sells_5m + 1) if sells_5m > 0 else buys_5m + 1
    velocity = (vol_5m / (liq + 1)) * 100 if liq > 0 else 0
    
    # Calculate holder growth
    h_growth = 0
    if len(history) > 1:
        prev_h = history[1].get("holders") or history[0].get("holders") or 0
        curr_h = holders
        if prev_h > 0:
            h_growth = ((curr_h - prev_h) / prev_h) * 100
    
    # Initialize scores
    base_score = 0
    risk_penalty = 0
    opportunity_bonus = 0
    
    # 1. Liquidity Score (0-20 points)
    if liq >= 5000:  # High liquidity
        base_score += 20
    elif liq >= 2000:  # Medium liquidity
        base_score += 15
    elif liq >= 1000:  # Low liquidity
        base_score += 10
    elif liq >= 500:   # Very low liquidity
        base_score += 5
    else:              # No liquidity
        base_score += 0
        risk_penalty += 20
    
    # 2. Liquidity/MCap Ratio Score (0-15 points)
    if liq_mcap_ratio >= 0.2:  # Very good ratio
        base_score += 15
    elif liq_mcap_ratio >= 0.1:  # Good ratio
        base_score += 10
    elif liq_mcap_ratio >= 0.05:  # Fair ratio
        base_score += 5
    else:  # Poor ratio
        risk_penalty += 10
    
    # 3. Holder Growth Score (0-15 points)
    if h_growth >= 50:  # Explosive growth
        base_score += 15
        opportunity_bonus += 10
    elif h_growth >= 20:  # Good growth
        base_score += 10
    elif h_growth >= 5:   # Moderate growth
        base_score += 5
    elif h_growth < 0:    # Declining holders
        risk_penalty += 10
    
    # 4. Instability Index Score (0-20 points)
    if instability >= 10:  # Very high instability
        base_score += 20
        opportunity_bonus += 15
    elif instability >= 5:  # High instability
        base_score += 15
        opportunity_bonus += 10
    elif instability >= 1:  # Moderate instability
        base_score += 10
    elif instability >= 0.1:  # Low instability
        base_score += 5
    else:  # No instability
        risk_penalty += 5
    
    # 5. Volume/Velocity Score (0-15 points)
    if velocity >= 50:  # Very high velocity
        base_score += 15
        opportunity_bonus += 10
    elif velocity >= 20:  # High velocity
        base_score += 10
    elif velocity >= 5:   # Moderate velocity
        base_score += 5
    else:  # Low velocity
        risk_penalty += 5
    
    # 6. Buy/Sell Ratio Score (0-10 points)
    if buy_sell_ratio >= 3:  # Strong buying pressure
        base_score += 10
    elif buy_sell_ratio >= 2:  # Good buying pressure
        base_score += 7
    elif buy_sell_ratio >= 1.5:  # Moderate buying pressure
        base_score += 5
    elif buy_sell_ratio < 0.5:  # Strong selling pressure
        risk_penalty += 10
    
    # 7. Insider Probability Penalty (0-20 points)
    if insider_psi >= 0.8:  # Very high insider probability
        risk_penalty += 20
    elif insider_psi >= 0.6:  # High insider probability
        risk_penalty += 15
    elif insider_psi >= 0.4:  # Moderate insider probability
        risk_penalty += 10
    elif insider_psi >= 0.2:  # Low insider probability
        risk_penalty += 5
    
    # 8. Top 10 Concentration Penalty (0-15 points)
    if top10 >= 0.7:  # Very high concentration
        risk_penalty += 15
    elif top10 >= 0.5:  # High concentration
        risk_penalty += 10
    elif top10 >= 0.3:  # Moderate concentration
        risk_penalty += 5
    
    # 9. Creator Risk Penalty (0-10 points)
    if creator_risk >= 0.8:  # Very high risk
        risk_penalty += 10
    elif creator_risk >= 0.6:  # High risk
        risk_penalty += 7
    elif creator_risk >= 0.4:  # Moderate risk
        risk_penalty += 5
    
    # 10. Authority Checks (Critical penalties)
    if mint_auth:  # Mint authority enabled
        risk_penalty += 50  # Critical penalty
    if freeze_auth:  # Freeze authority enabled
        risk_penalty += 50  # Critical penalty
    
    # Calculate final score
    final_score = base_score + opportunity_bonus - risk_penalty
    
    # Ensure score is within bounds
    final_score = max(0, min(100, final_score))
    
    # Determine verdict based on score
    if final_score >= 70:
        verdict = "BUY"
        risk_level = "MEDIUM" if risk_penalty < 20 else "HIGH"
    elif final_score >= 40:
        verdict = "WAIT"
        risk_level = "MEDIUM"
    else:
        verdict = "AVOID"
        risk_level = "HIGH" if risk_penalty > 30 else "MEDIUM"
    
    # Generate summary based on key metrics
    if verdict == "BUY":
        if instability >= 10 and velocity >= 20:
            summary = f"High instability ({instability:.1f}) + velocity ({velocity:.1f}%) = explosive potential"
        elif h_growth >= 50:
            summary = f"Explosive holder growth ({h_growth:+.1f}%) with good liquidity"
        else:
            summary = f"Strong metrics: LIQ ${liq:,.0f}, II {instability:.1f}, Holders {holders}"
    elif verdict == "WAIT":
        summary = f"Moderate potential: LIQ ${liq:,.0f}, II {instability:.1f}, Holders {holders}"
    else:
        if mint_auth or freeze_auth:
            summary = "CRITICAL: Mint/Freeze authority enabled - potential rug pull"
        elif top10 >= 0.5:
            summary = f"High concentration risk: Top 10 hold {top10*100:.1f}%"
        elif insider_psi >= 0.6:
            summary = f"High insider probability ({insider_psi:.2f}) - potential cabal"
        else:
            summary = f"Low potential: LIQ ${liq:,.0f}, II {instability:.1f}"
    
    # Generate risks based on penalties
    risks = []
    if mint_auth or freeze_auth:
        risks.append("CRITICAL: Mint/Freeze authority enabled")
    if top10 >= 0.5:
        risks.append(f"High concentration: Top 10 hold {top10*100:.1f}%")
    if insider_psi >= 0.6:
        risks.append(f"High insider probability ({insider_psi:.2f})")
    if liq < 1000:
        risks.append(f"Low liquidity (${liq:,.0f})")
    if liq_mcap_ratio < 0.05:
        risks.append(f"Poor liquidity ratio ({liq_mcap_ratio:.3f})")
    if h_growth < 0:
        risks.append(f"Declining holders ({h_growth:+.1f}%)")
    if velocity < 5:
        risks.append(f"Low velocity ({velocity:.1f}%)")
    if not risks and verdict != "BUY":
        risks.append("Insufficient upside potential")
    
    # Generate analysis
    bull_case = []
    bear_case = []
    
    if instability >= 5:
        bull_case.append(f"High instability ({instability:.1f}) indicates potential breakout")
    if velocity >= 20:
        bull_case.append(f"High velocity ({velocity:.1f}%) shows strong trading interest")
    if h_growth >= 20:
        bull_case.append(f"Strong holder growth ({h_growth:+.1f}%)")
    if liq >= 2000:
        bull_case.append(f"Good liquidity (${liq:,.0f}) for entry/exit")
    if buy_sell_ratio >= 2:
        bull_case.append(f"Strong buying pressure ({buy_sell_ratio:.1f}x)")
    
    if insider_psi >= 0.4:
        bear_case.append(f"High insider probability ({insider_psi:.2f}) suggests coordinated activity")
    if top10 >= 0.3:
        bear_case.append(f"Concentrated ownership (Top 10: {top10*100:.1f}%)")
    if creator_risk >= 0.4:
        bear_case.append(f"High creator risk ({creator_risk:.2f})")
    if liq < 1000:
        bear_case.append(f"Low liquidity (${liq:,.0f}) increases slippage risk")
    if h_growth < 0:
        bear_case.append(f"Declining holder count ({h_growth:+.1f}%)")
    
    if not bull_case:
        bull_case.append("Insufficient bullish indicators")
    if not bear_case:
        bear_case.append("No major red flags identified")
    
    return {
        "verdict": verdict,
        "degen_score": int(final_score),
        "rating": int(final_score / 10),
        "risk_level": risk_level,
        "summary": summary,
        "analysis": {
            "bull_case": "; ".join(bull_case),
            "bear_case": "; ".join(bear_case),
            "narrative_strength": 5  # Default for quantitative analysis
        },
        "risks": risks[:3]  # Limit to 3 main risks
    }
