# Financial Intelligence | Business Requirements

**Version:** 0.3 — Final for Phase 1; approved for Phase 2 (data model design)  
**Data:** 100% synthetic; no employer-specific information  
**Goal:** Demonstrate a reproducible batch analytics pipeline (Python → SQL Server → Power BI), with business reporting, reconciliation, and measured performance work.

## 1. Business scenario
A fictional payment-processing dataset records payment attempts, their outcomes, and subsequent refunds/reversals. Business users need consistent daily and monthly payment metrics and the ability to investigate failure patterns and data-quality exceptions.

## 2. In scope
- Generate synthetic USD payment attempts and separate adjustment events.
- Run full and incremental batch loads, with repeatable/idempotent processing.
- Validate source-to-target counts, uniqueness, mandatory fields, and business rules.
- Publish interactive trends, outcomes, failure drivers, and refund information in Power BI.
- Record reproducible query-performance baselines and measured improvements.

**Out of scope (v1):** live streaming, multi-currency FX, real customer data, settlement accounting, predictive fraud modeling, public Power BI embedding without verified access.

## 3. Reporting entities and grain
- **Payment attempt:** one unique `transaction_id` per attempt, with attempt timestamp, amount, and processing status. The status may change only once, from `Pending` to a final status (see §4.1).
- **Adjustment event:** one unique `adjustment_id` per refund or reversal, linked to an original successful `transaction_id`. Multiple partial refunds may reference the same payment; the **combined total of refunds and reversals** must not exceed the original successful amount.
- **Failure reason:** a controlled code associated with failed attempts only.
- **Reporting period:** use the payment's *attempt timestamp* for attempt-volume and success/failure KPIs; use the adjustment's *event timestamp* for refund/reversal activity. This prevents backdating refunds into prior periods.

## 4. Status lifecycle
`Pending → Success` or `Pending → Failed` or `Pending → Cancelled`.

- **Pending:** non-terminal; included in total attempts and pending count, excluded from success-rate denominator.
- **Success:** final processing outcome; included in success-rate numerator and denominator.
- **Failed:** final processing outcome; included in success-rate denominator.
- **Cancelled:** final status; the attempt was cancelled by the customer or merchant **before** processing reached a success/failure decision. Excluded from success-rate denominator and from transaction value. Generated at low frequency (about 1–2% of attempts).
- **Refund / Reversal:** **adjustment event types**, not processing statuses. An original successful attempt stays `Success`; adjustments are tracked separately so the success rate does not change after a refund.

### 4.1 Status update rules
- A later batch may update an existing attempt **only** from `Pending` to `Success`, `Failed`, or `Cancelled`. This update is applied as an upsert, and the time of the change is recorded (`status_updated_at`).
- A final status (`Success`, `Failed`, `Cancelled`) is never changed by a later batch. Any incoming row that tries to change a final status is quarantined and logged.
- An attempt still `Pending` more than **24 hours** after its attempt timestamp is logged as an aged-pending exception. It stays `Pending` until resolved.
- Because Pending attempts are excluded from rate denominators, a period's success rate can change only while some of its attempts are still Pending. A period's KPIs are treated as final once it contains no Pending attempts.

### 4.2 Adjustment types
| Type | Meaning | Amount rule |
|---|---|---|
| `Reversal` | Successful payment voided **before settlement** | Full original amount only; at most one per transaction |
| `Refund` | Money returned **after settlement** | Partial or full; multiple refunds allowed |

A transaction that has a reversal cannot also have refunds. For any transaction, total refunds + reversals ≤ original amount.

**Design caveat:** This is a simplified analytics lifecycle, not a claim about any actual payment network's rules.

## 5. Time, currency, and period rules
- All amounts are in **USD**; store as `DECIMAL(18,2)` in SQL Server.
- Source timestamps stored in **UTC**. Reporting hour/day/month use `America/New_York` (Eastern Time, including daylight-saving transitions); do not assume a fixed UTC−5 offset.
- **DST note:** on the spring-forward day, ET hour 2 does not occur; on the fall-back day, ET hour 1 occurs twice. Hourly counts on those two days are expected to show this.
- Default reporting comparison: **calendar month vs. previous calendar month (MoM)**, in Eastern Time.
- The partial current month is labeled **month-to-date (MTD)** and shown **without** a MoM comparison in v1.

## 6. Controlled failure codes
| Code | Description |
|---|---|
| `AUTH_TIMEOUT` | Authorization timed out |
| `INSUFFICIENT_FUNDS` | Insufficient funds |
| `FRAUD_DECLINE` | Fraud/risk decline |
| `INVALID_PAYMENT_DETAILS` | Invalid payment credentials/details |
| `PROCESSOR_ERROR` | Processor or network error |
| `LIMIT_EXCEEDED` | Payment limit exceeded |
| `OTHER` | Other classified failure |

Only `Failed` attempts may have a failure code; `Failed` attempts must have one of these codes. Root-cause narratives must be supported by the generated records, not assumed from a mockup.

## 7. Data quality and exception policy

### 7.1 Payment attempts

**Immutable fields:** `transaction_id`, `attempt_timestamp_utc`, `amount_usd`, `currency`, `merchant_id`, `payment_method`. These never change after the first load.  
**Mutable fields:** `status`, `failure_code` (set only when status becomes `Failed`), `status_updated_at`.

An incoming row whose `transaction_id` already exists in the curated layer is classified by comparing **both** its status and its immutable fields with the stored row:

| Rule | Acceptance threshold | Handling |
|---|---|---|
| Exact duplicate: all immutable fields match **and** status matches | **0 accepted** | Keep the first loaded copy; quarantine the incoming row and log batch and IDs |
| Valid status update: all immutable fields match, stored status is `Pending`, incoming status is `Success`, `Failed`, or `Cancelled` | Valid update | Apply as upsert (§4.1) |
| Final-status change: all immutable fields match, stored status is already final, incoming status differs | **0 accepted** | Keep stored row; quarantine and log |
| Immutable-field conflict: any immutable field differs, whatever the status | **0 accepted** | Keep stored row; quarantine and log |
| Missing/nonpositive payment amount | **0 accepted** | Quarantine and log |
| Missing transaction ID or timestamp | **0 accepted** | Quarantine and log |
| Attempt timestamp later than batch extraction time | **0 accepted** | Quarantine and log |
| Invalid status or failure code combination | **0 accepted** | Quarantine and log |
| Pending for more than 24 hours | Allowed, flagged | Log as aged-pending exception |

### 7.2 Adjustment events
| Rule | Acceptance threshold | Handling |
|---|---|---|
| Duplicate `adjustment_id` | **0 accepted** | Keep first loaded copy; quarantine and log |
| Original transaction missing | **0 accepted** | Quarantine and log |
| Original transaction not `Success` | **0 accepted** | Quarantine and log |
| Adjustment amount missing or ≤ 0 | **0 accepted** | Quarantine and log |
| Adjustment timestamp earlier than original attempt timestamp | **0 accepted** | Quarantine and log |
| Refunds + reversals greater than original amount | **0 accepted** | Quarantine and log |
| Reversal not equal to full original amount, more than one reversal, or refund on a reversed transaction | **0 accepted** | Quarantine and log |

### 7.3 Reconciliation
| Rule | Acceptance threshold | Handling |
|---|---|---|
| Source-to-curated reconciliation | **100% accounted for** | `source rows = inserted rows + applied status updates + rejected rows`, per batch |

Synthetic source data will deliberately include a **small, labeled set of invalid rows** to demonstrate detection; the curated layer must satisfy all rules. No invented "production quality" claims.

## 8. Batch and refresh expectations
- Start with a reproducible initial synthetic batch, then append dated batches.
- Use batch ID, extraction cutoff, load timestamps, row counts, and exception logs.
- Rerunning the same batch must not create duplicate curated transactions or adjustments, and must not reapply status updates.
- Power BI Desktop refresh is manual in v1; do not claim unattended refresh or public sharing until tested.

## 9. Acceptance criteria
1. Every displayed KPI can be traced to a written definition and a SQL query.
2. SQL and Power BI agree on totals for identical filters and reporting cutoffs.
3. Failed records have valid reason codes and peak-hour analysis uses ET consistently.
4. Reconciliation explains every input row (inserted, applied as a status update, or rejected).
5. An incremental batch adds new records and applies only allowed `Pending` → final updates; no other prior record changes.
6. Performance claims include query text, data volume, execution conditions, and before/after measurements.

## 10. Approved decisions (v0.3)
- **Refund and Reversal** are separate adjustment events, not processing statuses. The original `Success` status does not change.
- **Cancelled** attempts are generated in v1 at low frequency (about 1–2%).
- **MoM** compares completed calendar months only; the current partial month is shown as MTD with no comparison.
- **Status updates:** only `Pending` → final is allowed, applied as an upsert; final statuses never change. Duplicates and updates are told apart by comparing status **and** immutable fields (§7.1).
- **Net value:** v1 reports Gross Success Value, Refund Amount, and Reversal Amount as separate KPIs. A period-based net value is not shown, because payments and their adjustments can fall in different periods. Cohort-based Net Value is a planned enhancement.
