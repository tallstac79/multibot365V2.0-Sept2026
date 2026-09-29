"""LAN coordinator client. Pair using a private JSON config containing url and token."""
import argparse
import http.client
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

class Client:
    def __init__(self, config):
        self.config = config
        self.url = urlsplit(config['url'])
    def request(self, method, path, body=None, raw=False):
        connection = http.client.HTTPConnection(self.url.hostname, self.url.port, timeout=5)
        payload = body if isinstance(body, (str, bytes)) else json.dumps(body) if body is not None else None
        try:
            connection.request(method, path, payload, {'Authorization': 'Bearer ' + self.config['token'], 'Content-Type': 'application/json'})
            response = connection.getresponse()
            data = response.read()
            return response.status, data if raw else json.loads(data)
        finally:
            connection.close()
    def health(self):
        code, value = self.request('GET', '/health')
        if code != 200: raise RuntimeError(value)
        return value
    def prewarm(self, url):
        """Ask the phone to start loading this event page (navigation only). {'started': bool, ...}; a busy phone answers started False."""
        code, value = self.request('POST', '/prewarm', {'url': url})
        if code not in (200, 202, 409): raise RuntimeError(value)
        return value
    def submit(self, instruction, seconds=20):
        # Never generate a replacement ID after an uncertain response.
        deadline = time.monotonic() + seconds
        while True:
            try:
                code, reply = self.request('POST', '/instructions', instruction)
                if code == 202 or (code == 409 and reply.get('stage') == 'DUPLICATE'): return reply
                raise ValueError(reply)
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline: raise
                time.sleep(.5)
    def result(self, instruction_id, seconds=75):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                code, value = self.request('GET', '/instructions/' + instruction_id)
                if code == 200: return value
                if code != 202: raise ValueError(value)
            except (OSError, http.client.HTTPException): pass
            time.sleep(.25)
        raise TimeoutError('Result unavailable; retry the same ID, never a replacement ID')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='.local/coordinator.json')
    parser.add_argument('operation', choices=['health', 'send', 'result'])
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    client = Client(json.loads(Path(args.config).read_text(encoding='utf-8')))
    if args.operation == 'health': print(json.dumps(client.health(), indent=2))
    elif args.operation == 'result': print(json.dumps(client.result(args.value), indent=2))
    else:
        instruction = json.loads(Path(args.value).read_text(encoding='utf-8'))
        print(json.dumps(client.submit(instruction), indent=2))
        print(json.dumps(client.result(instruction['instruction_id']), indent=2))
