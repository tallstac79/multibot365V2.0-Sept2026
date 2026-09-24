"""Team/event identity registry (Milestone B6/B7): alias candidates with a strict promotion policy, and a
cache of resolved Bet365 events keyed by fixture and kick-off.

The phone's resolver (EventIdentity) reports an ALIAS_CANDIDATE whenever a verified event shows a team
under a bookmaker naming variant. Candidates are recorded here with their evidence and are promoted to
usable aliases only under the policy below; promoted aliases (and the cached names of an already
resolved fixture) travel to the phone with each instruction as `aliases`.

Promotion policy (auto):
  * confidence "deterministic" (event link resolved, kick-off agrees, opponent exact, variant score >= 0.85)
    -> promoted on first sight;
  * confidence "high" (same evidence, score >= 0.70) -> promoted after PROMOTE_HIGH_AFTER sightings;
  * anything else stays "candidate" for review and is never used automatically.
Every promotion is audited. A sighting whose bookmaker name differs from an existing promoted alias for
the same source name demotes it to "review" (conflict).
"""
import json
from datetime import datetime, timedelta

from core.pipeline_store import iso

PROMOTE_HIGH_AFTER = 2
EVENT_CACHE_TTL_HOURS = 36      # a cached event is only reused for the SAME kick-off, and not after it is long gone


def _key(name):
    return ' '.join((name or '').lower().split())


class IdentityRegistry:
    def __init__(self, store):
        self.store = store

    # ------------------------------------------------------------------ alias candidates
    def record_candidate(self, db, sport, source_name, bookmaker_name, evidence, confidence, instruction_id=None):
        """Record one sighting; returns the candidate's status after this sighting."""
        source, bookmaker = _key(source_name), _key(bookmaker_name)
        if not source or not bookmaker or source == bookmaker:
            return None
        now = iso(self.store.clock())
        conflict = db.execute("SELECT id, bookmaker_name, status FROM alias_candidates WHERE sport=? AND source_name=? AND bookmaker_name<>? "
                              "AND status='promoted'", (sport, source, bookmaker)).fetchone()
        if conflict:
            db.execute("UPDATE alias_candidates SET status='review', last_seen=? WHERE id=?", (now, conflict['id']))
            self.store.audit(db, 'ALIAS_DEMOTED', dict(sport=sport, source=source, was=conflict['bookmaker_name'], now=bookmaker,
                                                       reason='conflicting bookmaker name'), instruction_id)
        row = db.execute('SELECT * FROM alias_candidates WHERE sport=? AND source_name=? AND bookmaker_name=?',
                         (sport, source, bookmaker)).fetchone()
        confidence = confidence if confidence in ('deterministic', 'high') else 'review'
        if row is None:
            db.execute('INSERT INTO alias_candidates(sport,source_name,bookmaker_name,evidence,confidence,status,first_seen,last_seen,times_seen) '
                       'VALUES (?,?,?,?,?,?,?,?,1)', (sport, source, bookmaker, json.dumps(evidence, default=str), confidence, 'candidate', now, now))
            row = db.execute('SELECT * FROM alias_candidates WHERE sport=? AND source_name=? AND bookmaker_name=?', (sport, source, bookmaker)).fetchone()
        else:
            best = 'deterministic' if 'deterministic' in (row['confidence'], confidence) else ('high' if 'high' in (row['confidence'], confidence) else 'review')
            db.execute('UPDATE alias_candidates SET evidence=?, confidence=?, last_seen=?, times_seen=times_seen+1 WHERE id=?',
                       (json.dumps(evidence, default=str), best, now, row['id']))
            row = db.execute('SELECT * FROM alias_candidates WHERE id=?', (row['id'],)).fetchone()
        if row['status'] == 'candidate' and self._promotable(row):
            db.execute("UPDATE alias_candidates SET status='promoted', promoted_at=? WHERE id=?", (now, row['id']))
            self.store.audit(db, 'ALIAS_PROMOTED', dict(sport=sport, source=source, bookmaker=bookmaker, confidence=row['confidence'],
                                                        times_seen=row['times_seen']), instruction_id)
            return 'promoted'
        return row['status']

    @staticmethod
    def _promotable(row):
        if row['confidence'] == 'deterministic':
            return True
        if row['confidence'] == 'high':
            return row['times_seen'] >= PROMOTE_HIGH_AFTER
        return False

    def promoted_aliases(self, db, sport, names):
        """{feed name (lower): bookmaker name} for the given feed names."""
        out = {}
        for name in names:
            row = db.execute("SELECT bookmaker_name FROM alias_candidates WHERE sport=? AND source_name=? AND status='promoted' "
                             "ORDER BY promoted_at DESC LIMIT 1", (sport, _key(name))).fetchone()
            if row:
                out[_key(name)] = row['bookmaker_name']
        return out

    def review_queue(self, db):
        return [dict(r) for r in db.execute("SELECT * FROM alias_candidates WHERE status IN ('candidate','review') ORDER BY last_seen DESC")]

    # ------------------------------------------------------------------ event cache
    def record_event(self, db, sport, feed_home, feed_away, kickoff_utc, event_url, bookmaker_home, bookmaker_away, competition=None):
        if not (sport and feed_home and feed_away and kickoff_utc and event_url):
            return
        db.execute('INSERT INTO event_cache(sport,feed_home,feed_away,kickoff_utc,event_url,bookmaker_home,bookmaker_away,competition,resolved_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(sport,feed_home,feed_away,kickoff_utc) DO UPDATE SET event_url=excluded.event_url, '
                   'bookmaker_home=excluded.bookmaker_home, bookmaker_away=excluded.bookmaker_away, competition=excluded.competition, '
                   'resolved_at=excluded.resolved_at',
                   (sport, _key(feed_home), _key(feed_away), kickoff_utc, event_url, bookmaker_home, bookmaker_away, competition, iso(self.store.clock())))

    def cached_event(self, db, sport, feed_home, feed_away, kickoff_utc):
        """The resolved Bet365 event for this exact fixture and kick-off, or None. Never a stale kick-off."""
        if not kickoff_utc:
            return None
        row = db.execute('SELECT * FROM event_cache WHERE sport=? AND feed_home=? AND feed_away=? AND kickoff_utc=?',
                         (sport, _key(feed_home), _key(feed_away), kickoff_utc)).fetchone()
        if row is None:
            return None
        try:
            kickoff = datetime.fromisoformat(kickoff_utc).replace(tzinfo=self.store.clock().tzinfo)
        except ValueError:
            return None
        if self.store.clock() > kickoff + timedelta(hours=EVENT_CACHE_TTL_HOURS):
            return None
        return dict(row)

    def aliases_for(self, db, sport, feed_home, feed_away, kickoff_utc=None):
        """Aliases to send with an instruction: promoted registry entries plus the names Bet365 used for this
        same fixture before (only where they differ from the feed's)."""
        aliases = self.promoted_aliases(db, sport, [feed_home, feed_away])
        cached = self.cached_event(db, sport, feed_home, feed_away, kickoff_utc)
        if cached:
            for feed, book in ((feed_home, cached['bookmaker_home']), (feed_away, cached['bookmaker_away'])):
                if book and _key(feed) != _key(book):
                    aliases.setdefault(_key(feed), book)
        return aliases
