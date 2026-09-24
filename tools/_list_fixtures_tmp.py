import sqlite3, json
from pathlib import Path
db = sqlite3.connect('.local/pipeline.sqlite3')
db.row_factory = sqlite3.Row
rows = db.execute("""
SELECT home, away, competition, market, selection, line, minimum_price, stake
FROM instructions
WHERE sport='basketball' AND home IS NOT NULL AND away IS NOT NULL
ORDER BY rowid DESC LIMIT 40
""").fetchall()
seen=set(); out=[]
for r in rows:
    k=(r['home'], r['away'])
    if k in seen: continue
    seen.add(k)
    out.append(dict(r))
print(json.dumps(out[:12], indent=2))
print('FULHAM')
for r in db.execute("""SELECT home, away, sport, market FROM instructions WHERE home LIKE '%Fulham%' OR away LIKE '%Crystal Palace%' ORDER BY rowid DESC LIMIT 5"""):
    print(dict(r))
