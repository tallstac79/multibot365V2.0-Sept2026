"""Bet365 desktop betslip vocabulary shared by the visual slip flow (visual_slip.py / workflow.py).

The slip is read from the screen (screenshot + OCR) and Bet365's own addbet response, never from its DOM: the earlier
DOM reader (document.querySelectorAll('.bss-StandardBetslip') ...) ran a class-selector query inside the page before the
selection click, and Bet365 answered the next addbet with {"cs":2,"sr":-1} (evidence/desktop-worker-addbet/). It is
removed. Nothing here ever presses Place Bet.
"""

# Slip market labels per wire market (football as captured / as the phone's HeldSlipIdentity.labels; basketball's are the
# phone's labels - a basketball slip is verified against them and fails closed on anything else).
LABELS = {
    ('football', 'SPREAD'): {'asian handicap', 'alternative asian handicap'},
    ('football', 'TOTAL'): {'goal line', 'alternative goal line', 'goals over/under', 'alternative total goals'},
    ('football', 'MONEYLINE'): {'full time result'},
    ('basketball', 'SPREAD'): {'point spread', 'spread'},
    ('basketball', 'TOTAL'): {'game totals', 'total', 'game total'},
    ('basketball', 'MONEYLINE'): {'money line'},
}

# Slip labels that belong to one page group only (seen on the slip AND in Bet365's addbet 'md', 28 Sep 2026): a quote read
# from the 'Goals Over/Under' group is shown on the slip as 'Total Goals' (Belgium v France, Sweden v Poland, Turkiye v
# Italy, line 2.5). Accepted only for a quote from that group, never for Goal Line / Asian lines.
GROUP_LABELS = {
    ('football', 'Goals Over/Under'): {'total goals'},
}


def money(text):
    try:
        return float(str(text).replace('£', '').replace(',', '').strip())
    except (TypeError, ValueError):
        return None
