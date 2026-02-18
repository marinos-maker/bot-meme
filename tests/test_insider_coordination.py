
from early_detector.smart_wallets import detect_coordinated_entry, compute_insider_score

def test_coordination_spikes_insider_score():
    # 1. Simulate a coordinated launch
    # 3 wallets buying at almost the same time
    trades = [
        {"wallet": "W1", "type": "buy", "timestamp": 1000, "amount": 1.0},
        {"wallet": "W2", "type": "buy", "timestamp": 1001, "amount": 1.0},
        {"wallet": "W3", "type": "buy", "timestamp": 1002, "amount": 1.0},
        {"wallet": "R1", "type": "buy", "timestamp": 1100, "amount": 0.5}, # Random retail buy later
    ]
    
    coordinated = detect_coordinated_entry(trades, window_sec=5)
    print(f"\nCoordinated Wallets detected: {coordinated}")
    assert "W1" in coordinated
    assert "W2" in coordinated
    assert "W3" in coordinated
    assert "R1" not in coordinated
    
    # 2. Check Insider Score Bonus
    pair_created_at = 990 * 1000 # 10s before W1
    
    # Score without coordination
    score_normal = compute_insider_score(
        wallet_stats={"total_trades": 10, "win_rate": 0.5},
        first_trade_timestamp=1000,
        pair_created_at=pair_created_at,
        is_coordinated=False
    )
    
    # Score with coordination
    score_coord = compute_insider_score(
        wallet_stats={"total_trades": 10, "win_rate": 0.5},
        first_trade_timestamp=1000,
        pair_created_at=pair_created_at,
        is_coordinated=True
    )
    
    print(f"Score Normal: {score_normal:.2f}")
    print(f"Score Coordinated: {score_coord:.2f}")
    
    assert score_coord > score_normal
    assert abs(score_coord - score_normal - 0.3) < 0.01
    
    print("\nTest Passed: Coordination is correctly detected and rewarded.")

if __name__ == "__main__":
    test_coordination_spikes_insider_score()
