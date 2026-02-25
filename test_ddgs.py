try:
    from ddgs import DDGS
    print("Import from ddgs SUCCESS")
except ImportError:
    print("Import from ddgs FAILED")

try:
    from duckduckgo_search import DDGS
    print("Import from duckduckgo_search SUCCESS")
except ImportError:
    print("Import from duckduckgo_search FAILED")
