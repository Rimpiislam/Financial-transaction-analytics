/* Fingerprint of all data tables (row counts + order-independent checksums over every column).
   Run before and after a re-invocation: identical output = no data changed. etl_run is listed
   separately because an ALREADY_PROCESSED re-invocation is expected to ADD one audit row. */
SET NOCOUNT ON;
SELECT 'curated.fact_payment_attempt' AS tbl, COUNT(*) AS n, CHECKSUM_AGG(BINARY_CHECKSUM(*)) AS chk FROM curated.fact_payment_attempt
UNION ALL SELECT 'curated.fact_adjustment', COUNT(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM curated.fact_adjustment
UNION ALL SELECT 'audit.reject_log', COUNT(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM audit.reject_log
UNION ALL SELECT 'staging.payment_attempt_raw', COUNT(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM staging.payment_attempt_raw
UNION ALL SELECT 'staging.adjustment_raw', COUNT(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM staging.adjustment_raw
UNION ALL SELECT 'audit.etl_run (runs 1-2 only)', COUNT(*), CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM audit.etl_run WHERE run_id IN (1,2);
SELECT run_id, source_type, run_status, rows_read, rows_loaded, rows_rejected, message FROM audit.etl_run ORDER BY run_id;
