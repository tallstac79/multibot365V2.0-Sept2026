# Milestone B — defects found during the supervised proof (25 Sep 2026)

## 1. Bare-host Bet365 event links lost the event-link route (backend, FIXED)
`on-8f79281a7041821a63d6ed18` (Norrkoping Dolphins v Umea Basket, 11:36:43 UTC, SPREAD AWAY +27.5, hold run):
the alert's link was `https://bet365.com/#/AC/B18/C21169978/D19/E26741034/F19/` (no `www.`). `core.pipeline.EVENT_URL`
only accepted `https://www.bet365.com/...`, so the dispatch payload carried no `event_url` and the phone took the
Search route. 27 of 212 links received on 24-25 Sep have the bare host (first seen 23 Sep 13:58 UTC).
Fix: `event_link` normalises the bare host to the `www.` form (path unchanged; the phone's `EventPage.validUrl`
already validates that form). Tests: `tests/test_final_action.py::test_bare_host_event_link_is_normalised_to_the_www_form`.

## 2. Empty search bar refused because the voice icon OCRs as "HO" (phone, FIXED in 0.9.15-search)
Same run, Search route: `search_bar_checks` = `"Search bet365... HO"`, `empty=false` on attempts 0 and 3 →
`TARGET_NOT_FOUND "Search field still holds 'Search bet365... HO' after clear and re-open; not typing"` (fail-closed,
correct given the reading). Frame `on-8f79281a_s014_search_field_3.png`: the bar shows only the placeholder; the
token "HO" [574,172][598,211] is the microphone icon (24 px wide, taller than the text), left of "Close".
Fix: `SearchBar.locate` ignores an icon-sized token (<= 40 px wide) or a single glyph sitting past x=540 (the icon
zone left of Close); typed text starts at the field's left edge, so no query is lost. JVM test on the real frame:
`SearchBarTest.emptyBarWithVoiceIconReadAsHoIsStillEmpty` (+ `typedQueryReachingTheIconZoneIsStillNotEmpty`).
Verification on the phone (`verify-0.9.15/search-tofas-130256.json`): bar read `"Search bet365..."`, `empty=true`,
query typed, `QUERY_VERIFY ok`.

## 3. Search route: casino-only results recovery is fragile (phone, NOT fixed — fallback path only)
`verify-0.9.15/search-tofas-130256.json`: Bet365 returned only Casino results for "Tofas SK Bordo Sportif"
(`#/AX/K9`, single "Casino" chip). The recovery then (a) tapped the OCR-merged bar row for "Close casino search"
(bounds [38,175,682,206] — the query text, which opened the keyboard, not the Close button), (b) fell back to
`open(HOME_URL)`, which opened a further Chrome tab (tab count 4 → 5), (c) tapped Search on the home page while its
header was still laying out (Search moved from y 192 to y 279 within 0.5 s), and (d) the retry frame shows the
Bet365Agent app itself in the foreground → `TARGET_NOT_FOUND "Search control not visible on live Bet365"`
(fail-closed, no bet risk). Every alert since 24 Sep carried a Bet365 link (0 without), so with fix 1 the Search
route is only reached for malformed/in-play links. Left for the Milestone C recovery-procedure work; not changed
during the proof.

## Event-link route re-verified on 0.9.15-search
`verify-0.9.15/link-szolnoki-130334.json`: Szolnoki Olaj v OSE Lions opened by link, identity EXACT in 6.1 s; the
requested -19.5 line was no longer offered (market moved) → `TARGET_NOT_FOUND` at READ_SELECTION, as designed.
