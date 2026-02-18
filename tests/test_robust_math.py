
import pandas as pd
import numpy as np
from early_detector.scoring import zscore, zscore_robust

def test_robust_zscore_handles_outliers():
    # Data with a extreme outlier
    data = pd.Series([10, 12, 11, 13, 12, 11, 1000]) # 1000 is the outlier
    
    z_std = zscore(data)
    z_robust = zscore_robust(data)
    
    print("\nStandard Z-Scores:")
    print(z_std.values)
    
    print("\nRobust Z-Scores:")
    print(z_robust.values)
    
    # In standard z-score, the outlier (1000) pulls the mean up so much that 
    # the normal values (10-13) look very similar and have negative scores.
    # In robust z-score, the median and MAD stay stable.
    
    # Check that normal values are not crushed to near-zero by the outlier
    assert abs(z_robust[0]) > 0.1
    # Check that outlier is still identified as an outlier
    assert z_robust[6] > 10.0
    
    print("\nTest Passed: Robust Z-Score is stable against outliers.")

if __name__ == "__main__":
    test_robust_zscore_handles_outliers()
