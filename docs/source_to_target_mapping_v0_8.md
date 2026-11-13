# Financial Intelligence — Source-to-Target Mapping
**Phase 2 · Step 5 · Draft v0.8 (implementation-ready subject to noted decisions)**

## Conventions
- Staging columns are strings (`VARCHAR`) to preserve incoming text. Each row also carries `batch_id`, `source_row_ref`, and raw source identifiers; do not silently discard invalid rows.
- `*_utc` fields use `DATETIME2(3)` in curated SQL Server tables; UTC is the canonical storage timezone.
- Use explicit `TRY_CONVERT`, trim/normalization, validation, then insert/update. Preserve original raw strings for reject diagnostics.
- Required blank/NULL -> `MISSING_REQUIRED_FIELD`; nonparseable value -> `INVALID_FORMAT`; out-of-domain value -> `INVALID_CONTROLLED_VALUE`.
- One reject-log entry per rejected source row, with a primary code and additional violations in details. Apply the **approved Step 4 precedence** in code; the exact full precedence order must be copied from the locked design before implementing the CASE expression.
- `run_id` is an execution identifier, `batch_id` is the source batch identifier. Only `COMPLETED` batches are replay-skipped.

## A. Payment attempts — source CSV → staging.payment_attempt_raw → curated.fact_payment_attempt

| Source CSV field | Staging field/type | Curated field/type | Transformation / lookup | Primary validation examples |
|---|---|---|---|---|
| `transaction_id` | `transaction_id_raw VARCHAR(100)` | `transaction_id VARCHAR(100)` (PK) | Trim; preserve stable ID | Missing → `MISSING_REQUIRED_FIELD`; repeated in batch → `DUPLICATE_IN_BATCH`; immutable mismatch on later batch → `IMMUTABLE_FIELD_CONFLICT` |
| `attempt_timestamp_utc` | `attempt_timestamp_raw VARCHAR(80)` | `attempt_timestamp_utc DATETIME2(3)` | Parse as UTC; derive ET reporting `attempt_date_key` using SQL Server DST-aware `AT TIME ZONE 'UTC' AT TIME ZONE 'Eastern Standard Time'` | Missing → `MISSING_REQUIRED_FIELD`; parse failure → `INVALID_FORMAT`; future timestamp → `FUTURE_ATTEMPT_TIMESTAMP` |
| `amount` | `amount_raw VARCHAR(80)` | `amount_usd DECIMAL(18,2)` | Validate exact 2-decimal scale and precision *before* cast; `TRY_CONVERT` | Missing → `MISSING_REQUIRED_FIELD`; bad numeric/scale → `INVALID_FORMAT`; ≤0 → `NONPOSITIVE_AMOUNT` |
| `currency` | `currency_raw VARCHAR(50)` | `currency VARCHAR(3)` | Trim, uppercase; USD only | Missing → `MISSING_REQUIRED_FIELD`; non-USD → `INVALID_CONTROLLED_VALUE` |
| `merchant_id` | `merchant_id_raw VARCHAR(100)` | `merchant_id VARCHAR(100)` | Trim; no merchant dimension in v1 | Missing → `MISSING_REQUIRED_FIELD`; immutable mismatch → `IMMUTABLE_FIELD_CONFLICT` |
| `payment_method` | `payment_method_raw VARCHAR(50)` | `payment_method_key INT` (FK) | Normalize/lookup `dim_payment_method`: Card, ACH, Wallet | Missing → `MISSING_REQUIRED_FIELD`; unknown → `INVALID_CONTROLLED_VALUE` |
| `status` | `status_raw VARCHAR(50)` | `status VARCHAR(20)` | Normalize/validate: Pending, Success, Failed, Cancelled; update only Pending→final | Missing → `MISSING_REQUIRED_FIELD`; unknown → `INVALID_CONTROLLED_VALUE`; invalid update → `INVALID_STATUS_TRANSITION` |
| `failure_reason` | `failure_reason_raw VARCHAR(100)` | `failure_reason_key INT NULL` (FK) | Lookup `dim_failure_reason` only for Failed; NULL for other statuses | Failed without reason → `MISSING_REQUIRED_FIELD`; unknown code → `INVALID_CONTROLLED_VALUE`; reason on non-Failed → `FAILURE_REASON_STATUS_MISMATCH` |
| `status_updated_at_utc` | `status_updated_at_raw VARCHAR(80)` | `status_updated_at_utc DATETIME2(3)` | Parse UTC; must support Pending→final updates; validate temporal consistency per locked rules | Missing/invalid → `MISSING_REQUIRED_FIELD` / `INVALID_FORMAT` |

**Derived / lineage fields (not additional CSV columns):** `attempt_date_key INT` (ET date → `dim_date`), `inserted_run_id`, `status_updated_run_id`. `attempt_hour_et` may be derived in a SQL view or in the model rather than stored as an extra physical column. Confirm exact table/column naming against approved Step 1–4 DDL specification before writing SQL.

## B. Adjustments — source CSV → staging.adjustment_raw → curated.fact_adjustment

**Proposed source contract:** The prior approved design defines the business behavior, but the exact adjustment CSV headers are not present in the current context. The following headers are **proposed**, not previously approved.

| Proposed source CSV field | Staging field/type | Curated field/type | Transformation / lookup | Validation examples |
|---|---|---|---|---|
| `adjustment_id` | `adjustment_id_raw VARCHAR(100)` | `adjustment_id VARCHAR(100)` (PK) | Trim, deduplicate by ID | Missing → `MISSING_REQUIRED_FIELD`; duplicate batch → `DUPLICATE_IN_BATCH`; cross-batch duplicate → `DUPLICATE_ADJUSTMENT`; conflicting repeat → `ADJUSTMENT_FIELD_CONFLICT` |
| `transaction_id` | `transaction_id_raw VARCHAR(100)` | `transaction_id VARCHAR(100)` (FK) | Lookup original successful attempt | Missing → `MISSING_REQUIRED_FIELD`; missing parent → `ORPHAN_ADJUSTMENT`; non-Success parent → `ADJUSTMENT_ON_NON_SUCCESS` |
| `adjustment_type` | `adjustment_type_raw VARCHAR(50)` | `adjustment_type VARCHAR(20)` | Normalize to Refund or Reversal | Missing → `MISSING_REQUIRED_FIELD`; unknown → `INVALID_CONTROLLED_VALUE` |
| `adjustment_amount` | `adjustment_amount_raw VARCHAR(80)` | `adjustment_amount_usd DECIMAL(18,2)` | Strict precision/scale validation; `TRY_CONVERT` | Missing → `MISSING_REQUIRED_FIELD`; bad format → `INVALID_FORMAT`; ≤0 → `NONPOSITIVE_AMOUNT`; cumulative total > original → `ADJUSTMENT_EXCEEDS_ORIGINAL` |
| `adjustment_timestamp_utc` | `adjustment_timestamp_raw VARCHAR(80)` | `adjustment_timestamp_utc DATETIME2(3)` | Parse UTC; derive ET `adjustment_date_key` | Missing → `MISSING_REQUIRED_FIELD`; invalid → `INVALID_FORMAT`; violates settlement timing → `INVALID_ADJUSTMENT_TIMING` |

**Derived / lineage fields:** `adjustment_date_key INT` (active Power BI date relationship), `attempt_date_key INT` (inactive Power BI relationship for cohort measures), `payment_method_key INT` (copied from original payment attempt), `loaded_run_id`. Original `fact_payment_attempt` stays Success; adjustment is a separate event.

**Settlement rule:** Synthetic settlement = attempt timestamp +24 hours. Reversal before settlement; refund after settlement. Multiple partial refunds allowed; reversal only once and full amount; combined adjustments cannot exceed original amount. Adjustment on Pending→Success is generated only after the incremental extraction cutoff.

## C. Data model and BI behavior
- Curated: `fact_payment_attempt`, `fact_adjustment`, `dim_date`, `dim_payment_method`, `dim_failure_reason`.
- Audit: `audit.etl_run` (one row per execution), `audit.reject_log` (one per rejected source row). Staging: two raw tables. **Total: 9 tables.**
- `dim_date` active to payment attempt via `attempt_date_key`; active to adjustments via `adjustment_date_key`; inactive to adjustments via `attempt_date_key`. No fact-to-fact Power BI relationship.
- Success rate = Success / (Success + Failed), excluding Pending and Cancelled. Adjustment amount cards use event date. Cohort refund/reversal rates use original attempt date and as-of cutoff; cohorts are immature until period end +30 days.
- Only `COMPLETED` batches skip on replay; replays log `ALREADY_PROCESSED`. Failed data changes rollback; completion counts + `COMPLETED` audit update commit atomically.

## D. Before SQL DDL — only two contract checks
1. Confirm proposed adjustment CSV header names and exact staging/curated table/column identifiers.
2. Copy exact **approved** reject-code precedence from Phase 2 Step 4. Do not invent or reorder it during implementation.

**Next build artifact:** `sql/01_create_schemas_and_tables.sql` followed by a small fixed-fixture validation run.
