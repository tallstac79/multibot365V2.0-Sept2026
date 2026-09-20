"""
Tip parser — extracts bet details from Telegram messages and OCR text.
Based on CopytipBot's parsing patterns.
"""
import re

# Team name replacements (Bet365 uses different names than tipsters)
TEAM_REPLACEMENTS = {
    "Leicester City": "Leicester",
    "Sheffield United": "Sheff Utd",
    "Manchester United": "Man Utd",
    "Nottingham Forest": "Nottm Forest",
    "Manchester City": "Man City",
    "Wolverhampton": "Wolves",
}

# NBA team mappings
NBA_TEAMS = {
    "ATL Hawks": "Atlanta Hawks", "BOS Celtics": "Boston Celtics",
    "CHA Hornets": "Charlotte Hornets", "CHI Bulls": "Chicago Bulls",
    "CLE Cavaliers": "Cleveland Cavaliers", "DAL Mavericks": "Dallas Mavericks",
    "DEN Nuggets": "Denver Nuggets", "DET Pistons": "Detroit Pistons",
    "GS Warriors": "Golden State Warriors", "HOU Rockets": "Houston Rockets",
    "IND Pacers": "Indiana Pacers", "LA Clippers": "LA Clippers",
    "LA Lakers": "LA Lakers", "MEM Grizzlies": "Memphis Grizzlies",
    "MIL Bucks": "Milwaukee Bucks", "MIN Timberwolves": "Minnesota Timberwolves",
    "NO Pelicans": "New Orleans Pelicans", "NY Knicks": "New York Knicks",
    "OKC Thunder": "Oklahoma City Thunder", "ORL Magic": "Orlando Magic",
    "PHI 76ers": "Philadelphia 76ers", "PHO Suns": "Phoenix Suns",
    "POR Blazers": "Portland Trail Blazers", "SAC Kings": "Sacramento Kings",
    "SA Spurs": "San Antonio Spurs", "TOR Raptors": "Toronto Raptors",
    "UTA Jazz": "Utah Jazz", "WAS Wizards": "Washington Wizards",
}

# NBA stat categories
NBA_CATEGORIES = {
    "points": "Points O/U",
    "assists": "Assists O/U",
    "rebounds": "Rebounds O/U",
    "threes": "Threes Made O/U",
    "blocks": "Blocks O/U",
    "steals": "Steals & Blocks O/U",
    "turnovers": "Turnovers O/U",
    "points race": "points race",
    "assists race": "assists race",
    "rebounds race": "rebounds race",
    "threes race": "threes race",
}


def parse_nba_tip(text: str) -> dict:
    """
    Parse NBA player prop tips like:
    'Marcus Smart: 10+ Points 2.30'
    'Jayson Tatum Over 25.5 Points 1.85'
    """
    result = {
        "player": "",
        "line": 0.0,
        "category": "",
        "direction": "Over",
        "odds": 0.0,
        "stakes": [],
        "min_odd": 0.0,
    }

    # Extract stakes like '1.25u' or '2u'
    stake_matches = re.findall(r'([\d.]+)u', text)
    if stake_matches:
        result["stakes"] = [float(s) for s in stake_matches]

    # Extract minimum odd like 'min: 1.8' or 'Min. 2.0'
    min_match = re.search(r'[Mm]in[:.]?\s*([\d.]+)', text)
    if min_match:
        result["min_odd"] = float(min_match.group(1))

    # Pattern: "Player: 10+ Points 2.30"
    pattern1 = re.match(r'(.+?):\s*(\d+)\+\s*(Points|Assists|Rebounds|Threes|Blocks)\s+([\d.]+)', text)
    if pattern1:
        result["player"] = pattern1.group(1).strip()
        result["line"] = float(pattern1.group(2)) - 0.5  # "10+" means Over 9.5
        result["category"] = NBA_CATEGORIES.get(pattern1.group(3).lower(), pattern1.group(3))
        result["odds"] = float(pattern1.group(4))
        return result

    # Pattern: "Player Over/Under 25.5 Points 1.85"
    pattern2 = re.match(r'(.+?)\s+(Over|Under)\s+([\d.]+)\s+(Points|Assists|Rebounds|Threes|Blocks|Turnovers)\s+([\d.]+)', text, re.I)
    if pattern2:
        result["player"] = pattern2.group(1).strip()
        result["direction"] = pattern2.group(2).capitalize()
        result["line"] = float(pattern2.group(3))
        result["category"] = NBA_CATEGORIES.get(pattern2.group(4).lower(), pattern2.group(4))
        result["odds"] = float(pattern2.group(5))
        return result

    # Pattern: "Player - Over 25.5 Points"
    pattern3 = re.match(r'(.+?)\s*-\s*(Over|Under)\s+([\d.]+)\s*(.*)', text, re.I)
    if pattern3:
        result["player"] = pattern3.group(1).strip()
        result["direction"] = pattern3.group(2).capitalize()
        result["line"] = float(pattern3.group(3))
        rest = pattern3.group(4).strip()
        # Try to get category and odds from rest
        odds_match = re.search(r'([\d.]+)$', rest)
        if odds_match:
            result["odds"] = float(odds_match.group(1))
            rest = rest[:odds_match.start()].strip()
        if rest:
            result["category"] = NBA_CATEGORIES.get(rest.lower(), rest)
        return result

    return result


def parse_football_tip(text: str) -> dict:
    """
    Parse football tips like:
    'Milan v Juventus Over 2.5 1.90'
    'Arsenal - Under 1.5 Team Goals 2.10'
    """
    result = {
        "team1": "",
        "team2": "",
        "match": "",
        "tip": "",
        "category": "",
        "direction": "",
        "line": 0.0,
        "odds": 0.0,
        "stakes": [],
        "half": "match",
    }

    # Extract stakes
    stake_matches = re.findall(r'([\d.]+)u', text)
    if stake_matches:
        result["stakes"] = [float(s) for s in stake_matches]

    # Split by 'v' or 'vs'
    match_split = re.split(r'\bvs?\b', text, flags=re.I)
    if len(match_split) >= 2:
        result["team1"] = match_split[0].strip()
        rest = match_split[1].strip()

        # Extract odds (last number)
        odds_match = re.search(r'([\d.]+)\s*$', rest)
        if odds_match:
            result["odds"] = float(odds_match.group(1))
            rest = rest[:odds_match.start()].strip()

        # Check for Over/Under
        ou_match = re.search(r'(Over|Under)\s*([\d.]+)', rest, re.I)
        if ou_match:
            result["direction"] = ou_match.group(1).capitalize()
            result["line"] = float(ou_match.group(2))
            result["team2"] = rest[:ou_match.start()].strip()
            result["category"] = "Goal Line"
            rest_after = rest[ou_match.end():].strip()
            if rest_after:
                result["category"] = rest_after
        else:
            result["team2"] = rest

    result["match"] = f"{result['team1']} v {result['team2']}"

    # Apply team name replacements
    for full, short in TEAM_REPLACEMENTS.items():
        result["team1"] = result["team1"].replace(full, short)
        result["team2"] = result["team2"].replace(full, short)
        result["match"] = result["match"].replace(full, short)

    # Determine tip string for Bet365
    if result["direction"] and result["line"]:
        result["tip"] = f"{result['direction']} {result['line']}"

    # Check for halves
    if "1st half" in text.lower():
        result["half"] = "1st Half"
    elif "2nd half" in text.lower():
        result["half"] = "2nd Half"

    return result


def parse_bet_builder(text: str) -> dict:
    """
    Parse bet builder / multi-leg tips.
    Handles formats like:
      'Bet Builder: Arsenal v Chelsea
       Saka Over 0.5 Shots on Target
       Havertz Over 1.5 Tackles
       Over 2.5 Goals
       Combined odds: 4.50'

    Or TomsNBA style with multiple player props in one message.
    """
    result = {
        "bet_type": "betBuilder",
        "team1": "",
        "team2": "",
        "match": "",
        "legs": [],
        "odds": 0.0,
        "stakes": [],
        "min_odd": 0.0,
    }

    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]

    # Extract stakes
    stake_matches = re.findall(r'([\d.]+)u', text)
    if stake_matches:
        result["stakes"] = [float(s) for s in stake_matches]

    # Extract minimum odd
    min_match = re.search(r'[Mm]in[:.]?\s*([\d.]+)', text)
    if min_match:
        result["min_odd"] = float(min_match.group(1))

    # Try to find match name (Team1 v Team2)
    for line in lines:
        match_m = re.search(r'(.+?)\s+(?:v|vs)\s+(.+)', line, re.I)
        if match_m:
            result["team1"] = match_m.group(1).strip().rstrip(':').strip()
            result["team2"] = match_m.group(2).strip()
            result["match"] = f"{result['team1']} v {result['team2']}"
            # Apply team name replacements
            for full, short in TEAM_REPLACEMENTS.items():
                result["team1"] = result["team1"].replace(full, short)
                result["team2"] = result["team2"].replace(full, short)
                result["match"] = result["match"].replace(full, short)
            break

    # Extract combined odds (last standalone decimal in the message)
    odds_match = re.search(r'(?:combined|total|@)\s*(?:odds)?[:.]?\s*([\d.]+)', text, re.I)
    if odds_match:
        result["odds"] = float(odds_match.group(1))
    else:
        # Last decimal on its own line or at end
        all_odds = re.findall(r'\b(\d+\.\d+)\b', text)
        if all_odds:
            result["odds"] = float(all_odds[-1])

    # Parse individual legs — each line with Over/Under or player prop pattern
    for line in lines:
        # Skip the match header and odds/stakes lines
        if re.search(r'\b(?:v|vs)\b', line, re.I) and result["match"]:
            continue
        if re.search(r'(?:combined|total|stake|min)', line, re.I):
            continue
        if re.match(r'^\s*[\d.]+\s*$', line):
            continue

        leg = {}

        # Player prop: "PlayerName Over/Under X.X Category"
        player_match = re.match(
            r'(.+?)\s+(Over|Under)\s+([\d.]+)\s+(.*)',
            line, re.I
        )
        if player_match:
            leg["player"] = player_match.group(1).strip()
            leg["direction"] = player_match.group(2).capitalize()
            leg["line"] = float(player_match.group(3))
            cat_text = player_match.group(4).strip()
            # Remove trailing odds if present
            cat_text = re.sub(r'\s+[\d.]+\s*$', '', cat_text)
            leg["category"] = NBA_CATEGORIES.get(cat_text.lower(), cat_text)
            result["legs"].append(leg)
            continue

        # "Player: 10+ Points" format
        colon_match = re.match(r'(.+?):\s*(\d+)\+\s*(.*)', line)
        if colon_match:
            leg["player"] = colon_match.group(1).strip()
            leg["line"] = float(colon_match.group(2)) - 0.5
            leg["direction"] = "Over"
            cat_text = colon_match.group(3).strip()
            cat_text = re.sub(r'\s+[\d.]+\s*$', '', cat_text)
            leg["category"] = NBA_CATEGORIES.get(cat_text.lower(), cat_text)
            result["legs"].append(leg)
            continue

        # Match-level leg: "Over 2.5 Goals"
        match_leg = re.match(r'(Over|Under)\s+([\d.]+)\s+(.*)', line, re.I)
        if match_leg:
            leg["direction"] = match_leg.group(1).capitalize()
            leg["line"] = float(match_leg.group(2))
            leg["category"] = match_leg.group(3).strip()
            result["legs"].append(leg)
            continue

    return result


def parse_generic_tip(text: str) -> dict:
    """Parse a generic tip message and try to extract key info."""
    result = {
        "raw": text,
        "player": "",
        "team1": "",
        "team2": "",
        "match": "",
        "tip": "",
        "category": "",
        "direction": "",
        "line": 0.0,
        "odds": 0.0,
        "stakes": [],
        "min_odd": 0.0,
        "bet_type": "single",
        "legs": [],
    }

    # Check if it's a bet builder (explicit keyword or multiple legs detected)
    text_lower = text.lower()
    is_bet_builder = "bet builder" in text_lower or "betbuilder" in text_lower

    # Also detect multi-leg by counting Over/Under lines
    over_under_lines = len(re.findall(r'(?:^|\n).+(?:Over|Under)\s+[\d.]+', text, re.I))
    if over_under_lines >= 2:
        is_bet_builder = True

    if is_bet_builder:
        bb_result = parse_bet_builder(text)
        if bb_result["legs"]:
            result.update(bb_result)
            return result

    # Try NBA first
    nba_result = parse_nba_tip(text)
    if nba_result["player"]:
        result.update(nba_result)
        return result

    # Try football
    football_result = parse_football_tip(text)
    if football_result["team1"]:
        result.update(football_result)
        return result

    # Fallback — extract what we can
    odds_all = re.findall(r'(\d+\.\d+)', text)
    if odds_all:
        result["odds"] = float(odds_all[-1])  # Last number is usually the odd

    ou_match = re.search(r'(Over|Under)\s*([\d.]+)', text, re.I)
    if ou_match:
        result["direction"] = ou_match.group(1).capitalize()
        result["line"] = float(ou_match.group(2))

    return result
