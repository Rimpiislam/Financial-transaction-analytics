# Design decisions (why, in 1–2 lines each)

Approved sources: `business_requirements.md` v1.0, `kpi_definitions.md` v1.0,
[data_model_phase2_steps1_4_v0.7_locked.md](data_model_phase2_steps1_4_v0.7_locked.md) (locked),
`source_to_target_mapping_v0_8.md` (draft, defers to Step 4). Where documents disagree, the
locked/approved one wins and the conflict is listed here.

## Architecture
| Decision | Why |
|---|---|
| Three layers: staging (all VARCHAR) → curated → audit | Staging keeps exactly what arrived so bad rows can be diagnosed; only validated rows reach KPIs; audit explains every difference. |
| Attempt fact and adjustment fact are separate grains | Flattening refunds onto the attempt would duplicate payment value and corrupt success rate. |
| UTC stored, ET (DST-aware) used only for date keys / hours | UTC is unambiguous; ET is the business reporting day. `AT TIME ZONE 'Eastern Standard Time'` handles spring-forward and fall-back. |
| `merchant_id` is an attribute, not a dimension | No v1 business question segments by merchant (scope discipline). |

## ETL (Phase 4C)
| Decision | Why |
|---|---|
| Kept runs 1–2 as loaded (COMPLETED 2026-11-15) instead of reloading | Rule: never change run 1/2 metadata after COMPLETED. Instead the new loader was proven on a restored copy and matched production on every column (0 differences). |
| Validation is set-based SQL in `sql/etl/*.sql`; Python only orchestrates | One pass over all rows with `TRY_CONVERT` + temp tables instead of 1,000 round trips; the rules live next to the data and can be read as SQL. |
| One transaction per run, `SET XACT_ABORT ON`, completion update is the last statement | Data, rejects and the COMPLETED marker commit together or not at all; any error aborts the whole run (locked Step 4 transaction boundary). |
| On failure: rollback, then a separate small transaction marks FAILED | The audit trail survives the rollback; staging is untouched, so the same `run_id` can be retried (proven: F3→F4). |
| `sp_getapplock` per run, lock-busy is *not* marked FAILED | Stops two sessions processing one run; the other session is not failing, it is simply in progress (proven: F2). |
| COMPLETED run re-invoked → new `ALREADY_PROCESSED` audit row, nothing else | `etl_run` grain is one execution; a replay is recorded without touching the completed batch (business requirement idempotency). |
| A second RUNNING run of an already-COMPLETED batch → marked `ALREADY_PROCESSED` | Covers the "02 was re-run by mistake" case: only COMPLETED batches are replay-skipped, and duplicates are never loaded twice. |
| Preflight: staged rows = `rows_read`, dims match approved lists, no rejects yet | `rows_read` is written before staging; a mismatch means a partial stage, which must stop the run (pitfall 3). |
| Adjustment run refuses to start while a payment run at/before its cutoff is not COMPLETED | Requirement: attempts (including Pending→Success) are processed before adjustments. |
| Reject precedence = ONE Python list sent to SQL as `#precedence` | Single source of the locked order; SQL picks `MIN(ord)` and aborts on an unknown code. |
| `''` → NULL with `NULLIF(LTRIM(RTRIM(x)),'')` before any check | Staging keeps empty CSV fields as `''`; without this every Success row would reject (pitfall 1). |
| Timestamps: strict ISO-8601 `yyyy-mm-ddThh:mi:ss[.fff][Z]` | Source is UTC ISO; anything else (space separator, offsets) is ambiguous → `INVALID_FORMAT`. Verified `TRY_CONVERT` parses the `Z` form. |
| Amounts: up to 16 integer digits and 0–2 decimals, checked *before* the cast | Matches `DECIMAL(18,2)` exactly with no silent rounding (`12.345` rejects). All 1,102 real amounts have exactly 2 decimals. |
| ET date outside `dim_date` (2024–2030) → `INVALID_FORMAT` | Rejects one row instead of an FK error rolling back the whole run (pitfall 4); Step 4 groups it with timestamp/date-key parsing. |
| `status_updated_at` earlier than the attempt → `INVALID_FORMAT` | Step 5 asks for temporal consistency; an update before the event is not a valid timestamp pair. |
| Controlled values matched case-insensitively, stored in canonical form | Mapping says "trim, normalize/lookup": `card`→`Card`, `usd`→`USD`. |
| First occurrence = lowest `stg_row_id` with a non-blank ID, even if that row is rejected | Locked Step 4 wording. `stg_row_id` order equals CSV row order (verified), and unlike `source_row_ref` it sorts numerically. |
| Stage 4–6 checks only run on rows clean through the earlier stages | They compare parsed values with other records; on unparsed values they would be meaningless. Earlier-stage codes still appear in `reject_details`. |
| Cross-batch comparisons use business values (method name, reason code), not surrogate keys | Business requirements: "compare source business IDs, not dimension surrogate keys". |
| Failed reason is immutable only when the new row is also Failed | Failed→Success is a status-transition problem (`INVALID_STATUS_TRANSITION`), not a reason change. |
| Adjustment running totals: per-transaction rank passes ordered by (timestamp, adjustment_id) | A rejected adjustment must not count toward later ones (pitfall 5). Each pass is set-based; passes = max adjustments on one transaction (1 in real data). Proven by fixture rows 18–19 and 23–24. |
| Settlement = attempt + 24h; Reversal `<` settlement, Refund `>=` settlement | Business requirements wording ("refund at or after"). Proven at the exact boundary (fixture row 20). |
| No `rows_updated` column: inserted/updated split goes into `etl_run.message`; `rows_loaded` = inserted + updated | Smallest change: requirement asks for the split, DDL has no column, schema redesign not justified. |

## Conflicts resolved
| Conflict | Resolution | Why |
|---|---|---|
| Failed without reason: Step 4 = `FAILURE_REASON_STATUS_MISMATCH`, Step 5 draft = `MISSING_REQUIRED_FIELD` | Step 4 | Step 4 is locked; Step 5 says to copy Step 4 without change. |
| Step 4 wants reject codes restricted by SQL CHECK/lookup; DDL has none | Enforced in loader code (THROW on unknown code) | Avoids a schema change; same protection on the only write path. |
| Seeded AUTH_TIMEOUT window: business requirements say 18:00–20:59 ET; generator seeds 02:00–03:59 ET | Analyse the generator's 02:00–03:59 window | That is what the data actually contains; the requirements doc's window is a "candidate" and must be disclosed, not assumed. |
| An earlier row-by-row Python loader (no FAILED marking) | Replaced by set-based SQL | Approved Phase 4C design requires set-based SQL and FAILED-on-error; the rebuilt load is identical to the first one (test 3). |

## Power BI (.pbip)
| Decision | Why |
|---|---|
| `.pbip` with TMDL model + PBIR report, generated by `build_pbir_report.py` | Text files give reviewable diffs; the generator rebuilds the same layout every time. |
| Schema versions and base theme copied from a report saved by this Desktop (2.159) | Matches what Desktop itself writes instead of relying on backward compatibility. |
| Dedicated `_Measures` table with display folders and a "why" description per measure | Measures are found in one place and explain themselves in the field list. The underscore is required: Power BI rejects a table named `Measures` (reserved MDX keyword). |
| Theme follows the owner's locked design direction **Navy + Cyan + Teal** (portfolio concept): navy page `#0b1a33`, navy panels `#112a4d`, white/grey ink, header band, one accent border per KPI card, white "Key business insight" card | Matches the portfolio landing-page concept. (An earlier light default palette was replaced once the locked direction was shared.) |
| Series order cyan, amber, teal, violet, coral, blue | Cyan next to teal fails colour-blind separation (normal dE 9.3, CVD 5.9); this order passes every adjacent pair (worst 21.1 / 12.0) with >= 5.3:1 contrast on navy. Evidence 10 (Python port; the Node validator could not run). Status colours stay reserved. |
| Concept's numbers and "28% higher at 6–9 PM" claim are **not** used | They are illustrative. The insight card text is built from verified measures: seeded 02–04 ET uplift and the approved 18–21 ET peak result (no uplift). |
| Executive layout follows the concept's analytics area: 4 KPI tiles (icon, value, coloured latest-month line), trend panel, white insight + failure-by-hour panel; slicers moved into the header band | Owner's locked concept. Refund/reversal amounts and the monthly/cohort tables are approved v1 KPIs, so they stay in a third row. |
| KPI-tile line compares the **latest completed ET month that has data** with the month before (Sep vs Aug 2026), months named on the card (**approved by owner 2026-11-18**) | Applies the approved completed-month MoM rule. The strictly latest completed month (Oct 2026) has no data, which would show −100%; naming the months keeps it transparent. |
| No dual-axis chart (concept combines volume bars + success-rate line) | Two y-scales mislead; attempts and success rate are two side-by-side charts. |
| Classic cards: container title = metric + date basis; card's own label hidden; full values (no K) | Removes the duplicated, clipped label and makes the date basis explicit on every card. |
| Date charts open expanded to Month | Data covers ~4 months; a single Year bar says nothing at first glance. Drill down still reaches Day. |
| `Month State` blank when the month has no attempts; cohort numerators `COALESCE(…, 0)` | Hides empty calendar months; a cohort with successes but no refunds shows 0%, like SQL (zero denominator still blank). |
| No `///` descriptions on relationships | TMDL turns `///` into a `description` property, which relationships do not have; Desktop refuses to open the model. Relationship explanations live in `dax_measures.md`. |
| `dim_date` marked as date table + own Year > Quarter > Month > Day hierarchy | Needed for `DATEADD` in MoM and for one shared calendar across both facts (auto date/time would create hidden per-column tables). |
| Inactive `fact_adjustment[attempt_date_key]` + `USERELATIONSHIP` in cohort measures | Amount cards use the event date; cohort rates use the original attempt date (approved KPI semantics). |
| `attempt_hour_et` computed in SQL (native query) | Same DST-aware conversion as `attempt_date_key`; Power Query has no named-time-zone DST rules. |
| Hidden `AsOf` table from `audit.etl_run` (**approved by owner 2026-11-18**) | As-of must be the stored batch cutoff, not the clock; a fixed parameter would go stale with every batch. |
| Both peak windows as measures: approved 18–20 ET is the official KPI; seeded 02–03 ET is a pattern check (**owner decision 2026-11-18**) | The approved window shows −12.71% (no uplift); the generator seeded 02–03 (+82.25%). Known generator deviation, documented rather than hidden; a rule change needs a new requirements version. |

## Known limits (documented, not hidden)
- Single-worker v1: concurrent runs of the same batch are unsupported beyond the per-run app lock (locked Step 4).
- An abrupt process crash can leave a run `RUNNING` (no partial data is committed); an operator re-runs the same `run_id`.
- `sqlcmd` must be run with `-I` (QUOTED_IDENTIFIER ON) because of the filtered unique indexes.
