import os

path = "backend/data/settings.json"
if os.path.exists(path):
    print(f"Reading {path}...")
    with open(path, "r") as f:
        content = f.read()
    
    if '"mid": 100' in content:
        print("Found target 100. Updating to 110...")
        new_content = content.replace('"mid": 100', '"mid": 110')
        with open(path, "w") as f:
            f.write(new_content)
        print("Updated successfully.")
    else:
        print("Target 100 not found (already updated?).")
        if '"mid": 110' in content:
            print("Verified: Target is 110.")
        else:
            print("Could not verify target.")
else:
    print(f"File {path} not found.")
