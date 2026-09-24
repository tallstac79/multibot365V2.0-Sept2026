import sqlite3, json, re
c=sqlite3.connect(r".local/pipeline.sqlite3")
c.row_factory=sqlite3.Row
rows=c.execute("""
SELECT home, away, sport, fixture, competition, state
FROM instructions
WHERE sport='basketball' AND home IS NOT NULL AND away IS NOT NULL
ORDER BY rowid DESC LIMIT 80
""").fetchall()
print("count", len(rows))
prefs=re.compile(r'^(BC|KK|BK|FC|HJK)\b', re.I)
seen=set()
for r in rows:
    key=(r["home"], r["away"])
    if key in seen: continue
    seen.add(key)
    pref=bool(prefs.search(r["home"] or "") or prefs.search(r["away"] or ""))
    print(f"{'*' if pref else ' '} {r['home']} || {r['away']} | {r['competition']} | {r['state']}")
print("---prefix hits---")
for r in rows:
    if prefs.search(r["home"] or "") or prefs.search(r["away"] or ""):
        print(r["home"], "||", r["away"])
