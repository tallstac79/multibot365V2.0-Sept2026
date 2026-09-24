import sqlite3
c=sqlite3.connect(r".local/pipeline.sqlite3")
print([r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
cols=None
for t in ["alerts","instructions","odds_alerts","feed"]:
    try:
        cols=[r[1] for r in c.execute(f"PRAGMA table_info({t})")]
        print(t, cols[:20])
    except Exception as e:
        pass
