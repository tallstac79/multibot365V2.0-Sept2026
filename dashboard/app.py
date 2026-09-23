"""Run with python -m dashboard (loopback port 8780)."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dashboard.services import ROOT, Store, Health, sample_alerts, history, log_entries


def create_app(root=ROOT, db_path=None, health=None):
    app = FastAPI(title='MultiBot365 local dashboard', docs_url=None, redoc_url=None)
    store = Store(db_path or root / '.local/dashboard.sqlite3')
    health = health or Health(root)
    app.state.store, app.state.health = store, health
    static = Path(__file__).parent / 'static'

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        # Browser writes must originate from this dashboard; reject DNS rebinding.
        host = request.headers.get('host', '').split(':')[0]
        allowed = {'127.0.0.1', 'localhost', 'testserver'} | set(os.environ.get('DASHBOARD_ALLOWED_HOSTS', '').split(','))
        if host not in allowed:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Host not allowed'}, status_code=403)
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD') and (request.headers.get('sec-fetch-site') == 'cross-site' or
            (origin and urlsplit(origin).netloc != request.headers.get('host'))):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Cross-origin write rejected'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/')
    def index(): return FileResponse(static / 'index.html')

    @app.get('/api/status')
    def status(): return health.get()

    @app.get('/api/config')
    def config(): return store.get()

    @app.put('/api/config')
    def save_config(value: dict):
        try: return store.save(value)
        except (ValueError, TypeError, KeyError) as error: raise HTTPException(422, str(error))

    @app.get('/api/alerts')
    def alerts(mode: str = 'sample'):
        if mode not in ('sample', 'live'): raise HTTPException(422, 'Invalid mode')
        return {'mode': mode, 'items': sample_alerts(store.get(), root) if mode == 'sample' else [],
                'note': 'SAMPLE DATA — fixture replay; never submitted' if mode == 'sample' else 'Live feed is not connected'}

    @app.get('/api/history')
    def results(q: str = '', status: str = '', limit: int = 100, offset: int = 0):
        rows = history(root)
        rows = [r for r in rows if (not status or r['status'] == status or r['stage'] == status)
                and q.lower() in ' '.join(str(r.get(k) or '') for k in ('instruction_id', 'fixture', 'market', 'side', 'device_id')).lower()]
        return {'total': len(rows), 'items': rows[max(0, offset):max(0, offset) + max(1, min(limit, 200))]}

    @app.get('/api/logs')
    def logs(component: str = '', severity: str = '', instruction_id: str = '', device_id: str = '', since: str = '', until: str = ''):
        rows = log_entries(store, root)
        for key, value in [('component', component), ('severity', severity), ('instruction_id', instruction_id), ('device_id', device_id)]:
            if value: rows = [r for r in rows if value.lower() in str(r.get(key) or '').lower()]
        if since: rows = [r for r in rows if r['timestamp'] >= since]
        if until: rows = [r for r in rows if r['timestamp'] <= until]
        return {'total': len(rows), 'items': rows[:100]}

    @app.get('/api/evidence/{name:path}')
    def evidence(name: str):
        base = (root / 'evidence').resolve()
        path = (base / name).resolve()
        if not path.is_relative_to(base) or path.suffix.lower() not in ('.png', '.json', '.txt') or not path.is_file():
            raise HTTPException(404, 'Evidence unavailable')
        return FileResponse(path)

    app.mount('/static', StaticFiles(directory=static), name='static')
    return app

app = create_app()
