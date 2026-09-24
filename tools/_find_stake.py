import pathlib, re
roots = [pathlib.Path("core"), pathlib.Path("tools"), pathlib.Path("plugins"), pathlib.Path("config.py"), pathlib.Path("dashboard")]
pat = re.compile(r"default_stake|stake_amount|\"stake\"|stake\s*=|dispatch_enabled|execution_mode|place_bet", re.I)
for root in roots:
    files = [root] if root.is_file() else list(root.rglob("*.py"))
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                print(f"{p}:{i}:{line.strip()[:180]}")
