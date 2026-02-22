
import requests
try:
    resp = requests.get("http://localhost:8000/api/wallets")
    data = resp.json()
    if data.get("wallets"):
        for w in data["wallets"][:5]:
            print(f"Wallet: {w['wallet'][:8]}... Last Active: {w['last_active']}")
    else:
        print("No wallets found in API")
except Exception as e:
    print(f"Error: {e}")
