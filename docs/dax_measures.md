# DAX measures

Source of truth: [_Measures.tmdl](../PowerBi/FinancialIntelligence.SemanticModel/definition/tables/_Measures.tmdl)
(table `_Measures`: the name `Measures` is reserved in Power BI)
(each measure also carries its "why" as a description). Definitions follow `kpi_definitions.md` v1.0.
SQL reference numbers for the same KPIs: [07_kpi_validation_output.txt](test_evidence/07_kpi_validation_output.txt).

**Date basis.** The date slicer filters `dim_date`. Payment measures follow the **active**
`attempt_date_key` relationship. Adjustment amount/count measures follow the **active**
`adjustment_date_key` (event date). Cohort measures switch to the **inactive** `attempt_date_key`
relationship with `USERELATIONSHIP`. There is no fact-to-fact relationship.

| Folder | Measure | Why (one line) | SQL reference value (all data) |
|---|---|---|---|
| Attempts | Total Attempts | All valid attempts incl. Pending/Cancelled (KPI dictionary). | 1,000 |
| Attempts | Success Count | Current status Success; adjusted originals stay Success. | 806 |
| Attempts | Failed Count | Current status Failed. | 144 |
| Attempts | Pending Count | Non-final; shown, never in rate denominators. | 19 |
| Attempts | Cancelled Count | Pre-processing cancellation; excluded from rates and value. | 31 |
| Attempts | Processed Count | Success + Failed = rate denominator. | 950 |
| Rates | Success Rate | Success / (Success + Failed); approved rule. | 84.84% |
| Rates | Failure Rate | Failed / (Success + Failed); sums to 100% with Success Rate. | 15.16% |
| Amounts | Gross Successful Value | "Transaction Value" = Success amounts only. | $500,245.01 |
| Amounts | Attempted Value | Optional; all valid attempts; never labelled Transaction Value. | $614,959.52 |
| Amounts | Avg Successful Amount | Average successful ticket. | — |
| Adjustments (event date) | Refund Amount / Refund Count | Refunds by ET event date, reversals excluded. | $20,730.79 / 77 |
| Adjustments (event date) | Reversal Amount / Reversal Count | Reversals by ET event date, refunds excluded. | $14,698.93 / 25 |
| As-of | As-of Cutoff UTC / As-of ET Date / As-of Label | Stored cutoff of latest COMPLETED payment run, never the clock. | 2026-11-13 00:00 UTC / ET 2026-11-12 |
| Cohort | Refunded Txn Rate (cohort) | Distinct successful originals with ≥1 refund ÷ successful originals, same attempt-date cohort, as-of cutoff. | Jul 10.66%, Aug 10.51%, Sep 7.64% |
| Cohort | Reversed Txn Rate (cohort) | Same for reversals. | Jul 1.84%, Aug 3.50%, Sep 4.00% |
| Cohort | Refund Value Rate (cohort) | Cohort refunds ÷ the **same cohort's** gross successful value. | Jul 4.49%, Aug 5.53%, Sep 2.55% |
| Cohort | Cohort Maturity | Immature while as-of ET date < selected period end + 30 days. | Jun–Sep: Mature |
| Month over month | Month State | Completed if the ET month ended before the as-of date, else MTD. | Jun–Sep Completed |
| Month over month | MoM Attempts % | vs immediately preceding month; completed months only; prior 0 → blank. | Aug −2.11%, Sep +5.86% |
| Month over month | MoM Gross Successful Value % | Same rule, value. | — |
| Month over month | MoM Success Rate (pp) | Rate change in percentage points, not %. | Aug −1.83 pp, Sep +3.04 pp |
| Month over month | Latest Completed Month End | Latest completed ET month that has attempts (date filter ignored, method filter kept). | 2026-09-30 |
| Month over month | KPI Delta Attempts / Value / Success / Failed | KPI-tile line: that month vs the month before, months named on the card (approved MoM rule). | Sep vs Aug 2026: +5.9% / +7.2% / +3.04 pp / −15.4% (SQL Q2) |
| Formatting | KPI Delta Color … , Hour Bar Color | Green/red for good/bad change (failed: up = red); amber for seeded ET hours 2–3. Presentation only. | — |
| Failure analysis | Failure Share by Reason | Failures with reason ÷ all failures. | AUTH_TIMEOUT 25.00% |
| Failure analysis | AUTH_TIMEOUT Rate | AUTH_TIMEOUT failures ÷ processed; used on the hour chart. | — |
| Failure analysis | Failure Rate 02-03 ET / Other Hours / Seeded Window Uplift % | Checks the generator's seeded window (Phase 4C prompt); synthetic, disclosed. | 26.15% / 14.35% / +82.25% |
| Failure analysis | Failure Rate Peak 18-20 ET / Non-peak / Peak Uplift % | KPI doc test 7 approved peak definition (hours 18, 19, 20). | 13.45% / 15.40% / **−12.71%** (official peak KPI; no uplift because the generator seeded 02:00–03:59 instead: known generator deviation) |
| Failure analysis | Key Insight Text | Insight-card sentence built only from the measures above; states the seeded window and the approved peak. | "02:00-03:59 ET 26.2% vs 14.4% (+82%) … approved peak −12.7%" |
| Failure analysis | Aged Pending Count | Pending > 24h before as-of cutoff: flag only. | 19 |

**Known data quirk (not a bug):** 2 attempts at UTC 2026-07-01 early morning fall on ET 2026-06-30, so a
"June 2026" month exists with 2 attempts. July's MoM Attempts is therefore +16,450% versus June. It is
arithmetically correct under the completed-month rule; the dashboard shows it rather than hiding it.

**Cohort maturity with no date filter:** the "selected period" then runs to 2030-12-31, so the card reads
"Immature". That follows the approved rule literally; read cohort rates from the by-month table.

## Status
- Measure names, folders and every `[Measure]`/`table[column]` reference: statically checked
  ([08_pbip_static_checks.txt](test_evidence/08_pbip_static_checks.txt)).
- DAX values equal the SQL reference column on all three pages and the drill-through, checked in
  Power BI Desktop (see [test_results.md](test_results.md)).
