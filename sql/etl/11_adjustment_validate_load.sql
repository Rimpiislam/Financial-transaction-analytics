/* Phase 4C - set-based validation + curated load for ONE adjustment run.
   Executed by python/03_validate_and_load_curated.py inside its single run transaction.
   Requires #precedence(code, ord) in the session. Parameter: @run_id.
   Parents are read from curated.fact_payment_attempt, so payment runs for the same
   cutoff must be COMPLETED first (the orchestrator enforces this).
   Returns one row: staged, inserted, updated(always 0), rejected. */
SET NOCOUNT ON;
DECLARE @run_id BIGINT = ?;
DECLARE @batch_id VARCHAR(100);
SELECT @batch_id = batch_id FROM audit.etl_run WHERE run_id = @run_id;

DROP TABLE IF EXISTS #n, #a, #v, #c, #acc;

/* 1. Normalize ('' -> NULL). */
SELECT s.stg_row_id, s.source_row_ref,
       s.adjustment_id_raw, s.transaction_id_raw, s.adjustment_type_raw,
       s.adjustment_amount_raw, s.adjustment_timestamp_raw,
       NULLIF(LTRIM(RTRIM(s.adjustment_id_raw)), '')        AS aid,
       NULLIF(LTRIM(RTRIM(s.transaction_id_raw)), '')       AS tx,
       NULLIF(LTRIM(RTRIM(s.adjustment_type_raw)), '')      AS type_s,
       NULLIF(LTRIM(RTRIM(s.adjustment_amount_raw)), '')    AS amt_s,
       NULLIF(LTRIM(RTRIM(s.adjustment_timestamp_raw)), '') AS ts_s
INTO #n
FROM staging.adjustment_raw s
WHERE s.run_id = @run_id;

/* 2. Parse + look up (same strict timestamp / amount rules as payments). */
SELECT n.*,
       t1.ts, a.amt, ty.adj_type,
       dd.date_key AS adjustment_date_key,
       ROW_NUMBER() OVER (PARTITION BY n.aid ORDER BY n.stg_row_id) AS dup_rn
INTO #a
FROM #n n
OUTER APPLY (SELECT x.s, CASE WHEN RIGHT(x.s,1)='Z' THEN LEFT(x.s, LEN(x.s)-1) ELSE x.s END AS sfx
             FROM (SELECT SUBSTRING(n.ts_s, 20, 100) AS s) x) tsfx
OUTER APPLY (SELECT CASE WHEN n.ts_s LIKE '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]%'
                          AND (tsfx.sfx = '' OR tsfx.sfx LIKE '.[0-9]' OR tsfx.sfx LIKE '.[0-9][0-9]' OR tsfx.sfx LIKE '.[0-9][0-9][0-9]')
                         THEN TRY_CONVERT(DATETIME2(3), LEFT(n.ts_s,19) + tsfx.sfx, 126) END AS ts) t1
OUTER APPLY (SELECT CASE WHEN LEFT(n.amt_s,1) IN ('+','-') THEN STUFF(n.amt_s,1,1,'') ELSE n.amt_s END AS body) ab
OUTER APPLY (SELECT CHARINDEX('.', ab.body) AS dot) ad
OUTER APPLY (SELECT CASE WHEN ab.body NOT LIKE '%[^0-9.]%'
                          AND LEN(ab.body) - LEN(REPLACE(ab.body,'.','')) <= 1
                          AND (CASE ad.dot WHEN 0 THEN LEN(ab.body) ELSE ad.dot - 1 END) BETWEEN 1 AND 16
                          AND (ad.dot = 0 OR LEN(ab.body) - ad.dot BETWEEN 1 AND 2)
                         THEN TRY_CONVERT(DECIMAL(18,2), n.amt_s) END AS amt) a
OUTER APPLY (SELECT v.s AS adj_type FROM (VALUES ('Refund'),('Reversal')) v(s)
             WHERE UPPER(v.s) = UPPER(n.type_s)) ty
OUTER APPLY (SELECT CAST((t1.ts AT TIME ZONE 'UTC') AT TIME ZONE 'Eastern Standard Time' AS DATE) AS et_date) et
LEFT JOIN curated.dim_date dd ON dd.full_date = et.et_date;

/* 3. Stages 1-3 for every row. #v declared explicitly: SELECT INTO would size `code`
      to the longest literal in this statement and truncate longer later codes. */
CREATE TABLE #v (stg_row_id BIGINT NOT NULL, code VARCHAR(50) NOT NULL);
INSERT INTO #v (stg_row_id, code)
SELECT a.stg_row_id, c.code
FROM #a a
CROSS APPLY (VALUES
  (CASE WHEN a.aid IS NULL OR a.tx IS NULL OR a.type_s IS NULL OR a.amt_s IS NULL OR a.ts_s IS NULL
        THEN 'MISSING_REQUIRED_FIELD' END),
  (CASE WHEN (a.amt_s IS NOT NULL AND a.amt IS NULL)
          OR (a.ts_s  IS NOT NULL AND a.ts  IS NULL)
          OR (a.ts IS NOT NULL AND a.adjustment_date_key IS NULL)
        THEN 'INVALID_FORMAT' END),
  (CASE WHEN a.amt <= 0 THEN 'NONPOSITIVE_AMOUNT' END),
  (CASE WHEN a.type_s IS NOT NULL AND a.adj_type IS NULL THEN 'INVALID_CONTROLLED_VALUE' END),
  (CASE WHEN a.aid IS NOT NULL AND a.dup_rn > 1 THEN 'DUPLICATE_IN_BATCH' END)
) c(code)
WHERE c.code IS NOT NULL;

/* 4. Stage 4: existing adjustment with the same ID (rows clean through stage 3). */
INSERT INTO #v (stg_row_id, code)
SELECT a.stg_row_id,
       CASE WHEN ea.transaction_id = a.tx AND ea.adjustment_type = a.adj_type
                 AND ea.adjustment_amount_usd = a.amt AND ea.adjustment_timestamp_utc = a.ts
            THEN 'DUPLICATE_ADJUSTMENT' ELSE 'ADJUSTMENT_FIELD_CONFLICT' END
FROM #a a
JOIN curated.fact_adjustment ea ON ea.adjustment_id = a.aid
WHERE NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = a.stg_row_id);

/* 5. Stage 5: parent relationship + synthetic settlement timing (rows clean through 4).
      settlement = attempt + 24h; Reversal strictly before, Refund at/after; never before attempt. */
INSERT INTO #v (stg_row_id, code)
SELECT a.stg_row_id, c.code
FROM #a a
LEFT JOIN curated.fact_payment_attempt par ON par.transaction_id = a.tx
CROSS APPLY (VALUES
  (CASE WHEN par.transaction_id IS NULL THEN 'ORPHAN_ADJUSTMENT' END),
  (CASE WHEN par.status <> 'Success' THEN 'ADJUSTMENT_ON_NON_SUCCESS' END),
  (CASE WHEN a.ts < par.attempt_timestamp_utc
          OR (a.adj_type = 'Refund'   AND a.ts <  DATEADD(HOUR, 24, par.attempt_timestamp_utc))
          OR (a.adj_type = 'Reversal' AND a.ts >= DATEADD(HOUR, 24, par.attempt_timestamp_utc))
        THEN 'INVALID_ADJUSTMENT_TIMING' END)
) c(code)
WHERE c.code IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = a.stg_row_id);

/* 6. Stage 6: sibling / cumulative rules, against curated + EARLIER ACCEPTED rows of this batch,
      ordered by (adjustment_timestamp_utc, adjustment_id). A rejected row must not count toward
      later rows' running total, so candidates are evaluated one rank at a time per parent:
      each pass is set-based across all parents; passes = max candidates on one transaction. */
SELECT a.stg_row_id, a.tx, a.adj_type, a.amt, par.amount_usd AS original_amount,
       ROW_NUMBER() OVER (PARTITION BY a.tx ORDER BY a.ts, a.aid) AS seq
INTO #c
FROM #a a
JOIN curated.fact_payment_attempt par ON par.transaction_id = a.tx
WHERE NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = a.stg_row_id);

SELECT fa.transaction_id AS tx, fa.adjustment_type AS adj_type, fa.adjustment_amount_usd AS amt
INTO #acc
FROM curated.fact_adjustment fa
WHERE fa.transaction_id IN (SELECT tx FROM #c);

DECLARE @k INT = 1, @max_k INT = (SELECT ISNULL(MAX(seq), 0) FROM #c);
WHILE @k <= @max_k
BEGIN
    INSERT INTO #v (stg_row_id, code)
    SELECT c.stg_row_id, r.code
    FROM #c c
    OUTER APPLY (SELECT COUNT(*) AS n_prior,
                        SUM(CASE WHEN s.adj_type = 'Reversal' THEN 1 ELSE 0 END) AS n_rev,
                        ISNULL(SUM(s.amt), 0) AS prior_amt
                 FROM #acc s WHERE s.tx = c.tx) s
    CROSS APPLY (VALUES
      (CASE WHEN (c.adj_type = 'Reversal' AND (c.amt <> c.original_amount OR s.n_prior > 0))  -- full, once, exclusive
              OR (c.adj_type = 'Refund'   AND s.n_rev > 0)                                    -- no refund after reversal
            THEN 'INVALID_ADJUSTMENT_RULE' END),
      (CASE WHEN c.amt + s.prior_amt > c.original_amount THEN 'ADJUSTMENT_EXCEEDS_ORIGINAL' END)
    ) r(code)
    WHERE c.seq = @k AND r.code IS NOT NULL;

    INSERT INTO #acc (tx, adj_type, amt)
    SELECT c.tx, c.adj_type, c.amt FROM #c c
    WHERE c.seq = @k AND NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = c.stg_row_id);

    SET @k += 1;
END;

IF EXISTS (SELECT 1 FROM #v v WHERE NOT EXISTS (SELECT 1 FROM #precedence x WHERE x.code = v.code))
    THROW 50001, 'Validation produced a reject code that is not in the precedence list.', 1;

/* 7. One reject_log row per rejected source row. */
INSERT INTO audit.reject_log
    (run_id, batch_id, source_type, source_row_ref, primary_reject_code, reject_details, raw_record)
SELECT @run_id, @batch_id, 'ADJUSTMENT', a.source_row_ref, pr.code, det.details, rj.j
FROM #a a
CROSS APPLY (SELECT TOP (1) v.code FROM #v v JOIN #precedence x ON x.code = v.code
             WHERE v.stg_row_id = a.stg_row_id ORDER BY x.ord) pr
OUTER APPLY (SELECT STRING_AGG(v.code, ', ') WITHIN GROUP (ORDER BY x.ord) AS details
             FROM #v v JOIN #precedence x ON x.code = v.code
             WHERE v.stg_row_id = a.stg_row_id AND v.code <> pr.code) det
CROSS APPLY (SELECT (SELECT a.adjustment_id_raw AS adjustment_id, a.transaction_id_raw AS transaction_id,
                            a.adjustment_type_raw AS adjustment_type, a.adjustment_amount_raw AS adjustment_amount,
                            a.adjustment_timestamp_raw AS adjustment_timestamp_utc
                     FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) AS j) rj;
DECLARE @rejected INT = @@ROWCOUNT;

/* 8. Accepted adjustments; method + attempt date copied from the validated parent. */
INSERT INTO curated.fact_adjustment
    (adjustment_id, transaction_id, adjustment_type, adjustment_amount_usd, adjustment_timestamp_utc,
     adjustment_date_key, attempt_date_key, payment_method_key, loaded_run_id)
SELECT a.aid, par.transaction_id, a.adj_type, a.amt, a.ts,
       a.adjustment_date_key, par.attempt_date_key, par.payment_method_key, @run_id
FROM #a a
JOIN curated.fact_payment_attempt par ON par.transaction_id = a.tx
WHERE NOT EXISTS (SELECT 1 FROM #v v WHERE v.stg_row_id = a.stg_row_id);
DECLARE @inserted INT = @@ROWCOUNT;

SELECT (SELECT COUNT(*) FROM #a) AS staged, @inserted AS inserted, 0 AS updated, @rejected AS rejected;
