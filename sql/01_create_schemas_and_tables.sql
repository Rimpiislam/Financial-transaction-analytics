USE FinancialIntelligence;
GO
-- Schemas ------------------------------------------------------------
IF SCHEMA_ID('staging') IS NULL EXEC('CREATE SCHEMA staging');
IF SCHEMA_ID('curated') IS NULL EXEC('CREATE SCHEMA curated');
IF SCHEMA_ID('audit')   IS NULL EXEC('CREATE SCHEMA audit');
GO

-- 1. audit.etl_run (one row per execution) ---------------------------
IF OBJECT_ID('audit.etl_run') IS NULL
CREATE TABLE audit.etl_run (
    run_id                      BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_etl_run PRIMARY KEY,
    batch_id                    VARCHAR(100)  NOT NULL,
    source_type                 VARCHAR(30)   NOT NULL,
    batch_extraction_cutoff_utc DATETIME2(3)  NULL,
    run_started_utc             DATETIME2(3)  NOT NULL CONSTRAINT DF_etl_run_start DEFAULT (SYSUTCDATETIME()),
    run_completed_utc           DATETIME2(3)  NULL,
    run_status                  VARCHAR(20)   NOT NULL,
    rows_read                   INT           NULL,
    rows_loaded                 INT           NULL,
    rows_rejected               INT           NULL,
    message                     NVARCHAR(1000) NULL,
    CONSTRAINT CK_etl_run_source CHECK (source_type IN ('PAYMENT_ATTEMPT','ADJUSTMENT')),
    CONSTRAINT CK_etl_run_status CHECK (run_status IN ('RUNNING','COMPLETED','FAILED','ALREADY_PROCESSED'))
);
GO
-- Only COMPLETED batches are replay-skipped: at most one COMPLETED run per batch/source.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_etl_run_completed_batch')
CREATE UNIQUE INDEX UX_etl_run_completed_batch
    ON audit.etl_run (source_type, batch_id) WHERE run_status = 'COMPLETED';
GO

-- 2. curated.dim_date -------------------------------------------------
IF OBJECT_ID('curated.dim_date') IS NULL
CREATE TABLE curated.dim_date (
    date_key     INT          NOT NULL CONSTRAINT PK_dim_date PRIMARY KEY,  -- yyyymmdd (ET date)
    full_date    DATE         NOT NULL CONSTRAINT UQ_dim_date_full UNIQUE,
    year_num     SMALLINT     NOT NULL,
    quarter_num  TINYINT      NOT NULL,
    month_num    TINYINT      NOT NULL,
    month_name   VARCHAR(10)  NOT NULL,
    day_of_month TINYINT      NOT NULL,
    day_of_week  TINYINT      NOT NULL,   -- 1=Mon..7=Sun
    day_name     VARCHAR(10)  NOT NULL,
    is_weekend   BIT          NOT NULL
);
GO

-- 3. curated.dim_payment_method ---------------------------------------
IF OBJECT_ID('curated.dim_payment_method') IS NULL
CREATE TABLE curated.dim_payment_method (
    payment_method_key  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_dim_payment_method PRIMARY KEY,
    payment_method_name VARCHAR(20) NOT NULL CONSTRAINT UQ_dim_payment_method_name UNIQUE
);
GO
IF NOT EXISTS (SELECT 1 FROM curated.dim_payment_method)
INSERT INTO curated.dim_payment_method (payment_method_name) VALUES ('Card'),('ACH'),('Wallet');
GO

-- 4. curated.dim_failure_reason ----------------------------------------
IF OBJECT_ID('curated.dim_failure_reason') IS NULL
CREATE TABLE curated.dim_failure_reason (
    failure_reason_key  INT IDENTITY(1,1) NOT NULL CONSTRAINT PK_dim_failure_reason PRIMARY KEY,
    failure_reason_code VARCHAR(100) NOT NULL CONSTRAINT UQ_dim_failure_reason_code UNIQUE
);
GO

-- Seed approved controlled failure reason codes (idempotent).
INSERT INTO curated.dim_failure_reason (failure_reason_code)
SELECT v.failure_reason_code
FROM (VALUES ('AUTH_TIMEOUT'), ('INSUFFICIENT_FUNDS'), ('FRAUD_DECLINE'),
             ('INVALID_PAYMENT_DETAILS'), ('PROCESSOR_ERROR'),
             ('LIMIT_EXCEEDED'), ('OTHER')) v(failure_reason_code)
WHERE NOT EXISTS (
    SELECT 1 FROM curated.dim_failure_reason d
    WHERE d.failure_reason_code = v.failure_reason_code
);
GO

-- 5. staging.payment_attempt_raw (all VARCHAR; nothing silently dropped) --
IF OBJECT_ID('staging.payment_attempt_raw') IS NULL
CREATE TABLE staging.payment_attempt_raw (
    stg_row_id            BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_stg_payment_attempt PRIMARY KEY,
    run_id                BIGINT       NOT NULL,           -- execution that staged this row
    batch_id              VARCHAR(100) NOT NULL,
    source_row_ref        VARCHAR(100) NOT NULL,           -- e.g. file name + row number
    loaded_at_utc         DATETIME2(3) NOT NULL CONSTRAINT DF_stg_pa_loaded DEFAULT (SYSUTCDATETIME()),
    transaction_id_raw    VARCHAR(100) NULL,
    attempt_timestamp_raw VARCHAR(80)  NULL,
    amount_raw            VARCHAR(80)  NULL,
    currency_raw          VARCHAR(50)  NULL,
    merchant_id_raw       VARCHAR(100) NULL,
    payment_method_raw    VARCHAR(50)  NULL,
    status_raw            VARCHAR(50)  NULL,
    failure_reason_raw    VARCHAR(100) NULL,
    status_updated_at_raw VARCHAR(80)  NULL,
    CONSTRAINT FK_stg_pa_run FOREIGN KEY (run_id) REFERENCES audit.etl_run (run_id),
    CONSTRAINT UQ_stg_pa_run_row UNIQUE (run_id, source_row_ref)
);
GO

-- 6. staging.adjustment_raw (frozen 5-column contract) -----------------
IF OBJECT_ID('staging.adjustment_raw') IS NULL
CREATE TABLE staging.adjustment_raw (
    stg_row_id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_stg_adjustment PRIMARY KEY,
    run_id                  BIGINT       NOT NULL,
    batch_id                VARCHAR(100) NOT NULL,
    source_row_ref          VARCHAR(100) NOT NULL,
    loaded_at_utc           DATETIME2(3) NOT NULL CONSTRAINT DF_stg_adj_loaded DEFAULT (SYSUTCDATETIME()),
    adjustment_id_raw       VARCHAR(100) NULL,
    transaction_id_raw      VARCHAR(100) NULL,
    adjustment_type_raw     VARCHAR(50)  NULL,
    adjustment_amount_raw   VARCHAR(80)  NULL,
    adjustment_timestamp_raw VARCHAR(80) NULL,
    CONSTRAINT FK_stg_adj_run FOREIGN KEY (run_id) REFERENCES audit.etl_run (run_id),
    CONSTRAINT UQ_stg_adj_run_row UNIQUE (run_id, source_row_ref)
);
GO

-- 7. curated.fact_payment_attempt --------------------------------------
IF OBJECT_ID('curated.fact_payment_attempt') IS NULL
CREATE TABLE curated.fact_payment_attempt (
    transaction_id          VARCHAR(100)  NOT NULL CONSTRAINT PK_fact_payment_attempt PRIMARY KEY,
    attempt_timestamp_utc   DATETIME2(3)  NOT NULL,
    attempt_date_key        INT           NOT NULL,   -- ET date
    amount_usd              DECIMAL(18,2) NOT NULL,
    currency                VARCHAR(3)    NOT NULL,
    merchant_id             VARCHAR(100)  NOT NULL,
    payment_method_key      INT           NOT NULL,
    status                  VARCHAR(20)   NOT NULL,
    failure_reason_key      INT           NULL,
    status_updated_at_utc   DATETIME2(3)  NOT NULL,
    inserted_run_id         BIGINT        NOT NULL,
    status_updated_run_id   BIGINT        NOT NULL,
    CONSTRAINT FK_fpa_date    FOREIGN KEY (attempt_date_key)   REFERENCES curated.dim_date (date_key),
    CONSTRAINT FK_fpa_method  FOREIGN KEY (payment_method_key) REFERENCES curated.dim_payment_method (payment_method_key),
    CONSTRAINT FK_fpa_reason  FOREIGN KEY (failure_reason_key) REFERENCES curated.dim_failure_reason (failure_reason_key),
    CONSTRAINT FK_fpa_ins_run FOREIGN KEY (inserted_run_id)       REFERENCES audit.etl_run (run_id),
    CONSTRAINT FK_fpa_upd_run FOREIGN KEY (status_updated_run_id) REFERENCES audit.etl_run (run_id),
    CONSTRAINT CK_fpa_amount   CHECK (amount_usd > 0),
    CONSTRAINT CK_fpa_currency CHECK (currency = 'USD'),
    CONSTRAINT CK_fpa_status   CHECK (status IN ('Pending','Success','Failed','Cancelled')),
    CONSTRAINT CK_fpa_failure  CHECK (
        (status = 'Failed' AND failure_reason_key IS NOT NULL)
     OR (status <> 'Failed' AND failure_reason_key IS NULL))
);
GO

-- 8. curated.fact_adjustment -------------------------------------------
IF OBJECT_ID('curated.fact_adjustment') IS NULL
CREATE TABLE curated.fact_adjustment (
    adjustment_id            VARCHAR(100)  NOT NULL CONSTRAINT PK_fact_adjustment PRIMARY KEY,
    transaction_id           VARCHAR(100)  NOT NULL,
    adjustment_type          VARCHAR(20)   NOT NULL,
    adjustment_amount_usd    DECIMAL(18,2) NOT NULL,
    adjustment_timestamp_utc DATETIME2(3)  NOT NULL,
    adjustment_date_key      INT           NOT NULL,  -- active PBI relationship
    attempt_date_key         INT           NOT NULL,  -- inactive PBI relationship (cohort)
    payment_method_key       INT           NOT NULL,  -- copied from original attempt
    loaded_run_id            BIGINT        NOT NULL,
    CONSTRAINT FK_fadj_txn     FOREIGN KEY (transaction_id)      REFERENCES curated.fact_payment_attempt (transaction_id),
    CONSTRAINT FK_fadj_adjdate FOREIGN KEY (adjustment_date_key) REFERENCES curated.dim_date (date_key),
    CONSTRAINT FK_fadj_attdate FOREIGN KEY (attempt_date_key)    REFERENCES curated.dim_date (date_key),
    CONSTRAINT FK_fadj_method  FOREIGN KEY (payment_method_key)  REFERENCES curated.dim_payment_method (payment_method_key),
    CONSTRAINT FK_fadj_run     FOREIGN KEY (loaded_run_id)       REFERENCES audit.etl_run (run_id),
    CONSTRAINT CK_fadj_type    CHECK (adjustment_type IN ('Refund','Reversal')),
    CONSTRAINT CK_fadj_amount  CHECK (adjustment_amount_usd > 0)
);
GO
-- Reversal allowed only once per original transaction.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_fadj_one_reversal')
CREATE UNIQUE INDEX UX_fadj_one_reversal
    ON curated.fact_adjustment (transaction_id) WHERE adjustment_type = 'Reversal';
GO
-- NOTE: "cumulative adjustments <= original amount" and "reversal = full amount"
-- need cross-row checks; enforce in the load procedure (ADJUSTMENT_EXCEEDS_ORIGINAL).

-- 9. audit.reject_log (one row per rejected source row) -----------------
IF OBJECT_ID('audit.reject_log') IS NULL
CREATE TABLE audit.reject_log (
    reject_id           BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_reject_log PRIMARY KEY,
    run_id              BIGINT         NOT NULL,
    batch_id            VARCHAR(100)   NOT NULL,
    source_type         VARCHAR(30)    NOT NULL,
    source_row_ref      VARCHAR(100)   NOT NULL,
    primary_reject_code VARCHAR(50)    NOT NULL,   -- chosen per locked Step 4 precedence
    reject_details      NVARCHAR(MAX)  NULL,       -- additional violations
    raw_record          NVARCHAR(MAX)  NULL,       -- original raw strings
    rejected_at_utc     DATETIME2(3)   NOT NULL CONSTRAINT DF_reject_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT FK_reject_run FOREIGN KEY (run_id) REFERENCES audit.etl_run (run_id),
    CONSTRAINT CK_reject_source CHECK (source_type IN ('PAYMENT_ATTEMPT','ADJUSTMENT')),
    CONSTRAINT UQ_reject_one_per_row UNIQUE (run_id, source_type, source_row_ref)
);
GO

-- Staging replay contract: every staged row carries the run_id that loaded it.
-- ETL reads WHERE run_id = @run_id only; raw rows from earlier runs are kept
-- for diagnostics and never re-processed. COMPLETED batches skip before staging.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('staging.payment_attempt_raw') AND name = 'IX_stg_pa_batch')
    CREATE INDEX IX_stg_pa_batch ON staging.payment_attempt_raw (batch_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('staging.adjustment_raw') AND name = 'IX_stg_adj_batch')
    CREATE INDEX IX_stg_adj_batch ON staging.adjustment_raw (batch_id);
GO

-- dim_date population (ET calendar dates) --------------------------------
-- Weekday number and all names are independent of DATEFIRST and SET LANGUAGE.
IF NOT EXISTS (SELECT 1 FROM curated.dim_date)
BEGIN
    ;WITH d AS (
        SELECT CAST('2024-01-01' AS DATE) AS dt
        UNION ALL SELECT DATEADD(DAY,1,dt) FROM d WHERE dt < '2030-12-31'
    ), w AS (
        SELECT dt, (DATEDIFF(DAY, CONVERT(DATE,'19000101',112), dt) % 7) + 1 AS dow FROM d  -- 1900-01-01 = Monday
    )
    INSERT INTO curated.dim_date
        (date_key, full_date, year_num, quarter_num, month_num, month_name,
         day_of_month, day_of_week, day_name, is_weekend)
    SELECT CONVERT(INT, CONVERT(CHAR(8), dt, 112)), dt, YEAR(dt), DATEPART(QUARTER,dt), MONTH(dt),
           CHOOSE(MONTH(dt),'January','February','March','April','May','June',
                  'July','August','September','October','November','December'),
           DAY(dt), dow,
           CHOOSE(dow,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'),
           CASE WHEN dow >= 6 THEN 1 ELSE 0 END
    FROM w OPTION (MAXRECURSION 0);
END
GO
