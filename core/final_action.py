"""Final action (Place Bet): approval, safety limits, kill switch and My Bets reconciliation.

Safety model
* Two independent switches: Settings.dispatch_enabled (anything reaches the phone) and
  Settings.final_action_enabled (the phone may tap Place Bet). Both default to False.
* Kill switch: controls.paused (Telegram /stop, dashboard, CLI) blocks all dispatch at once.
* Every final action needs an approval: an operator APPROVE (default), or auto-approval
  only when Settings.auto_approve is on AND every limit below passes.
* Limits: per-bet stake cap, bets per day, stake per day, loss per day (settled bets).
  Counted over the UTC day, including placements whose outcome is still unknown.
* After a tap, nothing is ever re-tapped. Uncertain outcomes are PLACEMENT_UNKNOWN and are
  ended only by a My Bets check (FOUND -> COMPLETED, NOT_FOUND twice -> NOT_PLACED).
  Receipts and claimed rejections are also verified against My Bets.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from core import bet_matching
from core.lifecycle import State
from core.pipeline_store import iso

PAUSED = 'paused'
# bets.status values
PLACED_UNVERIFIED, OPEN, UNKNOWN, NOT_PLACED_CLAIMED, NOT_PLACED = (
    'PLACED_UNVERIFIED', 'OPEN', 'UNKNOWN', 'NOT_PLACED_CLAIMED', 'NOT_PLACED')
DISCREPANCY, SETTLED_STATES = 'DISCREPANCY', ('WON', 'LOST', 'VOID', 'CASHED_OUT', 'RETURNED')
VERIFY, SETTLE = 'VERIFY_PLACEMENT', 'SETTLEMENT'


def money(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


class FinalAction:
    def __init__(self, pipeline):
        self.p = pipeline

    @property
    def s(self):
        return self.p.settings

    # ------------------------------------------------------------------ switches
    def paused(self):
        return bool(self.p.store.control(PAUSED, False))

    def set_paused(self, value, by):
        self.p.store.set_control(PAUSED, bool(value), by=by)
        if value:
            # Cancel anything approved or awaiting approval; nothing already on the device is touched.
            with self.p.store.tx() as db:
                for row in db.execute("SELECT instruction_id FROM instructions WHERE state IN ('AWAITING_APPROVAL','APPROVED')"):
                    self.p.store.transition(db, row['instruction_id'], State.REJECTED, actor=by,
                                            reason='KILL_SWITCH: final action paused by operator')

    def enabled(self):
        return self.s.final_action_enabled and not self.paused()

    # ------------------------------------------------------------------ limits
    def exposure_today(self, db):
        day = self.p.clock().astimezone(timezone.utc).strftime('%Y-%m-%d')
        rows = db.execute("SELECT i.state, i.stake, b.status, b.stake AS bet_stake, b.returns FROM instructions i "
                          "LEFT JOIN bets b ON b.instruction_id=i.instruction_id WHERE i.execution_mode='dispatch' "
                          "AND substr(i.dispatched_at,1,10)=?", (day,)).fetchall()
        count, stake, loss = 0, Decimal(0), Decimal(0)
        in_flight = {State.APPROVED.value, State.DISPATCHED.value, State.DEVICE_ACTIVE.value, State.PLACEMENT_UNKNOWN.value}
        for r in rows:
            if r['status'] is None and r['state'] not in in_flight:
                continue  # ended before any tap (no bets row): nothing was staked
            if r['status'] in (NOT_PLACED, NOT_PLACED_CLAIMED):
                continue  # device or My Bets showed the bet was refused
            count += 1
            stake += money(r['bet_stake'] or r['stake']) or Decimal(0)
            if r['status'] == 'LOST':
                loss += money(r['bet_stake'] or r['stake']) or Decimal(0)
            elif r['status'] in ('WON', 'CASHED_OUT', 'VOID', 'RETURNED') and money(r['returns']) is not None:
                loss -= money(r['returns']) - (money(r['bet_stake'] or r['stake']) or Decimal(0))
        return dict(day=day, bets=count, stake=stake, loss=max(loss, Decimal(0)))

    def limit_breach(self, db, row):
        stake = money(row['stake'])
        if stake is None or stake <= 0:
            return 'LIMIT: stake missing or invalid'
        if stake > money(self.s.max_stake_per_bet):
            return f'LIMIT: stake {stake} above per-bet cap {self.s.max_stake_per_bet}'
        today = self.exposure_today(db)
        if today['bets'] + 1 > self.s.max_bets_per_day:
            return f"LIMIT: {today['bets']} bets already today (max {self.s.max_bets_per_day})"
        if today['stake'] + stake > money(self.s.max_daily_stake):
            return f"LIMIT: daily stake {today['stake'] + stake} would exceed {self.s.max_daily_stake}"
        if today['loss'] >= money(self.s.max_daily_loss):
            return f"LIMIT: daily loss {today['loss']} reached {self.s.max_daily_loss}"
        return None

    # ------------------------------------------------------------------ approval
    def on_queued(self, db, row):
        """Called by the dispatcher for a QUEUED row that passed every pre-dispatch check.

        Verify first: the row is sent to the phone as a READY run (fixture, market, side, line,
        price, £ stake + To Return, single selection; nothing placed, slip cleared). Only a
        device-verified READY result asks for approval (on_verified). Returns True if the READY
        verification may be dispatched now."""
        breach = self.limit_breach(db, row)
        if breach:
            self.p.store.transition(db, row['instruction_id'], State.REJECTED, actor='limits', reason=breach)
            return False
        return True

    def on_verified(self, db, row):
        """READY (device-verified) -> AWAITING_APPROVAL, or APPROVED under auto-approval."""
        breach = self.limit_breach(db, row)
        if breach:
            self.p.store.transition(db, row['instruction_id'], State.REJECTED, actor='limits', reason=breach)
            return
        if self.s.auto_approve:
            self.p.store.transition(db, row['instruction_id'], State.APPROVED, actor='auto-approval',
                                    reason='Auto-approved within configured limits', approved_by='auto')
            return True
        self.p.store.transition(db, row['instruction_id'], State.AWAITING_APPROVAL, actor='dispatcher',
                                reason=f'Device verified; operator approval required within {self.s.approval_timeout_seconds}s')

    def resolve(self, db, reference):
        """Instruction by full ID or unique prefix (Telegram short IDs)."""
        rows = db.execute('SELECT * FROM instructions WHERE instruction_id=? OR instruction_id LIKE ?',
                          (reference, f'{reference}%')).fetchall()
        exact = [r for r in rows if r['instruction_id'] == reference]
        if exact:
            return exact[0]
        if len(rows) == 1:
            return rows[0]
        raise LookupError(f'{len(rows)} instructions match {reference!r}')

    def approve(self, reference, by):
        with self.p.store.tx() as db:
            row = self.resolve(db, reference)
            if not self.enabled():
                raise PermissionError('Final action is disabled or paused')
            if row['state'] != State.AWAITING_APPROVAL.value:
                raise PermissionError(f"{row['instruction_id']} is {row['state']}, not AWAITING_APPROVAL")
            age = (self.p.clock() - datetime.fromisoformat(row['approval_requested_at'])).total_seconds()
            if age > self.s.approval_timeout_seconds:
                raise PermissionError(f'Approval window expired ({int(age)}s)')
            breach = self.limit_breach(db, row)
            if breach:
                raise PermissionError(breach)
            self.p.store.transition(db, row['instruction_id'], State.APPROVED, actor=by, reason=f'Approved by {by}',
                                    approved_by=by)
            return row['instruction_id']

    def reject(self, reference, by):
        with self.p.store.tx() as db:
            row = self.resolve(db, reference)
            if row['state'] not in (State.AWAITING_APPROVAL.value, State.APPROVED.value):
                raise PermissionError(f"{row['instruction_id']} is {row['state']}; only pending approvals can be rejected")
            self.p.store.transition(db, row['instruction_id'], State.REJECTED, actor=by, reason=f'Rejected by {by}')
            return row['instruction_id']

    def expire_approvals(self):
        for row in self.p.store.instructions_in([State.AWAITING_APPROVAL]):
            age = (self.p.clock() - datetime.fromisoformat(row['approval_requested_at'])).total_seconds()
            if age > self.s.approval_timeout_seconds:
                with self.p.store.tx() as db:
                    self.p.store.transition(db, row['instruction_id'], State.STALE, actor='dispatcher',
                                            reason=f'Approval not received within {self.s.approval_timeout_seconds}s')

    # ------------------------------------------------------------------ outcomes -> bets
    def record_outcome(self, db, row, state, result):
        """Create/update the bets row for a final-action instruction after its device result."""
        placement = (result or {}).get('placement') if isinstance((result or {}).get('placement'), dict) else {}
        observed = (result or {}).get('pretap') or (result or {}).get('selection') or {}
        actual = placement.get('actual_terms') or {}
        common = dict(fixture=row['fixture'], market=row['market'], selection=row['selection'], line=row['line'],
                      stake=placement.get('stake') or row['stake'], odds=placement.get('odds') or row['observed_price']
                      or row['alert_price'], potential_return=placement.get('potential_return'),
                      bet_reference=placement.get('bet_reference'), placed_at=iso(self.p.clock()),
                      evidence=dict(frames=placement.get('frames'), receipt_lines=placement.get('receipt_lines')))
        common.update(requested_line=row['line'], requested_odds=row['alert_price'], requested_stake=row['stake'],
                      verified_line=observed.get('line'), verified_odds=observed.get('price'), verified_stake=observed.get('stake'),
                      actual_line=actual.get('line'), actual_odds=actual.get('odds'), actual_stake=actual.get('stake'),
                      terms_provenance=json.dumps(dict(requested='alert/instruction', verified='phone pre-tap observation',
                          actual='receipt fields only; missing values unknown', legacy_display='may contain requested/pre-tap fallback')))
        if state == State.COMPLETED:
            status = PLACED_UNVERIFIED
        elif state == State.PLACEMENT_UNKNOWN:
            status = UNKNOWN
        else:
            status = NOT_PLACED_CLAIMED
        self.p.store.upsert_bet(db, row['instruction_id'], status=status, source='device', **common)
        if common['bet_reference']:
            self.p.store.update_fields(db, row['instruction_id'], bet_reference=common['bet_reference'])

    # ------------------------------------------------------------------ reconciliation
    def device_busy(self):
        with self.p.store.connection() as db:
            return db.execute('SELECT 1 FROM reconciliations WHERE completed_at IS NULL').fetchone() is not None

    def _device_id(self, instruction_id, purpose, attempt):
        digest = hashlib.sha256(f'{purpose}|{instruction_id}'.encode()).hexdigest()[:16]
        return f"{'rc' if purpose == VERIFY else 'st'}-{digest}-{attempt}"

    def payload(self, device_instruction_id, view):
        return dict(instruction_id=device_instruction_id, action='MY_BETS', adapter=self.s.adapter, scenario='live',
                    view=view, timeout_ms=self.s.reconcile_timeout_ms)

    def next_reconciliation(self, urgent_only=False):
        """(purpose, instruction_id or None, view, attempt) that is due now, most urgent first.

        urgent_only (A2): live placement work is waiting, so only a PLACEMENT_UNKNOWN resolution (bet status
        UNKNOWN) may take the phone; verification of claimed placements and settlement wait."""
        now = self.p.clock()
        with self.p.store.connection() as db:
            candidates = db.execute(
                "SELECT b.*, (SELECT COUNT(*) FROM reconciliations r WHERE r.instruction_id=b.instruction_id "
                "AND r.purpose=?) AS attempts, (SELECT MAX(requested_at) FROM reconciliations r WHERE "
                "r.instruction_id=b.instruction_id AND r.purpose=?) AS last_at FROM bets b WHERE b.status IN (?,?,?) "
                "AND b.verified_at IS NULL ORDER BY CASE b.status WHEN 'UNKNOWN' THEN 0 WHEN 'PLACED_UNVERIFIED' THEN 1 "
                "ELSE 2 END, b.id", (VERIFY, VERIFY, UNKNOWN, PLACED_UNVERIFIED, NOT_PLACED_CLAIMED)).fetchall()
            for bet in candidates:
                if bet['attempts'] >= self.s.reconcile_max_attempts:
                    continue
                if urgent_only and bet['status'] != UNKNOWN:
                    continue
                anchor = datetime.fromisoformat(bet['last_at'] or bet['placed_at'])
                wait = self.s.reconcile_delay_seconds * (1 if bet['attempts'] == 0 else 2)
                if (now - anchor).total_seconds() >= wait:
                    return VERIFY, bet['instruction_id'], 'OPEN', bet['attempts'] + 1
            if not urgent_only and db.execute("SELECT 1 FROM bets WHERE status=?", (OPEN,)).fetchone():
                last = db.execute("SELECT MAX(requested_at) FROM reconciliations WHERE purpose=?", (SETTLE,)).fetchone()[0]
                if last is None or (now - datetime.fromisoformat(last)).total_seconds() >= self.s.settlement_poll_minutes * 60:
                    count = db.execute("SELECT COUNT(*) FROM reconciliations WHERE purpose=?", (SETTLE,)).fetchone()[0]
                    return SETTLE, None, 'SETTLED', count + 1
        return None

    def schedule(self, gateway, health, device_free, urgent_only=False):
        """Submit one due My Bets check if the phone is free. Returns True if submitted."""
        if not device_free or health is None or health.get('healthy') is not True or health.get('current_instruction'):
            return False
        due = self.next_reconciliation(urgent_only)
        if due is None:
            return False
        purpose, instruction_id, view, attempt = due
        device_id = self._device_id(instruction_id or 'settlement', purpose, attempt)
        payload = self.payload(device_id, view)
        with self.p.store.tx() as db:
            db.execute('INSERT OR IGNORE INTO reconciliations(device_instruction_id,purpose,instruction_id,view,attempt,'
                       'requested_at) VALUES (?,?,?,?,?,?)', (device_id, purpose, instruction_id, view, attempt,
                                                               iso(self.p.clock())))
        try:
            gateway.submit(payload)
        except Exception as error:
            with self.p.store.tx() as db:
                self.p.store.audit(db, 'RECONCILE_SUBMIT_UNCERTAIN', dict(error=str(error)[:300], id=device_id), instruction_id)
        with self.p.store.tx() as db:
            db.execute('UPDATE reconciliations SET submitted_at=? WHERE device_instruction_id=?', (iso(self.p.clock()), device_id))
        return True

    def poll(self, gateway):
        with self.p.store.connection() as db:
            open_rows = db.execute('SELECT * FROM reconciliations WHERE completed_at IS NULL').fetchall()
        for rec in open_rows:
            try:
                result = gateway.result(rec['device_instruction_id'])
            except Exception as error:
                result = None
                with self.p.store.tx() as db:
                    self.p.store.audit(db, 'RECONCILE_POLL_FAILED', dict(error=str(error)[:300]), rec['instruction_id'])
            if isinstance(result, dict) and result.get('_pending'):
                continue
            if result is None:
                age = (self.p.clock() - datetime.fromisoformat(rec['requested_at'])).total_seconds()
                if age > self.s.reconcile_timeout_ms / 1000 + 60:
                    self._complete(rec, 'FAILED', dict(error='No My Bets result before timeout'))
                continue
            self._apply(rec, result)

    def _complete(self, rec, outcome, detail, db=None):
        def write(tx):
            tx.execute('UPDATE reconciliations SET completed_at=?, outcome=?, detail=? WHERE id=? AND completed_at IS NULL',
                       (iso(self.p.clock()), outcome, json.dumps(detail, default=str), rec['id']))
        if db is not None:
            write(db)  # caller runs _after_failed_verification after its transaction commits
            return
        with self.p.store.tx() as tx:
            write(tx)
        if outcome == 'FAILED' and rec['purpose'] == VERIFY:
            self._after_failed_verification(rec)

    def _after_failed_verification(self, rec):
        with self.p.store.tx() as db:
            attempts = db.execute('SELECT COUNT(*) FROM reconciliations WHERE instruction_id=? AND purpose=?',
                                  (rec['instruction_id'], VERIFY)).fetchone()[0]
            if attempts < self.s.reconcile_max_attempts:
                return
            bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (rec['instruction_id'],)).fetchone()
            row = self.p.store.get_instruction(db, rec['instruction_id'])
            if bet and bet['status'] == UNKNOWN and row['state'] == State.PLACEMENT_UNKNOWN.value:
                self.p.store.transition(db, row['instruction_id'], State.UNKNOWN, actor='reconciler',
                                        reason='MANUAL_CHECK_REQUIRED: tap may have placed a bet; My Bets could not be '
                                               f'read after {attempts} attempts. Never re-tapped.')
                self.p.store.audit(db, 'MANUAL_CHECK_REQUIRED', dict(bet=dict(bet)), row['instruction_id'])

    def _apply(self, rec, result):
        my_bets = result.get('my_bets') if isinstance(result, dict) else None
        if not isinstance(result, dict) or result.get('status') != 'PASS' or not isinstance(my_bets, dict):
            self._complete(rec, 'FAILED', dict(result=result))
            return
        if rec['purpose'] == SETTLE:
            self._apply_settlement(rec, my_bets)
            return
        if self._apply_verification(rec, my_bets) == 'FAILED':
            self._after_failed_verification(rec)

    def _apply_verification(self, rec, my_bets):
        with self.p.store.tx() as db:
            row = self.p.store.get_instruction(db, rec['instruction_id'])
            bet = db.execute('SELECT * FROM bets WHERE instruction_id=?', (rec['instruction_id'],)).fetchone()
            try:
                found = bet_matching.match(dict(dict(row), odds=bet['odds'], stake=bet['stake']), my_bets)
            except ValueError as error:
                self._complete(rec, 'FAILED', dict(error=str(error)), db)
                return 'FAILED'
            detail = dict(match=found, frames=my_bets.get('frames'))
            now = iso(self.p.clock())
            if found['confidence'] == 'INCONCLUSIVE' or (not found['found'] and my_bets.get('coverage_complete') is not True):
                # A collapsed card could be this bet: neither found nor absent. Retry; never infer NOT_PLACED.
                self._complete(rec, 'FAILED', dict(detail, reason='card identity or complete account coverage unproven; absence cannot be inferred'), db)
                return 'FAILED'
            if found['found']:
                self._complete(rec, 'FOUND', detail, db)
                self.p.store.upsert_bet(db, row['instruction_id'], status=OPEN, verified_at=now,
                                        bet_reference=bet['bet_reference'] or found['bet_reference'])
                if row['state'] == State.PLACEMENT_UNKNOWN.value:
                    self.p.store.transition(db, row['instruction_id'], State.COMPLETED, actor='reconciler',
                                            reason='PLACED: confirmed in My Bets after uncertain outcome')
                elif bet['status'] == NOT_PLACED_CLAIMED:
                    self.p.store.upsert_bet(db, row['instruction_id'], status=DISCREPANCY)
                    self.p.store.audit(db, 'PLACEMENT_DISCREPANCY', dict(claimed=row['state'], found=found),
                                       row['instruction_id'])
                return 'FOUND'
            self._complete(rec, 'NOT_FOUND', detail, db)
            not_found = db.execute("SELECT COUNT(*) FROM reconciliations WHERE instruction_id=? AND purpose=? AND "
                                   "outcome='NOT_FOUND'", (row['instruction_id'], VERIFY)).fetchone()[0]
            if bet['status'] == NOT_PLACED_CLAIMED:
                self.p.store.upsert_bet(db, row['instruction_id'], status=NOT_PLACED, verified_at=now)
            elif bet['status'] == UNKNOWN and not_found >= 2:
                self.p.store.upsert_bet(db, row['instruction_id'], status=NOT_PLACED, verified_at=now)
                self.p.store.transition(db, row['instruction_id'], State.NOT_PLACED, actor='reconciler',
                                        reason=f'NOT_PLACED: absent from My Bets in {not_found} checks. Never re-tapped.')
            elif bet['status'] == PLACED_UNVERIFIED and not_found >= self.s.reconcile_max_attempts:
                self.p.store.upsert_bet(db, row['instruction_id'], status=DISCREPANCY)
                self.p.store.audit(db, 'PLACEMENT_DISCREPANCY', dict(claimed='PLACED receipt', found=found),
                                   row['instruction_id'])
            return 'NOT_FOUND'

    def _apply_settlement(self, rec, my_bets):
        try:
            bet_matching.lines_of(my_bets)
            with self.p.store.connection() as db:
                for bet in db.execute('SELECT b.*, i.home, i.away FROM bets b JOIN instructions i USING(instruction_id) '
                                      'WHERE b.status=? LIMIT 1', (OPEN,)).fetchall():
                    bet_matching.match(dict(bet), my_bets)      # raises if the Settled view is not confirmed
        except ValueError as error:
            # Unconfirmed/unreadable Settled view: this check FAILED (retried next cycle). It must complete,
            # or the open reconciliation would block every later dispatch (real: 2026-09-24 21:22).
            self._complete(rec, 'FAILED', dict(error=str(error)[:200]))
            return
        with self.p.store.tx() as db:
            updated = []
            for bet in db.execute('SELECT b.*, i.home, i.away FROM bets b JOIN instructions i USING(instruction_id) '
                                  'WHERE b.status=?', (OPEN,)).fetchall():
                found = bet_matching.match(dict(bet), my_bets)
                if found['found'] and found['status'] in SETTLED_STATES:
                    self.p.store.upsert_bet(db, bet['instruction_id'], status=found['status'], returns=found['returns'],
                                            settled_at=iso(self.p.clock()))
                    updated.append(dict(instruction_id=bet['instruction_id'], status=found['status'], returns=found['returns']))
            self._complete(rec, 'SETTLED' if updated else 'NO_CHANGE', dict(updated=updated), db)
