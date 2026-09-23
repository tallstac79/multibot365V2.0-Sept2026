"""Thin, non-blocking adapter from the pipeline to the existing coordinator client.

Uses tools.coordinator_client.Client unchanged (same auth, same HTTP framing, same
instruction ID rules). Each call is one bounded request; the pipeline tick owns
scheduling, so a slow phone never blocks intake.
"""
import json
from pathlib import Path

from tools.coordinator_client import Client


class CoordinatorGateway:
    def __init__(self, config=None, config_path='.local/coordinator.json', client_factory=Client):
        if config is None:
            config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        self.client = client_factory(config)

    def health(self):
        return self.client.health()

    def submit(self, payload):
        # Client.submit retries uncertain sends with the SAME ID only (coordinator dedupes).
        return self.client.submit(payload, seconds=10)

    def result(self, instruction_id):
        """Terminal result dict, pending progress dict with _pending=True, or None if unknown."""
        code, value = self.client.request('GET', '/instructions/' + instruction_id)
        if code == 200:
            return value
        if code == 202 and isinstance(value, dict):
            pending = dict(value)
            pending['_pending'] = True
            return pending
        if code in (202, 404):
            return None
        raise ValueError(f'Unexpected result response HTTP {code}')
