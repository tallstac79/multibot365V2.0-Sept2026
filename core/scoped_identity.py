"""Competition-scoped aliases supported by independent, corroborated event observations.

Legacy aliases remain in the database for audit and are not consumed by this registry.
Neither repeated instruction delivery nor a confidence label creates independent proof.
"""
import hashlib
import json
from core.identity_registry import IdentityRegistry as LegacyRegistry, _key
from core.pipeline_store import iso


class IdentityRegistry(LegacyRegistry):
    def record_candidate(self, db, sport, source_name, bookmaker_name, evidence, confidence, instruction_id=None, competition=None):
        source, book, competition = _key(source_name), _key(bookmaker_name), _key(competition)
        if not source or not book or source == book: return None
        stamp = iso(self.store.clock())
        context = evidence.get('event_context') or {}
        identity = evidence.get('identity') or {}
        trusted = bool(competition and context.get('kickoff_utc') and context.get('home') and context.get('away')
                       and context.get('competition') and evidence.get('event_url')
                       and identity.get('kickoff_known') is True and identity.get('kickoff_agrees') is True
                       and not identity.get('reversed') and identity.get('verdict') == 'HIGH_CONFIDENCE_EVENT_MATCH'
                       and confidence in ('high', 'deterministic'))
        db.execute("INSERT OR IGNORE INTO scoped_alias_candidates(sport,competition,source_name,bookmaker_name,status,first_seen,last_seen) VALUES (?,?,?,?,'candidate',?,?)",
                   (sport, competition, source, book, stamp, stamp))
        row = db.execute('SELECT * FROM scoped_alias_candidates WHERE sport=? AND competition=? AND source_name=? AND bookmaker_name=?',
                         (sport, competition, source, book)).fetchone()
        if trusted:
            key = hashlib.sha256(json.dumps([sport, competition, context['kickoff_utc'], _key(context['home']), _key(context['away'])]).encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO alias_observations VALUES (?,?,?)', (row['id'], key, stamp))
        count = db.execute('SELECT COUNT(*) FROM alias_observations WHERE candidate_id=?', (row['id'],)).fetchone()[0]
        conflict = db.execute("SELECT id FROM scoped_alias_candidates WHERE sport=? AND competition=? AND source_name=? AND bookmaker_name<>? AND status IN ('promoted','review')",
                              (sport, competition, source, book)).fetchone()
        status = row['status']
        if trusted and conflict:
            db.execute("UPDATE scoped_alias_candidates SET status='review' WHERE id=?", (conflict['id'],))
            status = 'review'
            self.store.audit(db, 'ALIAS_DEMOTED', dict(source=source, competition=competition, reason='conflicting independently corroborated name'), instruction_id)
        elif status == 'candidate' and count >= 2:
            status = 'promoted'
            self.store.audit(db, 'ALIAS_PROMOTED', dict(source=source, competition=competition, independent_events=count), instruction_id)
        db.execute('UPDATE scoped_alias_candidates SET evidence=?,confidence=?,status=?,last_seen=?,times_seen=?,promoted_at=? WHERE id=?',
                   (json.dumps(evidence), confidence, status, stamp, count, stamp if status=='promoted' else None, row['id']))
        return status

    def promoted_aliases(self, db, sport, names, competition=None):
        if not competition: return {}
        out = {}
        for name in names:
            rows = db.execute("SELECT bookmaker_name FROM scoped_alias_candidates WHERE sport=? AND competition=? AND source_name=? AND status='promoted'",
                              (sport, _key(competition), _key(name))).fetchall()
            if len(rows) == 1: out[_key(name)] = rows[0]['bookmaker_name']
        return out

    def review_queue(self, db):
        return [dict(r) for r in db.execute("SELECT * FROM scoped_alias_candidates WHERE status IN ('candidate','review') ORDER BY last_seen DESC")]

    def record_event(self, db, sport, feed_home, feed_away, kickoff_utc, event_url, bookmaker_home, bookmaker_away, competition=None):
        if competition:
            super().record_event(db, sport, feed_home, feed_away, kickoff_utc, event_url, bookmaker_home, bookmaker_away, competition)

    def cached_event(self, db, sport, feed_home, feed_away, kickoff_utc, competition=None):
        if not competition: return None
        row = super().cached_event(db, sport, feed_home, feed_away, kickoff_utc)
        return row if row and _key(row['competition']) == _key(competition) else None

    def aliases_for(self, db, sport, feed_home, feed_away, kickoff_utc=None, competition=None):
        aliases = self.promoted_aliases(db, sport, [feed_home,feed_away], competition)
        cached = self.cached_event(db, sport, feed_home, feed_away, kickoff_utc, competition)
        if cached:
            for feed, book in ((feed_home,cached['bookmaker_home']), (feed_away,cached['bookmaker_away'])):
                if book and _key(feed) != _key(book): aliases.setdefault(_key(feed), book)
        return aliases
