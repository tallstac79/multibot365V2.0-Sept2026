# Milestone 5 — Multi-sport local simulator

## Status

**PASS on the physical Samsung** (2026-09-22). App **0.5.6-sim (11)**. Suite: `evidence/fixture-m5/results.json` — **25/25**. Baseline was `9133319`.

## Intent

Extend Milestone 4’s fictional LocalSimulator with football + basketball catalogs, DRAW/1X2 semantics (OCR-safe `Match winner`), simulated stake dry-run, `sport` / `minimum_price` / `stake` schema, `BELOW_MINIMUM` and `stale` scenarios. No live sportsbook path.

## Physical acceptance

LAN HTTP only; PC ADB server stopped. OCR fixes during the run: `REVIEW OK` (not `REVIEWONLY`), `D RAW`→DRAW, FIND above search input, basketball `Club` labels.

| Case | Expected | Observed | Duration ms |
| --- | --- | --- | --- |
| moneyline | PASS | PASS | 35818 |
| spread | PASS | PASS | 35683 |
| spread_home | PASS | PASS | 35063 |
| total | PASS | PASS | 34877 |
| fb_1x2_draw | PASS | PASS | 36875 |
| bb_ml | PASS | PASS | 35121 |
| bb_spread | PASS | PASS | 35443 |
| bb_total | PASS | PASS | 35021 |
| empty | NO_FIXTURE_FOUND | NO_FIXTURE_FOUND | 14534 |
| query_empty | NO_FIXTURE_FOUND | NO_FIXTURE_FOUND | 14391 |
| query_unverified | TEXT_NOT_VERIFIED | TEXT_NOT_VERIFIED | 12533 |
| ambiguous | AMBIGUOUS_FIXTURE | AMBIGUOUS_FIXTURE | 14725 |
| wrong_event | WRONG_EVENT | WRONG_EVENT | 18987 |
| click_ignored | CLICK_FAILED | CLICK_FAILED | 19018 |
| suspended | SUSPENDED | SUSPENDED | 23608 |
| unavailable | UNAVAILABLE | UNAVAILABLE | 23093 |
| changing | PRICE_CHANGED | PRICE_CHANGED | 35105 |
| wrong_line | LINE_CHANGED | LINE_CHANGED | 34078 |
| wrong_side | SELECTION_CHANGED | SELECTION_CHANGED | 34129 |
| below_min | BELOW_MINIMUM | BELOW_MINIMUM | 28335 |
| stale | NO_FIXTURE_FOUND | NO_FIXTURE_FOUND | 16475 |
| timeout | TIMEOUT | TIMEOUT | 216 |
| restart | INTERNAL_ERROR | INTERNAL_ERROR | 33359 |
| after_restart | PASS | PASS | 36975 |
| lost_response | PASS | PASS | 36620 |

Reproduction: `tools/SITE_ADAPTER.md`, `tools/test_site_adapter.py --output evidence/fixture-m5`.
