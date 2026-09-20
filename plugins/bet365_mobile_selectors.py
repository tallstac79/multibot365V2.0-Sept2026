"""
Bet365 MOBILE (Android Chrome) selectors.

Source of truth: docs/BET365_MOBILE_SELECTOR_AUDIT.md (Phase 2, 2026-09-20).

Rules:
- Prefer verified mobile selectors from the audit / probe JSON.
- Do NOT invent selectors. Anything not verified on mobile is marked UNVERIFIED.
- Desktop Wide selectors are kept only as fallbacks where noted — they failed on
  mobile in Phase 2 and must not be treated as proven.

Status tags in comments:
  VERIFIED   — observed working (or proposed from live discover) in Phase 2
  UNVERIFIED — not confirmed on mobile yet (e.g. login form while logged out)
  FALLBACK   — old desktop selector kept for probe discovery only
"""

# ============================================================
# SESSION
# ============================================================

# VERIFIED (Phase 2 session detect): currency balance text + mobile class
BALANCE = '[class*="sln-d0"]'  # VERIFIED: discover className sln-d0 text £0.00
BALANCE_ALT = '[class*="hrm-b"]'  # VERIFIED alt discover
BALANCE_TEXT_RE = r"[£$€]\s*[\d,.]+"  # VERIFIED via body text match

# VERIFIED indicators while logged in
MY_BETS = 'text=My Bets'  # VERIFIED: <a class="tbm-d tbm-9e">My Bets</a>
MY_BETS_CSS = 'a.tbm-d'  # VERIFIED class token from discover
LOGGED_IN_MEMBERS_CLASS = '[class*="Members"],[class*="Balance"]'  # VERIFIED probe heuristic

# VERIFIED 2026-09-20 live: header person/account icon opens account sheet
MEMBERS_MENU = 'header button.hrm-6c >> nth=-1'  # VERIFIED: rightmost header button (person icon)
MEMBERS_MENU_CSS = 'button.hrm-6c'  # VERIFIED (also used by balance; prefer last)
MEMBERS_MENU_ICON = '[class*="hrm-ff"]'  # VERIFIED account icon wrapper
MEMBERS_MENU_FALLBACK = '//div[@class="hm-MainHeaderMembersWide_MembersMenuIcon "]'  # FALLBACK desktop

LOGOUT = 'text=Log Out'  # VERIFIED after account menu open
LOGOUT_CSS = 'div.zsa-d'  # VERIFIED class on Log Out row
LOGOUT_FALLBACK = '//div[@class="ul-MembersLinkButton_Text " and text()="Log Out"]'  # FALLBACK

# Logged-out / login entry — VERIFIED 2026-09-20
LOGGED_OUT_INDICATOR = 'text=Log In'  # VERIFIED
LOGIN_BUTTON = 'text=Log In'  # VERIFIED
LOGIN_BUTTON_FALLBACK = '//div[contains(@class, "hm-MainHeaderRHSLoggedOutWide_Login ")]'  # FALLBACK
JOIN_BUTTON = 'text=Join'  # VERIFIED

# Login form — VERIFIED 2026-09-20 after programmatic open of header Log In
USERNAME_INPUT = 'input.slm2-8'  # VERIFIED placeholder Username or email address
USERNAME_INPUT_ALT = 'input[placeholder*="Username" i]'  # VERIFIED
PASSWORD_INPUT = 'input.slm2-c2'  # VERIFIED placeholder Password
PASSWORD_INPUT_ALT = 'input[type="password"]'  # VERIFIED
LOGIN_SUBMIT = 'button.slm2-f9'  # VERIFIED form Log In submit
LOGIN_SUBMIT_ALT = 'css=button.slm2-f9'  # VERIFIED
LOGIN_CONTAINER = '[class*="slm2-"]'  # VERIFIED mobile login module
LOGIN_BUTTON_HEADER = 'button.hrm-35'  # VERIFIED header Log In
# Desktop leftovers kept as last-resort fallbacks
USERNAME_INPUT_DESKTOP = '//input[contains(@class,"lms-StandardLogin_Username")]'  # FALLBACK
PASSWORD_INPUT_DESKTOP = '//input[contains(@class,"lms-StandardLogin_Password")]'  # FALLBACK
LOGIN_SUBMIT_DESKTOP = '.lms-LoginButton_Text'  # FALLBACK

# ============================================================
# COMMON LOGGED-IN POPUPS (desktop classes; mobile UNVERIFIED)
# ============================================================
INTRO_POPUP_CLOSE = '//div[@class="iip-IntroductoryPopup_Cross"]'  # UNVERIFIED
COOKIES_ACCEPT = '//div[@class="ccm-CookieConsentPopup_Accept "]'  # UNVERIFIED
COOKIES_ACCEPT2 = 'button:has-text("Accept All")'  # UNVERIFIED
REMAIN_LOGGED_IN = '//div[@class="alm-InactivityAlertRemainButton "]'  # UNVERIFIED
REALITY_CHECK_REMAIN = '//div[@class="alm-ActivityLimitStayButton " and text()="Remain Logged In"]'  # UNVERIFIED
NO_THANKS = 'button:has-text("No thanks")'  # UNVERIFIED
CLOSE_BUTTON = '//div[@class="sml-CloseButton "]'  # UNVERIFIED
CLOSE_BUTTON2 = '//div[@class="pm-MessageOverlayCloseButton "]'  # UNVERIFIED
LAST_LOGIN_BUTTON = '//div[@class="llm-LastLoginModule_Button "]'  # UNVERIFIED
NOT_INTERESTED = '//div[contains(@class, "pm-FreeBetsPushGraphicCloseButton")]'  # UNVERIFIED
INACTIVITY_LOGGED_OUT = '//div[@class="wlm-InactivityLoggedOutPopup_Close "]'  # UNVERIFIED
RESTRICTIONS_MODAL = '//div[@class="modal partialAuthentication general-account-restrictions"]'  # UNVERIFIED
RESTRICTIONS_CONTINUE = 'button.accept-button:has-text("Continue")'  # UNVERIFIED

# ============================================================
# SEARCH
# ============================================================
SEARCH_BUTTON = '[aria-label="Search"]'  # VERIFIED med: button.sln-a1
SEARCH_BUTTON_CSS = 'button.sln-a1'  # VERIFIED
SEARCH_INPUT = '[aria-label="Search"]'  # VERIFIED proposed (same control opens search)
SEARCH_INPUT_FALLBACK = '//input[contains(@class,"sml-SearchTextInput")]'  # FALLBACK
SEARCH_RESULT_ROW = '[class*="ssm-"], [class*="SiteSearch"]'  # UNVERIFIED generic
EVENT_LINK = 'text=View Event'  # UNVERIFIED (proposed; not confirmed open)

# ============================================================
# MARKETS / NAV
# ============================================================
FOOTBALL_NAV = 'text=Football'  # VERIFIED present (click stability issues noted)
BASKETBALL_NAV = 'text=Basketball'  # VERIFIED present
IN_PLAY_NAV = 'text=In-Play'  # UNVERIFIED low proposal
ALL_SPORTS_NAV = 'text=All Sports'  # UNVERIFIED low proposal

MARKET_HEADING = '[class*="MarketGroup"], [class*="cpr-35"]'  # UNVERIFIED / partial
SELECTION = '[class*="Participant"], [class*="cpr-"]'  # UNVERIFIED generic
ODDS = None  # UNVERIFIED — Phase 2 used numeric text click heuristic, not a stable selector
SUSPENDED = '[class*="Suspended"]'  # UNVERIFIED

# Basketball market text patterns seen live (examples, not unique selectors)
BB_MONEYLINE_HINT = "Money Line"  # VERIFIED text present in discover
BB_SPREAD_HINT = "Spread"  # VERIFIED
BB_TOTAL_HINT = "Total"  # VERIFIED

# Football
FB_1X2_HINT = "Match Result"  # UNVERIFIED on mobile event page
FB_AH_HINT = "Asian Handicap"  # NOT confirmed that run
FB_TOTALS_HINT = "Goal Line"  # partial / noisy

MARKET_NAV_POPULAR = 'text=Popular'  # UNVERIFIED proposed
MARKET_NAV_ASIAN = 'text=Asian Lines'  # UNVERIFIED proposed

# ============================================================
# BETSLIP
# ============================================================
BETSLIP_OPEN = '[class*="bsf-"]'  # VERIFIED presence when slip open
BETSLIP_FIXTURE = None  # UNVERIFIED — not isolated in audit
BETSLIP_SELECTION = None  # UNVERIFIED
BETSLIP_MARKET = None  # UNVERIFIED
BETSLIP_LINE = None  # UNVERIFIED
BETSLIP_ODDS = None  # UNVERIFIED

STAKE_INPUT = '//div[contains(@class, "bsf-StakeBox_StakeValue-input ")]'  # VERIFIED YES
STAKE_INPUT_CSS = '[class*="bsf-StakeBox"]'  # VERIFIED YES

REMOVE_SELECTION = 'text=Remove'  # UNVERIFIED proposed
CLEAR_BETSLIP = 'text=Remove all'  # UNVERIFIED proposed
REMOVE_BUTTON_FALLBACK = '//div[contains(@class, "-RemoveButton")]'  # FALLBACK

# Present in DOM — MUST NOT click during Phase 3A
PLACE_BET = '[class*="bsf-BetButtonsWrapper"]'  # VERIFIED wrapper present
PLACE_BET_BUTTON = '[class*="bsf-PlaceBetButton"]'  # VERIFIED class present
PLACE_BET_DESKTOP = '//div[contains(@class, "AcceptButton_Text") and contains(text(), "Place Bet")]'  # VERIFIED count>0 once

DONE_SUCCESS = 'text=Done'  # UNVERIFIED proposed
DONE_FALLBACK = '//div[contains(@class, "ReceiptContent_Done")]'  # FALLBACK

ACCEPT_CHANGES = 'text=Accept'  # VERIFIED low / AcceptButton_Text ok

SHOW_OPTIONS = '//div[contains(@class, "-EditButton") and contains(@class, "-DefaultContent_TitleEdit")]'  # VERIFIED YES
UP_ARROW_CLOSE = '//div[contains(@class, "-DefaultContent_Close")]'  # VERIFIED YES

# ============================================================
# HELPERS
# ============================================================

# Ordered candidate lists for the session probe (first match wins).
LOGIN_BUTTON_CANDIDATES = [
    LOGIN_BUTTON_HEADER,
    'css=button.hrm-35',
    LOGIN_BUTTON,
    LOGIN_BUTTON_FALLBACK,
]

USERNAME_CANDIDATES = [
    USERNAME_INPUT,
    USERNAME_INPUT_ALT,
    'css=input[type="email"]',
    'css=input[placeholder*="Username" i]',
    USERNAME_INPUT_DESKTOP,
]

PASSWORD_CANDIDATES = [
    PASSWORD_INPUT,
    PASSWORD_INPUT_ALT,
    PASSWORD_INPUT_DESKTOP,
]

LOGIN_SUBMIT_CANDIDATES = [
    LOGIN_SUBMIT,
    LOGIN_SUBMIT_ALT,
    'css=button.slm2-f9',
    LOGIN_SUBMIT_DESKTOP,
]

MEMBERS_MENU_CANDIDATES = [
    MEMBERS_MENU_ICON,
    'css=header button.hrm-6c >> nth=-1',
    'css=header .hrm-ff',
    MEMBERS_MENU_CSS,
    MEMBERS_MENU,
    '[class*="Members"]',
    MEMBERS_MENU_FALLBACK,
]

LOGOUT_CANDIDATES = [
    LOGOUT_CSS,
    LOGOUT,
    'text=Logout',
    'text=Sign Out',
    LOGOUT_FALLBACK,
]

BALANCE_CANDIDATES = [
    BALANCE,
    BALANCE_ALT,
    '[class*="Balance"]',
]

POPUP_CLOSE_CANDIDATES = [
    COOKIES_ACCEPT2,
    COOKIES_ACCEPT,
    INTRO_POPUP_CLOSE,
    NO_THANKS,
    CLOSE_BUTTON,
    CLOSE_BUTTON2,
    LAST_LOGIN_BUTTON,
    NOT_INTERESTED,
    REMAIN_LOGGED_IN,
    REALITY_CHECK_REMAIN,
]
