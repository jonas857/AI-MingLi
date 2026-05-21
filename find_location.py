with open("app_simplified_v2.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        if "location" in line:
            print(f"{i+1}: {line.strip()}")
