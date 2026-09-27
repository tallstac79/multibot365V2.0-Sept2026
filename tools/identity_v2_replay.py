"""Offline extraction/replay of frozen identity failures. No network or live DB access.

    python -m tools.identity_v2_replay --extract --java-home PATH_TO_JDK
    python -m tools.identity_v2_replay

The optional extraction uses the existing, unchanged pure Java grid parser on
stored OCR words. Replays use frozen inputs and never call a phone or pipeline.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo
from tools.offline_event_identity import resolve, CONFIRMED, VARIANT, CONFLICT

ROOT=Path(__file__).resolve().parents[1]
WORD=re.compile(r'^(.*?) \[(\d+),(\d+)\]\[(\d+),(\d+)\]$')
DATE=re.compile(r'(?<!\d)(?:\d(?=\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)))?(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}:\d{2})',re.I)


def dump(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')


def event_id(url):
    match=re.search(r'/E(\d+)(?:/|$)',url or '')
    return match[1] if match else None


def text_rows(path):
    words=[]
    for line in path.read_text(encoding='utf-8').splitlines():
        m=WORD.fullmatch(line)
        if m:words.append(dict(text=m[1],left=int(m[2]),top=int(m[3]),right=int(m[4]),bottom=int(m[5])))
    rows=[]
    for w in sorted(words,key=lambda w:((w['top']+w['bottom'])/2,w['left'])):
        cy=(w['top']+w['bottom'])/2
        row=next((r for r in rows if abs(r['cy']-cy)<=10),None)
        if row is None:row=dict(cy=cy,words=[]);rows.append(row)
        row['words'].append(w)
    for row in rows:
        row['text']=' '.join(w['text'] for w in sorted(row['words'],key=lambda w:w['left']))
    return rows


def captured_header(rows,year):
    header=[r for r in rows if 210<=r['cy']<500]
    date_row=next((r for r in header if DATE.search(r['text'])),None)
    competition=kickoff=None
    if date_row:
        m=DATE.search(date_row['text']);competition=date_row['text'][:m.start()].strip(' .•')
        month=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].index(m[2].lower())+1
        hour,minute=map(int,m[3].split(':'))
        local=datetime(year,month,int(m[1]),hour,minute,tzinfo=ZoneInfo('Europe/London'))
        # A repeated/missing local hour cannot be resolved from a timezone-free image.
        valid=local.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None)==local.replace(tzinfo=None)
        if valid and local.utcoffset()==local.replace(fold=1).utcoffset():kickoff=local.isoformat()
    fixture_rows=[];started=False
    for r in header:
        text=r['text']
        if re.search(r'\b(Popular|Builder|Quarter|Markets)\b',text,re.I):break
        if re.search(r'\s(?:vs|v)\s',text,re.I):started=True
        if started:fixture_rows.append(text)
    pair=re.split(r'\s(?:vs|v)\s',' '.join(fixture_rows),maxsplit=1,flags=re.I)
    return dict(home=pair[0] if len(pair)==2 else None,away=pair[1] if len(pair)==2 else None,
                competition=competition,kickoff=kickoff,header_lines=[r['text'] for r in header])


def utc_wire(value):
    if not value:return None
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()


def archive_inventory(folder):
    """Freeze every other saved terminal failure, deduplicated by run/ID.

    Includes old diagnostic probes and search runs separately from real intake.
    Missing original quotes are not reconstructed from a probe's minimum price.
    """
    known={c['instruction_id'] for c in json.loads((folder/'inputs.json').read_text())['cases']}
    found={};read_errors=[]
    def visit(value,origin,payload=None):
        if isinstance(value,list):
            for item in value:visit(item,origin,payload)
        elif isinstance(value,dict):
            q=value.get('payload') if isinstance(value.get('payload'),dict) else payload or {}
            stage=value.get('stage') or value.get('device_stage') or value.get('status')
            iid=value.get('instruction_id') or value.get('id') or q.get('instruction_id')
            run=value.get('run_id')
            if stage in ('ALIAS_REQUIRED','TARGET_NOT_FOUND','WRONG_EVENT') and (iid or run) and iid not in known:
                key=run or iid;old=found.get(key)
                candidate=dict(result=value,payload=q,sources=[origin],instruction_id=iid or 'run:'+run)
                richness=lambda c:len(c['payload'])+len(c['result'])+10*bool(c['result'].get('identity'))
                if old:
                    sources=sorted(set(old['sources']+[origin]))
                    if richness(candidate)>richness(old):found[key]=candidate
                    found[key]['sources']=sources
                else:found[key]=candidate
            for key,item in value.items():
                if key not in ('events','raw_text','progress','stage_timings'):visit(item,origin,q)
    for path in sorted((ROOT/'evidence').rglob('*.json')):
        if folder.resolve() in path.resolve().parents:continue
        try:
            raw=path.read_bytes()
            data=json.loads(raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'))
        except (ValueError,UnicodeError) as exc:
            read_errors.append(dict(path=path.relative_to(ROOT).as_posix(),error=type(exc).__name__));continue
        visit(data,path.relative_to(ROOT).as_posix())
    cases=[]
    for key,item in sorted(found.items()):
        r=item['result'];q=item['payload'];identity=r.get('identity') or {}
        query=q.get('query','').split('||');pair=query if len(query)==2 else [None,None]
        a=dict(home=(identity.get('home') or {}).get('feed') or r.get('feed_home') or pair[0],
               away=(identity.get('away') or {}).get('feed') or r.get('feed_away') or pair[1],
               sport=q.get('sport') or r.get('sport'),competition=q.get('competition') or r.get('competition'),
               kickoff=utc_wire(q.get('kickoff_utc')),event_url=q.get('event_url') or r.get('event_url'))
        a['event_id']=event_id(a['event_url'])
        p=dict(home=dict(name=(identity.get('home') or {}).get('bookmaker') or r.get('book_home'),source='ocr'),
               away=dict(name=(identity.get('away') or {}).get('bookmaker') or r.get('book_away'),source='ocr'),
               competition=r.get('page_competition'),event_id=None,event_id_observed=False,
               archive_sources=item['sources'])
        # An explicit historical timestamp contradiction can be replayed from the
        # recorded diagnostic without treating the old verdict itself as truth.
        detail=identity.get('reason') or r.get('detail') or ''
        mismatch=re.search(r'kick-off differs: alert (\d+ \w+ \d+:\d+) vs page (\d+ \w+ \d+:\d+) \(UK\)',detail)
        if mismatch and a['kickoff']:
            year=datetime.fromisoformat(a['kickoff']).year
            p['kickoff']=datetime.strptime(f'{year} {mismatch[2]}','%Y %d %b %H:%M').replace(tzinfo=ZoneInfo('Europe/London')).isoformat()
            p['kickoff_source']='timestamp explicitly preserved in historical comparison diagnostic'
        cases.append(dict(instruction_id=item['instruction_id'],source_id=';'.join(item['sources']),cohort='archive',
                          archive_kind='historical probes/search/incomplete records; separate from intake cohort',
                          old_stage=r.get('stage') or r.get('device_stage') or r.get('status'),old_verdict=identity.get('verdict') or r.get('verdict'),
                          old_reason=detail,alert=a,page=p,observations=[]))
    dump(folder/'archive-inputs.json',cases)
    dump(folder/'archive-inventory.json',dict(records=len(cases),read_errors=read_errors,
         scope='All saved JSON terminal failures, deduplicated by run ID or instruction ID; operational snapshot IDs excluded',
         limitations='Original quote/capture fields absent in an archive are unknown, never borrowed from another event or minimum_price.'))


def compile_grid(java_home):
    build=ROOT/'.local/identity-v2-java';build.mkdir(exist_ok=True)
    source=ROOT/'android/Bet365Agent/app/src/main/java/com/bet365agent/GameLinesParser.java'
    helper=ROOT/'tools/identity_v2_grid/IdentityV2Grid.java'
    subprocess.run([str(Path(java_home)/'bin/javac.exe'),'-d',str(build),str(source),str(helper)],check=True,capture_output=True)
    return [str(Path(java_home)/'bin/java.exe'),'-cp',str(build),'com.bet365agent.IdentityV2Grid'],hashlib.sha256(source.read_bytes()).hexdigest()


def grid(command,path,home,away,market,side):
    proc=subprocess.run(command+[str(path),home or '',away or ''],capture_output=True,text=True,encoding='utf-8',check=True)
    cells=[];notes=[]
    for line in proc.stdout.splitlines():
        fields=line.split('\t')
        if fields[0]=='NOTE':notes.append(' '.join(fields[1:]));continue
        if len(fields)==4:cells.append(dict(market='TOTALS' if fields[0]=='TOTAL' else fields[0],side=fields[1],line=fields[2],price=fields[3]))
    own=next((c for c in cells if c['market']==market and c['side']==side),None)
    prices={c['side']:c['price'] for c in cells if c['market']==market}
    if not own:return None,notes
    return dict(market=market,side=side,line=None if market=='MONEYLINE' else own['line'],prices=prices,period='FULL_GAME'),notes


def extract(folder,java_home):
    data=json.loads((folder/'snapshot.json').read_text(encoding='utf-8'))
    reviews=json.loads((folder/'visual-reviews.json').read_text(encoding='utf-8')) if (folder/'visual-reviews.json').exists() else {}
    command,parser_sha=compile_grid(java_home)
    cases=[]
    for row in data['rows']:
        iid=row['instruction_id'];d=folder/'captures'/iid
        m=json.loads((d/'evidence.json').read_text(encoding='utf-8')) if (d/'evidence.json').exists() else {}
        p=row['normalized_alert'];q=row['dispatch_payload'];r=row['result_payload']
        url=q.get('event_url') or r.get('event_url');eid=event_id(url)
        alert=dict(event_id=eid,event_url=url,sport=row['sport'],competition=row['competition'],country=q.get('country') or p.get('country'),
                   home=row['home'],away=row['away'],kickoff=utc_wire(q.get('kickoff_utc')),
                   market_fingerprint=dict(market=row['market'],side=row['selection'],line=row['line'],period=q.get('period','FULL_GAME'),
                       prices={c['side']:c['price'] for c in (p.get('comparison') or {}).get('quotes',[]) if c.get('side') and c.get('price')}))
        old=r.get('identity') or {};observations=[]
        paths=sorted(d.glob('s*_event_direct.txt')) if d.exists() else []
        events=[e for e in m.get('events',[]) if e.get('phase')=='CAPTURED_event_direct']
        for index,path in enumerate(paths):
            year=datetime.fromisoformat(row['received_at']).year
            header=captured_header(text_rows(path),year)
            requested_event=event_id(m.get('event_url'))
            page_type='event' if header['home'] and header['away'] else None
            when=events[index].get('wall_ts_ms') if index<len(events) else None
            timestamp=datetime.fromtimestamp(when/1000,timezone.utc).isoformat() if when else None
            is_prematch=datetime.fromisoformat(timestamp)<datetime.fromisoformat(header['kickoff']) if timestamp and header['kickoff'] else None
            fp,notes=grid(command,path,header['home'],header['away'],row['market'],row['selection']) if row['sport']=='basketball' else (None,['Football layout not extracted by basketball grid adapter'])
            sport_code=re.search(r'/B(\d+)/',m.get('event_url') or '')
            page=dict(event_id=None,event_id_observed=False,requested_event_id=requested_event,event_url=m.get('event_url'),
                      direct_link_capture=m.get('route')=='event_link' and bool(paths),page_type=page_type,unique_event=bool(page_type),
                      competitor_count=0 if page_type else None,competitor_scope='single captured direct event page, not a global search',
                      prematch=is_prematch,orientation='home_away' if page_type else None,
                      sport={'18':'basketball','1':'football'}.get(sport_code[1]) if sport_code else None,sport_source='recorded navigation URL; correlated with event-link anchor',
                      competition=header['competition'],kickoff=header['kickoff'],
                      home=dict(name=header['home'],source='ocr',confidence=None),away=dict(name=header['away'],source='ocr',confidence=None),
                      captured_at=timestamp,market_fingerprint=fp,grid_notes=notes,header_lines=header['header_lines'],capture=path.relative_to(ROOT).as_posix())
            png=path.with_suffix('.png')
            review=reviews.get(png.relative_to(ROOT).as_posix())
            if review:
                assert hashlib.sha256(png.read_bytes()).hexdigest()==review['artifact_sha256'],'Reviewed image changed'
                for side in ('home','away'):
                    if side in review:page[side]['reread']=dict(review[side],source='visual_review',independent=True,legible=True,artifact_sha256=review['artifact_sha256'])
            observations.append(page)
        if observations:page=observations[-1]
        else:
            page=dict(home=dict(name=(old.get('home') or {}).get('bookmaker'),source='ocr'),
                      away=dict(name=(old.get('away') or {}).get('bookmaker'),source='ocr'))
        cases.append(dict(instruction_id=iid,source_id=f"{row['chat_id']}:{row['message_id']}",old_stage=row['device_stage'],
                          old_verdict=old.get('verdict'),old_reason=row['failure_reason'],alert=alert,page=page,observations=observations))
    # Earlier independently captured snapshots can explain later changes; no
    # movement or tolerance is invented from the size of the difference.
    for case in cases:
        page=case['page'];eid=case['alert']['event_id'];prior=[]
        for other in cases:
            if other['alert']['event_id']!=eid:continue
            for observation in other['observations']:
                if observation.get('market_fingerprint') and observation.get('captured_at') and page.get('captured_at') and observation['captured_at']<page['captured_at']:
                    prior.append(dict(event_id=eid,independently_observed=True,observed_at=observation['captured_at'],fingerprint=observation['market_fingerprint']))
        page['prior_snapshots']=prior
    aliases=[dict(sport=a['sport'],competition=a['competition'],source=a['source_name'],target=a['bookmaker_name'],approved=True) for a in data['scoped_aliases']]
    # Preserve already approved production competition mappings as explicit audit inputs.
    source=(ROOT/'android/Bet365Agent/app/src/main/java/com/bet365agent/EventIdentity.java').read_text(encoding='utf-8')
    mappings=[dict(sport='basketball' if country in ('poland','korea','japan','spain') else 'football',country=country,source=label,target=target,approved=True)
              for country,label,target in re.findall(r'COMPETITION_ALIASES.put\("([^"|]+)\|([^"]+)",\s*"([^"]+)"\)',source)]
    dump(folder/'inputs.json',dict(captured_at=data['captured_at'],grid_parser_sha256=parser_sha,aliases=aliases,competition_mappings=mappings,cases=cases))


def report(folder):
    data=json.loads((folder/'inputs.json').read_text(encoding='utf-8'));results=[]
    archive_path=folder/'archive-inputs.json'
    archived=json.loads(archive_path.read_text(encoding='utf-8')) if archive_path.exists() else []
    for case in data['cases']+archived:
        result=resolve(case['alert'],case['page'],aliases=data['aliases'],competition_mappings=data['competition_mappings'])
        results.append(dict(case,result=result))
    dump(folder/'results.json',results)
    fields=['instruction_id','source_id','cohort','feed_teams','bookmaker_teams','direct_url_evidence','kickoff','sport','competition','market_fingerprint',
            'gender','age','squad_tier','reserve','academy','home_name_evidence','away_name_evidence','ocr_reread','old_stage','old_verdict','new_offline_verdict','reason']
    with (folder/'replay.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader()
        for row in results:
            r=row['result'];e=r['evidence'];a=row['alert'];p=row['page']
            item=dict(instruction_id=row['instruction_id'],source_id=row['source_id'],cohort=row.get('cohort','operational'),feed_teams=[a['home'],a['away']],
                      bookmaker_teams=[e['home_name']['page']['name'],e['away_name']['page']['name']],direct_url_evidence=e['event_id'],
                      kickoff=e['kickoff'],sport=e['sport'],competition=e['competition'],market_fingerprint=e['market_fingerprint'],
                      home_name_evidence=e['home_name'],away_name_evidence=e['away_name'],old_stage=row['old_stage'],old_verdict=row['old_verdict'],
                      new_offline_verdict=r['verdict'],reason=dict(conflicts=r['conflicts'],needs_recheck=r['needs_recheck'],missing=r['missing_evidence']),
                      ocr_reread={s:dict(original=p.get(s),used=e[s+'_name']['page']['reread_used']) for s in ('home','away')})
            for label,key in [('gender','gender'),('age','age_group'),('squad_tier','squad_tier'),('reserve','reserve'),('academy','academy')]:
                item[label]={s:e[s+'_'+key] for s in ('home','away')}
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in item.items()})
    archive_results=[r for r in results if r.get('cohort')=='archive']
    results=[r for r in results if r.get('cohort','operational')=='operational']
    confirmed=lambda r:r['result']['verdict'] in (CONFIRMED,VARIANT)
    summary=dict(captured_at=data['captured_at'],total=len(results),old_stages=dict(Counter(r['old_stage'] for r in results)),
                 offline_verdicts=dict(Counter(r['result']['verdict'] for r in results)),
                 recovered_identity_failures=[r['instruction_id'] for r in results if confirmed(r) and r['old_verdict'] not in ('EXACT','CANONICAL_MATCH','ALIAS_MATCH','HIGH_CONFIDENCE_EVENT_MATCH')],
                 fingerprints=dict(Counter(r['result']['evidence']['market_fingerprint']['fingerprint_match'] for r in results)),
                 conflicts=[dict(instruction_id=r['instruction_id'],fields=r['result']['conflicts']) for r in results if r['result']['verdict']==CONFLICT],
                 archive_total=len(archive_results),archive_verdicts=dict(Counter(r['result']['verdict'] for r in archive_results)),
                 limitations=['Frozen direct-link operational DB cohort; verdict concerns identity, not execution eligibility.',
                              'Destination event IDs were not read back; requested-link/captured-page anchor provenance is explicit.',
                              'OCR confidence absent in old artifacts remains null. Visual reviews are labelled separately.',
                              'Search never receives direct-link privileges. No global aliases, production changes or device actions.'])
    dump(folder/'summary.json',summary);print(json.dumps(summary,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,default=ROOT/'evidence/identity-v2')
    parser.add_argument('--extract',action='store_true');parser.add_argument('--java-home')
    parser.add_argument('--inventory-archives',action='store_true')
    args=parser.parse_args()
    if args.extract:
        if not args.java_home:parser.error('--extract requires --java-home')
        extract(args.folder,args.java_home)
    if args.inventory_archives:archive_inventory(args.folder)
    report(args.folder)
