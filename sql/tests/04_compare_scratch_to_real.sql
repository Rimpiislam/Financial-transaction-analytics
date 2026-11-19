/* All-column comparison of curated facts: scratch database rebuilt by this loader vs the production database.
   Read-only on both databases. Expect 0 differences in every direction. */
SET NOCOUNT ON;
SELECT 'fact_payment_attempt' AS tbl,
  (SELECT COUNT(*) FROM FinancialIntelligence.curated.fact_payment_attempt)          AS real_rows,
  (SELECT COUNT(*) FROM FinancialIntelligence_Scratch.curated.fact_payment_attempt)  AS scratch_rows,
  (SELECT COUNT(*) FROM (SELECT * FROM FinancialIntelligence.curated.fact_payment_attempt
                         EXCEPT SELECT * FROM FinancialIntelligence_Scratch.curated.fact_payment_attempt) d) AS in_real_not_scratch,
  (SELECT COUNT(*) FROM (SELECT * FROM FinancialIntelligence_Scratch.curated.fact_payment_attempt
                         EXCEPT SELECT * FROM FinancialIntelligence.curated.fact_payment_attempt) d) AS in_scratch_not_real
UNION ALL
SELECT 'fact_adjustment',
  (SELECT COUNT(*) FROM FinancialIntelligence.curated.fact_adjustment),
  (SELECT COUNT(*) FROM FinancialIntelligence_Scratch.curated.fact_adjustment),
  (SELECT COUNT(*) FROM (SELECT * FROM FinancialIntelligence.curated.fact_adjustment
                         EXCEPT SELECT * FROM FinancialIntelligence_Scratch.curated.fact_adjustment) d),
  (SELECT COUNT(*) FROM (SELECT * FROM FinancialIntelligence_Scratch.curated.fact_adjustment
                         EXCEPT SELECT * FROM FinancialIntelligence.curated.fact_adjustment) d)
UNION ALL
SELECT 'reject_log',
  (SELECT COUNT(*) FROM FinancialIntelligence.audit.reject_log),
  (SELECT COUNT(*) FROM FinancialIntelligence_Scratch.audit.reject_log), NULL, NULL;

SELECT 'real' AS db, run_id, source_type, run_status, rows_read, rows_loaded, rows_rejected, message
FROM FinancialIntelligence.audit.etl_run
UNION ALL
SELECT 'scratch', run_id, source_type, run_status, rows_read, rows_loaded, rows_rejected, message
FROM FinancialIntelligence_Scratch.audit.etl_run
ORDER BY db, run_id;
