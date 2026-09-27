"""Pure event-record comparison for offline lookup QA.

Inputs are observations, never instructions. This module has no database, device,
network, alias-promotion or execution dependency. Missing evidence stays unknown.
No live resolver imports it. Its verdicts describe record identity only.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from urllib.parse import urlsplit

CONFIRMED = 'DIRECT_URL_CONFIRMED'
VARIANT = 'DIRECT_URL_CONFIRMED_NAME_VARIANT'
RECHECK = 'NEEDS_RECHECK'
AMBIGUOUS = 'AMBIGUOUS'
CONFLICT = 'CONFLICT'
DIMENSIONS = ('gender', 'age_group', 'squad_tier', 'reserve', 'academy')
AFFIXES = {'fc', 'bc', 'bk', 'kk', 'ks', 'lks', 'kc', 'ac', 'sc', 'cf', 'cd', 'club', 'atletico'}
GENERIC = {'basket', 'basketball', 'team', 'sport', 'sports', 'united', 'city', 'town',
           'tigers', 'lions', 'eagles', 'giants', 'thunders', 'de', 'la', 'the', 'of'}
WOMEN = {'women', 'womens', 'woman', 'ladies', 'female'}
MEN = {'men', 'mens', 'male'}
BODY_PREFIXES = {'basketball': {'fiba'}, 'football': {'fifa','uefa','concacaf','conmebol','afc','caf'}}


def direct_event_id(url):
    """Only an actual bookmaker event path can supply a URL anchor."""
    try:
        parsed = urlsplit(url or '')
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not (host == 'bet365.com' or host.endswith('.bet365.com')):
            return None
        m = re.search(r'/E(\d+)(?:/|$)', parsed.path + '/' + parsed.fragment)
        return m[1] if m else None
    except ValueError:
        return None


def normalize(value):
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    value = value.translate(str.maketrans({'ł': 'l', 'ø': 'o', 'đ': 'd', 'ß': 'ss'}))
    value = ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))
    value = re.sub(r'\bu[\s-]*(\d{2})\b', r'u\1', value)
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in value).split())


def dimensions(name, explicit=None):
    """Absent markers are unknown, never implicitly male or first team.

    Juniors is part of many club names (including Boca Juniors), not automatically
    a youth/reserve flag. B in B-Corsairs is not a suffix squad designation.
    """
    tokens = normalize(name).split()
    out = dict.fromkeys(DIMENSIONS)
    genders = set()
    for t in tokens:
        if t in WOMEN: genders.add('women')
        if t in MEN: genders.add('men')
    if re.search(r'(?i)(?:\(\s*w\s*\)|\bw\s*$)', str(name or '')): genders.add('women')
    if re.search(r'(?i)(?:\(\s*m\s*\)|\bm\s*$)', str(name or '')): genders.add('men')
    if genders: out['gender'] = next(iter(genders)) if len(genders) == 1 else 'CONTRADICTORY'
    ages = {t for t in tokens if re.fullmatch(r'u\d{2}', t)}
    if ages: out['age_group'] = next(iter(ages)) if len(ages) == 1 else 'CONTRADICTORY'
    tiers = {t.upper() for t in tokens if t in ('i', 'ii', 'iii')}
    without_gender = [t for t in tokens if t not in WOMEN | MEN | {'w', 'm'}]
    if without_gender and without_gender[-1] in ('b', 'c'): tiers.add(without_gender[-1].upper())
    if re.search(r'\bfirst team\b', normalize(name)): tiers.add('I')
    if tiers: out['squad_tier'] = next(iter(tiers)) if len(tiers) == 1 else 'CONTRADICTORY'
    if set(tokens) & {'reserve', 'reserves'}: out['reserve'] = True
    if 'academy' in tokens: out['academy'] = True
    for key, value in (explicit or {}).items():
        if key in out and value is not None:
            out[key] = value if out[key] is None or out[key] == value else 'CONTRADICTORY'
    return out


def _team(observation):
    if isinstance(observation, str): observation = {'name': observation, 'source': 'structured'}
    observation = dict(observation or {})
    reread = observation.get('reread') or {}
    numeric_confidence = reread.get('confidence')
    scored = isinstance(numeric_confidence, (int,float)) and .9 <= numeric_confidence <= 1
    visual = reread.get('source') == 'visual_review' and reread.get('legible') is True and bool(reread.get('artifact_sha256'))
    used = (reread.get('independent') is True and bool(reread.get('name'))
            and ((reread.get('source') in ('structured', 'enhanced_ocr', 'human') and scored) or visual))
    effective = reread if used else observation
    return dict(name=effective.get('name', ''), source=effective.get('source', 'unknown'),
                confidence=effective.get('confidence'), original_name=observation.get('name', ''),
                reread_used=used, dimensions=dimensions(effective.get('name'), effective.get('dimensions')))


def _core(name):
    tokens = normalize(name).split()
    remove = AFFIXES | WOMEN | MEN | {'i', 'ii', 'iii', 'reserve', 'reserves', 'academy'}
    if dimensions(name)['gender'] is not None: remove = remove | {'w','m'}
    if tokens and tokens[-1] in ('b', 'c'): tokens = tokens[:-1]
    return [t for t in tokens if t not in remove and not re.fullmatch(r'u\d{2}', t)]


def name_evidence(first, second, aliases=(), sport=None, competition=None):
    a, b = _team(first), _team(second)
    ca, cb = _core(a['name']), _core(b['name'])
    sa, sb = set(ca), set(cb)
    shared = sa & sb
    weight = lambda t: .15 if t in GENERIC or len(t) == 1 else 1.0
    score = sum(weight(t) for t in shared) / max(sum(weight(t) for t in sa | sb), 1)
    kind, compatible = 'UNRELATED', False
    if not ca or not cb:
        kind = 'MISSING'
    elif normalize(a['name']) == normalize(b['name']):
        kind, compatible = 'EXACT', True
    elif sorted(ca) == sorted(cb):
        kind, compatible = 'CANONICAL_MATCH', True
    elif any(normalize(x.get('sport')) == normalize(sport) and normalize(x.get('competition')) == normalize(competition)
             and x.get('approved') is True and normalize(x.get('source')) == normalize(a['name'])
             and normalize(x.get('target')) == normalize(b['name']) for x in aliases):
        kind, compatible = 'ALIAS_MATCH', True
    elif ''.join(ca) == ''.join(cb):
        kind, compatible = 'TOKEN_SPLIT', True
    elif sa <= sb or sb <= sa:
        kind, compatible = 'TOKEN_CONTAINMENT', True
    elif len(ca) == len(cb) and all(x == y or (len(x) == 1 and y.startswith(x))
                                  or (len(y) == 1 and x.startswith(y)) for x, y in zip(ca, cb)):
        kind, compatible = 'INITIALS', True
    elif shared - GENERIC and any(len(t) > 2 for t in shared - GENERIC):
        kind, compatible = 'SHARED_CORE_CONTEXT_ONLY', True
    distinctive = sorted(t for t in shared if t not in GENERIC and len(t) > 1)
    # No edit-distance or arbitrary single shared word can establish compatibility.
    strong = compatible and bool(distinctive) and (kind in ('EXACT', 'CANONICAL_MATCH', 'ALIAS_MATCH', 'TOKEN_SPLIT') or score >= .65)
    return dict(feed=a, page=b, kind=kind, compatible=compatible, strong=strong,
                shared_distinctive_tokens=distinctive, similarity=round(score, 4))


def marker_evidence(name, gender=None):
    a, b = name['feed'], name['page']
    result = {}
    for key in DIMENSIONS:
        x, y = a['dimensions'][key], b['dimensions'][key]
        inferred = False
        if key == 'gender' and gender:
            if (x is not None and x != gender) or (y is not None and y != gender):
                result[key] = dict(status='CONFLICT', feed=x, page=y, competition=gender)
                continue
            inferred = x is None or y is None
            x, y = x or gender, y or gender
        status = 'AGREE' if x == y and x is not None else 'UNKNOWN' if x is None and y is None else 'NEEDS_RECHECK'
        if 'CONTRADICTORY' in (x, y): status = 'CONFLICT'
        elif x is not None and y is not None and x != y:
            status = 'CONFLICT'
            if key == 'squad_tier' and b['source'] in ('ocr', 'unknown') and not b['reread_used']:
                status = 'NEEDS_RECHECK'
        result[key] = dict(status=status, feed=x, page=y, supplied_by_competition=inferred)
        if key == 'squad_tier' and status == 'NEEDS_RECHECK':
            result[key]['request'] = 'Independent enhanced crop reread of the home/away header tier; preserve both readings'
    return result


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.utcoffset() is not None else None
    except (ValueError, TypeError): return None


def _fingerprint(value):
    if not isinstance(value, dict): return None
    try:
        market = {'ML': 'MONEYLINE', '1X2': 'MONEYLINE', 'TOTAL': 'TOTALS', 'ASIAN_HANDICAP': 'SPREAD'}.get(value['market'], value['market'])
        if market not in ('MONEYLINE', 'SPREAD', 'TOTALS'): return None
        side = value['side']; period = value['period']
        outcomes = ('OVER', 'UNDER') if market == 'TOTALS' else ('HOME', 'DRAW', 'AWAY') if market == 'MONEYLINE' else ('HOME', 'AWAY')
        if side not in outcomes or not period: return None
        line = None if value.get('line') in (None, '') else Decimal(str(value['line']))
        if market != 'MONEYLINE' and (line is None or not line.is_finite()): return None
        if market == 'MONEYLINE' and line is not None: return None
        prices = {k: Decimal(str(v)) for k, v in value['prices'].items()}
        if side not in prices or any(k not in outcomes for k in prices) or any(not v.is_finite() or v < 1 for v in prices.values()): return None
        return dict(market=market, side=side, period=period, line=line, prices=prices)
    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation): return None


def fingerprint_evidence(alert, page, event_id, prior_snapshots=(), captured_at=None):
    a, b = _fingerprint(alert), _fingerprint(page)
    out = dict(alert_market_fingerprint=alert, page_market_fingerprint=page, fingerprint_match='UNAVAILABLE')
    if isinstance(alert,dict) and isinstance(page,dict):
        labels={'ML':'MONEYLINE','1X2':'MONEYLINE','TOTAL':'TOTALS','ASIAN_HANDICAP':'SPREAD'}
        am=labels.get(alert.get('market'),alert.get('market'));pm=labels.get(page.get('market'),page.get('market'))
        if am in ('MONEYLINE','SPREAD','TOTALS') and pm in ('MONEYLINE','SPREAD','TOTALS') and am!=pm:
            return dict(out,fingerprint_match='CONFLICT',reason='Market differs')
    if a is None or b is None: return out
    structural = ('market', 'side', 'period')
    if any(a[k] != b[k] for k in structural):
        return dict(out, fingerprint_match='CONFLICT', reason='Market, side or period differs')
    same = lambda x, y: x['line'] == y['line'] and all(y['prices'].get(k) == v for k, v in x['prices'].items())
    if same(a, b): return dict(out, fingerprint_match='MATCHES')
    for old in prior_snapshots:
        p = _fingerprint(old.get('fingerprint'))
        before, after = _time(old.get('observed_at')), _time(captured_at)
        if (old.get('independently_observed') is True and event_id and old.get('event_id') == event_id
                and before and after and before < after and p and all(a[k] == p[k] for k in structural) and same(a, p)):
            return dict(out, fingerprint_match='MOVED_PLAUSIBLY',
                        reason='Original snapshot independently captured on this event; current quote differs',
                        prior_observed_at=old['observed_at'])
    return dict(out, fingerprint_match='CONFLICT', reason='Line/price snapshot differs without corroborating history')


def resolve(alert, page, *, kickoff_tolerance_seconds=120, aliases=(), competition_mappings=()):
    """Return a diagnostic verdict and every evidence check; never mutate inputs.

    event_id_observed means the actual destination event ID was observed separately.
    Alternatively a recorded direct-link navigation with a captured unique event
    page is an anchor, explicitly labelled as such rather than a read-back URL.
    A bare copied URL or `anchored=True` is insufficient. Missing competition,
    capture/fingerprint or competitor evidence is never filled from the alert.
    """
    if not 0 <= kickoff_tolerance_seconds <= 300: raise ValueError('Kickoff tolerance must be 0..300 seconds')
    evidence, conflicts, missing, rereads = {}, [], [], []
    def check(key, status, **facts):
        evidence[key] = dict(status=status, **facts)
        if status == 'CONFLICT': conflicts.append(key)
        elif status == 'NEEDS_RECHECK': rereads.append(key)
        elif status == 'UNKNOWN': missing.append(key)
    aid, pid = alert.get('event_id'), page.get('event_id')
    for side, record in [('alert', alert), ('page', page)]:
        if record.get('event_url'):
            url_id = direct_event_id(record['event_url'])
            expected = aid if side == 'alert' else pid or page.get('requested_event_id')
            check(side+'_url', 'AGREE' if url_id and (not expected or url_id == expected) else 'CONFLICT',
                  url=record['event_url'], extracted_event_id=url_id)
    linked_capture = (page.get('direct_link_capture') is True and aid and page.get('requested_event_id') == aid
                      and page.get('page_type') == 'event' and page.get('unique_event') is True)
    check('event_id', 'CONFLICT' if aid and pid and aid != pid else 'AGREE' if aid and pid and page.get('event_id_observed') is True or linked_capture else 'UNKNOWN',
          requested=aid, observed=pid, independently_observed=page.get('event_id_observed'),
          direct_link_capture=bool(linked_capture), basis='observed destination ID' if page.get('event_id_observed') else 'recorded direct-link navigation plus captured unique event page' if linked_capture else 'unverified')
    check('event_page', 'CONFLICT' if page.get('page_type') in ('home', 'search', 'generic', 'closed') or page.get('prematch') is False
          else 'AGREE' if page.get('page_type') == 'event' and page.get('prematch') is True and page.get('unique_event') is True else 'UNKNOWN',
          page_type=page.get('page_type'), unique_event=page.get('unique_event'), prematch=page.get('prematch'))
    check('competing_event', 'AGREE' if type(page.get('competitor_count')) is int and page['competitor_count'] == 0 else 'NEEDS_RECHECK' if page.get('competitor_count') else 'UNKNOWN',
          count=page.get('competitor_count'))
    sport_a, sport_b = normalize(alert.get('sport')), normalize(page.get('sport'))
    check('sport', 'AGREE' if sport_a and sport_a == sport_b else 'CONFLICT' if sport_a and sport_b else 'UNKNOWN', feed=sport_a, page=sport_b)
    first, second = _time(alert.get('kickoff')), _time(page.get('kickoff'))
    delta = abs((first-second).total_seconds()) if first and second else None
    check('kickoff', 'UNKNOWN' if delta is None else 'AGREE' if delta <= kickoff_tolerance_seconds else 'CONFLICT',
          feed=alert.get('kickoff'), page=page.get('kickoff'), difference_seconds=delta, tolerance_seconds=kickoff_tolerance_seconds)
    ac, pc = normalize(alert.get('competition')), normalize(page.get('competition'))
    country = normalize(alert.get('country'))
    pc_without_country = pc[len(country)+1:] if country and pc.startswith(country+' ') else pc
    for body in BODY_PREFIXES.get(sport_a, ()):
        if pc_without_country.startswith(body+' '): pc_without_country=pc_without_country[len(body)+1:]
    mapped = any(x.get('approved') is True and normalize(x.get('sport')) == sport_a
                 and normalize(x.get('country')) == country and normalize(x.get('source')) == ac
                 and normalize(x.get('target')) == pc for x in competition_mappings)
    # Country prefixes and numeral/word ordering do not change the league label.
    # No translation, league-level collapse or fuzzy competition match is used.
    league_tokens = lambda value: sorted('division' if t == 'div' else t for t in value.split())
    comp_agrees = bool(ac and pc and (league_tokens(ac) == league_tokens(pc_without_country) or mapped))
    # Different labels are not proof of different competitions. Only conflicting
    # protected attributes/numbered divisions or explicit independent IDs prove it.
    ad, pd = dimensions(ac), dimensions(pc)
    protected_conflict = any(ad[k] and pd[k] and ad[k] != pd[k] for k in ('gender','age_group'))
    nums = lambda v: set(re.findall(r'\b\d+\b', v))
    division_conflict = bool(nums(ac) and nums(pc_without_country) and nums(ac) != nums(pc_without_country))
    comp_id_conflict = bool(alert.get('competition_id') and page.get('competition_id') and alert['competition_id'] != page['competition_id'])
    check('competition', 'CONFLICT' if protected_conflict or division_conflict or comp_id_conflict else 'AGREE' if comp_agrees else 'UNKNOWN',
          feed=ac, page=pc, approved_mapping=mapped, reason='compatible label' if comp_agrees else 'unmapped label or conflicting independent evidence')
    fg = fingerprint_evidence(alert.get('market_fingerprint'), page.get('market_fingerprint'), pid or page.get('requested_event_id'),
                              page.get('prior_snapshots') or (), page.get('captured_at'))
    check('market_fingerprint', 'AGREE' if fg['fingerprint_match'] in ('MATCHES','MOVED_PLAUSIBLY')
          else 'UNKNOWN' if fg['fingerprint_match']=='UNAVAILABLE' else fg['fingerprint_match'], **fg)
    context_gender = dimensions(ac)['gender'] if comp_agrees else None
    home = name_evidence(alert.get('home'), page.get('home'), aliases, sport_a, ac)
    away = name_evidence(alert.get('away'), page.get('away'), aliases, sport_a, ac)
    for side, names in (('home',home), ('away',away)):
        evidence[side+'_name'] = names
        for key, facts in marker_evidence(names, context_gender).items():
            # Both unknown is recorded but not a fabricated contradiction.
            if facts['status'] == 'UNKNOWN': evidence[side+'_'+key] = facts
            else: check(side+'_'+key, **facts)
    reverse_h = name_evidence(alert.get('home'), page.get('away'))
    reverse_a = name_evidence(alert.get('away'), page.get('home'))
    reversed_pair = (reverse_h['compatible'] and reverse_a['compatible'] and (reverse_h['strong'] or reverse_a['strong'])
                     and not (home['compatible'] and away['compatible']))
    symmetric = (reverse_h['strong'] and reverse_a['strong'] and home['strong'] and away['strong']) or (
        bool(normalize(home['page']['name'])) and normalize(home['page']['name']) == normalize(away['page']['name']))
    check('orientation', 'CONFLICT' if reversed_pair or page.get('orientation') == 'reversed' else 'NEEDS_RECHECK' if symmetric
          else 'AGREE' if page.get('orientation') == 'home_away' else 'UNKNOWN', reversed_pair=reversed_pair, ambiguous_pair=symmetric)
    # An unshared nickname can be linked to this one observed event only, not a
    # global club alias. The opposite name must have distinctive corroboration.
    contextual_nickname = False
    # A nickname with no shared core needs explicit event-scoped corroboration.
    # Strong opponent + generic nickname alone cannot establish the second club.
    for proof in page.get('name_relationships') or ():
        side = proof.get('side'); names = home if side=='home' else away if side=='away' else None
        if (names and names['kind']=='UNRELATED' and proof.get('independent') is True
                and proof.get('event_id') == aid and aid
                and normalize(proof.get('feed')) == normalize(names['feed']['name'])
                and normalize(proof.get('page')) == normalize(names['page']['name'])
                and proof.get('source')):
            names['kind']='EVENT_SCOPED_RELATIONSHIP';names['compatible']=True
            names['relationship_source']=proof['source'];contextual_nickname=True
    ordinary = home['compatible'] and away['compatible']
    if not ordinary: missing.append('names_incomplete_or_unrelated')
    if conflicts: verdict = CONFLICT
    elif rereads: verdict = RECHECK
    elif missing: verdict = AMBIGUOUS
    elif home['kind'] == away['kind'] == 'EXACT': verdict = CONFIRMED
    else: verdict = VARIANT
    return dict(verdict=verdict, evidence=evidence, conflicts=conflicts, needs_recheck=rereads, missing_evidence=missing,
                nickname_event_context_only=contextual_nickname, permanent_aliases_created=[],
                scope='offline record linkage; no execution integration')
