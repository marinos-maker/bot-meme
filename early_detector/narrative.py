
import re
from loguru import logger

class NarrativeManager:
    """
    Categorizes tokens into narratives based on keywords.
    Used for capital rotation analysis.
    """
    
    # Narrative definitions: { Category: [Keywords] }
    # Keywords are processed as lowercase and case-insensitive regex.
    NARRATIVES = {
        "AI": [r"ai", r"gpt", r"agent", r"btu", r"neural", r"zero", r"compute", r"autonomous", r"inference", r"fart", r"terminal"],
        "POLITICS": [r"trump", r"magai", r"kamala", r"usa", r"election", r"vp", r"potus", r"democracy", r"freedom", r"constitution"],
        "ANIMALS": [r"pepe", r"dog", r"cat", r"frog", r"goat", r"pnut", r"shib", r"inu", r"wojak", r"moodeng", r"pochita", r"popcat", r"chillguy"],
        "CELEBRITIES": [r"elon", r"tate", r"vitalik", r"saylor", r"trump", r"rogon", r"mrbeast", r"ishowspeed"],
        "CULTURE/MEMES": [r"meme", r"sigma", r"alpha", r"rekt", r"moon", r"gem", r"based", r"degen", r"ponzi", r"rug"],
        "TECH/INFRA": [r"sol", r"eth", r"bridge", r"dex", r"yield", r"staking", r"lp", r"node", r"rpc"],
    }

    @classmethod
    def classify(cls, name: str, symbol: str) -> str:
        """
        Assign a narrative to a token based on name and symbol.
        Returns the category name or 'UNKNOWN'.
        """
        text = f"{name} {symbol}".lower()
        
        # Priority matching: some narratives might be more specific
        # We check in order of the dictionary
        for category, keywords in cls.NARRATIVES.items():
            for kw in keywords:
                if re.search(kw, text):
                    return category
                    
        return "GENERIC"

    @classmethod
    def get_narrative_stats(cls, tokens: list[dict]) -> dict:
        """
        Given a list of tokens with their latest volume,
        calculate volume dominance per narrative.
        """
        stats = {cat: {"count": 0, "volume": 0.0} for cat in cls.NARRATIVES.keys()}
        stats["GENERIC"] = {"count": 0, "volume": 0.0}
        
        total_vol = 0.0
        
        for t in tokens:
            narr = cls.classify(t.get("name", ""), t.get("symbol", ""))
            vol = float(t.get("volume_5m", 0) or 0)
            
            stats[narr]["count"] += 1
            stats[narr]["volume"] += vol
            total_vol += vol
            
        # Calculate dominance %
        for cat in stats:
            stats[cat]["dominance"] = (stats[cat]["volume"] / total_vol * 100) if total_vol > 0 else 0
            
        return stats
