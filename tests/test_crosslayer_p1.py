"""The four P1 findings of the 27 Sep 2026 cross-layer audit (docs/CROSS_LAYER_AUDIT_20260927.md on codex/ops-tracking-audit):

  P1-1 a reconciliation still "pending" never holds the device (and every later dispatch) indefinitely;
  P1-2 My Bets matching is reference-first, date-checked, unique, and settlement assigns one card to one bet;
  P1-3 reconciliation is bound to the worker/account that placed the bet;
  P1-4 Telegram delivery can never delay a dispatch tick.
Fake coordinator only: no phone, no bookmaker, no money.
"""
import asyncio
import json
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path

from core import bet_matching
from core.final_action import OPEN, SETTLE, VERIFY
from tests.pipeline_support import ACCOUNT_FINGERPRINT, MELBOURNE, RYTAS, WORKER_ID, Clock, FakeGateway, message, pipeline
from tests.test_final_action import MELBOURNE_CARD, my_bets

MELBOURNE_TERMS = dict(home='SE Melbourne Phoenix', away='Melbourne United', market='TOTALS', selection='OVER', line='190.5',
                       stake='1.00', odds='2.20')


def lines(*frames):
    return {'lines': [{'text': t, 'top': i * 40, 'frame': f} for f, texts in enumerate(frames) for i, t in enumerate(texts)]}


class Harness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.gateway = FakeGateway(self.clock)
        self.p = pipeline(Path(tmp.name) / 'p.sqlite3', self.clock, final_action_enabled=True)

    def bet(self, iid, status=OPEN, worker=WORKER_ID, account=ACCOUNT_FINGERPRINT, **extra):
        with self.p.store.tx() as db:
            self.p.store.upsert_bet(db, iid, status=status, stake='1.00', odds='2.20', line='190.5', market='TOTALS', selection='OVER', placed_at=self.clock().isoformat(),
                                    source='device', worker_id=worker, account_fingerprint=account, **extra)

    def clone(self, iid, new_id):
        with self.p.store.tx() as db:
            row = dict(db.execute('SELECT * FROM instructions WHERE instruction_id=?', (iid,)).fetchone())
            row.update(instruction_id=new_id, selection_key=(row.get('selection_key') or '') + new_id)
            db.execute(f"INSERT INTO instructions({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
        return new_id

    def recs(self):
        with self.p.store.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM reconciliations ORDER BY id')]

    def audits(self, kind):
        with self.p.store.connection() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT detail FROM audit_events WHERE kind=?', (kind,))]

    def health(self):
        self.p.tick(self.gateway)            # refresh_device stores the phone's health (worker/account)
        return self.gateway.health()


class PendingDeadline(Harness):
    def test_a_check_still_pending_at_its_deadline_releases_the_device(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.bet(iid, status='PLACED_UNVERIFIED')
        health = self.health()
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.assertTrue(self.p.final.schedule(self.gateway, health, True))
        rid = self.recs()[0]['device_instruction_id']
        self.gateway.results[rid] = {'_pending': True}            # the phone keeps saying "still running"
        self.p.final.poll(self.gateway)
        self.assertTrue(self.p.final.device_busy())                # within its deadline it owns the device
        self.clock.advance(self.p.settings.reconcile_timeout_ms / 1000 + 61)
        self.p.final.poll(self.gateway)
        rec = self.recs()[0]
        self.assertEqual(rec['outcome'], 'FAILED')                 # bounded: an audited failed attempt
        self.assertIn('pending at its deadline', rec['detail'])
        self.assertTrue(self.audits('RECONCILE_DEADLINE')[0]['pending'])
        self.assertFalse(self.p.final.device_busy())               # new work may take the phone again
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM bets WHERE instruction_id=?', (iid,)).fetchone()[0], 'PLACED_UNVERIFIED')


class MatchingGuarantees(unittest.TestCase):
    def test_reference_first(self):
        mine = dict(MELBOURNE_TERMS, bet_reference='JL1234567890')
        self.assertTrue(bet_matching.match(mine, lines(MELBOURNE_CARD))['found'])
        other = [x if not x.startswith('Bet Ref') else 'Bet Ref ZZ9999999999' for x in MELBOURNE_CARD]
        self.assertFalse(bet_matching.match(mine, lines(other))['found'])          # a different printed reference
        both = lines(other + MELBOURNE_CARD)                                          # two identical terms, refs differ
        found = bet_matching.match(mine, both)
        self.assertTrue(found['found'])
        self.assertEqual(found['bet_reference'], 'JL1234567890')

    def test_two_matching_cards_are_ambiguous(self):
        no_ref = [x for x in MELBOURNE_CARD if not x.startswith('Bet Ref')]
        twin = bet_matching.match(MELBOURNE_TERMS, lines(no_ref + no_ref))           # two bets with the same terms
        self.assertFalse(twin['found'])
        self.assertEqual(twin['confidence'], 'AMBIGUOUS')
        # the same card seen again in an overlapping scrolled frame is ONE card
        self.assertTrue(bet_matching.match(MELBOURNE_TERMS, lines(no_ref, no_ref))['found'])

    def test_event_date(self):
        dated = MELBOURNE_CARD[:3] + ['SE Melbourne Phoenix Sun 27 Sep', 'Melbourne United 17:45'] + MELBOURNE_CARD[4:]
        self.assertTrue(bet_matching.match(dict(MELBOURNE_TERMS, event_time='2026-09-27T17:45'), lines(dated))['found'])
        self.assertFalse(bet_matching.match(dict(MELBOURNE_TERMS, event_time='2026-10-04T17:45'), lines(dated))['found'])


class AccountBinding(Harness):
    def test_only_bets_of_the_phones_account_are_reconciled(self):
        ours = self.p.ingest(message(MELBOURNE))['instruction_id']
        theirs = self.p.ingest(message(RYTAS))['instruction_id']
        self.bet(theirs, status='PLACED_UNVERIFIED', account='acct-other')
        self.bet(ours, status='PLACED_UNVERIFIED', worker=None, account=None)      # unbound (no evidence)
        health = self.health()
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.assertFalse(self.p.final.schedule(self.gateway, health, True))       # neither is checked on this account
        self.bet(ours, status='PLACED_UNVERIFIED')                                 # bound to this phone's account
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.assertTrue(self.p.final.schedule(self.gateway, health, True))
        rec = self.recs()[0]
        self.assertEqual((rec['instruction_id'], rec['worker_id'], rec['account_fingerprint']), (ours, WORKER_ID, ACCOUNT_FINGERPRINT))

    def test_a_result_read_after_an_account_switch_is_not_used(self):
        iid = self.p.ingest(message(MELBOURNE))['instruction_id']
        self.bet(iid, status='PLACED_UNVERIFIED', bet_reference='JL1234567890')
        health = self.health()
        self.clock.advance(self.p.settings.reconcile_delay_seconds + 1)
        self.p.final.schedule(self.gateway, health, True)
        rid = self.recs()[0]['device_instruction_id']
        self.gateway.health_extra = {'account_fingerprint': 'acct-other'}        # the phone is now another account
        self.p.tick(self.gateway)
        self.gateway.results[rid] = dict(my_bets(rid, MELBOURNE_CARD), instruction_id=rid)
        self.p.final.poll(self.gateway)
        rec = self.recs()[0]
        self.assertEqual(rec['outcome'], 'FAILED')
        self.assertIn('account/worker changed', rec['detail'])
        with self.p.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM bets WHERE instruction_id=?', (iid,)).fetchone()[0], 'PLACED_UNVERIFIED')

    def test_settlement_one_card_one_bet_and_own_account_only(self):
        a = self.p.ingest(message(MELBOURNE))['instruction_id']
        b, c = self.clone(a, 'on-twin-b'), self.clone(a, 'on-twin-c')             # same terms, separate bets
        self.bet(a); self.bet(b); self.bet(c, account='acct-other')
        settled = [x for x in MELBOURNE_CARD if not x.startswith('Bet Ref')] + ['Won', 'Returns £2.20']
        with self.p.store.tx() as db:
            db.execute("INSERT INTO reconciliations(device_instruction_id,purpose,instruction_id,view,attempt,requested_at,worker_id,"
                       "account_fingerprint) VALUES ('st-x-1',?,NULL,'SETTLED',1,?,?,?)", (SETTLE, self.clock().isoformat(), WORKER_ID, ACCOUNT_FINGERPRINT))
        with self.p.store.connection() as db:
            rec = db.execute("SELECT * FROM reconciliations WHERE device_instruction_id='st-x-1'").fetchone()
        self.p.tick(self.gateway)
        self.p.final._apply_settlement(rec, my_bets('st-x-1', settled, view='SETTLED')['my_bets'])
        with self.p.store.connection() as db:
            status = dict(db.execute('SELECT instruction_id, status FROM bets').fetchall())
        self.assertEqual((status[a], status[b], status[c]), (OPEN, OPEN, OPEN))   # one card, two bets: neither settled
        self.assertEqual({x['instruction_id'] for x in self.audits('SETTLEMENT_AMBIGUOUS')}, {a, b})


class TelegramNeverDelaysDispatch(unittest.TestCase):
    """Measured: alert ingested -> DISPATCHED, with a Telegram bot that takes 1 s per message and a 6-message backlog."""

    def run_loops(self, concurrent):
        from core.status_notifier import AUTOMATIC_STATES, Notifier
        from tools.pipeline_service import dispatch_loop, telegram_loop

        class SlowSender:
            def send(self, text):
                time.sleep(1.0)

        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        clock = Clock(); gateway = FakeGateway(clock)
        p = pipeline(Path(tmp.name) / 'p.sqlite3', clock)
        notifier = Notifier(p.store, SlowSender(), AUTOMATIC_STATES, clock=clock)
        notifier.enqueue()
        with p.store.tx() as db:
            for i in range(6):
                db.execute('INSERT INTO notifications(instruction_id,state,text,created_at,next_attempt_at) VALUES (?,?,?,?,?)',
                           (f'backlog-{i}', 'X', 'x', clock().isoformat(), clock().isoformat()))

        async def scenario():
            stop = asyncio.Event()
            if concurrent:
                loops = [asyncio.create_task(dispatch_loop(p, gateway, 0.05, stop=stop)),
                         asyncio.create_task(telegram_loop(notifier, None, 0.05, {}, stop=stop))]
            else:   # the previous single cycle: tick, then enqueue + deliver everything, then sleep
                async def old_cycle():
                    while not stop.is_set():
                        await asyncio.to_thread(p.tick, gateway)
                        await asyncio.to_thread(notifier.enqueue)
                        await asyncio.to_thread(notifier.deliver)
                        await asyncio.sleep(0.05)
                loops = [asyncio.create_task(old_cycle())]
            await asyncio.sleep(0.2)                      # the loops are running; the backlog is being sent
            start = time.monotonic()
            iid = p.ingest(message(MELBOURNE))['instruction_id']
            while time.monotonic() - start < 20:
                with p.store.connection() as db:
                    if db.execute("SELECT 1 FROM transitions WHERE instruction_id=? AND to_state='DISPATCHED'", (iid,)).fetchone():
                        break
                await asyncio.sleep(0.01)
            elapsed = time.monotonic() - start
            stop.set()
            await asyncio.gather(*loops, return_exceptions=True)
            return elapsed

        return asyncio.run(scenario())

    def test_slow_telegram_does_not_delay_dispatch(self):
        before, after = self.run_loops(False), self.run_loops(True)
        print(f'\nALERT->DISPATCH with a 1 s/message bot and 6 queued messages: sequential {before:.2f}s, separate loops {after:.2f}s')
        self.assertGreater(before, 3.0)         # the old cycle waited for Telegram
        self.assertLess(after, 1.0)             # now bounded by the dispatcher tick alone


if __name__ == '__main__':
    unittest.main()
