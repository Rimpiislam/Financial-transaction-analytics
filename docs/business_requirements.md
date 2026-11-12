# Financial Intelligence | Business Requirements

**Version:** 1.0 — Approved  
**Data:** Synthetic payment data only  
**Pipeline:** Python ETL → SQL Server → Power BI

## Business problem and questions
Build a reproducible payment-analytics pipeline answering: How do volume, gross successful value and success rate trend? When and why do failures occur by hour, payment method and reason? How do refunds/reversals relate to successful payments? Do source, staging and reporting reconcile?

## v1 scope
- Generate synthetic USD attempts and linked adjustment events using a documented fixed seed; no region field or region filter.
- Python full load plus **one incremental batch** demonstrating new inserts, valid Pending-to-final updates and rejected duplicates/conflicts. No scheduler or orchestration in v1.
- SQL Server staging, curated reporting model, reconciliation and reject/audit logs.
- Two Power BI pages: Overview and Failure Analysis, with synchronized date and payment-method slicers. Refund and reversal amounts shown separately.
- Document measured performance improvements only if actually benchmarked.

## Grain and lifecycle
- **Attempt grain:** one row per `transaction_id` (one payment attempt), with its current processing status.
- **Adjustment grain:** one row per `adjustment_id`, linked to one successful original `transaction_id`.
- `Pending` is nonfinal; only `Pending → Success`, `Pending → Failed` or `Pending → Cancelled` is permitted. `Success`, `Failed` and `Cancelled` are terminal and immutable.
- `Cancelled` means the customer/merchant cancelled before a processing outcome; it is excluded from processed success/failure rates and gross successful value. Seed approximately 1–2% cancelled.
- Pending older than 24 hours at extraction cutoff is flagged as an aged-pending exception; it is not silently converted.
- `Refund` is a post-settlement return, partial/full and multiple events permitted. `Reversal` is a pre-settlement full void, at most once. Both require an original `Success`; the original remains `Success`. No refund on a reversed attempt; combined refund and reversal amounts cannot exceed the original amount. Adjustment amounts must be positive and event timestamps cannot precede the attempt timestamp.
- **Synthetic generation note:** for attempts that transition `Pending → Success` in an incremental batch, generate any linked adjustment only after that batch’s extraction cutoff; do not backdate adjustments before the Success update is observed.
- **Synthetic settlement proxy:** settlement is assumed to occur exactly 24 hours after the original attempt timestamp (UTC). Reversal events must occur before that instant; refund events must occur at or after it. This is a testable modeling convention, **not actual settlement accounting**. Reject violations as `INVALID_ADJUSTMENT_TIMING`.
- This is a simplified portfolio lifecycle, not a universal payment-network policy.

## Controlled values
- Payment method: `Card`, `ACH`, `Wallet` (v1 fixed list).
- Failure reason: `AUTH_TIMEOUT`, `INSUFFICIENT_FUNDS`, `FRAUD_DECLINE`, `INVALID_PAYMENT_DETAILS`, `PROCESSOR_ERROR`, `LIMIT_EXCEEDED`, `OTHER`.
- Only `Failed` has a failure reason; every `Failed` requires one. Other statuses have null failure reason.
- Status: `Pending`, `Success`, `Failed`, `Cancelled`. Adjustment types: `Refund`, `Reversal`.

## Time, amounts and reporting
- Store UTC timestamps; report in `America/New_York`, including DST (spring-forward missing 02:00; fall-back repeated 01:00). Use ET attempt date for payment KPIs and ET adjustment-event date for adjustment activity.
- All amounts USD, SQL `DECIMAL(18,2)`; payment amount must be positive. Gross successful value excludes failed/pending/cancelled attempts. No period-based net value KPI in v1; cohort-based net value deferred to v2.
- **Synced date slicer semantics:** selected ET date range filters payment KPIs by attempt date, and refund/reversal amount KPIs by adjustment event date. Each card labels its date basis. Cohort adjustment rates use original attempt-date selection plus one explicit report-level as-of cutoff.
- MoM compares completed ET calendar months only; partial month labeled MTD without MoM delta.
- Cohort adjustment rates use original attempt date and an explicit as-of cutoff. A cohort is **immature while the as-of cutoff is earlier than the ET cohort period end (last calendar day, end of day) + 30 days**; show a maturity label or distinct styling, not an unqualified trend comparison. The 30-day period is an analysis convention, not a legal refund deadline; later adjustments may still change mature cohorts.

## Data quality, conflicts and batch processing
- **Valid attempt** = passes required-field, type, controlled-value, timestamp and business-rule checks; rejected source rows are excluded from KPIs.
- Immutable attempt fields: `transaction_id`, `attempt_timestamp_utc`, `amount_usd`, `currency`, `merchant_id`, `payment_method`. Compare source business IDs, not dimension surrogate keys.
- **Within one batch:** at most one attempt row per `transaction_id` is accepted; retain the first source row in deterministic source-row order and reject subsequent occurrences as `DUPLICATE_IN_BATCH` (even if the later row proposes a status transition).
- On repeated `transaction_id` in a **new** batch: (1) identical immutable fields and status = exact duplicate (`DUPLICATE_RECORD`, reject/log); (2) same immutable fields and `Pending → final` = valid update (`VALID_STATUS_UPDATE`, upsert and record `status_updated_at`); (3) attempted final-status change or other invalid transition = `INVALID_STATUS_TRANSITION` (reject/log); (4) immutable-field difference (e.g., changed amount/merchant/method) = `IMMUTABLE_FIELD_CONFLICT` (reject/log). Preserve first accepted immutable values. For a terminal `Failed` attempt, `failure_reason` is also immutable; a changed reason under the same ID is `IMMUTABLE_FIELD_CONFLICT`. Reject malformed or missing IDs, nonpositive/missing amounts, future attempt timestamps relative to extraction cutoff, invalid failure codes and invalid adjustment relationships.
- **Adjustment validation:** immutable adjustment fields are `adjustment_id`, `transaction_id`, `adjustment_type`, `amount_usd`, `adjustment_timestamp_utc`. For a new batch, an identical existing adjustment ID is rejected/logged as `DUPLICATE_ADJUSTMENT`; changed fields under an existing ID are `ADJUSTMENT_FIELD_CONFLICT`. Within a batch, keep the first adjustment ID and reject repeats as `DUPLICATE_IN_BATCH`. A missing original is `ORPHAN_ADJUSTMENT`; a non-Success original is `ADJUSTMENT_ON_NON_SUCCESS`; cumulative amount over original is `ADJUSTMENT_EXCEEDS_ORIGINAL`. Also reject nonpositive amounts, invalid timing (`INVALID_ADJUSTMENT_TIMING`), non-full/multiple reversals, and refunds on reversed originals (`INVALID_ADJUSTMENT_RULE`). Attempts (including Pending → Success updates) are processed **before** adjustments within each batch. Rejected adjustments are not included in KPIs.
- Reject log includes batch ID, record ID, reason code and source row reference. Record batch extraction cutoff and counts of inserted, updated and rejected rows.
- **Idempotency:** re-running the *same identified batch* is a no-op for curated data: 0 inserts, 0 updates, unchanged row counts and values; audit result `ALREADY_PROCESSED`. Do not treat same-batch replay as new-batch duplicate rejects.
- Reconcile each first-run batch: `input rows = inserted + applied updates + rejected` (separately by entity type). A rerun is accounted for as an already-processed batch, not as another first-run input.

## Seeded pattern disclosure
- Predefine a candidate peak window of **18:00–20:59 ET** and optionally inject elevated `AUTH_TIMEOUT` failures with a fixed random seed. Document generation parameters; do not publish any uplift number until computed from actual data. Treat observed patterns as synthetic validation, not real-world discovery.

## Acceptance and out-of-scope
- SQL and Power BI agree on every displayed KPI for identical cutoff and filters; all rejected rows have traceable reason codes; batch reconciliation and rerun no-op tests pass; refund/reversal rules hold; performance claims have measured evidence.
- Out of scope: real/employer data, region, FX, live streaming, settlement accounting, predictive fraud, automated scheduling, unverified public Power BI embedding, v1 period net value.

## Approval
Approved as v1.0 after independent review and owner approval. Changes after this version require a new version and review.
