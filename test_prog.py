def test_progress(mcap, liq):
    if mcap <= 0: return 0
    v_tok_millions = 500 * liq / mcap
    tokens_sold = 1073 - v_tok_millions
    progress = (tokens_sold / 800) * 100
    return max(0, min(100, progress))

print(f"MC=13630, Liq=11323 -> Prog={test_progress(13630, 11323):.1f}%")
print(f"MC=8160, Liq=9403 -> Prog={test_progress(8160, 9403):.1f}%")
