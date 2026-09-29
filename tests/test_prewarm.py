"""30 Sep 2026: the phone starts loading the event page of the next queued alert while the dispatcher is still doing its own
intake -> dispatch work. Navigation only; these tests pin when it is (and is not) asked for. Fake coordinator only."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tests.pipeline_support import MELBOURNE, RYTAS, T0, Clock, FakeGateway, message, pipeline, ready_result


class Prewarm(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'p.sqlite3'
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)

    def make(self, **settings):
        return pipeline(self.path, self.clock, instant_verification=False, final_action_enabled=True, approval_mode='automatic', **settings)

    def test_the_queued_alerts_event_page_is_prewarmed_once_before_the_dispatch(self):
        p = self.make()
        p.ingest(message(MELBOURNE))
        p.tick(self.gateway)
        self.assertEqual(self.gateway.prewarmed, ['https://www.bet365.com/#/AC/B18/C21167989/D19/E26735656/F19/I0/'])
        p.tick(self.gateway)
        self.assertEqual(len(self.gateway.prewarmed), 1)            # not again for the same alert

    def test_the_freshest_queued_alert_is_the_one_prewarmed(self):
        p = self.make()
        p.ingest(message(MELBOURNE))
        self.clock.advance(5)
        p.ingest(message(RYTAS, received=T0 + timedelta(seconds=5)))
        p.tick(self.gateway)
        first_hold = [x for x in self.gateway.submitted if x.get('execution_mode') == 'hold'][0]
        self.assertEqual(self.gateway.prewarmed, [first_hold['event_url']])

    def test_nothing_is_prewarmed_while_a_job_is_on_the_phone_or_a_slip_is_held(self):
        p = self.make()
        iid = p.ingest(message(MELBOURNE))['instruction_id']
        p.tick(self.gateway)                                       # hold dispatched (prewarm sent first, before it)
        self.gateway.prewarmed.clear()
        p.ingest(message(RYTAS, received=T0 + timedelta(seconds=1)))
        p.tick(self.gateway)                                       # the hold is in flight: no prewarm, no navigation under it
        self.assertEqual(self.gateway.prewarmed, [])
        self.gateway.results[iid] = ready_result(iid)
        p.tick(self.gateway)                                       # READY / approved / place dispatched: still none
        self.assertEqual(self.gateway.prewarmed, [])

    def test_no_prewarm_when_paused_disabled_or_switched_off(self):
        p = self.make()
        p.final.set_paused(True, 'test')
        p.ingest(message(MELBOURNE))
        p.tick(self.gateway)
        self.assertEqual(self.gateway.prewarmed, [])
        p.final.set_paused(False, 'test')
        p2 = self.make(prewarm_enabled=False)
        p2.tick(self.gateway)
        self.assertEqual(self.gateway.prewarmed, [])

    def test_a_busy_phone_is_asked_again_shortly_not_every_tick(self):
        class Busy(FakeGateway):
            calls = 0
            def prewarm(self, url):
                Busy.calls += 1
                return {'started': False, 'reason': 'phone busy'}
        gateway = Busy(self.clock)
        p = self.make()
        p.ingest(message(MELBOURNE))
        p._prewarm(gateway); p._prewarm(gateway)
        self.assertEqual(Busy.calls, 1)                            # retried no sooner than 0.5 s later
        self.clock.advance(0.6)
        p._prewarm(gateway)
        self.assertEqual(Busy.calls, 2)

    def test_a_failing_phone_never_breaks_the_tick(self):
        class Broken(FakeGateway):
            def prewarm(self, url):
                raise OSError('no route')
        p = self.make()
        p.ingest(message(MELBOURNE))
        gateway = Broken(self.clock)
        p.tick(gateway)                                            # must not raise
        self.assertTrue([x for x in gateway.submitted if x.get('execution_mode') == 'hold'])


if __name__ == '__main__':
    unittest.main()
