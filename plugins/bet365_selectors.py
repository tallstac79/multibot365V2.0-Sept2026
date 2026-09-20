"""
All Bet365 DOM selectors in one place.
When Bet365 updates their UI, only this file needs to change.
"""

# ============================================================
# LOGIN
# ============================================================
LOGIN_BUTTON = '//div[contains(@class, "hm-MainHeaderRHSLoggedOutWide_Login ")]'
LOGIN_CONTAINER = '//div[@class="hm-MainHeaderRHSLoggedOutWide_LoginContainer "]'
USERNAME_INPUT = '//input[@class="lms-StandardLogin_Username "]'
PASSWORD_INPUT = '//input[@class="lms-StandardLogin_Password "]'
CONFIRM_LOGIN_BUTTON = '.lms-LoginButton_Text'
BALANCE_DISPLAY = '//div[@class="hm-MainHeaderMembersWide_Balance hm-Balance "]'
MY_BETS_COUNT = '//span[@class="hm-HeaderMenuItemMyBets_MyBetsCount "]'

# ============================================================
# POPUPS & MODALS
# ============================================================
INTRO_POPUP_CLOSE = '//div[@class="iip-IntroductoryPopup_Cross"]'
COOKIES_ACCEPT = '//div[@class="ccm-CookieConsentPopup_Accept "]'
COOKIES_ACCEPT2 = '//button[text()="Accept All"]'
REMAIN_LOGGED_IN = '//div[@class="alm-InactivityAlertRemainButton "]'
REALITY_CHECK_REMAIN = '//div[@class="alm-ActivityLimitStayButton " and text()="Remain Logged In"]'
NO_THANKS = '//button[@class="default_Button text-button" and text()="No thanks"]'
CLOSE_BUTTON = '//div[@class="sml-CloseButton "]'
CLOSE_BUTTON2 = '//div[@class="pm-MessageOverlayCloseButton "]'
LAST_LOGIN_BUTTON = '//div[@class="llm-LastLoginModule_Button "]'
NOT_INTERESTED = '//div[contains(@class, "pm-FreeBetsPushGraphicCloseButton") and (contains(text(), "Not Interested"))]'
INACTIVITY_LOGGED_OUT = '//div[@class="wlm-InactivityLoggedOutPopup_Close "]'

# Restrictions
RESTRICTIONS_MODAL = '//div[@class="modal partialAuthentication general-account-restrictions"]'
RESTRICTIONS_CONTINUE = '//button[@class="accept-button" and text()="Continue"]'

# ============================================================
# NAVIGATION
# ============================================================
ALL_SPORTS = '//div[contains(@class, "hm-HeaderMenuItem ")]/div[text()="All Sports" or text()="Όλα τα Σπορ"]'
IN_PLAY = '//div[contains(@class, "hm-HeaderMenuItem ")]/div[text()="In-Play" or text()="Σε-Εξέλιξη"]'
MEMBERS_MENU = '//div[@class="hm-MainHeaderMembersWide_MembersMenuIcon "]'
LOG_OUT = '//div[@class="ul-MembersLinkButton_Text " and text()="Log Out"]'

# ============================================================
# SEARCH
# ============================================================
SEARCH_BAR = '//div[contains(@class, "c-SearchBar_Inner")]'
SEARCH_INPUT = '//input[@class="sml-SearchTextInput "]'
NO_SEARCH_RESULTS = '//div[@class="ssm-DynamicSearchPane_NoResults "]'
VIEW_EVENT_TEXT = '//div[@class="ssm-SiteSearchTextHeaderTextLabel " and contains(text(), "View Event")]'
VIEW_EVENT_BETS = '//div[@class="ssm-SiteSearchBetsHeaderTextLabel " and contains(text(), "View Event")]'

# ============================================================
# BET SLIP
# ============================================================
STAKE_INPUT = '//div[contains(@class, "bsf-StakeBox_StakeValue-input ")]'
PLACE_BET_BUTTON = '//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden")) and not(contains(@class, "Disabled"))]/div[contains(@class, "AcceptButton_Text") and contains(text(), "Place Bet")]'
ACCEPT_CHANGES_TEXT = '//div[contains(@class, "AcceptButton_Text")]'
ACCEPT_CHANGES_NO_PLACE = '//div[contains(@class, "AcceptButton_Text") and not(contains(text(), "Place Bet"))]'
ACCEPT_CHANGES_AND_PLACE = '//div[contains(@class, "AcceptButton_Text") and contains(text(), "Place Bet")]'
ACCEPT_BUTTON_DISABLED = '//div[contains(@class, "AcceptButton ") and contains(@class, "Disabled")]'
ACCEPT_BUTTON_VISIBLE = '//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden"))]'
ACCEPT_BUTTON_MESSAGE = '//div[contains(@class, "AcceptButton_Message")]'
UPDATE_STAKE_BUTTON = '//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden"))]/div[contains(@class, "AcceptButton_Text") and contains(text(), "Update Stake")]'
DONE_BUTTON = '//div[contains(@class, "ReceiptContent_Done")]'
INSUFFICIENT_FUNDS_CLOSE = '//div[contains(@class, "qd-CrossButton ")]'

# Bet slip cleanup
REMOVE_BUTTON = '//div[contains(@class, "-RemoveButton")]'
MULTIPLE_REMOVE = '//div[contains(@class, "-MultipleHeaderRemoveButton")]'
UP_ARROW = '//div[contains(@class, "-DefaultContent_Close")]'
SHOW_OPTIONS = '//div[contains(@class, "-EditButton") and contains(@class, "-DefaultContent_TitleEdit") and contains(text(), "Show Options")]'
REMOVE_ALL = '//div[contains(@class, "edit")]/div/div[contains(@class, "ControlBar") and contains(text(), "Remove all")]'

# ============================================================
# EVENT PAGE — MARKET NAVIGATION
# ============================================================
MARKET_NAV_BUTTONS = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]'
BET_BUILDER_TAB = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Bet Builder"]'
PLAYER_TAB = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Player"]'
ASIAN_LINES_TAB = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Asian Lines"]'
CORNERS_TAB = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Corners"]'
POPULAR_TAB = '//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Popular"]'

# In-Play event tabs
IP_BET_BUILDER = '//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Bet Builder")]'
IP_PLAYER = '//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Player")]'
IP_ASIAN_LINES = '//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Asian Lines")]'
IP_CORNERS = '//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Corners")]'
IP_POPULAR = '//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Popular")]'

# Match header
EVENT_HEADER_LABEL = '//div[contains(@class, "sph-EventHeader_Label ")]/span'
EVENT_WRAPPER_LABEL = '//div[contains(@class, "sph-EventWrapper_Label ")]'
EVENT_TIMESTAMP = '//div[contains(@class, "sph-ExtraData_TimeStamp ")]'
IP_EVENT_HEADER = '//div[contains(@class, "ipe-EventHeader_Fixture ")]'
FIXTURE_TEAM1 = '//div[contains(@class, "sph-FixturePodHeader_BottomInfoWrapper ")]/div[1]/div'
FIXTURE_TEAM2 = '//div[contains(@class, "sph-FixturePodHeader_BottomInfoWrapper ")]/div[3]/div'

# ============================================================
# GOAL LINE MARKETS
# ============================================================
def goal_line_values(position: int) -> str:
    return f'//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[1]/div[{position}]/div'

GOAL_LINE_OVER = '//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[2]/div/span'
GOAL_LINE_UNDER = '//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[3]/div/span'
GOAL_LINE_OVER_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[2]/div[not(contains(@class,"Suspended"))]/span'
GOAL_LINE_UNDER_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[3]/div[not(contains(@class,"Suspended"))]/span'

# Alternative Goal Line
ALT_GOAL_LINE_OPEN = '//div[contains(@class, "MarketGroupButton") and contains(@class, "MarketGroup_Open ")]/div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="Alternative Goal Line"]'
ALT_GOAL_LINE_BUTTON = '//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="Alternative Goal Line"]'

def alt_goal_line_value(position: int) -> str:
    return f'//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="Alternative Goal Line"]/parent::*/parent::*/div[2]/div/div[1]/child::*[contains(@class, "Participant")][{position}]/div[1]'

def alt_goal_line_over(position: int) -> str:
    return f'//div[contains(@class, "MarketGroup ")]//div[text()="Alternative Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[2]/div[contains(@class, "Participant")][{position}]/span'

def alt_goal_line_under(position: int) -> str:
    return f'//div[contains(@class, "MarketGroup ")]//div[text()="Alternative Goal Line"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[3]/div[contains(@class, "Participant")][{position}]/span'

# ============================================================
# ASIAN HANDICAP MARKETS
# ============================================================
AH_TEAM1_VALUE = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[1]/div/span[2]'
AH_TEAM2_VALUE = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[2]/div/span[2]'
AH_TEAM1_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[1]/div[not(contains(@class,"Suspended"))]/span[2]'
AH_TEAM2_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[2]/div[not(contains(@class,"Suspended"))]/span[2]'

ALT_AH_OPEN = '//div[contains(@class, "MarketGroupButton") and contains(@class, "MarketGroup_Open ")]/div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="Alternative Asian Handicap"]'
ALT_AH_BUTTON = '//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="Alternative Asian Handicap"]'

# ============================================================
# DRAW NO BET
# ============================================================
DNB_TEAM1 = '//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[1]/span[2]'
DNB_TEAM2 = '//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[2]/span[2]'
DNB_TEAM1_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[1][not(contains(@class,"Suspended"))]/span[2]'
DNB_TEAM2_ACTIVE = '//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[2][not(contains(@class,"Suspended"))]/span[2]'

# ============================================================
# CORNERS MARKETS
# ============================================================
CORNERS_RACE_VALUES = '//div[contains(@class, "MarketGroupWithIconsButton_Text ") and text()="Corners Race"]/parent::*/parent::*/parent::*/parent::*/div[2]/div/div[1]/div[contains(@class, "Participant")]/div'
AH_CORNERS_TEAM1 = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap Corners"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[1]/div/span[2]'
AH_CORNERS_TEAM2 = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap Corners"]//ancestor::div[contains(@class, "MarketGroup ")]/div[2]/div/div[2]/div/span[2]'
ASIAN_TOTAL_CORNERS_OVER = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Total Corners"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[2]/div/span'
ASIAN_TOTAL_CORNERS_UNDER = '//div[contains(@class, "MarketGroup ")]//div[text()="Asian Total Corners"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div[3]/div/span'
CORNER_MATCH_BET_TEAM1 = '//div[contains(@class, "MarketGroup ")]//div[text()="Corner Match Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[1]/span[2]'
CORNER_MATCH_BET_TEAM2 = '//div[contains(@class, "MarketGroup ")]//div[text()="Corner Match Bet"]//ancestor::div[contains(@class, "MarketGroup ")]/div/div/div/div[3]/span[2]'

# ============================================================
# SEARCH RESULT BET SELECTORS
# ============================================================
def search_bet_description(category_lower: str) -> str:
    return f'//div[@class="ssm-SiteSearchBetsMarketGroupButton_Description " and contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{category_lower}")]'

def search_bet_participant(category_lower: str, tip: str) -> str:
    return f'{search_bet_description(category_lower)}//ancestor::div[@class="ssm-SiteSearchMarketGroup "]//child::div[contains(@class, "ssm-SiteSearchBetOnlyParticipant gl-Participant_General gl-Market_General")]/div[1]/div[text()="{tip}"]'

def search_bet_with_odds(category_lower: str, name_lower: str, tip: str) -> str:
    base = '//div[@class="ssm-SiteSearchBetsMarketGroupButton_Description " and contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "' + category_lower + '") and contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "' + name_lower + '")]'
    ancestor = '//ancestor::div[@class="ssm-SiteSearchMarketGroup "]'
    participant = '//child::div[contains(@class, "ssm-SiteSearchBetOnlyParticipant gl-Participant_General gl-Market_General")]'
    tip_part = '/div[1]/div[text()="' + tip + '"]'
    odds_part = '//ancestor::div[contains(@class, "ssm-SiteSearchBetOnlyParticipant gl-Participant_General gl-Market_General")]/div[2]/span'
    return base + ancestor + participant + tip_part + odds_part

# ============================================================
# CATEGORY BUTTON (dynamic)
# ============================================================
def category_button(name: str) -> str:
    return f'//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="{name}"]'

def category_button_open(name: str) -> str:
    return f'//div[contains(@class, "MarketGroup") and contains(@class, "Button ") and contains(@class, "MarketGroup_Open ")]//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") and text()="{name}"]'

# ============================================================
# VIDEO PLAYER (auto-stop)
# ============================================================
VIDEO_PLAYING = '//div[contains(@class, "fpm-FloatableMediaPlayerControls-playing")]'
VIDEO_PITCH_BUTTON = '//div[contains(@class, "MediaButtonLoader_ML1 ")]'
VIDEO_STOP_BUTTON = '//div[@class="fpm-PlayButton "]'
VIDEO_MATCH_PITCH = '//div[@class="lv-ButtonBar_MatchLive "]/div'

# ============================================================
# MY BETS
# ============================================================
MY_BETS_TAB = '//div[contains(@class, "hm-MainHeaderTabRow_MyBetsLabel ")]'
MY_BETS_BUTTON = '//div[contains(@class, "hm-HeaderMenuItemMyBets ")]'
CASH_OUT_TAB = '//div[contains(@class, "HeaderButton ") and text()="Cash Out"]'
LIVE_NOW_TAB = '//div[contains(@class, "HeaderButton ") and text()="Live Now"]'
UNSETTLED_TAB = '//div[contains(@class, "HeaderButton ") and text()="Unsettled"]'
SETTLED_TAB = '//div[contains(@class, "HeaderButton ") and text()="Settled"]'
ALL_BETS_TAB = '//div[contains(@class, "HeaderButton ") and text()="All"]'
