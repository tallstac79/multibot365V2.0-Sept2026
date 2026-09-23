"""User-confirmed basketball Totals/Spread profile; no Moneyline mapping."""
import re
from decimal import Decimal
from urllib.parse import urlsplit, parse_qs

PROFILE = 'oddsnotifier_basketball_v1'


def parse_basketball(text, *, channel_id=None, message_id=None, source_timestamp=None,
                     sample_provenance='unspecified', target_position=None):
    from core.oddsnotifier_parser import AlertFormatError, _source, _quotes, NUMBER, LINE
    if target_position is not None and (type(target_position) is not int or target_position not in (1,2)):
        raise AlertFormatError('Confirmed target position must be 1 or 2')
    # Accept the supplied Telegram Markdown links and whitespace-flattened paste.
    pattern = (r'New odds update on Pinnacle\s+Basketball - (?P<country>.+?) - (?P<competition>.+?)\s+'
        r'\[(?P<fixture>[^\]\r\n]+)\]\((?P<fixture_url>https://[^\s)]+)\)\s+'
        r'(?P<date>\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\s+'
        rf'(?P<market>Totals|Spread) \((?P<current>{LINE})\)(?P<current_alt>\s*\(alt\. line\))?\s+'
        r'(?P<pinnacle>[0-9.⬇⬆️()\s-]+?)\s+🟢\s+Opening '
        rf'\((?P<opening>{LINE})\)(?P<opening_alt>\s*\(alt\. line\))?\s+(?P<opening_prices>[0-9.\s-]+?)\s+'
        rf'\[Bet365 \((?P<comparison_market>Totals|Spread) (?P<comparison>{LINE})\)(?P<comparison_alt>\s*\(alt\. line\))?\]'
        r'\((?P<comparison_url>https://[^\s)]+)\)\s+(?P<prices>[0-9.*\s-]+?)\s+'
        rf'🎯\s+EV: (?P<ev>{NUMBER})%')
    m=re.fullmatch(pattern,text.strip(),flags=re.DOTALL)
    if not m: raise AlertFormatError('Unsupported production basketball layout')
    v=m.groupdict()
    if v['market']!=v['comparison_market']: raise AlertFormatError('Conflicting comparison market')
    url=urlsplit(v['fixture_url']);comparison_url=urlsplit(v['comparison_url'])
    for value in (url,comparison_url):
        if value.username or value.password or value.port: raise AlertFormatError('Unexpected source URL authority')
    if url.hostname!='oddshub.io' or not url.path.startswith('/basketball/') or parse_qs(url.query).get('market')!=[v['market']]:
        raise AlertFormatError('Basketball fixture URL market conflicts with label')
    if comparison_url.hostname not in ('bet365.com','www.bet365.com'):
        raise AlertFormatError('Unsupported comparison URL')
    teams=re.split(r'\s+vs\s+',v['fixture'])
    if len(teams)!=2 or not all(teams) or teams[0].casefold()==teams[1].casefold():
        raise AlertFormatError('Expected two distinct basketball teams')
    from datetime import datetime
    try: scheduled=datetime.strptime(v['date'],'%d.%m.%Y %H:%M')
    except ValueError as error: raise AlertFormatError('Invalid fixture date') from error
    market='TOTALS' if v['market']=='Totals' else 'SPREAD'
    sides=['OVER','UNDER'] if market=='TOTALS' else ['HOME','AWAY']
    if market=='TOTALS' and any(Decimal(v[key])<0 for key in ('current','opening','comparison')):
        raise AlertFormatError('Total lines cannot be negative')
    price_cells=re.split(r'\s+-\s+',v['prices'])
    if len(price_cells)!=2: raise AlertFormatError('Expected exactly two Bet365 quotes')
    bold=[];clean=[]
    for index,cell in enumerate(price_cells):
        target=re.fullmatch(rf'\*\*({NUMBER})\*\*',cell)
        if target: bold.append(index);clean.append(target[1])
        else: clean.append(cell)
    if len(bold)>1: raise AlertFormatError('Multiple bold Bet365 target prices')
    def group(line, quotes):
        for index,quote in enumerate(quotes):
            signed=Decimal(line) if index==0 or market=='TOTALS' else -Decimal(line)
            quote['line']=line if index==0 or market=='TOTALS' else format(signed,'+f') if signed>0 else str(signed)
        return {'line':line,'quotes':quotes}
    pinnacle=group(v['current'],_quotes(v['pinnacle'],2,True,sides))
    opening=group(v['opening'],_quotes(v['opening_prices'],2,sides=sides))
    opening['outcome_count_matches_market']=True
    comparison=group(v['comparison'],_quotes(' - '.join(clean),2,sides=sides));comparison['site']='Bet365'
    if bold and target_position is not None and bold[0]+1 != target_position:
        raise AlertFormatError('Bold target conflicts with explicit target confirmation')
    target_index=bold[0] if bold else target_position-1 if target_position is not None else None
    target=comparison['quotes'][target_index] if target_index is not None else None
    warnings=['event_timezone_unspecified']
    if not target: warnings.append('target_selection_not_explicit: Bet365 bold marker absent')
    if any('parenthetical_price' in q for q in pinnacle['quotes']): warnings.append('parenthetical_price_meaning_unspecified')
    identity,source_time=_source(channel_id,message_id,source_timestamp)
    return dict(schema_version=4,source='OddsNotifier',observation_id=identity,format_variant='linked_basketball',
        fixture_url=v['fixture_url'],comparison_url=v['comparison_url'],market_label_source='label_and_fixture_url',
        sample_provenance=sample_provenance,quote_mapping={'profile':PROFILE,'production_verified':True,
            'sides_by_position':sides,'group_sides_by_position':{key:sides for key in ('pinnacle','opening','comparison')},
            'confirmation_source':'User confirmation 2026-09-23; basketball Totals and Spread only'},
        telegram_channel_id=channel_id,telegram_message_id=message_id,source_timestamp=source_time,raw_text=text,
        sport='basketball',country=v['country'],competition=v['competition'],fixture=v['fixture'],home=teams[0],away=teams[1],
        scheduled_at_local=scheduled.isoformat(timespec='minutes'),scheduled_timezone=None,market=market,market_label=v['market'],
        displayed_line=v['current'],pinnacle=pinnacle,opening=opening,comparison=comparison,displayed_ev_percent=v['ev'],
        alternate_line={key:bool(v[key+'_alt']) for key in ('current','opening','comparison')},
        target_side=target['side'] if target else None,target_line=target['line'] if target else None,
        alert_price=target['price'] if target else None,target_price_source=('bold_bet365_quote' if bold else 'user_confirmed_quote_position') if target else None,unresolved=warnings)
