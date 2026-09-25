"""Is a competition independently established as women's? (pure; tests: test_competition_gender.py)

Used only to let the phone's identity resolver accept a feed team name WITHOUT a women's marker for a
Bet365 team WITH one ("Explosivas de Moca" vs "Explosivas de Moca (W)") when the competition itself says
women's, the other team, the pairing and the kick-off agree. Nothing here strips markers; an unknown
competition is not women's and the resolver keeps failing closed.
"""
import re

# Whole-token matches (case-insensitive) in the competition / competition_full string.
WOMEN_TOKENS = {'women', "women's", 'womens', 'ladies', 'female', 'femenino', 'femenina', 'feminine', 'feminin',
                'feminino', 'feminina', 'frauen', 'damen', 'dames', 'wnba', 'wnbl', 'wbbl', 'wcba', 'wkbl', 'lfb', 'bsnf',
                'wabl', 'wsbl', 'w'}
_TOKEN = re.compile(r"[a-z0-9']+")


def womens_competition(*names):
    """True when any of the competition strings carries an explicit women's token."""
    for name in names:
        if not name:
            continue
        tokens = set(_TOKEN.findall(str(name).lower().replace('é', 'e')))
        if tokens & WOMEN_TOKENS or '(w)' in str(name).lower():
            return True
    return False
