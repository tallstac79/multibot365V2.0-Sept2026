"""29 Sep 2026 hot-path latency, backend side. No rule, tolerance, stake or approval value is involved; these tests pin
the behaviours that make the same decisions sooner:

  - approved place dispatch in the SAME tick as the hold result (a stale 'phone busy' snapshot from the start of the tick
    used to delay it a whole cycle: the ~2 s tail of approved -> place dispatch, p90 1.96 s)
  - approval judged on health read after the result and before the decision
  - newest queued alert first (an approved final action still outranks everything)
  - the dispatcher wakes at once on an intake commit and runs the short cadence while work is queued
  - the phone's health is reused only briefly while a job is in flight
Fake coordinator only: no phone, no bookmaker, no money."""
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path

from tests.pipeline_support import MELBOURNE, RYTAS, T0, Clock, FakeGateway, message, pipeline, ready_result
from tests.test_final_action import placement_result


class BusyThenIdleGateway(FakeGateway):
    """Reports the phone busy with `busy_with` until its result has been READ, then idle - the real sequence at the moment
    a hold finishes while a dispatcher tick is under way."""

    def __init__(self, clock):
        super().__init__(clock)
        self.busy_with = None
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        self.health_extra = dict(self.health_extra, current_instruction=self.busy_with)
        return super().health()

    def result(self, instruction_id):
        value = super().result(instruction_id)
        if value is not None and not (isinstance(value, dict) and value.get('_pending')) and instruction_id == self.busy_with:
            self.busy_with = None
        return value


class SpeedPath(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = BusyThenIdleGateway(self.clock)

    def make(self, **settings):
        return pipeline(self.path, self.clock, instant_verification=False, final_action_enabled=True, approval_mode='automatic', **settings)

    def place_jobs(self):
        return [x['instruction_id'] for x in self.gateway.submitted if x.get('action') == 'PLACE_HELD']

    # ------------------------------------------------------------------ same-tick place dispatch
    def test_the_approved_place_is_sent_in_the_tick_that_reads_the_hold_result(self):
        p = self.make()
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)                                   # hold dispatched
        self.clock.advance(3)                                  # the phone works on it; the next tick begins...
        self.gateway.busy_with = iid                           # ...reading health that says 'busy with the hold'
        self.gateway.results[iid] = ready_result(iid)          # while the result is there by the time the tick polls it
        p.tick(self.gateway)                                   # ONE tick: read result -> approve -> dispatch the place
        self.assertEqual(self.place_jobs(), [iid + '-place'])

    def test_a_stale_busy_snapshot_alone_would_have_deferred_it(self):
        """The reused snapshot says busy; only the re-read at the result makes the same-tick dispatch possible."""
        p = self.make(health_reuse_seconds=60)                 # the snapshot is reused for a minute...
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)
        self.gateway.busy_with = iid
        p.tick(self.gateway)                                   # a tick while the hold runs: reuses the cached snapshot
        self.gateway.results[iid] = ready_result(iid)
        p.tick(self.gateway)                                   # ...and the result tick still re-reads before it decides
        self.assertEqual(self.place_jobs(), [iid + '-place'])

    def test_approval_is_judged_on_health_read_after_the_result(self):
        p = self.make()
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)
        self.gateway.busy_with = iid
        p.tick(self.gateway)                                   # in flight: snapshot cached (worker/account fine)
        self.gateway.health_extra = dict(self.gateway.health_extra, worker_id='someone-elses-phone')   # changes before the result
        self.gateway.results[iid] = ready_result(iid)
        p.tick(self.gateway)                                   # the cached snapshot is still 'fine'; only the re-read sees the change
        self.assertEqual(self.place_jobs(), [])                # refused on the worker identity read at approval time
        with p.store.connection() as db:
            row = db.execute('SELECT state, failure_reason FROM instructions WHERE instruction_id=?', (iid,)).fetchone()
        self.assertEqual(row['state'], 'REJECTED')
        self.assertIn('worker_identity', row['failure_reason'])

    # ------------------------------------------------------------------ newest first
    def two_alerts(self, p):
        older = p.ingest(message(MELBOURNE))['instruction_id']
        self.clock.advance(5)
        newer = p.ingest(message(RYTAS, received=T0 + timedelta(seconds=5)))['instruction_id']
        return older, newer

    def first_hold(self):
        return [x['instruction_id'] for x in self.gateway.submitted if x.get('execution_mode') == 'hold'][0]

    def test_the_freshest_queued_alert_is_dispatched_first(self):
        p = self.make()
        older, newer = self.two_alerts(p)
        p.tick(self.gateway)
        self.assertEqual(self.first_hold(), newer)
        self.assertEqual(len([x for x in self.gateway.submitted if x.get('execution_mode') == 'hold']), 1)   # one job at a time

    def test_oldest_first_is_still_available(self):
        p = self.make(dispatch_newest_first=False)
        older, newer = self.two_alerts(p)
        p.tick(self.gateway)
        self.assertEqual(self.first_hold(), older)

    def test_an_approved_final_action_outranks_a_fresher_queued_alert(self):
        p = self.make()
        older = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)                                   # older: hold dispatched
        self.gateway.busy_with = older
        self.gateway.results[older] = ready_result(older)
        newer = p.ingest(message(RYTAS, received=T0 + timedelta(seconds=1)))['instruction_id']   # a fresher alert queued meanwhile
        p.tick(self.gateway)
        self.assertEqual(self.place_jobs(), [older + '-place'])   # the approved final action, not the new alert's hold

    # ------------------------------------------------------------------ wake and cadence
    def test_an_intake_commit_wakes_the_dispatcher_and_selects_the_busy_cadence(self):
        p = self.make()
        self.assertEqual(p.next_tick_delay(1.0), 1.0)          # nothing queued: idle cadence
        started = time.monotonic()
        threading.Timer(0.05, lambda: p.ingest(message(MELBOURNE))).start()
        p.wait_for_work(5.0)                                   # returns when the intake commit happens, not after 5 s
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(p.next_tick_delay(1.0), p.settings.busy_tick_seconds)   # a QUEUED alert: short cadence
        self.assertEqual(p.next_tick_delay(0.1), 0.1)          # never slower than the configured idle cadence

    # ------------------------------------------------------------------ health reuse
    def test_health_is_reused_briefly_while_a_job_is_in_flight_then_re_read(self):
        p = self.make(health_reuse_seconds=1.5)
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)                                   # nothing in flight at the start: read
        base = self.gateway.health_calls
        self.gateway.busy_with = iid
        p.tick(self.gateway)                                   # in flight, snapshot 0 s old: reused
        p.tick(self.gateway)
        self.assertEqual(self.gateway.health_calls, base)
        self.clock.advance(2)
        p.tick(self.gateway)                                   # older than 1.5 s: re-read
        self.assertEqual(self.gateway.health_calls, base + 1)

    def test_reuse_can_be_switched_off(self):
        p = self.make(health_reuse_seconds=0)
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)
        self.gateway.busy_with = iid
        base = self.gateway.health_calls
        p.tick(self.gateway); p.tick(self.gateway)
        self.assertEqual(self.gateway.health_calls, base + 2)


if __name__ == '__main__':
    unittest.main()
