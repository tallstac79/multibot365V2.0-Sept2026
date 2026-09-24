"""Pipeline absolute timeout + progress poll; version bump; ladder checkpoints."""
from pathlib import Path
import re

# ---- pipeline Settings ----
pp = Path('core/pipeline.py')
pt = pp.read_text(encoding='utf-8')
pt2 = pt.replace(
    "device_timeout_ms: int = 120000\n    result_timeout_seconds: int = 240",
    "device_timeout_ms: int = 300000  # absolute backstop; stage inactivity on device fails closed sooner\n    result_timeout_seconds: int = 360",
    1)
if pt2 == pt:
    raise SystemExit('pipeline timeout defaults not updated')
# progress polling in _poll_in_flight
old_poll = '''    def _poll_in_flight(self, gateway):
        for row in self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]):
            try:
                result = gateway.result(row['instruction_id'])
            except Exception as error:
                result = None
                with self.store.tx() as db:
                    self.store.audit(db, 'RESULT_POLL_FAILED', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                     row['instruction_id'], row['device_id'])
            if result is not None:
                self.apply_result(row['instruction_id'], result)
                continue
            dispatched = datetime.fromisoformat(row['dispatched_at'])
            if (self.clock() - dispatched).total_seconds() > self.settings.result_timeout_seconds:
                with self.store.tx() as db:
                    self.store.transition(db, row['instruction_id'], State.TIMEOUT, actor='dispatcher',
                                          reason=f'No device result within {self.settings.result_timeout_seconds}s; '
                                                 'outcome unknown, never re-dispatched')'''

new_poll = '''    def _poll_in_flight(self, gateway):
        for row in self.store.instructions_in([State.DISPATCHED, State.DEVICE_ACTIVE]):
            try:
                result = gateway.result(row['instruction_id'])
            except Exception as error:
                result = None
                with self.store.tx() as db:
                    self.store.audit(db, 'RESULT_POLL_FAILED', dict(error=f'{type(error).__name__}: {error}'[:300]),
                                     row['instruction_id'], row['device_id'])
            if result is not None:
                if isinstance(result, dict) and result.get('_pending'):
                    # Mid-flight progress heartbeat from coordinator acknowledgement.
                    stage = None
                    progress = result.get('progress') if isinstance(result.get('progress'), dict) else {}
                    stage = result.get('device_stage') or progress.get('stage')
                    if stage and stage != row.get('device_stage'):
                        with self.store.tx() as db:
                            self.store.update_fields(db, row['instruction_id'], device_stage=stage)
                            self.store.audit(db, 'DEVICE_PROGRESS', dict(progress=progress or result),
                                             row['instruction_id'], row.get('device_id') or self.settings.device_id)
                    continue
                self.apply_result(row['instruction_id'], result)
                continue
            dispatched = datetime.fromisoformat(row['dispatched_at'])
            if (self.clock() - dispatched).total_seconds() > self.settings.result_timeout_seconds:
                with self.store.tx() as db:
                    self.store.transition(db, row['instruction_id'], State.TIMEOUT, actor='dispatcher',
                                          reason=f'No device result within {self.settings.result_timeout_seconds}s; '
                                                 'outcome unknown, never re-dispatched')'''

if old_poll not in pt2:
    raise SystemExit('poll block not found')
pt2 = pt2.replace(old_poll, new_poll, 1)
pp.write_text(pt2, encoding='utf-8')
print('OK pipeline.py')

# ---- device_gateway ----
dg = Path('core/device_gateway.py')
dt = dg.read_text(encoding='utf-8')
old_r = '''    def result(self, instruction_id):
        """Terminal result dict, or None while pending / not (yet) known to the phone."""
        code, value = self.client.request('GET', '/instructions/' + instruction_id)
        if code == 200:
            return value
        if code in (202, 404):
            return None
        raise ValueError(f'Unexpected result response HTTP {code}')'''
new_r = '''    def result(self, instruction_id):
        """Terminal result dict, pending progress dict with _pending=True, or None if unknown."""
        code, value = self.client.request('GET', '/instructions/' + instruction_id)
        if code == 200:
            return value
        if code == 202 and isinstance(value, dict):
            pending = dict(value)
            pending['_pending'] = True
            return pending
        if code in (202, 404):
            return None
        raise ValueError(f'Unexpected result response HTTP {code}')'''
if old_r not in dt:
    raise SystemExit('gateway result not found')
dg.write_text(dt.replace(old_r, new_r, 1), encoding='utf-8')
print('OK device_gateway.py')

# ---- version bump ----
bg = Path('android/Bet365Agent/app/build.gradle.kts')
bt = bg.read_text(encoding='utf-8')
bt2 = bt.replace('versionCode = 39', 'versionCode = 40', 1).replace(
    'versionName = "0.6.27-sports"', 'versionName = "0.6.28-stage"', 1)
if bt2 == bt:
    raise SystemExit('version bump failed')
bg.write_text(bt2, encoding='utf-8')
print('OK version 0.6.28-stage vc40')

# ---- ladder: QUERY_VERIFY / RESULTS_WAIT checkpoints ----
ba = Path('android/Bet365Agent/app/src/main/java/com/bet365agent/Bet365LiveAdapter.java')
bt = ba.read_text(encoding='utf-8')

# Find type-into-search success path in runSearchQueryLadder - look for QUERY_VERIFIED or similar
# Add after TextEntryFlow success / enter path
markers = []
for m in re.finditer(r'ui\.type\(|QUERY_VERIFIED|enterSearch|typeIntoSearch|results_wait|waitForResults', bt):
    markers.append((m.start(), m.group()))
print('markers', markers[:20])

# Look for runSearchQueryLadder body snippet with clearSearchField / type
idx = bt.find('private CompletableFuture<Void> runSearchQueryLadder')
print(bt[idx:idx+1800])
