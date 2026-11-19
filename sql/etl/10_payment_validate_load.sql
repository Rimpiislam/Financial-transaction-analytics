/* Phase 4C - set-based validation + curated load for ONE payment-attempt run.
   Executed by python/03_validate_and_load_curated.py inside its single run transaction
   (SET XACT_ABORT ON, sp_getapplock already held). Do not run on its own.

   Preconditions created by the orchestrator in the same session:
     #precedence(code, ord)  -- the ONE ordered reject-code list (docs/reject_codes.md)
   Parameter: @run_id (the single ODBC parameter marker below).
   Returns one row: staged, inserted, updated, rejected. */
SET NOCOUNT ON;
DECLARE @run_id BIGINT = ?;
DECLARE @cutoff DATETIME2(3), @batch_id VARCHAR(100);
SELECT @cutoff = batch_extraction_cutoff_utc, @batch_id = batch_id
FROM audit.etl_run WHERE run_id = @run_id;

DROP TABLE IF EXISTS #n, #p, #v;

/* 1. Normalize. Staging stores empty CSV fields as '' -> NULLIF(TRIM) so blanks = NULL. */
SELECT s.stg_row_id, s.source_row_ref,
       s.transaction_id_raw, s.attempt_timestamp_raw, s.amount_raw, s.currency_raw,
       s.merchant_id_raw, s.payment_method_raw, s.status_raw, s.failure_reason_raw,
       s.status_updated_at_raw,
       NULLIF(LTRIM(RTRIM(s.transaction_id_raw)), '')            AS tx,
       NULLIF(LTRIM(RTRIM(s.attempt_timestamp_raw)), '')         AS ts_s,
       NULLIF(LTRIM(RTRIM(s.amount_raw)), '')                    AS amt_s,
       UPPER(NULLIF(LTRIM(RTRIM(s.currency_raw)), ''))           AS cur,
       NULLIF(LTRIM(RTRIM(s.merchant_id_raw)), '')               AS merchant,
       NULLIF(LTRIM(RTRIM(s.payment_method_raw)), '')            AS method_s,
       NULLIF(LTRIM(RTRIM(s.status_raw)), '')                    AS status_s,
       NULLIF(LTRIM(RTRIM(s.failure_reason_raw)), '')            AS reason_s,
       NULLIF(LTRIM(RTRIM(s.status_updated_at_raw)), '')         AS upd_s
INTO #n
FROM staging.payment_attempt_raw s
WHERE s.run_id = @run_id;

/* 2. Parse + look up (no rounding, no guessing).
   Timestamp: strict ISO-8601 UTC  yyyy-mm-ddThh:mi:ss[.f{1,3}][Z]
   Amount:    [+|-] 1-16 digits [. 1-2 digits]  -> fits DECIMAL(18,2) exactly
   ET date:   DST-aware AT TIME ZONE 'Eastern Standard Time' -> dim_date key */
SELECT n.*,
       t1.ts, t2.upd, a.amt,
       dd.date_key                                   AS attempt_date_key,
       pm.payment_method_key, pm.payment_method_name,
       st.status,
       fr.failure_reason_key, fr.failure_reason_code,
       ROW_NUMBER() OVER (PARTITION BY n.tx ORDER BY n.stg_row_id) AS dup_rn, -- first occurrence wins
       CASE WHEN EXISTS (SELECT 1 FROM curated.fact_payment_attempt e WHERE e.transaction_id = n.tx)
            THEN 1 ELSE 0 END AS is_existing                                     -- captured before any write
INTO #p
FROM #n n
OUTER APPLY (SELECT x.s, CASE WHEN RIGHT(x.s,1)='Z' THEN LEFT(x.s, LEN(x.s)-1) ELSE x.s END AS sfx
             FROM (SELECT SUBSTRING(n.ts_s, 20, 100) AS s) x) tsfx
OUTER APPLY (SELECT CASE WHEN n.ts_s LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]%'
                          AND (tsfx.sfx = '' OR tsfx.sfx LIKE '.[0-9]' OR tsfx.sfx LIKE '.[0-9][0-9]' OR tsfx.sfx LIKE '.[0-9][0-9][0-9]')
                         THEN TRY_CONVERT(DATETIME2(3), LEFT(n.ts_s,19) + tsfx.sfx, 126) END AS ts) t1
OUTER APPLY (SELECT x.s, CASE WHEN RIGHT(x.s,1)='Z' THEN LEFT(x.s, LEN(x.s)-1) ELSE x.s END AS sfx
             FROM (SELECT SUBSTRING(n.upd_s, 20, 100) AS s) x) usfx
OUTER APPLY (SELECT CASE WHEN n.upd_s LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]%'
                          AND (usfx.sfx = '' OR usfx.sfx LIKE '.[0-9]' OR usfx.sfx LIKE '.[0-9][0-9]' OR usfx.sfx LIKE '.[0-9][0-9][0-9]')
                         THEN TRY_CONVERT(DATETIME2(3), LEFT(n.upd_s,19) + usfx.sfx, 126) END AS upd) t2
OUTER APPLY (SELECT CASE WHEN LEFT(n.amt_s,1) IN ('+','-') THEN STUFF(n.amt_s,1,1,'') ELSE n.amt_s END AS body) ab
OUTER APPLY (SELECT CHARINDEX('.', ab.body) AS dot) ad
OUTER APPLY (SELECT CASE WHEN ab.body NOT LIKE '%[^0-9.]%'
                          AND LEN(ab.body) - LEN(REPLACE(ab.body,'.','')) <= 1
                          AND (CASE ad.dot WHEN 0 THEN LEN(ab.body) ELSE ad.dot - 1 END) BETWEEN 1 AND 16
                          AND (ad.dot = 0 OR LEN(ab.body) - ad.dot BETWEEN 1 AND 2)
                         THEN TRY_CONVERT(DECIMAL(18,2), n.amt_s) END AS amt) a
OUTER APPLY (SELECT CAST((t1.ts AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time' AS DATE) AS et_date) et
LEFT JOIN curated.dim_date dd            ON dd.full_date = et.et_date
LEFT JOIN curated.dim_payment_method pm  ON UPPER(pm.payment_method_name) = UPPER(n.method_s)
LEFT JOIN curated.dim_failure_reason fr  ON UPPER(fr.failure_reason_code) = UPPER(n.reason_s)
OUTER APPLY (SELECT v.s AS status FROM (VALUES ('Pending'),('Success'),('Failed'),('Cancelled')) v(s)
             WHERE UPPER(v.s) = UPPER(n.status_s)) st;

/* 3. Stages 1-3: every check evaluated for every row (all violations kept for details).
      #v declared explicitly: SELECT INTO would size `code` to the longest literal in this
      statement and truncate longer codes added later. */
CREATE TABLE #v (stg_row_id BIGINT NOT NULL, code VARCHAR(50) NOT NULL);
INSERT INTO #v (stg_row_id, code)
SELECT p.stg_row_id, c.code
FROM #p p
CROSS APPLY (VALUES
  -- stage 1: required / parse / type / amount / timestamp
  (CASE WHEN p.tx IS NULL OR p.ts_s IS NULL OR p.amt_s IS NULL OR p.cur IS NULL OR p.merchant IS NULL
              OR p.method_s IS NULL OR p.status_s IS NULL OR p.upd_s IS NULL
        THEN 'MISSING_REQUIRED_FIELD' END),
  (CASE WHEN (p.ts_s  IS NOT NULL AND p.ts  IS NULL)
          OR (p.upd_s IS NOT NULL AND p.upd IS NULL)
          OR (p.amt_s IS NOT NULL AND p.amt IS NULL)
          OR (p.ts IS NOT NULL AND p.attempt_date_key IS NULL)       -- ET date outside dim_date (2024-2030)
          OR (p.ts IS NOT NULL AND p.upd IS NOT NULL AND p.upd < p.ts) -- status update before attempt
        THEN 'INVALID_FORMAT' END),
  (CASE WHEN p.amt <= 0 THEN 'NONPOSITIVE_AMOUNT' END),
  (CASE WHEN p.ts > @cutoff THEN 'FUTURE_ATTEMPT_TIMESTAMP' END),  -- stored cutoff, never the clock
  -- stage 2: controlled values / status-reason consistency
  (CASE WHEN (p.cur IS NOT NULL AND p.cur <> 'USD')
          OR (p.method_s IS NOT NULL AND p.payment_method_key IS NULL)
          OR (p.status_s IS NOT NULL AND p.status IS NULL)
          OR (p.reason_s IS NOT NULL AND p.failure_reason_key IS NULL)
        THEN 'INVALID_CONTROLLED_VALUE' END),
  (CASE WHEN (p.status = 'Failed' AND p.reason_s IS NULL)
          OR (p.status IN ('Pending','Success','Cancelled') AND p.reason_s IS NOT NULL)
        THEN 'FAILURE_REASON_STATUS_MISMATCH' END),
  -- stage 3: intra-batch duplicate identity (first parseable occurrence reserved, even if rejected)
  (CASE WHEN p.tx IS NOT NULL AND p.dup_rn > 1 THEN 'DUPLICATE_IN_BATCH' END)
) c(code)
WHERE c.code IS NOT NULL;

/* 4. Stage 4: existing-record conflicts. Needs valid parsed values, so only rows clean
      through stage 3 are compared. Business IDs compared (method name), not surrogate keys. */
INSERT INTO #v (stg_row_id, code)
SELECT p.stg_row_id, k.code
FROM #p p
JOIN curated.fact_payment_attempt e      ON e.transaction_id = p.tx
JOIN curated.dim_payment_method em       ON em.payment_method_key = e.payment_method_key
LEFT JOIN curated.dim_failure_reason ef  ON ef.failure_reason_key = e.failure_reason_key
CROSS APPLY (SELECT CASE
    WHEN NOT (e.attempt_timestamp_utc = p.ts AND e.amount_usd = p.amt AND e.currency = p.cur
              AND e.merchant_id = p.merchant AND em.payment_method_name = p.payment_method_name
              AND NOT (e.status = 'Failed' AND p.status = 'Failed'
                       AND ef.failure_reason_code <> p.failure_reason_code))
        THEN 'IMMUTABLE_FIELD_CONFLICT'
    WHEN e.status = p.status
         AND ISNULL(e.failure_reason_key, -1) = ISNULL(p.failure_reason_key, -1)
        THEN 'DUPLICATE_RECORD'
    WHEN e.status = 'Pending' AND p.status IN ('Success','Failed','Cancelled')
         AND p.upd >= e.status_updated_at_utc
        THEN NULL                                   -- VALID_STATUS_UPDATE
    ELSE 'INVALID_STATUS_TRANSITION' END AS code) k
WHERE k.code IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = p.stg_row_id);

/* Guard: every code produced must be in the ONE precedence list. */
IF EXISTS (SELECT 1 FROM #v v WHERE NOT EXISTS (SELECT 1 FROM #precedence x WHERE x.code = v.code))
    THROW 50001, 'Validation produced a reject code that is not in the precedence list.', 1;

/* 5. Exactly one reject_log row per rejected source row: primary + other violations. */
INSERT INTO audit.reject_log
    (run_id, batch_id, source_type, source_row_ref, primary_reject_code, reject_details, raw_record)
SELECT @run_id, @batch_id, 'PAYMENT_ATTEMPT', p.source_row_ref, pr.code, det.details, rj.j
FROM #p p
CROSS APPLY (SELECT TOP (1) v.code FROM #v v JOIN #precedence x ON x.code = v.code
             WHERE v.stg_row_id = p.stg_row_id ORDER BY x.ord) pr
OUTER APPLY (SELECT STRING_AGG(v.code, ', ') WITHIN GROUP (ORDER BY x.ord) AS details
             FROM #v v JOIN #precedence x ON x.code = v.code
             WHERE v.stg_row_id = p.stg_row_id AND v.code <> pr.code) det
CROSS APPLY (SELECT (SELECT p.transaction_id_raw AS transaction_id, p.attempt_timestamp_raw AS attempt_timestamp_utc,
                            p.amount_raw AS amount, p.currency_raw AS currency, p.merchant_id_raw AS merchant_id,
                            p.payment_method_raw AS payment_method, p.status_raw AS status,
                            p.failure_reason_raw AS failure_reason, p.status_updated_at_raw AS status_updated_at_utc
                     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) AS j) rj;
DECLARE @rejected INT = @@ROWCOUNT;

/* 6. Valid Pending -> final updates (existing row, passed stage 4). */
UPDATE e
SET e.status = p.status, e.failure_reason_key = p.failure_reason_key,
    e.status_updated_at_utc = p.upd, e.status_updated_run_id = @run_id
FROM curated.fact_payment_attempt e
JOIN #p p ON p.tx = e.transaction_id
WHERE p.is_existing = 1
  AND NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = p.stg_row_id);
DECLARE @updated INT = @@ROWCOUNT;

/* 7. New attempts. */
INSERT INTO curated.fact_payment_attempt
    (transaction_id, attempt_timestamp_utc, attempt_date_key, amount_usd, currency, merchant_id,
     payment_method_key, status, failure_reason_key, status_updated_at_utc, inserted_run_id, status_updated_run_id)
SELECT p.tx, p.ts, p.attempt_date_key, p.amt, p.cur, p.merchant,
       p.payment_method_key, p.status, p.failure_reason_key, p.upd, @run_id, @run_id
FROM #p p
WHERE p.is_existing = 0
  AND NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = p.stg_row_id);
DECLARE @inserted INT = @@ROWCOUNT;

SELECT (SELECT COUNT(*) FROM #p) AS staged, @inserted AS inserted, @updated AS updated, @rejected AS rejected;
