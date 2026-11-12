# Financial Intelligence | KPI Definitions

**Version:** 0.3 — Final for Phase 1; approved for Phase 2 (data model design)  
**Scope:** Synthetic USD payment attempts; all date filters use Eastern Time unless explicitly stated.  
**Related:** [business_requirements.md](business_requirements.md)

## Canonical rules
- **Attempt cohort:** attempts whose `attempt_timestamp_et` falls within the selected reporting period.
- **Status:** each attempt has one current status. It can change only once, from `Pending` to a final status (`Success`, `Failed`, `Cancelled`). See requirements §4.1.
- **Processed outcomes:** `Success` and `Failed` **only**.
- **Adjustment events:** refunds and reversals are separate records linked to original successful transactions. They do not overwrite the original attempt status. See requirements §4.2 for the difference between the two.
- **Currency:** USD. Amounts are summed from `DECIMAL(18,2)`, not floating point.
- **Rate display:** percentage to two decimals; compute from unrounded counts, then round only for display. Return blank/N/A if denominator is zero.
- **Finality:** a period's rate KPIs are final once the period has no `Pending` attempts. Until then, the period's rates may still change.

## KPI dictionary
| KPI | Definition / calculation | Includes / excludes | Date basis |
|---|---|---|---|
| Total transactions (attempts) | `COUNT(DISTINCT transaction_id)` | All valid attempts, including Pending and Cancelled | Attempt date ET |
| Successful transactions | Count of valid attempts with `status = 'Success'` | Original attempts, including those later refunded or reversed | Attempt date ET |
| Failed transactions | Count of valid attempts with `status = 'Failed'` | Excludes Pending, Cancelled | Attempt date ET |
| Pending transactions | Count of valid attempts with `status = 'Pending'` | Excludes final statuses | Attempt date ET |
| Cancelled transactions | Count of valid attempts with `status = 'Cancelled'` | Excludes processed outcomes | Attempt date ET |
| Success rate | `Success / (Success + Failed) × 100` | Excludes Pending and Cancelled from denominator | Attempt date ET |
| Failure rate | `Failed / (Success + Failed) × 100` | Excludes Pending and Cancelled | Attempt date ET |
| Transaction value (gross successful) | `SUM(amount_usd)` where `status = 'Success'` | Includes original value of later refunded or reversed payments; excludes failed/pending/cancelled attempts | Attempt date ET |
| Attempted value | `SUM(amount_usd)` for all valid attempts | Separate optional KPI; **not** labeled Transaction Value | Attempt date ET |
| Refund amount | Sum of valid `Refund` adjustment amounts | Refunds only, no reversals | Adjustment event date ET |
| Reversal amount | Sum of valid `Reversal` adjustment amounts | Reversals only, no refunds | Adjustment event date ET |
| Net successful value | **Out of scope for v1.** Planned enhancement: cohort-based, i.e. gross value of payments attempted in a period minus all refunds and reversals linked to those same payments | Not shown in v1. Subtracting one period's adjustments from that period's gross value would mix different payment cohorts | Attempt date ET of the original payment (planned) |
| Failure rate by hour | Failed attempts in hour / (Success + Failed attempts in same hour) × 100 | ET hour-of-day, 0–23; excludes Pending/Cancelled | Attempt timestamp ET |
| Failure share by reason | Failed attempts with code / all failed attempts × 100 | Only valid failure codes | Attempt date ET |
| Aged pending (operational) | Count of attempts still `Pending` more than 24 hours after attempt timestamp | Data-quality indicator, not a business KPI | As of last load |

## Period-over-period comparison
For **completed calendar months**, compare the selected month with the **immediately preceding completed calendar month** in ET:

- **Count/value growth %** = `(current − prior) / prior × 100` (blank if prior = 0).
- **Success/failure rate change** = `current rate − prior rate`, expressed in **percentage points (pp)**, not relative percent.
- Display the actual months (for example, `Oct 2026 vs Sep 2026`) rather than an ambiguous "vs. prior period".
- **No comparison for incomplete months in v1**; mark them MTD without a MoM delta.

## Data consistency tests
1. `Total attempts = Success + Failed + Pending + Cancelled` for every filter selection.
2. `Success rate + Failure rate = 100%` when at least one processed outcome exists (allow display rounding).
3. Overall success rate must be the **processed-volume-weighted average** of the component monthly success rates, if months partition the same selected cohort; it cannot fall below every monthly rate or exceed every monthly rate.
4. `Gross successful value` never includes failed, pending, or cancelled attempts.
5. For every transaction, `refunds + reversals ≤ original amount`, and adjustments exist only for `Success` attempts.
6. Hourly failure-rate visual has 24 hourly buckets (0–23) where applicable, a labeled percentage axis, and an explicit ET timezone label. On DST-change days, ET hour 2 is missing (spring forward) and ET hour 1 appears twice (fall back); this is expected.
7. Peak-hour uplift claim must specify the comparison: `(peak failure rate / non-peak failure rate − 1) × 100`, where peak is **18:00–20:59 ET** (three hourly buckets: 18, 19, 20); no uplift percentage is published before computing it.
8. Reconciliation SQL and DAX measures must match on filters, date basis, and status rules.

## Approved clarifications
- **"6–9 PM" means 18:00 inclusive to 21:00 exclusive ET**, i.e. three hourly buckets.
- Refunds and reversals are distinct adjustment event types; gross transaction value is unchanged by later adjustments.
- Monthly comparisons use completed months only in v1.
- Only `Pending` → final status updates are allowed; final statuses never change.
- v1 shows **Gross Success Value, Refund Amount, and Reversal Amount** separately. Cohort-based Net Value is deferred to a later version.

## Implementation note
Use one canonical SQL view or documented metric query per KPI and mirror the same filter semantics in DAX. Validate both on small test cases before generating large synthetic batches.
