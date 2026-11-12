# Financial Transaction Analytics

End-to-end analytics on synthetic payment data: where payments fail, why, and how refunds and reversals relate to successful payments.

**Stack:** Python ETL → SQL Server → Power BI

> All data is synthetic. No employer or customer data is used.

## Key design decisions

- Refunds and reversals are tracked separately and never change a payment's original success status or the success-rate denominator.
- Every KPI has a written definition, date basis, and consistency test before any number is published.
- The dataset uses a fixed random seed; any intentionally injected pattern is documented as synthetic, not presented as a real-world insight.

## Dashboard

In progress. Screenshots will be added once built from the generated data.

## Project status

- [x] Phase 1: Business requirements and KPI definitions (v1.0 approved)
- [ ] Phase 2: Data model design
- [ ] Phase 3: Synthetic data generation and ETL
- [ ] Phase 4: Power BI dashboard

## Documentation

- [Business requirements](docs/business_requirements.md)
- [KPI definitions](docs/kpi_definitions.md)
