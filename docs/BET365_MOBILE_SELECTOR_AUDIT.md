# Bet365 Mobile Selector Audit

Generated: 2026-09-20T12:18:46.390089+00:00
Surface: Android Chrome via CDP (logged_in=True)
Browser: Chrome/126.0.6478.110

## Summary

- Reusable unchanged: **5**
- Need modification: **22**
- Unusable (no proposal yet): **66**
- Expected fail while logged-in (login UI): **6**
- Football 1X2/AH/totals discoverable: `{'1x2': True, 'spread': False, 'totals': True}`
- Basketball ML/spread/totals discoverable: `{'ml': True, 'spread': True, 'totals': True}`
- Betslip fields discoverable: **True**

## Rules followed

- No stake entry, no Place Bet, no wager, no challenge bypass.
- Selections clicked only to open betslip; betslip cleared after tests.

## Table

| Element | Old Selector | Mobile Works? | Proposed Selector | Confidence | Notes |
|---|---|---|---|---|---|
| SESSION balance | `//div[@class="hm-MainHeaderMembersWide_Balance hm-Balance "]` | NO (needs new) | `text=£0.00` | low | modify |
| SESSION members/account menu | `//div[@class="hm-MainHeaderMembersWide_MembersMenuIcon "]` | NO (needs new) | `text=Members` | low | modify |
| SESSION logout | `//div[@class="ul-MembersLinkButton_Text " and text()="Log Out"]` | NO (needs new) | `text=Log Out` | low | modify |
| SESSION logged-out indicator | `//div[contains(@class, "hm-MainHeaderRHSLoggedOutWide_Login ")]` | N/A (logged in) | `text=Log In` | low | expected_fail_logged_in |
| PUBLIC login button | `//div[contains(@class, "hm-MainHeaderRHSLoggedOutWide_Login ")]` | N/A (logged in) | `text=Log In` | low | expected_fail_logged_in |
| PUBLIC login container | `//div[@class="hm-MainHeaderRHSLoggedOutWide_LoginContainer "]` | N/A (logged in) | `text=Login` | low | expected_fail_logged_in |
| PUBLIC username | `//input[@class="lms-StandardLogin_Username "]` | N/A (logged in) | `text=Username` | low | expected_fail_logged_in |
| PUBLIC password | `//input[@class="lms-StandardLogin_Password "]` | N/A (logged in) | `text=Password` | low | expected_fail_logged_in |
| PUBLIC login submit | `.lms-LoginButton_Text` | N/A (logged in) | `text=Log In` | low | expected_fail_logged_in |
| SEARCH control/bar | `//div[contains(@class, "c-SearchBar_Inner")]` | NO (needs new) | `[aria-label="Search"]` | med | modify |
| SEARCH input | `//input[@class="sml-SearchTextInput "]` | NO (needs new) | `[aria-label="Search"]` | med | modify |
| SEARCH view event text | `//div[@class="ssm-SiteSearchTextHeaderTextLabel " and contains(text(), "View ...` | NO (needs new) | `text=View Event` | low | modify |
| SEARCH view event bets | `//div[@class="ssm-SiteSearchBetsHeaderTextLabel " and contains(text(), "View ...` | NO (needs new) | `text=View Event` | low | modify |
| NAV all sports | `//div[contains(@class, "hm-HeaderMenuItem ")]/div[text()="All Sports" or text...` | NO (needs new) | `text=Home All Sports In-Play My Bets Casino` | low | modify |
| NAV in-play | `//div[contains(@class, "hm-HeaderMenuItem ")]/div[text()="In-Play" or text()=...` | NO (needs new) | `text=In-Play` | low | modify |
| BETSLIP stake input | `//div[contains(@class, "bsf-StakeBox_StakeValue-input ")]` | YES | `[class*="bsf-StakeBox"]` | med | unchanged |
| BETSLIP place bet | `//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden")) a...` | NO (needs new) | `[class*="bsf-BetButtonsWrapper"]` | med | modify |
| BETSLIP accept changes text | `//div[contains(@class, "AcceptButton_Text")]` | YES | `text=Accept` | low | unchanged |
| BETSLIP done | `//div[contains(@class, "ReceiptContent_Done")]` | NO (needs new) | `text=Done` | low | modify |
| BETSLIP remove | `//div[contains(@class, "-RemoveButton")]` | NO (needs new) | `text=Remove` | low | modify |
| BETSLIP remove all | `//div[contains(@class, "edit")]/div/div[contains(@class, "ControlBar") and co...` | NO (needs new) | `text=Remove all` | low | modify |
| MARKET nav buttons | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]` | NO (needs new) | `text=Popular` | low | modify |
| MARKET asian lines tab | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="As...` | NO (needs new) | `text=Asian Lines` | low | modify |
| MARKET popular tab | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Po...` | NO (needs new) | `text=Popular` | low | modify |
| EVENT header label | `//div[contains(@class, "sph-EventHeader_Label ")]/span` | NO | `` | none | unusable |
| AH team1 | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancest...` | NO (needs new) | `text=Asian Handicap` | low | modify |
| GOAL LINE over | `//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::d...` | NO (needs new) | `text=Goal Line` | low | modify |
| MY BETS tab | `//div[contains(@class, "hm-MainHeaderTabRow_MyBetsLabel ")]` | NO (needs new) | `text=Home All Sports In-Play My Bets Casino` | low | modify |
| MY BETS button | `//div[contains(@class, "hm-HeaderMenuItemMyBets ")]` | NO (needs new) | `text=Home All Sports In-Play My Bets Casino` | low | modify |
| FOOTBALL nav | `` | NO (needs new) | `text=Football` | low | modify |
| BASKETBALL nav | `` | NO (needs new) | `text=Basketball` | low | modify |
| CONST ACCEPT_BUTTON_DISABLED | `//div[contains(@class, "AcceptButton ") and contains(@class, "Disabled")]` | NO | `` | none | unusable |
| CONST ACCEPT_BUTTON_MESSAGE | `//div[contains(@class, "AcceptButton_Message")]` | NO | `` | none | unusable |
| CONST ACCEPT_BUTTON_VISIBLE | `//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden"))]` | NO | `` | none | unusable |
| CONST ACCEPT_CHANGES_AND_PLACE | `//div[contains(@class, "AcceptButton_Text") and contains(text(), "Place Bet")]` | YES | `` | none | unchanged |
| CONST ACCEPT_CHANGES_NO_PLACE | `//div[contains(@class, "AcceptButton_Text") and not(contains(text(), "Place B...` | NO | `` | none | unusable |
| CONST AH_CORNERS_TEAM1 | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap Corners"]...` | NO | `` | none | unusable |
| CONST AH_CORNERS_TEAM2 | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap Corners"]...` | NO | `` | none | unusable |
| CONST AH_TEAM1_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancest...` | NO | `` | none | unusable |
| CONST AH_TEAM2_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancest...` | NO | `` | none | unusable |
| CONST AH_TEAM2_VALUE | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Handicap"]//ancest...` | NO | `` | none | unusable |
| CONST ALL_BETS_TAB | `//div[contains(@class, "HeaderButton ") and text()="All"]` | NO | `` | none | unusable |
| CONST ALT_AH_BUTTON | `//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") an...` | NO | `` | none | unusable |
| CONST ALT_AH_OPEN | `//div[contains(@class, "MarketGroupButton") and contains(@class, "MarketGroup...` | NO | `` | none | unusable |
| CONST ALT_GOAL_LINE_BUTTON | `//div[contains(@class, "MarketGroup") and contains(@class, "Button_Text ") an...` | NO | `` | none | unusable |
| CONST ALT_GOAL_LINE_OPEN | `//div[contains(@class, "MarketGroupButton") and contains(@class, "MarketGroup...` | NO | `` | none | unusable |
| CONST ASIAN_TOTAL_CORNERS_OVER | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Total Corners"]//a...` | NO | `` | none | unusable |
| CONST ASIAN_TOTAL_CORNERS_UNDER | `//div[contains(@class, "MarketGroup ")]//div[text()="Asian Total Corners"]//a...` | NO | `` | none | unusable |
| CONST BET_BUILDER_TAB | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Be...` | NO | `` | none | unusable |
| CONST CASH_OUT_TAB | `//div[contains(@class, "HeaderButton ") and text()="Cash Out"]` | NO | `` | none | unusable |
| CONST CLOSE_BUTTON | `//div[@class="sml-CloseButton "]` | NO | `` | none | unusable |
| CONST CLOSE_BUTTON2 | `//div[@class="pm-MessageOverlayCloseButton "]` | NO | `` | none | unusable |
| CONST COOKIES_ACCEPT | `//div[@class="ccm-CookieConsentPopup_Accept "]` | NO | `` | none | unusable |
| CONST COOKIES_ACCEPT2 | `//button[text()="Accept All"]` | NO | `` | none | unusable |
| CONST CORNERS_RACE_VALUES | `//div[contains(@class, "MarketGroupWithIconsButton_Text ") and text()="Corner...` | NO | `` | none | unusable |
| CONST CORNERS_TAB | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Co...` | NO | `` | none | unusable |
| CONST CORNER_MATCH_BET_TEAM1 | `//div[contains(@class, "MarketGroup ")]//div[text()="Corner Match Bet"]//ance...` | NO | `` | none | unusable |
| CONST CORNER_MATCH_BET_TEAM2 | `//div[contains(@class, "MarketGroup ")]//div[text()="Corner Match Bet"]//ance...` | NO | `` | none | unusable |
| CONST DNB_TEAM1 | `//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor:...` | NO | `` | none | unusable |
| CONST DNB_TEAM1_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor:...` | NO | `` | none | unusable |
| CONST DNB_TEAM2 | `//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor:...` | NO | `` | none | unusable |
| CONST DNB_TEAM2_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Draw No Bet"]//ancestor:...` | NO | `` | none | unusable |
| CONST EVENT_TIMESTAMP | `//div[contains(@class, "sph-ExtraData_TimeStamp ")]` | NO | `` | none | unusable |
| CONST EVENT_WRAPPER_LABEL | `//div[contains(@class, "sph-EventWrapper_Label ")]` | NO | `` | none | unusable |
| CONST FIXTURE_TEAM1 | `//div[contains(@class, "sph-FixturePodHeader_BottomInfoWrapper ")]/div[1]/div` | NO | `` | none | unusable |
| CONST FIXTURE_TEAM2 | `//div[contains(@class, "sph-FixturePodHeader_BottomInfoWrapper ")]/div[3]/div` | NO | `` | none | unusable |
| CONST GOAL_LINE_OVER_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::d...` | NO | `` | none | unusable |
| CONST GOAL_LINE_UNDER | `//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::d...` | NO | `` | none | unusable |
| CONST GOAL_LINE_UNDER_ACTIVE | `//div[contains(@class, "MarketGroup ")]//div[text()="Goal Line"]//ancestor::d...` | NO | `` | none | unusable |
| CONST INACTIVITY_LOGGED_OUT | `//div[@class="wlm-InactivityLoggedOutPopup_Close "]` | NO | `` | none | unusable |
| CONST INSUFFICIENT_FUNDS_CLOSE | `//div[contains(@class, "qd-CrossButton ")]` | NO | `` | none | unusable |
| CONST INTRO_POPUP_CLOSE | `//div[@class="iip-IntroductoryPopup_Cross"]` | NO | `` | none | unusable |
| CONST IP_ASIAN_LINES | `//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Asian...` | NO | `` | none | unusable |
| CONST IP_BET_BUILDER | `//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Bet B...` | NO | `` | none | unusable |
| CONST IP_CORNERS | `//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Corne...` | NO | `` | none | unusable |
| CONST IP_EVENT_HEADER | `//div[contains(@class, "ipe-EventHeader_Fixture ")]` | NO | `` | none | unusable |
| CONST IP_PLAYER | `//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Playe...` | NO | `` | none | unusable |
| CONST IP_POPULAR | `//div[contains(@class, "ipe-GridHeaderTabLink ")]/div[contains(text(), "Popul...` | NO | `` | none | unusable |
| CONST LAST_LOGIN_BUTTON | `//div[@class="llm-LastLoginModule_Button "]` | NO | `` | none | unusable |
| CONST LIVE_NOW_TAB | `//div[contains(@class, "HeaderButton ") and text()="Live Now"]` | NO | `` | none | unusable |
| CONST MULTIPLE_REMOVE | `//div[contains(@class, "-MultipleHeaderRemoveButton")]` | NO | `` | none | unusable |
| CONST MY_BETS_COUNT | `//span[@class="hm-HeaderMenuItemMyBets_MyBetsCount "]` | NO | `` | none | unusable |
| CONST NOT_INTERESTED | `//div[contains(@class, "pm-FreeBetsPushGraphicCloseButton") and (contains(tex...` | NO | `` | none | unusable |
| CONST NO_SEARCH_RESULTS | `//div[@class="ssm-DynamicSearchPane_NoResults "]` | NO | `` | none | unusable |
| CONST NO_THANKS | `//button[@class="default_Button text-button" and text()="No thanks"]` | NO | `` | none | unusable |
| CONST PLAYER_TAB | `//div[contains(@class, "sph-MarketGroupNavBarButton ")]/div[@data-content="Pl...` | NO | `` | none | unusable |
| CONST REALITY_CHECK_REMAIN | `//div[@class="alm-ActivityLimitStayButton " and text()="Remain Logged In"]` | NO | `` | none | unusable |
| CONST REMAIN_LOGGED_IN | `//div[@class="alm-InactivityAlertRemainButton "]` | NO | `` | none | unusable |
| CONST RESTRICTIONS_CONTINUE | `//button[@class="accept-button" and text()="Continue"]` | NO | `` | none | unusable |
| CONST RESTRICTIONS_MODAL | `//div[@class="modal partialAuthentication general-account-restrictions"]` | NO | `` | none | unusable |
| CONST SETTLED_TAB | `//div[contains(@class, "HeaderButton ") and text()="Settled"]` | NO | `` | none | unusable |
| CONST SHOW_OPTIONS | `//div[contains(@class, "-EditButton") and contains(@class, "-DefaultContent_T...` | YES | `` | none | unchanged |
| CONST UNSETTLED_TAB | `//div[contains(@class, "HeaderButton ") and text()="Unsettled"]` | NO | `` | none | unusable |
| CONST UPDATE_STAKE_BUTTON | `//div[contains(@class, "AcceptButton ") and not(contains(@class, "Hidden"))]/...` | NO | `` | none | unusable |
| CONST UP_ARROW | `//div[contains(@class, "-DefaultContent_Close")]` | YES | `` | none | unchanged |
| CONST VIDEO_MATCH_PITCH | `//div[@class="lv-ButtonBar_MatchLive "]/div` | NO | `` | none | unusable |
| CONST VIDEO_PITCH_BUTTON | `//div[contains(@class, "MediaButtonLoader_ML1 ")]` | NO | `` | none | unusable |
| CONST VIDEO_PLAYING | `//div[contains(@class, "fpm-FloatableMediaPlayerControls-playing")]` | NO | `` | none | unusable |
| CONST VIDEO_STOP_BUTTON | `//div[@class="fpm-PlayButton "]` | NO | `` | none | unusable |

## Football notes

```json
{
  "ok": true,
  "notes": [
    "Locator.click: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"text=Football\").first\n    - locator resolved to <div class=\"crr-3d\">Football</div>\n  - attempting click action\n    - waiting for element to be visible, enabled and stable\n",
    "Locator.click: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"//div[normalize-space()=\\\"Football\\\"]\").first\n    - locator resolved to <div class=\"crr-6\">\u2026</div>\n  - attempting click action\n    - waiting for element to be visible, enabled and stable\n",
    "opened=Bournemouth",
    "selection_odds=None"
  ],
  "markets": {
    "1X2/moneyline": {
      "discover": [
        {
          "text": "Scores & Results Live Scores Results",
          "tag": "div",
          "id": null,
          "className": "frm-d1 frm-f5",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Scores & Results",
          "tag": "div",
          "id": null,
          "className": "frm-98",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Results",
          "tag": "div",
          "id": null,
          "className": "frm-a9",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Results",
          "tag": "div",
          "id": null,
          "className": "frm-b7",
          "role": null,
          "aria": null,
          "data": {}
        }
      ],
      "old": {
        "selector": "//div[contains(@class, \"MarketGroup\") and contains(@class, \"Button_Text \") and text()=\"Match Result\"]",
        "count": 0,
        "visible": 0,
        "ok": false,
        "error": null,
        "sample": null
      },
      "proposed": "text=Scores & Results Live Scores Results"
    },
    "asian_handicap": {
      "discover": [],
      "old": {
        "selector": "//div[contains(@class, \"MarketGroup\") and contains(@class, \"Button_Text \") and text()=\"Asian Handicap\"]",
        "count": 0,
        "visible": 0,
        "ok": false,
        "error": null,
        "sample": null
      },
      "proposed": ""
    },
    "totals": {
      "discover": [
        {
          "text": "Total Stake\u00a30.00\u00a30.00Total StakePlace Bet\u00a30.00Total To ReturnFee\u00a30.00Place Bet",
          "tag": "div",
          "id": null,
          "className": "bsf-BetButtonsWrapper ",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Total Stake\u00a30.00\u00a30.00Total StakePlace Bet\u00a30.00Total To ReturnFee\u00a30.00",
          "tag": "div",
          "id": null,
          "className": "bsf-PlaceBetButton bsf-PlaceBetButton_Disabled bsf-PlaceBetButton-ccyprefixsymbol ",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Total Stake\u00a30.00\u00a30.00Total StakePlace Bet\u00a30.00Total To ReturnFee\u00a30.00",
          "tag": "div",
          "id": null,
          "className": "bsf-PlaceBetButton_Wrapper",
          "role": null,
          "aria": null,
          "data": {}
        }
      ],
      "old": {
        "selector": "//div[contains(@class, \"MarketGroup\") and contains(@class, \"Button_Text \") and text()=\"Goal Line\"]",
        "count": 0,
        "visible": 0,
        "ok": false,
        "error": null,
        "sample": null
      },
      "proposed": "[class*=\"bsf-BetButtonsWrapper\"]"
    }
  },
  "betslip": {
    "stake": {
      "selector": "//div[contains(@class, \"bsf-StakeBox_StakeValue-input \")]",
      "count": 1,
      "visible": 0,
      "ok": true,
      "error": null,
      "sample": null
    },
    "place_bet": {
      "selector": "//div[contains(@class, \"AcceptButton \") and not(contains(@class, \"Hidden\")) and not(contains(@class, \"Disabled\"))]/div[contains(@class, \"AcceptButton_Text\") and contains(text(), \"Place Bet\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "accept": {
      "selector": "//div[contains(@class, \"AcceptButton_Text\")]",
      "count": 1,
      "visible": 0,
      "ok": true,
      "error": null,
      "sample": null
    },
    "remove": {
      "selector": "//div[contains(@class, \"-RemoveButton\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "remove_all": {
      "selector": "//div[contains(@class, \"edit\")]/div/div[contains(@class, \"ControlBar\") and contains(text(), \"Remove all\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "done": {
      "selector": "//div[contains(@class, \"ReceiptContent_Done\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "discover": [
      {
        "text": "Set Stake",
        "
```

## Basketball notes

```json
{
  "ok": true,
  "notes": [
    "Locator.click: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"text=Basketball\").first\n    - locator resolved to <div class=\"crr-3d\">Basketball</div>\n  - attempting click action\n    - waiting for element to be visible, enabled and stable\n",
    "Locator.click: Timeout 3000ms exceeded.\nCall log:\n  - waiting for locator(\"//div[normalize-space()=\\\"Basketball\\\"]\").first\n    - locator resolved to <div class=\"crr-6\">\u2026</div>\n  - attempting click action\n    - waiting for element to be visible, enabled and stable\n",
    "opened=Sun 20 Sep\nBournemouth\nLiverpool\n14:00\n1\n3.10\nX\n3.70\n2\n2.20",
    "selection_odds=3.10"
  ],
  "markets": {
    "moneyline": {
      "discover": [
        {
          "text": "Money Line 2.80 1.45",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Money Line 3.00 1.40",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Money Line 2.25 1.66",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Money Line 4.25 1.23",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        }
      ],
      "proposed": "text=Money Line 2.80 1.45"
    },
    "spread": {
      "discover": [
        {
          "text": "Spread +4.5 1.90 -4.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Money Line 2.80 1.45",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Spread +5.5 1.90 -5.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Money Line 3.00 1.40",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        }
      ],
      "proposed": "text=Spread +4.5 1.90 -4.5 1.90"
    },
    "totals": {
      "discover": [
        {
          "text": "Total O 47.5 1.90 U 47.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Total O 41.5 1.90 U 41.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Total O 45.5 1.90 U 45.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        },
        {
          "text": "Total O 45.5 1.90 U 45.5 1.90",
          "tag": "div",
          "id": null,
          "className": "cpr-35",
          "role": null,
          "aria": null,
          "data": {}
        }
      ],
      "proposed": "text=Total O 47.5 1.90 U 47.5 1.90"
    }
  },
  "betslip": {
    "stake": {
      "selector": "//div[contains(@class, \"bsf-StakeBox_StakeValue-input \")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "place_bet": {
      "selector": "//div[contains(@class, \"AcceptButton \") and not(contains(@class, \"Hidden\")) and not(contains(@class, \"Disabled\"))]/div[contains(@class, \"AcceptButton_Text\") and contains(text(), \"Place Bet\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "remove": {
      "selector": "//div[contains(@class, \"-RemoveButton\")]",
      "count": 0,
      "visible": 0,
      "ok": false,
      "error": null,
      "sample": null
    },
    "discover": [],
    "clear": "no clear controls found"
  }
}
```
