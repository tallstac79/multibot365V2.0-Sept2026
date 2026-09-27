"""Operator commands over the notification bot: /approve, /reject, /stop, /resume, /status.

A command is obeyed only if it comes from the configured chat_id AND from one of the
configured operator user IDs (notifications.allowed_user_ids). Other members of the group,
other chats and anonymous-admin posts are audited and ignored. With no user IDs configured,
every command is refused (fail closed). The update offset is stored in the database so a restart never re-applies an old
command. Commands act through core.final_action, which enforces every rule (approval
window, limits, kill switch) regardless of where the command came from.
"""
import json
import urllib.parse
import urllib.request

OFFSET_KEY = 'telegram_update_offset'
MAX_COMMAND_AGE_SECONDS = 300
HELP = ('Commands:\n/approve - place the awaiting bet (/approve <id> when several wait)\n/reject - decline it\n'
        '/stop - kill switch: stop all dispatch now\n/resume - allow dispatch again\n/status - current state')


class BotApi:
    def __init__(self, bot_token, timeout=10):
        self.base = f'https://api.telegram.org/bot{bot_token}/'
        self.timeout = timeout

    def call(self, method, **params):
        body = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data=body, timeout=self.timeout) as response:
            reply = json.loads(response.read())
        if not reply.get('ok'):
            raise RuntimeError(f"Telegram API error: {reply.get('description')}")
        return reply['result']

    def get_updates(self, offset):
        return self.call('getUpdates', offset=offset, timeout=0, allowed_updates=json.dumps(['message']))

    def send(self, chat_id, text):
        self.call('sendMessage', chat_id=chat_id, text=text, disable_web_page_preview='true')


class CommandHandler:
    def __init__(self, pipeline, api, chat_id, allowed_user_ids=()):
        self.p, self.api, self.chat_id = pipeline, api, str(chat_id)
        self.allowed = {str(u).strip() for u in (allowed_user_ids or ()) if str(u).strip()}

    def poll(self):
        """Fetch and apply new commands. Returns the number of commands handled."""
        stored = self.p.store.control(OFFSET_KEY)
        offset = int(stored or 0)
        updates = self.api.get_updates(offset + 1 if offset else 0)
        if stored is None:
            # First run: anything already waiting predates this service. Consume, never act.
            if updates:
                offset = max(int(u.get('update_id', 0)) for u in updates)
            self.p.store.set_control(OFFSET_KEY, offset, by='telegram-baseline')
            return 0
        handled = 0
        now = self.p.clock().timestamp()
        for update in updates:
            offset = max(offset, int(update.get('update_id', 0)))
            message = update.get('message') or {}
            chat = str((message.get('chat') or {}).get('id', ''))
            user = str((message.get('from') or {}).get('id', ''))
            text = (message.get('text') or '').strip()
            # Store the offset before acting so a crash never replays a command.
            self.p.store.set_control(OFFSET_KEY, offset, by='telegram')
            if now - float(message.get('date', 0)) > MAX_COMMAND_AGE_SECONDS:
                continue  # stale command (e.g. sent while the service was down): never act on it
            if not text.startswith('/'):
                continue
            if chat != self.chat_id or user not in self.allowed:
                # Both must match: the operator's own account, in the configured group.
                reason = 'chat' if chat != self.chat_id else 'user' if self.allowed else 'no operator configured'
                with self.p.store.tx() as db:
                    self.p.store.audit(db, 'UNAUTHORISED_COMMAND', dict(chat=chat, user=user, reason=reason, text=text[:80]))
                continue
            reply = self.handle(text, by=f'telegram:{chat}:{user}')
            handled += 1
            try:
                self.api.send(self.chat_id, reply)
            except Exception:
                pass  # the action itself is already stored; a lost reply changes nothing
        if updates:
            self.p.store.set_control(OFFSET_KEY, offset, by='telegram')
        return handled

    def handle(self, text, by):
        parts = text.split()
        command = parts[0].split('@')[0].lower()
        argument = parts[1] if len(parts) > 1 else ''
        try:
            if command == '/approve':
                instruction_id = self.p.final.approve(argument or self.pending_reference(), by)
                return f'APPROVED {instruction_id}. The phone will place it next.'
            if command == '/reject':
                instruction_id = self.p.final.reject(argument or self.pending_reference(), by)
                return f'REJECTED {instruction_id}. Nothing will be placed.'
            if command == '/stop':
                self.p.final.set_paused(True, by)
                return 'STOPPED. Nothing will be dispatched until /resume. Pending approvals were cancelled.'
            if command == '/resume':
                self.p.final.set_paused(False, by)
                return 'RESUMED. Dispatch rules apply again.'
            if command == '/status':
                return self.status()
            return HELP
        except (LookupError, PermissionError) as error:
            return f'Not done: {error}'

    def pending_reference(self):
        """The one bet awaiting approval, so a bare /approve or /reject needs no id (the phone holds at most one
        verified slip at a time). With none, or with several, the operator must name the bet."""
        with self.p.store.connection() as db:
            waiting = [r['instruction_id'] for r in db.execute(
                "SELECT instruction_id FROM instructions WHERE state='AWAITING_APPROVAL' ORDER BY approval_requested_at")]
        if len(waiting) == 1:
            return waiting[0]
        if not waiting:
            raise LookupError('nothing is awaiting approval')
        raise LookupError('several bets are awaiting approval, say which: ' + ', '.join(w[:10] for w in waiting))

    def status(self):
        s = self.p.settings
        with self.p.store.connection() as db:
            today = self.p.final.exposure_today(db)
            waiting = [r['instruction_id'][:10] for r in db.execute(
                "SELECT instruction_id FROM instructions WHERE state='AWAITING_APPROVAL'")]
            unknown = db.execute("SELECT COUNT(*) FROM instructions WHERE state='PLACEMENT_UNKNOWN'").fetchone()[0]
        return '\n'.join([
            'MultiBot365 status',
            f"Dispatch: {'ON' if s.dispatch_enabled else 'OFF'} | Final action: {'ON' if s.final_action_enabled else 'OFF'}"
            f" | {'PAUSED' if self.p.final.paused() else 'running'} | Approval: {s.approval_mode.upper()}",
            f"Today: {today['bets']} bets, stake {today['stake']}, loss {today['loss']} "
            f"(limits {s.max_bets_per_day if s.max_bets_per_day is not None else 'no'} bet cap / {s.max_daily_stake if s.max_daily_stake is not None else 'no'} stake cap / {s.max_daily_loss} loss)",
            f"Awaiting approval: {', '.join(waiting) or 'none'}", f'Placement uncertain: {unknown}'])
