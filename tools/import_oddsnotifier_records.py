"""Import an explicitly captured OddsNotifier message snapshot; no Telegram/network access."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from core.observation_store import record_alert


def import_snapshot(path, database):
    rows=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(rows,list): raise ValueError('Expected captured message list')
    received_at=datetime.now(timezone.utc).isoformat()
    ids=[]
    for row in rows:
        ids.append(record_alert(database,row['raw_text'],channel_id=row['chat_id'],message_id=row['message_id'],
            source_timestamp=row.get('source_timestamp'),received_at=row.get('received_at',received_at),origin='production',
            ordering_profile='oddsnotifier_basketball_v1',provenance={'capture':'User-authorized Telegram browser observation',
                'feed':row.get('feed'),'displayed_date':row.get('displayed_date'),'displayed_time':row.get('displayed_time'),
                'source_timestamp_note':'Unknown when only local display time is available; receipt is snapshot import time',
                'format':'DOM-visible text, links serialized as Markdown, numeric bold preserved; no private app state read',
                'source_url':'https://web.telegram.org/a/#'+row['chat_id']}))
    return ids

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('--database',type=Path,default=Path('.local/oddsnotifier.sqlite3'))
    args=parser.parse_args()
    print(json.dumps({'record_ids':import_snapshot(args.snapshot,args.database)}))
