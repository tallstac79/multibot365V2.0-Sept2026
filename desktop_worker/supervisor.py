"""Persistent supervisor for the desktop worker server (desktop_worker.server), owned by no app.

Run by the Windows Scheduled Task 'MultiBot365DesktopWorker' (at log on of WINDOWS11, interactive session, restart on
failure, plus a 5-minute repeating trigger that is ignored while an instance runs). The supervisor:
  * holds a single-instance lock (.local/desktop_supervisor.lock), so a second copy exits at once;
  * starts `python -m desktop_worker.server` (no console window), stdout/stderr appended to logs/desktop_worker_server.log;
  * restarts it when it exits, with backoff (2 s doubling to 60 s; reset after 5 minutes of uptime);
  * never starts a second server while port 8768 is already served (e.g. a server left over from an earlier supervisor):
    it waits and re-checks instead;
  * stops cleanly (terminating its server) when .local/desktop_supervisor.stop appears.
Chrome is NOT a child of the server or the supervisor (it is launched through WMI), so a server restart leaves it running.

    py -3.11 -m desktop_worker.supervisor run       the loop (what the task runs, under pythonw.exe)
    py -3.11 -m desktop_worker.supervisor status    supervisor / server / Chrome status (no secrets printed)
    py -3.11 -m desktop_worker.supervisor start     enable the task and start it now
    py -3.11 -m desktop_worker.supervisor stop      disable the task, then ask the supervisor to stop (it stops its server)
    py -3.11 -m desktop_worker.supervisor install   (re-)register the Scheduled Task and start it
    py -3.11 -m desktop_worker.supervisor uninstall remove the Scheduled Task (after `stop`)
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / 'logs'
LOCAL = ROOT / '.local'
LOCK = LOCAL / 'desktop_supervisor.lock'
STOP = LOCAL / 'desktop_supervisor.stop'
STATE = LOCAL / 'desktop_supervisor.json'
SERVER_LOG = LOGS / 'desktop_worker_server.log'
SUP_LOG = LOGS / 'desktop_worker_supervisor.log'
TASK = 'MultiBot365DesktopWorker'
PORT = 8768
MAX_LOG = 5 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def log(msg):
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(SUP_LOG, 'a', encoding='utf-8') as f:
        f.write(f'{stamp()} pid={os.getpid()} {msg}\n')


def rotate(path):
    try:
        if path.exists() and path.stat().st_size > MAX_LOG:
            old = path.with_suffix(path.suffix + '.1')
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


def port_served(port=PORT):
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(('127.0.0.1', port)) == 0


def python_exe():
    """python.exe next to the running interpreter (pythonw.exe runs the supervisor itself without a console)."""
    exe = Path(sys.executable)
    cand = exe.with_name('python.exe')
    return str(cand if cand.exists() else exe)


class SingleInstance:
    def __init__(self, path=LOCK):
        self.path, self.fh = Path(path), None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, 'a+')
        try:
            if os.name == 'nt':
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True


def write_state(**kw):
    try:
        STATE.write_text(json.dumps(dict(kw, updated=stamp()), indent=1), encoding='utf-8')
    except OSError:
        pass


def start_server():
    LOGS.mkdir(parents=True, exist_ok=True)
    rotate(SERVER_LOG)
    out = open(SERVER_LOG, 'a', encoding='utf-8')
    out.write(f'\n{stamp()} ---- supervisor {os.getpid()} starting desktop_worker.server\n')
    out.flush()
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    flags = CREATE_NO_WINDOW if os.name == 'nt' else 0
    proc = subprocess.Popen([python_exe(), '-m', 'desktop_worker.server'], cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, creationflags=flags)
    out.close()
    return proc


def run(poll=2.0, max_backoff=60.0, healthy_after=300.0):
    lock = SingleInstance()
    if not lock.acquire():
        log('another supervisor holds the lock; exiting')
        return 0
    if STOP.exists():
        STOP.unlink()
    log(f'supervisor started (task {TASK}); server log {SERVER_LOG}')
    proc, backoff, restarts, started = None, 2.0, 0, 0.0
    try:
        while True:
            if STOP.exists():
                log('stop file seen: stopping')
                break
            if proc is None:
                if port_served():
                    write_state(supervisor_pid=os.getpid(), server_pid=None, restarts=restarts,
                                note=f'port {PORT} already served by another process; not starting a second server')
                    time.sleep(10)
                    continue
                proc, started = start_server(), time.monotonic()
                log(f'server started pid={proc.pid} (restart #{restarts})')
                write_state(supervisor_pid=os.getpid(), server_pid=proc.pid, restarts=restarts, server_started=stamp())
            code = proc.poll()
            if code is not None:
                up = time.monotonic() - started
                log(f'server pid={proc.pid} exited code={code} after {up:.0f}s')
                proc = None
                restarts += 1
                backoff = 2.0 if up >= healthy_after else min(backoff * 2, max_backoff) if restarts > 1 else 2.0
                log(f'restarting in {backoff:.0f}s')
                end = time.monotonic() + backoff
                while time.monotonic() < end and not STOP.exists():
                    time.sleep(0.5)
                continue
            time.sleep(poll)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
            log(f'server pid={proc.pid} stopped')
        write_state(supervisor_pid=None, server_pid=None, restarts=restarts, note='stopped')
        if STOP.exists():
            STOP.unlink()
        log('supervisor exiting')
    return 0


def health():
    try:
        import urllib.request
        cfg = json.loads((LOCAL / 'desktop_worker.json').read_text(encoding='utf-8-sig'))
        req = urllib.request.Request(f'http://127.0.0.1:{cfg.get("port", PORT)}/health', headers={'Authorization': 'Bearer ' + cfg['token']})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return dict(error=f'{type(e).__name__}: {e}'[:200])


def status():
    st = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    h = health()
    task = subprocess.run(['schtasks', '/Query', '/TN', TASK, '/FO', 'LIST'], capture_output=True, text=True).stdout if os.name == 'nt' else ''
    status_line = next((l.split(':', 1)[1].strip() for l in task.splitlines() if l.startswith('Status')), 'not registered')
    out = dict(task=TASK, task_status=status_line, supervisor=st, port_served=port_served(),
               server=dict((k, h.get(k)) for k in ('healthy', 'ready', 'blocked_reason', 'state', 'pid', 'uptime_ms', 'error')),
               chrome=h.get('chrome'), logs=[str(SUP_LOG), str(SERVER_LOG)])
    print(json.dumps(out, indent=1, default=str))


TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>MultiBot365 desktop worker supervisor (desktop_worker.supervisor run): keeps desktop_worker.server running in the WINDOWS11 session.</Description></RegistrationInfo>
  <Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <RestartOnFailure><Count>999</Count><Interval>PT1M</Interval></RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <AllowHardTerminate>true</AllowHardTerminate>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <Enabled>true</Enabled>
  </Settings>
  <Triggers>
    <LogonTrigger><UserId>{user}</UserId></LogonTrigger>
    <TimeTrigger><StartBoundary>2026-09-28T00:00:00</StartBoundary><Repetition><Interval>PT5M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></TimeTrigger>
  </Triggers>
  <Actions Context="Author"><Exec><Command>{pythonw}</Command><Arguments>-m desktop_worker.supervisor run</Arguments><WorkingDirectory>{root}</WorkingDirectory></Exec></Actions>
</Task>
"""


def install():
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    user = os.environ.get('USERDOMAIN', '') + '\\' + os.environ.get('USERNAME', '')
    xml = TASK_XML.format(user=user, pythonw=pythonw, root=ROOT)
    path = LOCAL / 'desktop_supervisor_task.xml'
    path.write_text(xml, encoding='utf-16')
    r = subprocess.run(['schtasks', '/Create', '/TN', TASK, '/XML', str(path), '/F'], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    r = subprocess.run(['schtasks', '/Run', '/TN', TASK], capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['run', 'status', 'start', 'stop', 'install', 'uninstall'])
    a = ap.parse_args()
    if a.command == 'run':
        try:
            sys.exit(run())
        except Exception as e:
            log(f'supervisor crashed: {type(e).__name__}: {e}')
            sys.exit(1)                             # non-zero: the task's restart-on-failure starts it again
    if a.command == 'status':
        return status()
    if a.command == 'start':
        for args in (['/Change', '/TN', TASK, '/ENABLE'], ['/Run', '/TN', TASK]):
            r = subprocess.run(['schtasks'] + args, capture_output=True, text=True)
            print(r.stdout.strip() or r.stderr.strip())
        return
    if a.command == 'stop':
        r = subprocess.run(['schtasks', '/Change', '/TN', TASK, '/DISABLE'], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        LOCAL.mkdir(exist_ok=True)
        STOP.write_text(stamp(), encoding='utf-8')
        print(f'stop requested ({STOP}); the supervisor stops its server within a few seconds (task disabled; '
              f'`start` re-enables it). Chrome is left running.')
        return
    if a.command == 'install':
        return install()
    if a.command == 'uninstall':
        r = subprocess.run(['schtasks', '/Delete', '/TN', TASK, '/F'], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())


if __name__ == '__main__':
    main()
