"""Evidence hygiene: no unredacted addbet token fields (bg/pc/cc/sa), no cookie or x-net-sync-term values in any run file."""
import glob, json, re, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
bad = 0
for f in root.glob('runs/*/*.json'):
    s = f.read_text(encoding='utf-8')
    for k in ('bg', 'pc', 'cc', 'sa'):
        for m in re.finditer(r'"%s": "([^"]*)"' % k, s):
            if m.group(1) != '<redacted>':
                bad += 1; print('unredacted', f.name, k)
    if 'x-net-sync-term' in s or '"cookie"' in s.lower():
        bad += 1; print('header', f)
print('files', len(list(root.glob('runs/*/*.json'))), 'problems', bad)
sys.exit(1 if bad else 0)
