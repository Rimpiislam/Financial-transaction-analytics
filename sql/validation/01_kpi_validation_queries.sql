/* Phase 4C step 6 - canonical SQL KPI queries (read-only).
   These are the reference numbers Power BI must match (kpi_definitions.md acceptance test 8).
   Reporting basis: ET dates via curated.dim_date; as-of cutoff = batch_extraction_cutoff_utc of the
   latest COMPLETED payment run (2026-11-13 00:00 UTC). Run with: sqlcmd -I -i this_file */
SET NOCOUNT ON;
DECLARE @asof_utc DATETIME2(3) = (SELECT MAX(batch_extraction_cutoff_utc) FROM audit.etl_run
                                  WHERE run_status = 'COMPLETED' AND source_type = 'PAYMENT_ATTEMPT');
DECLARE @asof_et_date DATE = CAST((@asof_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time' AS DATE);
SELECT @asof_utc AS as_of_cutoff_utc, @asof_et_date AS as_of_et_date;

PRINT '== Q1 Overall KPIs (attempt date ET, all data)';
SELECT COUNT(*)                                                     AS total_attempts,
       SUM(CASE WHEN status = 'Success'   THEN 1 ELSE 0 END)        AS success_count,
       SUM(CASE WHEN status = 'Failed'    THEN 1 ELSE 0 END)        AS failed_count,
       SUM(CASE WHEN status = 'Pending'   THEN 1 ELSE 0 END)        AS pending_count,
       SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END)        AS cancelled_count,
       CAST(100.0 * SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END), 0) AS DECIMAL(6,2)) AS success_rate_pct,
       CAST(100.0 * SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END), 0) AS DECIMAL(6,2)) AS failure_rate_pct,
       SUM(CASE WHEN status = 'Success' THEN amount_usd ELSE 0 END) AS gross_successful_value_usd,
       SUM(amount_usd)                                              AS attempted_value_usd
FROM curated.fact_payment_attempt;

PRINT '== Q2 Status mix by ET month + MoM (completed months only; month containing the as-of date = MTD)';
WITH m AS (
    SELECT d.year_num, d.month_num, MIN(d.month_name) AS month_name,
           EOMONTH(DATEFROMPARTS(d.year_num, d.month_num, 1)) AS month_end,
           COUNT(*) AS attempts,
           SUM(CASE WHEN f.status = 'Success' THEN 1 ELSE 0 END) AS success,
           SUM(CASE WHEN f.status = 'Failed' THEN 1 ELSE 0 END) AS failed,
           SUM(CASE WHEN f.status = 'Pending' THEN 1 ELSE 0 END) AS pending,
           SUM(CASE WHEN f.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled,
           SUM(CASE WHEN f.status = 'Success' THEN f.amount_usd ELSE 0 END) AS gross_successful_value
    FROM curated.fact_payment_attempt f JOIN curated.dim_date d ON d.date_key = f.attempt_date_key
    GROUP BY d.year_num, d.month_num
), r AS (
    SELECT *, CAST(100.0 * success / NULLIF(success + failed, 0) AS DECIMAL(6,2)) AS success_rate_pct,
           CASE WHEN month_end < @asof_et_date THEN 'Completed' ELSE 'MTD' END AS month_state
    FROM m
)
SELECT year_num, month_num, month_name, month_state, attempts, success, failed, pending, cancelled,
       success_rate_pct, gross_successful_value,
       CASE WHEN month_state = 'Completed' AND LAG(month_state) OVER (ORDER BY year_num, month_num) = 'Completed'
                 AND DATEDIFF(MONTH, LAG(month_end) OVER (ORDER BY year_num, month_num), month_end) = 1
            THEN CAST(100.0 * (attempts - LAG(attempts) OVER (ORDER BY year_num, month_num))
                      / NULLIF(LAG(attempts) OVER (ORDER BY year_num, month_num), 0) AS DECIMAL(8,2)) END AS mom_attempts_pct,
       CASE WHEN month_state = 'Completed' AND LAG(month_state) OVER (ORDER BY year_num, month_num) = 'Completed'
                 AND DATEDIFF(MONTH, LAG(month_end) OVER (ORDER BY year_num, month_num), month_end) = 1
            THEN success_rate_pct - LAG(success_rate_pct) OVER (ORDER BY year_num, month_num) END AS mom_success_rate_pp
FROM r ORDER BY year_num, month_num;

PRINT '== Q3 Status mix by payment method';
SELECT m.payment_method_name, COUNT(*) AS attempts,
       SUM(CASE WHEN f.status = 'Success' THEN 1 ELSE 0 END) AS success,
       SUM(CASE WHEN f.status = 'Failed' THEN 1 ELSE 0 END) AS failed,
       CAST(100.0 * SUM(CASE WHEN f.status = 'Success' THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN f.status IN ('Success','Failed') THEN 1 ELSE 0 END), 0) AS DECIMAL(6,2)) AS success_rate_pct
FROM curated.fact_payment_attempt f JOIN curated.dim_payment_method m ON m.payment_method_key = f.payment_method_key
GROUP BY m.payment_method_name ORDER BY m.payment_method_name;

PRINT '== Q4 Failure share by reason';
SELECT r.failure_reason_code, COUNT(*) AS failures,
       CAST(100.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS DECIMAL(6,2)) AS share_of_failures_pct
FROM curated.fact_payment_attempt f JOIN curated.dim_failure_reason r ON r.failure_reason_key = f.failure_reason_key
WHERE f.status = 'Failed'
GROUP BY r.failure_reason_code ORDER BY failures DESC;

PRINT '== Q5 Failure rate and AUTH_TIMEOUT by ET hour (0-23)';
WITH h AS (
    SELECT DATEPART(HOUR, (f.attempt_timestamp_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time') AS et_hour,
           f.status, r.failure_reason_code
    FROM curated.fact_payment_attempt f LEFT JOIN curated.dim_failure_reason r ON r.failure_reason_key = f.failure_reason_key
)
SELECT et_hour,
       SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END) AS processed,
       SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
       SUM(CASE WHEN failure_reason_code = 'AUTH_TIMEOUT' THEN 1 ELSE 0 END) AS auth_timeout,
       CAST(100.0 * SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END), 0) AS DECIMAL(6,2)) AS failure_rate_pct,
       CAST(100.0 * SUM(CASE WHEN failure_reason_code = 'AUTH_TIMEOUT' THEN 1 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END), 0) AS DECIMAL(6,2)) AS auth_timeout_rate_pct
FROM h GROUP BY et_hour ORDER BY et_hour;

PRINT '== Q6 Seeded window check: 02:00-03:59 ET vs all other hours (synthetic pattern, disclosed)';
WITH h AS (
    SELECT CASE WHEN DATEPART(HOUR, (f.attempt_timestamp_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time') IN (2, 3)
                THEN '02:00-03:59 ET' ELSE 'other hours' END AS window_name,
           f.status, r.failure_reason_code
    FROM curated.fact_payment_attempt f LEFT JOIN curated.dim_failure_reason r ON r.failure_reason_key = f.failure_reason_key
), w AS (
    SELECT window_name,
           SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END) AS processed,
           SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
           SUM(CASE WHEN failure_reason_code = 'AUTH_TIMEOUT' THEN 1 ELSE 0 END) AS auth_timeout
    FROM h GROUP BY window_name
)
SELECT window_name, processed, failed, auth_timeout,
       CAST(100.0 * failed / NULLIF(processed, 0) AS DECIMAL(6,2)) AS failure_rate_pct,
       CAST(100.0 * auth_timeout / NULLIF(failed, 0) AS DECIMAL(6,2)) AS auth_timeout_share_of_failures_pct
FROM w ORDER BY window_name;
SELECT CAST(100.0 * (
        (SELECT 1.0 * SUM(CASE WHEN f.status='Failed' THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN f.status IN ('Success','Failed') THEN 1 ELSE 0 END),0)
         FROM curated.fact_payment_attempt f WHERE DATEPART(HOUR, (f.attempt_timestamp_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time') IN (2,3))
      / NULLIF((SELECT 1.0 * SUM(CASE WHEN f.status='Failed' THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN f.status IN ('Success','Failed') THEN 1 ELSE 0 END),0)
         FROM curated.fact_payment_attempt f WHERE DATEPART(HOUR, (f.attempt_timestamp_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time') NOT IN (2,3)), 0)
      - 1) AS DECIMAL(8,2)) AS failure_rate_uplift_pct_window_vs_other;

PRINT '== Q6b Approved KPI peak window (kpi_definitions.md test 7): ET hours 18,19,20 vs non-peak';
WITH h AS (
    SELECT CASE WHEN DATEPART(HOUR, (f.attempt_timestamp_utc AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time') IN (18, 19, 20)
                THEN 'peak 18:00-20:59 ET' ELSE 'non-peak' END AS window_name, f.status
    FROM curated.fact_payment_attempt f
), w AS (
    SELECT window_name, SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END) AS processed,
           SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed
    FROM h GROUP BY window_name
)
SELECT window_name, processed, failed, CAST(100.0 * failed / NULLIF(processed, 0) AS DECIMAL(6,2)) AS failure_rate_pct,
       CAST(100.0 * ((1.0 * failed / processed) / NULLIF((SELECT 1.0 * failed / processed FROM w WHERE window_name = 'non-peak'), 0) - 1) AS DECIMAL(8,2)) AS uplift_vs_nonpeak_pct
FROM w ORDER BY window_name DESC;

PRINT '== Q7 Adjustments by type (event date ET, by month)';
SELECT d.year_num, d.month_num, a.adjustment_type, COUNT(*) AS events, SUM(a.adjustment_amount_usd) AS amount_usd
FROM curated.fact_adjustment a JOIN curated.dim_date d ON d.date_key = a.adjustment_date_key
GROUP BY d.year_num, d.month_num, a.adjustment_type ORDER BY d.year_num, d.month_num, a.adjustment_type;
SELECT adjustment_type, COUNT(*) AS events, SUM(adjustment_amount_usd) AS amount_usd
FROM curated.fact_adjustment GROUP BY adjustment_type ORDER BY adjustment_type;

PRINT '== Q8 Cohort refund / reversal rates by ORIGINAL attempt month, as-of cutoff, maturity';
WITH s AS (
    SELECT d.year_num, d.month_num, EOMONTH(DATEFROMPARTS(d.year_num, d.month_num, 1)) AS cohort_end,
           f.transaction_id, f.amount_usd
    FROM curated.fact_payment_attempt f JOIN curated.dim_date d ON d.date_key = f.attempt_date_key
    WHERE f.status = 'Success'
), a AS (
    SELECT transaction_id,
           MAX(CASE WHEN adjustment_type = 'Refund' THEN 1 ELSE 0 END)   AS has_refund,
           MAX(CASE WHEN adjustment_type = 'Reversal' THEN 1 ELSE 0 END) AS has_reversal,
           SUM(CASE WHEN adjustment_type = 'Refund' THEN adjustment_amount_usd ELSE 0 END) AS refund_amt
    FROM curated.fact_adjustment
    WHERE adjustment_timestamp_utc <= @asof_utc            -- only adjustments observed by the as-of cutoff
    GROUP BY transaction_id
)
SELECT s.year_num, s.month_num,
       CASE WHEN @asof_et_date < DATEADD(DAY, 30, MAX(s.cohort_end)) THEN 'Immature' ELSE 'Mature' END AS maturity,
       COUNT(*) AS successful_originals,
       SUM(ISNULL(a.has_refund, 0))   AS refunded_txns,
       SUM(ISNULL(a.has_reversal, 0)) AS reversed_txns,
       CAST(100.0 * SUM(ISNULL(a.has_refund, 0)) / COUNT(*) AS DECIMAL(6,2))   AS refunded_txn_rate_pct,
       CAST(100.0 * SUM(ISNULL(a.has_reversal, 0)) / COUNT(*) AS DECIMAL(6,2)) AS reversed_txn_rate_pct,
       CAST(100.0 * SUM(ISNULL(a.refund_amt, 0)) / NULLIF(SUM(s.amount_usd), 0) AS DECIMAL(6,2)) AS refund_value_rate_pct
FROM s LEFT JOIN a ON a.transaction_id = s.transaction_id
GROUP BY s.year_num, s.month_num ORDER BY s.year_num, s.month_num;

PRINT '== Q9 Aged pending (> 24h before as-of cutoff; flag only, not rejected)';
SELECT COUNT(*) AS aged_pending FROM curated.fact_payment_attempt
WHERE status = 'Pending' AND attempt_timestamp_utc < DATEADD(HOUR, -24, @asof_utc);

PRINT '== Q10 Consistency tests (kpi_definitions.md 1, 2, 4, 5): every row must show PASS';
SELECT 'T1 total = success+failed+pending+cancelled' AS test,
       CASE WHEN COUNT(*) = SUM(CASE WHEN status IN ('Success','Failed','Pending','Cancelled') THEN 1 ELSE 0 END) THEN 'PASS' ELSE 'FAIL' END AS result
FROM curated.fact_payment_attempt
UNION ALL
SELECT 'T2 success rate + failure rate = 100',
       CASE WHEN ABS(100.0 * SUM(CASE WHEN status='Success' THEN 1 ELSE 0 END) / SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END)
                   + 100.0 * SUM(CASE WHEN status='Failed' THEN 1 ELSE 0 END) / SUM(CASE WHEN status IN ('Success','Failed') THEN 1 ELSE 0 END) - 100) < 0.0001
            THEN 'PASS' ELSE 'FAIL' END
FROM curated.fact_payment_attempt
UNION ALL
SELECT 'T5a every adjustment parent is Success',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             WHERE f.status <> 'Success') THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T5b adjustment timestamp >= attempt timestamp',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             WHERE a.adjustment_timestamp_utc < f.attempt_timestamp_utc) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T5c cumulative adjustments <= original amount',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             GROUP BY a.transaction_id, f.amount_usd HAVING SUM(a.adjustment_amount_usd) > f.amount_usd) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T5d reversal = full amount and alone on its transaction',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             WHERE a.adjustment_type = 'Reversal'
                               AND (a.adjustment_amount_usd <> f.amount_usd
                                    OR EXISTS (SELECT 1 FROM curated.fact_adjustment o WHERE o.transaction_id = a.transaction_id AND o.adjustment_id <> a.adjustment_id)))
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T5e settlement timing (reversal < +24h <= refund)',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             WHERE (a.adjustment_type = 'Reversal' AND a.adjustment_timestamp_utc >= DATEADD(HOUR, 24, f.attempt_timestamp_utc))
                                OR (a.adjustment_type = 'Refund'   AND a.adjustment_timestamp_utc <  DATEADD(HOUR, 24, f.attempt_timestamp_utc)))
            THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T6 adjustment method/attempt date = parent (denormalized keys)',
       CASE WHEN NOT EXISTS (SELECT 1 FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt f ON f.transaction_id = a.transaction_id
                             WHERE a.attempt_date_key <> f.attempt_date_key OR a.payment_method_key <> f.payment_method_key) THEN 'PASS' ELSE 'FAIL' END
UNION ALL
SELECT 'T7 every run reconciles rows_read = loaded + rejected',
       CASE WHEN NOT EXISTS (SELECT 1 FROM audit.etl_run WHERE run_status = 'COMPLETED' AND rows_read <> rows_loaded + rows_rejected) THEN 'PASS' ELSE 'FAIL' END;
