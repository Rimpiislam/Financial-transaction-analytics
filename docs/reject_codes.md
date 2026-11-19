# Reject codes and precedence

**Source (locked):** [data_model_phase2_steps1_4_v0.7_locked.md](data_model_phase2_steps1_4_v0.7_locked.md),
section *"Closed reject reason codes and deterministic precedence"* (Phase 2 Step 4).
Copied verbatim from the owner's locked design file; SHA-256 `9FB7E908…DD4A16` matches the original.
This page restates that rule; it does not change it.

## Rule
One rejected source row → one `audit.reject_log` row → one **primary** code.
Every other violation found on that row is listed in `reject_details`, never as a second reject row.

Validation runs in six stages. The primary code is the first code that fired, reading the list
below top to bottom (stage order first, then the listed order of codes inside a stage as the tie-breaker).

| Order | Stage | Code | Applies to | Meaning |
|---|---|---|---|---|
| 1 | 1. Required / parse / type / amount / timestamp | `MISSING_REQUIRED_FIELD` | both | Required value blank or NULL |
| 2 | 1 | `INVALID_FORMAT` | both | Unparseable timestamp/decimal, bad amount scale, too long, ET date outside `dim_date` |
| 3 | 1 | `NONPOSITIVE_AMOUNT` | both | Amount ≤ 0 |
| 4 | 1 | `FUTURE_ATTEMPT_TIMESTAMP` | attempts | `attempt_timestamp_utc` > stored `batch_extraction_cutoff_utc` |
| 5 | 2. Controlled values / status–reason consistency | `INVALID_CONTROLLED_VALUE` | both | Unknown currency, method, status, failure code or adjustment type |
| 6 | 2 | `FAILURE_REASON_STATUS_MISMATCH` | attempts | Reason on a non-Failed row (see open point below for Failed without reason) |
| 7 | 3. Intra-batch duplicate identity | `DUPLICATE_IN_BATCH` | both | Later row with an ID already seen in this batch |
| 8 | 4. Existing-record conflicts | `DUPLICATE_RECORD` | attempts | Same ID, identical immutable fields and status as curated |
| 9 | 4 | `IMMUTABLE_FIELD_CONFLICT` | attempts | Same ID, changed immutable field (or changed reason on a Failed row) |
| 10 | 4 | `INVALID_STATUS_TRANSITION` | attempts | Anything other than Pending → Success/Failed/Cancelled |
| 11 | 4 | `DUPLICATE_ADJUSTMENT` | adjustments | Same adjustment ID, identical fields to curated |
| 12 | 4 | `ADJUSTMENT_FIELD_CONFLICT` | adjustments | Same adjustment ID, changed field |
| 13 | 5. Parent relationship / timing | `ORPHAN_ADJUSTMENT` | adjustments | Parent transaction not in curated |
| 14 | 5 | `ADJUSTMENT_ON_NON_SUCCESS` | adjustments | Parent status is not Success |
| 15 | 5 | `INVALID_ADJUSTMENT_TIMING` | adjustments | Before attempt; Reversal ≥ attempt+24h; Refund < attempt+24h |
| 16 | 6. Aggregate / sibling rules | `INVALID_ADJUSTMENT_RULE` | adjustments | Second reversal, non-full reversal, refund after reversal |
| 17 | 6 | `ADJUSTMENT_EXCEEDS_ORIGINAL` | adjustments | Running total (curated + earlier same-batch rows) > original amount |

**First occurrence:** the first source row (in `source_row_ref` / `stg_row_id` order) with a
*parseable* business ID reserves that ID, even if that row is itself rejected for another reason.
Later rows with the same ID get `DUPLICATE_IN_BATCH`.

**Not reject codes:** aged Pending (>24h at cutoff) is a report flag only. A staging
`source_row_ref` collision is a load error that fails the run, not a business reject.
`ALREADY_PROCESSED` is an `etl_run.run_status`, not a reject code.

In code, this list lives in exactly one place (the ordered precedence table in
`python/03_validate_and_load_curated.py`).

## Resolved conflicts between documents (2026-11-18)
1. **Failed without a failure reason → `FAILURE_REASON_STATUS_MISMATCH`.** The locked Step 4
   table lists it there explicitly ("Failed without reason or non-Failed with reason"). The later
   Step 5 mapping draft v0.8 says `MISSING_REQUIRED_FIELD`, but that draft itself says to copy the
   approved Step 4 rules without change, so Step 4 wins. The original `03` script followed Step 5.
   No real row is affected (0 rejects); proven by fixture row `payment_attempts_fixture.csv:11`.
2. **Closed code set enforced in code, not by a new SQL CHECK.** Step 4 allows "a SQL CHECK (or a
   fixed seeded lookup)". The deployed DDL has neither, so to avoid a schema change the loader
   aborts the run (`THROW 50001`) if validation produces a code outside the precedence list.

## Evidence
All 17 codes fire as primary codes, precedence/details verified, see
[test_evidence/05_reject_fixture_output.txt](test_evidence/05_reject_fixture_output.txt) and
[data/fixtures/reject_path/expected_results.csv](../data/fixtures/reject_path/expected_results.csv).
