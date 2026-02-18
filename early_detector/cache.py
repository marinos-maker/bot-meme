"""
Simple in-memory TTL cache for API responses.
"""

import time
from typing import Any
from loguru import logger

class CacheManager:
    def __init__(self):
        self._cache = {}

    def get(self, key: str) -> Any | None:
        """Retrieve value if key exists and is not expired."""
        if key not in self._cache:
            return None
        
        value, expiry = self._cache[key]
        if time.time() > expiry:
            del self._cache[key]
            return None
        
        return value

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Set value with TTL (default 5 min)."""
        expiry = time.time() + ttl_seconds
        self._cache[key] = (value, expiry)

    def clear(self) -> None:
        self._cache.clear()

# Global instance
cache = CacheManager()
