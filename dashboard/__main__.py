import argparse
import os
import uvicorn

parser = argparse.ArgumentParser(description='MultiBot365 local dashboard; no device actions')
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=8780)
args = parser.parse_args()
if args.host != '127.0.0.1':
    os.environ['DASHBOARD_ALLOWED_HOSTS'] = os.environ.get('DASHBOARD_ALLOWED_HOSTS', '') + ',' + args.host
uvicorn.run('dashboard.app:app', host=args.host, port=args.port)
