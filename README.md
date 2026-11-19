# Financial Transaction Analytics

End-to-end analytics on synthetic payment data: where payments fail, why, and how refunds and reversals relate to successful payments.

**Stack:** Python ETL → SQL Server → Power BI

> All data is synthetic. No employer or customer data is used.

## Key design decisions

- Refunds and reversals are tracked separately and never change a payment's original success status or the success-rate denominator.
- Every KPI has a written definition, date basis, and consistency test before any number is published.
- The dataset uses a fixed random seed; any intentionally injected pattern is documented as synthetic, not presented as a real-world insight.

## Dashboard

Power BI project: `PowerBi/FinancialIntelligence.pbip` (open in Power BI Desktop, then Refresh).

- **Executive Overview:** attempts, gross successful value, success rate and failed attempts with
  latest-month change; volume and success-rate trend; key insight; failure rate by hour;
  refund / reversal amounts; monthly KPIs and cohort refund / reversal rates.
- **Failure Analysis:** failure and AUTH_TIMEOUT rates by ET hour, failures by reason and payment method.
- **Transaction Detail:** drill-through to the attempts behind a payment method or failure reason.

Every dashboard number is checked against SQL reference queries ([test results](docs/test_results.md)).

## How it works

Python generates synthetic CSVs → staged in SQL Server with an audit row per run → set-based SQL
validates each row (17 reject codes, fixed precedence) and loads curated facts in one transaction
per run → Power BI reads the curated model.

## How to run

1. Create the schema: `sql/01_create_schemas_and_tables.sql`
2. `python python/01_generate_synthetic_data.py`
3. `python python/02_load_staging.py`
4. `python python/03_validate_and_load_curated.py --run-id 1 --run-id 2`
5. Open `PowerBi/FinancialIntelligence.pbip` and Refresh.

## Project status

- [x] Phase 1: Business requirements and KPI definitions (v1.0 approved)
- [x] Phase 2: Data model design
- [x] Phase 3: Synthetic data generation and ETL
- [x] Phase 4: Power BI dashboard

## Documentation

- [Business requirements](docs/business_requirements.md)
- [KPI definitions](docs/kpi_definitions.md)
- [Design decisions](docs/design_decisions.md)
- [Reject codes and precedence](docs/reject_codes.md)
- [DAX measures](docs/dax_measures.md)
- [Test results](docs/test_results.md)
