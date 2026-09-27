"""Automatic mode sends exactly ONE Telegram message per qualified instruction: PLACED or MISSED - <reason>
(operator, 27 Sep 2026). Intermediate lifecycle states (QUALIFIED, AUTO APPROVED, READY, ...) are never sent; they stay in
the database. The outcome pass runs after every tick here to prove nothing intermediate leaks out.
Fake coordinator only: no phone, no bookmaker, no money."""
import unittest

from core.status_notifier import AUTOMATIC_STATES, CORRECTION_KEY, OUTCOME_KEY, Notifier
from tests.pipeline_support import MELBOURNE, fail_result, message
from tests.test_automatic_approval import Base
from tests.test_final_action import placement_result


class OutcomeOnly(Base):
    instant = False

    def setUp(self):
        super().setUp()
        self.notifier = Notifier(self.p.store, sender=None, states=AUTOMATIC_STATES, clock=self.clock, outcome_only=True)
        self.notifier.enqueue()                      # baseline
        self.clock.advance(1)

    def tick(self):
        self.p.tick(self.gateway)
        self.notifier.enqueue()

    def messages(self, iid=None):
        with self.p.store.connection() as db:
            q = 'SELECT instruction_id, state, text FROM notifications' + (' WHERE instruction_id=?' if iid else '')
            return [dict(r) for r in db.execute(q, (iid,) if iid else ())]

    def test_placed_is_one_message_and_nothing_before_it(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.tick()                                              # QUEUED -> hold dispatched
        self.assertEqual(self.messages(), [])                    # no QUALIFIED
        self.gateway.results[iid] = dict(__import__('tests.pipeline_support', fromlist=['ready_result']).ready_result(iid))
        self.tick()                                              # READY -> AUTO APPROVED -> PLACE_HELD sent
        self.assertEqual(self.messages(), [])                    # no AUTO APPROVED
        self.gateway.results[iid + '-place'] = placement_result(iid)
        self.tick(); self.tick()                                 # COMPLETED
        sent = self.messages(iid)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['state'], OUTCOME_KEY)
        self.assertTrue(sent[0]['text'].startswith('MultiBot365 - PLACED'))
        self.assertIn('Bet ref: JL1234567890', sent[0]['text'])
        self.assertIn('Requested: TOTALS Over 190.5 @ 2.20', sent[0]['text'])
        for _ in range(3):
            self.clock.advance(60); self.tick()                  # My Bets verification etc.: still one message
        self.assertEqual(len(self.messages(iid)), 1)

    def test_every_terminal_failure_is_one_missed_message_with_the_reason(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.tick()
        self.gateway.results[iid] = fail_result(iid, 'BELOW_MINIMUM', 'Visible price 1.95 is below minimum 2.08')
        self.tick(); self.tick()
        sent = self.messages(iid)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0]['text'].startswith('MultiBot365 - MISSED - price below minimum'), sent[0]['text'])
        self.assertIn('Requested: TOTALS Over 190.5 @ 2.20', sent[0]['text'])
        self.assertIn('Reason: BELOW_MINIMUM: Visible price 1.95 is below minimum 2.08', sent[0]['text'])

    def test_pre_tap_refusal_after_auto_approval_is_one_missed_message(self):
        from tests.pipeline_support import ready_result
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.tick()
        self.gateway.results[iid] = ready_result(iid)
        self.tick()
        self.gateway.results[iid + '-place'] = placement_result(iid, outcome='LINE_CHANGED', tapped=False, detail='Line 191.5 now')
        self.tick(); self.tick()
        sent = self.messages(iid)
        self.assertEqual(len(sent), 1, sent)
        self.assertTrue(sent[0]['text'].startswith('MultiBot365 - MISSED'), sent[0]['text'])

    def test_a_rules_rejected_alert_sends_nothing(self):
        text = MELBOURNE['raw_text'].replace('190.5', '190.5')
        rejected = self.p.ingest(message(MELBOURNE, message_id='970001', text=text + '\n'))
        self.tick()
        # whatever the rules decided for a duplicate/never-queued alert, nothing is announced unless it was QUALIFIED
        for row in self.messages():
            self.assertNotEqual(row['instruction_id'], rejected.get('instruction_id') if rejected.get('state') != 'QUEUED' else None)

    def test_correction_when_a_missed_bet_is_found_later(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.tick()
        self.gateway.results[iid] = fail_result(iid, 'BELOW_MINIMUM', 'x')
        self.tick(); self.tick()
        with self.p.store.tx() as db:                            # e.g. My Bets later shows the bet (DISCREPANCY)
            self.p.store.upsert_bet(db, iid, status='DISCREPANCY', stake='1.00', odds='2.20', bet_reference='JL1234567890')
        self.tick(); self.tick()
        states = sorted(m['state'] for m in self.messages(iid))
        self.assertEqual(states, [OUTCOME_KEY, CORRECTION_KEY])
        correction = [m for m in self.messages(iid) if m['state'] == CORRECTION_KEY][0]['text']
        self.assertTrue(correction.startswith('MultiBot365 - PLACED (correction'))


if __name__ == '__main__':
    unittest.main()
