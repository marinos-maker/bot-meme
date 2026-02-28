import collections

def check_rejections():
    reasons = collections.Counter()
    with open("logs/runtime.log", "r", encoding="utf-8", errors="replace") as f:
        # read last 2000 lines
        lines = f.readlines()[-2000:]
        for line in lines:
            if "REJECTED" in line or "rejected" in line:
                if "Trigger rejected:" in line:
                    reason = line.split("Trigger rejected:")[1].split("for")[0].strip()
                    reasons[f"Trigger rejected: {reason}"] += 1
                elif "Quality Gate: REJECTED" in line:
                    reason = line.split("Quality Gate: REJECTED")[1].split("-")[1].strip() if "-" in line else line.split("Quality Gate: REJECTED")[1].strip()
                    reasons[f"Quality Gate: {reason}"] += 1
                elif "Safety:" in line and "REJECTED" in line:
                    reason = line.split("Safety:")[1].split("—")[0].strip()
                    reasons[f"Safety: {reason}"] += 1
                else:
                    reasons["Other: " + line.strip()[-50:]] += 1
    
    for r, count in reasons.most_common():
        print(f"{count}: {r}")

if __name__ == "__main__":
    check_rejections()
