
import pandas as pd
import numpy as np

def zscore_robust(series: pd.Series) -> pd.Series:
    s = series.fillna(0.0)
    median = s.median()
    mad = (s - median).abs().median()
    if mad < 1e-7:
        std = s.std()
        if pd.isna(std) or std < 1e-9:
            return pd.Series(0.0, index=s.index)
        return (s - median) / (std + 1e-9)
    return (s - median) / (1.4826 * mad + 1e-9)

def test():
    # Simulate a batch with mostly 0s
    data = {
        "sa": [0, 0, 0, 0, 1.0], # one token has data
        "holder_acc": [0, 0, 0, 0, 0],
        "vol_shift": [1, 1, 1, 1, 1],
        "swr": [0, 0, 0, 0, 0],
        "vol_intensity": [0, 0, 0, 0, 0],
        "sell_pressure": [0, 0, 0, 0, 0]
    }
    df = pd.DataFrame(data)
    
    # Calculate Z-scores
    df["z_sa"] = zscore_robust(df["sa"])
    df["z_holder"] = zscore_robust(df["holder_acc"])
    df["z_vs"] = zscore_robust(df["vol_shift"])
    
    w_sa = 2.0
    df["instability"] = w_sa * df["z_sa"]
    
    print("Before Epsilon:")
    print(df[["sa", "z_sa", "instability"]])
    
    epsilon = 0.0001
    has_data_mask = (df["sa"] > 0)
    df.loc[has_data_mask, "instability"] += epsilon
    
    print("\nAfter Epsilon:")
    print(df[["sa", "z_sa", "instability"]])
    
    threshold = np.percentile(df["instability"], 40) # P40
    print(f"\nThreshold (P40): {threshold}")
    
    for i, row in df.iterrows():
        ii = row["instability"]
        passes = ii >= threshold and not (ii == 0 and threshold == 0)
        print(f"Token {i}: II={ii}, Threshold={threshold}, Passes={passes}")

if __name__ == "__main__":
    test()
