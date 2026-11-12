# Financial Intelligence | KPI Definitions

**Version:** 1.0 — Approved  
**Scope:** Synthetic USD payment attempts; ET reporting unless noted.  
**Related:** [business_requirements.md](business_requirements.md)

## Canonical rules
- **Valid attempt:** curated record that passes required fields, types, status/failure-code and other DQ checks; rejected rows never contribute to KPIs.
- **Attempt cohort:** original attempts selected by `attempt_timestamp_et`; adjustment activity selected by its own `adjustment_timestamp_et`.
- **Processed outcomes:** `Success` and `Failed` only; `Pending` and `Cancelled` excluded from rate denominator.
- **Outcome finality:** a cohort's success/failure rates are final when no attempts remain Pending. **This does not finalize refund/reversal rates**, which can change when later adjustments arrive.
- **Synced date slicer:** the selected ET date range filters payment KPIs by original attempt date and refund/reversal **amount** KPIs by adjustment event date; each card labels its date basis. Cohort adjustment rates use original attempt-date selection and one explicit report-level as-of cutoff.
- **Adjustment as-of cutoff:** only adjustments observed by the stated extraction/reporting cutoff are included in cohort rates. A cohort is **immature while as-of cutoff < cohort period end (ET) + 30 days**. Cohort period end means the end of the last calendar day of the selected cohort period, not the last observed attempt; label immature trends separately. Mature does not mean permanently final.
- **Currency:** USD `DECIMAL(18,2)`; round rates only for display to 2 decimals; zero denominator → blank/N/A. Region excluded.

## KPI dictionary
| KPI | Definition | Date basis |
|---|---|---|
| Total attempts | Count distinct valid `transaction_id`, including Pending and Cancelled | Attempt date ET |
| Success count | Count status `Success`, including later adjusted originals | Attempt date ET |
| Failure count | Count status `Failed` | Attempt date ET |
| Pending count | Count status `Pending` | Attempt date ET |
| Cancelled count | Count status `Cancelled` | Attempt date ET |
| Success rate | Success / (Success + Failed) × 100 | Attempt date ET |
| Failure rate | Failed / (Success + Failed) × 100 | Attempt date ET |
| Gross successful value (Transaction Value) | Sum original `amount_usd` for Success attempts only | Attempt date ET |
| Attempted value (optional) | Sum original amount for all valid attempts; never label as Transaction Value | Attempt date ET |
| Refund amount | Sum valid Refund adjustment amounts, excluding reversals | Adjustment date ET |
| Reversal amount | Sum valid Reversal adjustment amounts, excluding refunds | Adjustment date ET |
| Refunded transaction rate | Distinct successful originals with ≥1 valid refund / all successful originals in same attempt-date cohort × 100 | Original attempt-date ET cohort; as-of cutoff |
| Refund value rate | Sum refunds attributed to original successful cohort / gross successful value of **same cohort** × 100 | Original attempt-date ET cohort; as-of cutoff |
| Reversed transaction rate | Distinct successful originals with a valid reversal / all successful originals in same cohort × 100 | Original attempt-date ET cohort; as-of cutoff |
| Failure rate by hour | Failed / (Success + Failed) within ET hour (0–23) × 100 | Attempt hour ET |
| Failure share by reason | Failures with code / all failed attempts × 100 | Attempt date ET |
| Aged pending | Pending attempts older than 24 hours at extraction cutoff | As-of cutoff |
| Net successful value (v2 only) | Cohort gross successful value − refunds attributed to cohort − reversals attributed to cohort | Original attempt cohort and explicit as-of cutoff; **not a v1 period KPI** |

## Period comparisons
- Completed ET calendar month vs immediately preceding completed month only. Display labels such as `Oct 2026 vs Sep 2026`.
- Count/value growth = `(current − prior) / prior × 100`; prior zero → blank. Rate change = current minus prior in **percentage points**.
- Current incomplete month = `MTD`, **no** MoM percentage change in v1.
- Cohort refund/reversal rates are shown with as-of cutoff and maturity status; avoid misleading comparisons between cohorts of unequal age.

## Data consistency and acceptance tests
1. Total attempts = Success + Failed + Pending + Cancelled under the same filters.
2. Success rate + Failure rate = 100% when processed denominator > 0 (allow display rounding).
3. Overall success rate equals the processed-count-weighted mean of component monthly rates for the same cohort; it cannot lie outside all component rates.
4. Gross successful value excludes Failed, Pending and Cancelled. Original Success status is unchanged by refunds/reversals.
5. Every adjustment references a Success original, amount > 0, timestamp ≥ original attempt; cumulative refunds + reversals ≤ original amount; reversals full-only and mutually exclusive with refunds.
6. Hourly failure visual uses ET hours 0–23 and labeled percentage axis. DST spring hour 02 may be absent, fall hour 01 may occur twice (two UTC hours); aggregation must not silently double-count source events.
7. Peak hour = 18:00 inclusive to 21:00 exclusive ET (hours 18,19,20). Uplift = `(peak failure rate / nonpeak failure rate − 1) × 100`; publish only after computing from generated data and disclose injected pattern.
8. SQL and DAX match on identical filters, cohort basis and as-of cutoff.
9. **Idempotency proof:** run the identical incremental batch twice. First run has expected inserts/updates/rejections; second run records `ALREADY_PROCESSED`, **0 inserts, 0 updates**, unchanged curated counts **and row values**. Reconciliation does not count replay rows twice.
10. **Conflict proof:** new-batch exact duplicate → `DUPLICATE_RECORD`; same immutable values and Pending → final → accepted `VALID_STATUS_UPDATE`; attempted change to terminal status → `INVALID_STATUS_TRANSITION`; changed amount, merchant or payment method under same ID → `IMMUTABLE_FIELD_CONFLICT`. Same `transaction_id` twice within one batch → second row `DUPLICATE_IN_BATCH`; changed `failure_reason` for an already `Failed` attempt → `IMMUTABLE_FIELD_CONFLICT`. Every rejected row has a reason code and batch ID.
11. Adjustment duplicate and relationship proof: repeated `adjustment_id` → `DUPLICATE_ADJUSTMENT` or `ADJUSTMENT_FIELD_CONFLICT`; missing/non-Success original, over-limit amount, invalid synthetic settlement timing and forbidden reversal/refund combinations are rejected with documented reason codes. Attempts are applied before same-batch adjustments.
12. Refund/reversal cohort rate display includes as-of cutoff and maturity label; immature cohorts (as-of cutoff < ET cohort period end + 30 days) are clearly identified. Later adjustments may still revise mature cohort rates.

## Clarifications (draft)
- Cancelled = pre-processing cancellation by customer/merchant; Reversal = pre-settlement void of successful payment; Refund = post-settlement return. These are distinct.
- Count-based adjustment rates use distinct **successful original** IDs in same cohort; refund value rate uses **same-cohort gross successful value**, not all attempts or event-date gross value.
- Payment methods: `Card`, `ACH`, `Wallet`; failure codes: `AUTH_TIMEOUT`, `INSUFFICIENT_FUNDS`, `FRAUD_DECLINE`, `INVALID_PAYMENT_DETAILS`, `PROCESSOR_ERROR`, `LIMIT_EXCEEDED`, `OTHER`.
- Status may only change Pending → Success/Failed/Cancelled; final statuses immutable. Exact duplicate and immutable-field conflicts are not valid status updates.
- One full load and one incremental batch are in v1; advanced scheduling deferred.

## Implementation note
Use canonical SQL metric queries/views and equivalent DAX semantics; test on small fixtures before generating large datasets. Approved as v1.0.
