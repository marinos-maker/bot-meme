import time
from early_detector.cache import CacheManager

def test_cache_set_get():
    c = CacheManager()
    c.set("key", "value", ttl_seconds=10)
    assert c.get("key") == "value"

def test_cache_expiry():
    c = CacheManager()
    c.set("key", "value", ttl_seconds=1)
    time.sleep(1.1)
    assert c.get("key") is None
