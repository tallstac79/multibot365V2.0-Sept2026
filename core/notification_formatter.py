"""Concise plain-text notification formatter. Does not send messages."""
from decimal import Decimal, InvalidOperation


def format_result(record):
    def obj(value): return value if isinstance(value, dict) else {}
    payload = obj(record.get('payload')) or record
    selected = obj(payload.get('selection'))
    ready = obj(payload.get('ready_state'))
    final = obj(payload.get('final_state'))
    def first(*values): return next((v for v in values if v is not None and v != ''), None)
    def clean(value): return ' '.join(str(value).split())[:240]
    stake=first(record.get('stake'),final.get('stake'),ready.get('stake'),payload.get('stake'))
    if stake is not None:
        try: stake = f'£{Decimal(str(stake)):.2f}' if Decimal(str(stake)).is_finite() else None
        except InvalidOperation: stake = None
    fields = [('Event',first(record.get('fixture'),payload.get('fixture_name'),payload.get('fixture'))),
        ('Sport',first(record.get('sport'),payload.get('sport'))),
        ('Market',first(record.get('market'),selected.get('market'),ready.get('market'))),
        ('Selection',first(selected.get('selection_name'),ready.get('selection_name'),record.get('side'),selected.get('side'))),
        ('Odds',first(record.get('observed_price'),selected.get('price'),ready.get('price'))),('Stake',stake),
        ('Source',first(record.get('alert_source'),payload.get('source'))),
        ('Status',first(record.get('status'),payload.get('status'),ready.get('state'))),
        ('Stage',first(record.get('stage'),payload.get('stage'))),
        ('Instruction',first(record.get('instruction_id'),payload.get('instruction_id'))),
        ('Device',first(record.get('device_id'),payload.get('device_id'))),
        ('Reason',first(record.get('failure_reason'),payload.get('detail') if payload.get('status')=='FAIL' else None))]
    return 'MultiBot365\n\n'+'\n'.join(f'{label}: {clean(value)}' for label,value in fields if value is not None)
