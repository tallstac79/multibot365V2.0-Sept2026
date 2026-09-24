from pathlib import Path
p = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/CoordinatorInstruction.java')
t = p.read_text(encoding='utf-8')
old = 'if (timeout < 100 || timeout > 120000) throw new IllegalArgumentException("timeout_ms must be 100..120000");'
new = 'if (timeout < 100 || timeout > 600000) throw new IllegalArgumentException("timeout_ms must be 100..600000");'
if old not in t:
    raise SystemExit('timeout guard not found: ' + repr(t[t.find('timeout <'):t.find('timeout <')+120]))
p.write_text(t.replace(old, new, 1), encoding='utf-8')
print('OK')
