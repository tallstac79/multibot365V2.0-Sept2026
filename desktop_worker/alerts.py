"""Telegram operator alerts for the desktop worker: once per blocking episode, plus a recovery message when it clears.

Hysteresis (29 Sep 2026): the RESUMED message is sent only after the worker has stayed unblocked for RESUME_QUIET_S; a
block that comes back within that window is the same episode (no second BLOCKED, no RESUMED/BLOCKED pair). Reality Check
auto-acknowledgement: every click the worker makes on 'Remain Logged In' is reported at once (acknowledged(): time plus
what the dialog showed), and if it cannot clear the dialog one BLOCKED message says so (ack_failed()). A message that
fails to send is kept in the persisted outbox and retried; it is never dropped.

Uses the repo's own sender (core.status_notifier.TelegramBotSender) and the pipeline's notification config
(.local/pipeline.json -> notifications.bot_token / chat_id). The token is never printed, logged or stored here; errors are
sanitised before they are kept. The episode state is persisted (.local/desktop_alerts.json) so a server restart during
one Reality Check does not send the alert again. Reality Check and login stay manual: this only tells David.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.local' / 'desktop_alerts.json'
PIPELINE_CONFIG = ROOT / '.local' / 'pipeline.json'
RETRY_S = 60                                        # a failed send is retried at most once a minute
UNKNOWN_AFTER_S = 300                               # SESSION_UNKNOWN alerts only once it has lasted 5 minutes
RESUME_QUIET_S = 45                                 # unblocked this long before RESUMED is sent (flapping = one episode)

MESSAGES = {
    'REALITY_CHECK': 'Bet365 Reality Check is open on the mini PC and the desktop worker did not acknowledge it automatically; '
                     'answer it manually to resume the desktop worker. The desktop worker (desktop-chrome) is blocked and not '
                     'routable meanwhile.',
    'LOGGED_OUT': "Bet365 is logged out in the desktop worker's Chrome on the mini PC; log in manually to resume the desktop worker. "
                  'It is blocked and not routable meanwhile; it never logs in itself.',
    'CHROME_DOWN': "The desktop worker's dedicated Chrome is down on the mini PC and could not be restarted automatically; start it "
                   '(py -3.11 -m desktop_worker.lifecycle) to resume the desktop worker. It is not routable meanwhile.',
    'SESSION_UNKNOWN': "The desktop worker cannot read the Bet365 session state in its Chrome on the mini PC (a login, verification or "
                       'other prompt may be open); check that window. It is not routable meanwhile.',
}
LABELS = {'REALITY_CHECK': 'Reality Check open', 'LOGGED_OUT': 'logged out', 'CHROME_DOWN': 'Chrome down', 'SESSION_UNKNOWN': 'session unknown'}


def _clock():
    return datetime.now().astimezone().strftime('%H:%M %Z').replace('GMT Summer Time', 'BST').replace('GMT Daylight Time', 'BST').replace('GMT Standard Time', 'GMT')


def sanitise(text, secrets=()):
    text = str(text)
    for s in secrets:
        if s:
            text = text.replace(s, '<redacted>')
    return re.sub(r'bot\d+:[A-Za-z0-9_-]+', 'bot<redacted>', text)[:300]


def pipeline_sender(config_path=PIPELINE_CONFIG):
    """(sender, secrets) from the pipeline's notification config, or (None, ()) when not configured/enabled."""
    try:
        cfg = json.loads(Path(config_path).read_text(encoding='utf-8-sig')).get('notifications') or {}
    except (OSError, ValueError):
        return None, ()
    token, chat = cfg.get('bot_token'), cfg.get('chat_id')
    if not (cfg.get('enabled') and token and chat):
        return None, ()
    from core.status_notifier import TelegramBotSender
    return TelegramBotSender(token, chat), (token,)


class Alerter:
    def __init__(self, sender=None, secrets=(), state_path=STATE, clock=time.time, prefix='[MultiBot365 desktop worker] '):
        self.sender, self.secrets, self.path, self.clock, self.prefix = sender, tuple(secrets), Path(state_path), clock, prefix

    @classmethod
    def from_config(cls, **kw):
        sender, secrets = pipeline_sender()
        return cls(sender, secrets, **kw)

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def _save(self, st):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(st, indent=1), encoding='utf-8')
        except OSError:
            pass

    def _send(self, text, st):
        if self.sender is None:
            st['last_error'] = 'Telegram not configured'
            return False
        try:
            self.sender.send(self.prefix + text)
            st.pop('last_error', None)
            return True
        except Exception as e:                      # never raise into the worker; never keep the token
            st['last_error'] = sanitise(f'{type(e).__name__}: {e}', self.secrets)
            st['last_failed_at'] = self.clock()
            return False

    def _flush(self, st, now):
        """Retry queued messages (auto-acknowledge reports) - at most once a minute after a failure."""
        box = st.get('outbox') or []
        if not box or now - st.get('last_failed_at', 0) < RETRY_S:
            return
        while box:
            if not self._send(box[0], st):
                break
            box.pop(0)
        st['outbox'] = box
        self._save(st)

    def update(self, blocked_reason, detail=None):
        """Feed the current blocked_reason (None = routable). Returns 'ALERT' / 'RECOVERY' when a message was sent now."""
        st = self._load()
        now = self.clock()
        self._flush(st, now)
        active, pending = st.get('active'), st.get('pending')
        reason = blocked_reason if blocked_reason in MESSAGES else None
        if reason == 'SESSION_UNKNOWN':             # startup / a transient unreadable frame is not worth a message
            first = st.get('unknown_since') if st.get('unknown_reason') == reason else None
            if first is None:
                st.update(unknown_since=now, unknown_reason=reason)
                self._save(st)
                return None
            if now - first < UNKNOWN_AFTER_S:
                return None
        else:
            if 'unknown_since' in st or 'unknown_reason' in st:
                st.pop('unknown_since', None); st.pop('unknown_reason', None)
                self._save(st)
        if reason and reason == active:
            if st.get('clear_since') is not None:   # blocked again inside the quiet window: the same episode
                st['clear_since'] = None
                self._save(st)
            return None
        if reason and reason != active:
            if pending == reason and now - st.get('last_failed_at', 0) < RETRY_S:
                return None
            extra = f' ({detail})' if detail else ''
            if self._send(f"BLOCKED ({LABELS[reason]}, since {_clock()}): {MESSAGES[reason]}{extra}", st):
                st.update(active=reason, since=now, pending=None, sent_at=now, clear_since=None, auto_ack=None, ack_failed=None)
                self._save(st)
                return 'ALERT'
            st['pending'] = reason
            self._save(st)
            return None
        if reason is None and active and blocked_reason is None:
            if st.get('clear_since') is None:
                st['clear_since'] = now
                self._save(st)
                return None
            if now - st['clear_since'] < RESUME_QUIET_S:
                return None
            if now - st.get('last_failed_at', 0) < RETRY_S and st.get('pending') == 'RECOVERY':
                return None
            how = ' after the automatic Reality Check acknowledgement' if st.get('auto_ack') and active == 'REALITY_CHECK' else ''
            if self._send(f"RESUMED ({_clock()}): the desktop worker is unblocked (was: {LABELS.get(active, active)}){how}; "
                          'the Bet365 session reads LOGGED_IN on consecutive clean screenshots and it is routable again.', st):
                st.update(active=None, pending=None, recovered_at=now, clear_since=None, auto_ack=None, ack_failed=None)
                self._save(st)
                return 'RECOVERY'
            st['pending'] = 'RECOVERY'
            self._save(st)
        return None

    def acknowledged(self, info, attempt, max_attempts):
        """Report ONE automatic 'Remain Logged In' click: time plus what the dialog showed. The Reality Check episode
        is then this message's (no separate BLOCKED unless the click does not clear it: ack_failed)."""
        st = self._load()
        text = (f"REALITY CHECK AUTO-ACKNOWLEDGED ({_clock()}, click {attempt}/{max_attempts}): Bet365's Reality Check "
                f"opened in the desktop worker's Chrome; " + '; '.join(info) + ". The worker clicked 'Remain Logged In' once "
                "(never 'Log out' or any other option). The desktop stays blocked (not routable) until consecutive clean "
                'screenshots show the dialog gone.')
        if not self._send(text, st):
            st.setdefault('outbox', []).append(text)
        st.update(active='REALITY_CHECK', since=st.get('since') if st.get('active') == 'REALITY_CHECK' else self.clock(),
                  pending=None, clear_since=None, auto_ack=True)
        self._save(st)
        return text

    def ack_failed(self, detail):
        """One BLOCKED message when the worker could not clear the Reality Check itself (once per episode)."""
        st = self._load()
        if st.get('ack_failed') and st.get('active') == 'REALITY_CHECK':
            return None
        text = (f"BLOCKED ({LABELS['REALITY_CHECK']}, since {_clock()}): the desktop worker did not clear Bet365's Reality Check "
                f"automatically ({detail}); answer it manually on the mini PC. The desktop worker is blocked and not routable meanwhile.")
        if not self._send(text, st):
            st.setdefault('outbox', []).append(text)
        st.update(active='REALITY_CHECK', since=st.get('since') or self.clock(), pending=None, clear_since=None, ack_failed=True)
        self._save(st)
        return text

    def test(self):
        """One labelled TEST message in the real format (used once for David to see it)."""
        st = self._load()
        ok = self._send(f"TEST ONLY - no action needed. Example of the blocking alert format: BLOCKED (Reality Check open, since "
                        f"{_clock()}): {MESSAGES['REALITY_CHECK']}", st)
        return ok, st.get('last_error')


class NullAlerter:
    def update(self, blocked_reason, detail=None):
        return None

    def acknowledged(self, info, attempt, max_attempts):
        return None

    def ack_failed(self, detail):
        return None


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--test']:
        ok, err = Alerter.from_config().test()
        print('TEST alert sent' if ok else f'TEST alert failed: {err}')
