import re

path = 'early_detector/static/dashboard.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace N/A insider_psi display
old_ins = "${s.insider_psi > 0 ? (s.insider_psi).toFixed(2) : 'N/A'}"
new_ins = "${(s.insider_psi || 0).toFixed(2)}"

# Replace N/A creator_risk display
old_cr = "${s.creator_risk > 0 ? (s.creator_risk).toFixed(2) : 'N/A'}"
new_cr = "${(s.creator_risk || 0).toFixed(2)}"

# Replace N/A top10 display
old_t10 = "${s.top10_ratio > 0 ? (s.top10_ratio).toFixed(1) + '%' : 'N/A'}"
new_t10 = "${(s.top10_ratio || 0).toFixed(1)}%"

# Replace insider color (add green for low)
old_ins_color = "color:${s.insider_psi > 0.5 ? 'var(--red)' : 'var(--text-secondary)'}; margin-bottom:2px;"
new_ins_color = "color:${s.insider_psi > 0.5 ? 'var(--red)' : s.insider_psi > 0.3 ? 'var(--yellow)' : 'var(--green)'}; margin-bottom:2px;"

# Replace creator_risk color
old_cr_color = "color:${s.creator_risk > 0.5 ? 'var(--red)' : 'var(--text-secondary)'};"
new_cr_color = "color:${s.creator_risk > 0.5 ? 'var(--red)' : s.creator_risk > 0.3 ? 'var(--yellow)' : 'var(--green)'};"

# Replace top10 color
old_t10_color = "color:var(--yellow)"
new_t10_color = "color:${s.top10_ratio > 85 ? 'var(--yellow)' : 'var(--text-secondary)'}"

replacements = [
    (old_ins, new_ins),
    (old_cr, new_cr),
    (old_t10, new_t10),
    (old_ins_color, new_ins_color),
    (old_cr_color, new_cr_color),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new, 1)
        print(f"OK: replaced '{old[:40]}...'")
    else:
        print(f"NOT FOUND: '{old[:60]}'")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
