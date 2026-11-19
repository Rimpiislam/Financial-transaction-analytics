# Test results

Only tests that were actually run, with their saved output. Anything not listed is **NOT TESTED**.
All tests ran on 2026-11-18 against SQL Server 2025 Express (`localhost\SQLEXPRESS01`).
Data-changing tests ran only in isolated databases restored from a verified backup
(`FinancialIntelligence_Scratch`, `FinancialIntelligence_Fixture`); the production database was only read.

| # | Test | Where it ran | Result | Evidence |
|---|---|---|---|---|
| 1 | Full backup + `RESTORE VERIFYONLY WITH CHECKSUM` | production DB (read) | PASS: backup set valid | [01_backup_output.txt](test_evidence/01_backup_output.txt) |
| 2 | 17 negative constraint tests in `BEGIN TRAN … ROLLBACK` | production DB, rolled back | 17/17 PASS, each blocked by its named constraint; row counts unchanged | [02_negative_constraint_tests_output.txt](test_evidence/02_negative_constraint_tests_output.txt) · [script](../sql/tests/02_negative_constraint_tests.sql) |
| 3 | Loader replays runs 1–2 from staging, then column-by-column `EXCEPT` vs production | scratch DB | PASS: 1,000 / 102 rows, 0 differences both directions, 0 rejects | [03_scratch_replay_output.txt](test_evidence/03_scratch_replay_output.txt) |
| 4 | Idempotency: re-invoke COMPLETED runs 1 and 2 | scratch DB | PASS: 2 `ALREADY_PROCESSED` audit rows; all data-table checksums identical before/after | [04_idempotency_output.txt](test_evidence/04_idempotency_output.txt) |
| 5 | Reject-path fixture (31 payment + 24 adjustment rows) | fixture DB | 79/79 checks PASS: all 17 codes fire as primary; details + precedence; ET/DST date keys; normalization | [05_reject_fixture_output.txt](test_evidence/05_reject_fixture_output.txt) · [expected](../data/fixtures/reject_path/expected_results.csv) |
| 5-F1 | Adjustment run before its payment run → FAILED, no data change | fixture DB | PASS | same file |
| 5-F2 | Run locked by another session → skipped, stays RUNNING | fixture DB | PASS | same file |
| 5-F3 | Injected failure after all writes → full rollback, FAILED | fixture DB | PASS | same file |
| 5-F4 | Retry same `run_id`s after FAILED → COMPLETED, reconciled | fixture DB | PASS | same file |
| 5-F5 | Staged count ≠ `rows_read` → FAILED before any write | fixture DB | PASS | same file |
| 5-I | Duplicate RUNNING run of a COMPLETED batch → ALREADY_PROCESSED, no change | fixture DB | PASS | same file |
| 6 | Production DB unchanged after all testing | production DB (read) | PASS: still runs 1–2 only; curated checksums equal the scratch rebuild | [06_real_db_untouched.txt](test_evidence/06_real_db_untouched.txt) |
| 7 | SQL KPI validation queries + 9 consistency tests | production DB, **read-only SELECTs** | 9/9 PASS; reference values for every DAX measure | [07_kpi_validation_output.txt](test_evidence/07_kpi_validation_output.txt) · [script](../sql/validation/01_kpi_validation_queries.sql) |
| 8 | `.pbip` static checks: JSON, TMDL syntax rules, every visual/DAX/relationship reference, page bounds | files only | 446/446 PASS; negative controls fail as expected | [08_pbip_static_checks.txt](test_evidence/08_pbip_static_checks.txt) · [script](../python/tests/check_pbip_static.py) |
| 9 | Colour-blind / contrast check of the Navy + Cyan + Teal palette | files only | PASS: worst adjacent pair normal ΔE 21.1, CVD ΔE 12.0; contrast ≥ 5.3:1 | [10_palette_check.txt](test_evidence/10_palette_check.txt) · [script](../python/tests/palette_check.py) |
| 10 | Dashboard in Power BI Desktop vs SQL reference values | Power BI Desktop | PASS (see below) | checked by hand |

Evidence files 1–6 were produced at an earlier file layout of this project; paths printed inside them
reflect that layout, the content is unchanged.

## Power BI Desktop checks (test 10)
- **Executive Overview:** KPI tiles 1,000 / $500,245.01 / 84.84% / 144 with latest-month lines
  Sep 2026 vs Aug 2026 +5.9% / +7.2% / +3.04 pp / −15.4% (green/red correct); trend 2 / 331 / 324 / 343 attempts
  and 100% / 85.00% / 83.17% / 86.21% success; insight text (+82%, 26.2% vs 14.4%, approved peak −12.7%); hour
  chart 0–23 with hours 2–3 highlighted; refund $20,730.79, reversal $14,698.93; monthly and cohort tables equal
  SQL Q2 / Q8.
- **Failure Analysis:** failed 144, failure rate 15.16%, AUTH_TIMEOUT rate 3.79% (36/950), aged pending 19;
  hour chart = SQL Q5; reasons AUTH_TIMEOUT 36, FRAUD_DECLINE 13, INSUFFICIENT_FUNDS 20,
  INVALID_PAYMENT_DETAILS 12, LIMIT_EXCEEDED 22; failure rate by method ACH 16.95% / Card 12.17% / Wallet 16.77%.
- **Drill-through:** AUTH_TIMEOUT bar → Transaction Detail shows 36 rows (= SQL Q4).

## Bugs found by testing and fixed
- `#v` (violations) was created with `SELECT … INTO`, so its `code` column took the length of the longest
  literal in that statement and longer codes such as `ADJUSTMENT_FIELD_CONFLICT` were truncated. Real data never
  hit it (0 rejects); the fixture did. Fixed by declaring `#v (code VARCHAR(50))`; tests 3–6 re-run.
- Power BI Desktop rejected `///` descriptions on relationships (relationships have no description) and a table
  named `Measures` (reserved). Fixed (`_Measures`), and the static check now catches both.

## NOT TESTED
- Abrupt process kill mid-transaction (expected: SQL Server rolls back, run stays RUNNING; not simulated).
- Two loader processes started at the same moment (only a held lock was simulated, 5-F2).
- Running the loader against the production database (not needed: runs 1–2 were already COMPLETED).
- Changing the date / payment-method slicers and slicer sync between pages (values above are unfiltered).
- Drill-down from Month to Day on the trend charts.
