filepath = r'C:\bolo_ai\bolus_ai\backend\app\api\bolus.py'
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix lines with 22 spaces that should have 21 (in the async function block)
for i in range(len(lines)):
    line = lines[i]
    # Lines in the inner async function should have 21 spaces base indent
    # Check for lines with exactly 22 leading spaces that should be 21
    if line.startswith('                      ') and not line.startswith('                       '):
        # Check if this is in the autosens advisor block (lines ~277-380)
        if 277 <= i <= 380:
            lines[i] = line[1:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print('Fixed all')
