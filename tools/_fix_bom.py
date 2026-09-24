from pathlib import Path
p = Path('tools/_run_stage_timeout_gunma_proof.py')
t = p.read_text(encoding='utf-8')
t2 = t.replace('.read_text(encoding="utf-8")', '.read_text(encoding="utf-8-sig")')
p.write_text(t2, encoding='utf-8')
print('count utf-8-sig', t2.count('utf-8-sig'))
