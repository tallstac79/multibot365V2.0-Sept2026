from pathlib import Path
import re
hp = Path("tools/_run_sports_discovery_proof.py")
ht = hp.read_text(encoding="utf-8")
start = ht.find("def team_pos(team_name, requested):")
if start < 0:
    raise SystemExit("team_pos missing")
end = ht.find("\ndef adb(", start)
if end < 0:
    end = ht.find("\ndef chrome_reset(", start)
new_tp = '''def _norm_team(s):
    t = re.sub(r"\\s+", " ", str(s or "").strip())
    t = re.sub(r"(?i)\\s*\\((?:W|M|F|Women|Men)\\)\\s*$", "", t)
    t = re.sub(r"(?i)\\s+(?:Women|Men|Womens|Ladies)$", "", t)
    return t.strip().lower()

def team_pos(team_name, requested):
    if not team_name or not requested: return False
    t = _norm_team(team_name); r = _norm_team(requested)
    if not t or not r: return False
    if t == r or r in t or (t in r and len(t) >= 4): return True
    if r.endswith(" " + t) and len(t) >= 4: return True
    if t.endswith(" " + r) and len(r) >= 4: return True
    return False
'''
ht2 = ht[:start] + new_tp + ht[end:]
hp.write_text(ht2, encoding="utf-8")
ns = {}
exec(new_tp, {"re": re}, ns)
assert ns["team_pos"]("Beroe (W)", "BC Beroe")
assert ns["team_pos"]("Uni Ferrol (W)", "Ferrol")
print("harness ok")
