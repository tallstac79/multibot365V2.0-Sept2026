"""Python side of the decision bridge (desktop_worker/jvm/DesktopDecisions.java).

The desktop worker makes no identity, competition, kick-off, line-band or tolerance decision of its own: it asks the
phone's own Java classes, compiled unchanged from android/Bet365Agent (build(): javac + jar), through one long-lived
JVM process. If the bridge is missing or answers with an error, the caller fails closed.
"""
import json
import os
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'android' / 'Bet365Agent' / 'app' / 'src' / 'main' / 'java' / 'com' / 'bet365agent'
BRIDGE = Path(__file__).resolve().parent / 'jvm' / 'DesktopDecisions.java'
BUILD = ROOT / '.local' / 'desktop-decisions'
JAR = BUILD / 'decisions.jar'
JDK = Path(os.environ.get('JAVA_HOME') or r'C:\Program Files\Microsoft\jdk-17.0.20.101-hotspot')
ANDROID_JAR = Path(os.environ.get('LOCALAPPDATA', '')) / 'Android' / 'Sdk' / 'platforms' / 'android-34' / 'android.jar'
# The phone classes the decisions come from (pure Java; org.json only at compile time, from android.jar's stubs).
PHONE_CLASSES = ('EventIdentity', 'EventPage', 'EventHeader', 'CompetitionStructure', 'FootballLineCheck', 'ExecutionTolerance',
                 'GameLinesParser', 'TeamAliases', 'HeldSlipIdentity', 'HeldSlipQuote', 'FootballMarkets', 'OcrText')
LIST, KV = '\u001f', '\u001e'


def build():
    """Compile the phone's decision classes + the bridge into .local/desktop-decisions/decisions.jar."""
    classes = BUILD / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    files = [str(SOURCES / f'{c}.java') for c in PHONE_CLASSES] + [str(BRIDGE)]
    subprocess.run([str(JDK / 'bin' / 'javac'), '-encoding', 'UTF-8', '-nowarn', '-d', str(classes), '-cp', str(ANDROID_JAR), *files],
                   check=True, capture_output=True)
    subprocess.run([str(JDK / 'bin' / 'jar'), 'cf', str(JAR), '-C', str(classes), '.'], check=True, capture_output=True)
    return JAR


def stale():
    """The jar is missing or older than any phone source or the bridge: rebuild so the decisions are the current code."""
    if not JAR.exists():
        return True
    built = JAR.stat().st_mtime
    return any(p.stat().st_mtime > built for p in [SOURCES / f'{c}.java' for c in PHONE_CLASSES] + [BRIDGE])


def _enc(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, dict):
        return LIST.join(f'{k}{KV}{v}' for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return LIST.join(KV.join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v) for v in value)
    return str(value).replace('\t', ' ').replace('\n', ' ')


class Decisions:
    def __init__(self):
        if stale():
            build()
        # android.jar supplies org.json's classes at runtime too (only its stubs; the bridge never calls org.json).
        self.proc = subprocess.Popen([str(JDK / 'bin' / 'java'), '-cp', f'{JAR}{os.pathsep}{ANDROID_JAR}', 'com.bet365agent.DesktopDecisions'],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding='utf-8', bufsize=1)
        self.lock = threading.Lock()
        if self.call('ping') != 'pong':
            raise RuntimeError('decision bridge did not answer')

    def call(self, op, *args):
        line = '\t'.join([op, *(_enc(a) for a in args)])
        with self.lock:
            self.proc.stdin.write(line + '\n'); self.proc.stdin.flush()
            reply = json.loads(self.proc.stdout.readline())
        if not reply.get('ok'):
            raise RuntimeError(f"decision bridge {op}: {reply.get('error')}")
        return reply.get('value')

    # --- the phone's decisions
    def decide(self, header, sport, home, away, kickoff_utc, competition, country, anchored, women, aliases=None):
        return self.call('decide', list(header), sport, home, away, kickoff_utc or '', competition or '', country or '', anchored, women, aliases or {})

    def uk(self, kickoff_utc):
        return self.call('uk', kickoff_utc)

    def competition_key(self, text):
        return self.call('competition_key', text)

    def nearest(self, quotes, market, side, requested, allowance):
        return self.call('nearest', [(q['market'], q['side'], q['line'] or '', q['price']) for q in quotes], market, side, requested or '', allowance or '')

    def refusal(self, quotes, market, side, requested, allowance):
        return self.call('refusal', [(q['market'], q['side'], q['line'] or '', q['price']) for q in quotes], market, side, requested or '', allowance or '')

    def fresh(self, market, side, requested_line, live_line, live_price, allowance, minimum):
        return self.call('fresh', market, side, requested_line or '', live_line or '', live_price, allowance or '', minimum)

    def line_ok(self, sport, market, side, requested, live, maximum):
        return self.call('line', sport, market, side, requested, live, maximum)

    def price_ok(self, live, minimum):
        return self.call('price', live, minimum)

    def norm_line(self, raw):
        """The phone's FootballMarkets.normaliseLine: "+0.5", "0" -> "0.0", "2.5,3.0" -> "2.75"; None if not a line."""
        return self.call('norm_line', raw)

    def same_slip_name(self, held, slip):
        return self.call('same_slip_name', held, slip)

    def close(self):
        try:
            self.proc.stdin.close(); self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
