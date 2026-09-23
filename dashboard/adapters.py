"""Read-only adapters over parser observations and persisted coordinator evidence."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from core.observation_store import read_records
from core.decision_support import apply_rules
from core.notification_formatter import format_result
from dashboard.services import ROOT, read_json, history as recorded_history


def iso(value):
    if value is None: return None
    try:
        if isinstance(value,(int,float)): return datetime.fromtimestamp(value/1000,timezone.utc).isoformat()
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else parsed.isoformat()
    except (ValueError, OverflowError, OSError): return None


def obj(value): return value if isinstance(value,dict) else {}


def real_alerts(snapshot, root=ROOT):
    rows=[]
    for record in read_records(root/'.local/oddsnotifier.sqlite3'):
        if record.get('origin') != 'production': continue
        p=obj(record.get('parsed'))
        # A sample/mapping hypothesis can never enter the REAL view, even in a mislabeled envelope.
        if p.get('sample_provenance')=='synthetic' or obj(p.get('quote_mapping')).get('profile')=='synthetic_order_v1': continue
        warnings=list(record.get('warnings') or [])
        status=record.get('status')
        if status not in ('PARSED','AMBIGUOUS','INVALID','DUPLICATE','IGNORED'):
            status='INVALID';warnings.append('Unrecognized stored parse status')
        if status=='PARSED' and (not p.get('target_side') or not obj(p.get('quote_mapping')).get('production_verified')):
            status='AMBIGUOUS';warnings.append('Target/quote mapping unresolved')
        instruction=record.get('instruction')
        recommendation=None
        recommendation_reason=None
        if status=='PARSED':
            try:
                recommendation,recommendation_reason=apply_rules(p,p.get('target_side'),snapshot['config'],
                    record.get('instruction_id'),datetime.now(timezone.utc).isoformat(),sample=False)
            except (KeyError,ValueError,TypeError): recommendation_reason='Stored observation lacks recommendation fields'
        row=dict(id='stored-'+str(record['record_id']), instruction_id=record.get('instruction_id'),
            received_at=record.get('received_at'), source_message_id=record.get('source_message_id'), source_timestamp=record.get('source_timestamp'),
            source_chat_id=record.get('channel_id'),
            **{k:p.get(k) for k in ('sport','competition','fixture','market')},
            side=p.get('target_side'),line=p.get('target_line') if p.get('target_line') is not None else p.get('displayed_line'),
            alert_price=p.get('alert_price'),minimum_price=record.get('minimum_price'),displayed_ev=p.get('displayed_ev_percent'),
            status=status,raw_text=record.get('raw_text'),parsed=p or None,instruction=instruction,
            warnings=warnings,provenance={'mode':'REAL DATA','stored':record.get('provenance'),'record_id':record['record_id']},
            applied_config=record.get('applied_config'),recommendation=recommendation,recommendation_reason=recommendation_reason,
            recommendation_config=snapshot if recommendation else None,
            timeline=[event for event in record.get('timeline',[]) if isinstance(event,dict) and event.get('stage') in
                      ('RECEIVED','PARSED','NORMALIZED','RULES_APPLIED','COORDINATOR_STATE','DEVICE_RESULT')])
        rows.append(row)
    return rows


def evidence_link(path,root=ROOT):
    base=(root/'evidence').resolve();path=path.resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.png','.txt','.json'): return None
    return {'name':path.name,'url':'/api/evidence/'+quote(path.relative_to(base).as_posix(),safe='/')}


def result_history(root=ROOT,mode='real',alerts=None):
    rows=[]
    for row in recorded_history(root):
        folder=(root/row['source']).parent
        payload=row['payload']
        instruction=obj(read_json(folder/'instruction.json'))
        if instruction.get('instruction_id')!=row['instruction_id']: instruction={}
        evidence=obj(read_json(folder/'evidence.json'))
        if evidence.get('run_id')!=payload.get('run_id') or not payload.get('run_id'): evidence={}
        adapter=instruction.get('adapter') or evidence.get('adapter')
        # Fail closed: a file's directory/name alone cannot establish production origin.
        production=adapter=='live_bet365' or payload.get('record_origin')=='production'
        if (mode=='real') != production: continue
        ack=obj(read_json(folder/'ack.json'))
        if ack.get('instruction_id')!=row['instruction_id']: ack={}
        selection=obj(payload.get('selection')); ready=obj(payload.get('ready_state'))
        if row['time'] is None and evidence.get('started_at_ms') is not None and isinstance(evidence.get('duration_ms'),(int,float)):
            row['time']=iso(evidence['started_at_ms']+evidence['duration_ms'])
            row['time_source']='Evidence started_at_ms + duration_ms'
        row['sport']=instruction.get('sport') or payload.get('sport')
        row['market']=row['market'] or instruction.get('market') or ready.get('market')
        row['side']=row['side'] or instruction.get('side') or ready.get('selection_role')
        row['line']=row['line'] if row['line'] is not None else instruction.get('line')
        row['stake']=row['stake'] or ready.get('stake') or instruction.get('stake')
        row['minimum_price']=instruction.get('minimum_price')
        row['origin']='REAL DATA · persisted device result' if production else 'SAMPLE DATA · recorded backend test'
        row['timeline']=[]
        linked=next((a for a in (alerts or []) if a.get('instruction_id')==row['instruction_id']),None)
        if linked: row['timeline'].extend(linked['timeline'])
        if ack:
            row['timeline'].append(dict(stage='RECEIVED',timestamp=iso(ack.get('received_at_ms')),detail='Coordinator acknowledged instruction',payload=ack))
            if ack.get('state'):
                row['timeline'].append(dict(stage='COORDINATOR_STATE',timestamp=iso(ack.get('received_at_ms')),detail=ack['state']))
        if evidence:
            for event in evidence.get('events',[]):
                if not isinstance(event,dict): continue
                elapsed=event.get('elapsed_ms');start=evidence.get('started_at_ms')
                stamp=iso(start+elapsed) if isinstance(start,(int,float)) and isinstance(elapsed,(int,float)) else None
                row['timeline'].append(dict(stage='COORDINATOR_STATE',timestamp=stamp,detail=event.get('phase'),payload=event))
        row['timeline'].append(dict(stage='DEVICE_RESULT',timestamp=row['time'],detail=payload.get('detail') or row['status'],
                                    evidence=row['evidence']))
        # Join the existing confirmation normalizer only by exact instruction identity.
        poll=obj(read_json(root/'evidence/confirmation-live-poll/poll.json'))
        normal=obj(poll.get('normalized'))
        if poll.get('instruction_id')==row['instruction_id'] and normal.get('instruction_id')==row['instruction_id']:
            row['device_id']=row['device_id'] or normal.get('device_id')
        row['notification']=format_result(row)
        rows.append(row)
    return rows


def application_logs(store,root=ROOT):
    entries=store.changes()
    # Bounded tail of each actual app log; never manufacture log entries from file mtimes.
    for path in sorted((root/'logs').glob('*.log'))[:20]:
        with path.open('rb') as stream:
            offset=max(0,path.stat().st_size-65536);stream.seek(offset)
            content=stream.read(65536).decode('utf-8',errors='replace')
        lines=content.splitlines()
        if offset: lines=lines[1:]
        for line in lines[-300:]:
            try:
                item=json.loads(line)
                if not isinstance(item,dict): continue
                stamp=iso(item.get('timestamp'))
                if not stamp: continue
                entry=dict(timestamp=stamp,component=item.get('component',path.stem),severity=item.get('severity',item.get('level','INFO')),
                    instruction_id=item.get('instruction_id'),device_id=item.get('device_id'),message=str(item.get('message',''))[:240],detail=item)
            except ValueError:
                match=re.match(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}) \[(.*?)\] (\w+): (.*)',line)
                if not match: continue
                raw_time,component,severity,message=match.groups()
                try: stamp=datetime.strptime(raw_time,'%d/%m/%Y %H:%M:%S').astimezone().isoformat()
                except ValueError: continue
                ids={key:(m.group(1) if (m:=re.search(r'\b'+key+r'[=:]\s*([\w.-]+)',message)) else None) for key in ('instruction_id','device_id')}
                entry=dict(timestamp=stamp,component=component,severity=severity,message=message[:240],detail=message,**ids)
            entries.append(entry)
    return sorted(entries,key=lambda r:iso(r['timestamp']) or '',reverse=True)
