/* Restore the pre-Phase-4C backup as a SCRATCH database and reset it to the
   "staging loaded, runs RUNNING" state, so the new loader can replay runs 1 and 2.
   Usage (sqlcmd -I):  sqlcmd -S localhost\SQLEXPRESS01 -E -C -I -b -v SCRATCH=FinancialIntelligence_Scratch -i this_file
   Safety: refuses to run against the real database name. Staging rows are not touched. */
:on error exit
IF '$(SCRATCH)' = 'FinancialIntelligence' THROW 50000, 'Refusing to reset the real database.', 1;
GO
USE master;
IF DB_ID('$(SCRATCH)') IS NOT NULL
BEGIN
    ALTER DATABASE [$(SCRATCH)] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE [$(SCRATCH)];
END;
RESTORE DATABASE [$(SCRATCH)]
FROM DISK = N'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\Backup\FinancialIntelligence_pre_phase4C_20261118.bak'
WITH MOVE 'FinancialIntelligence'     TO N'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\DATA\$(SCRATCH).mdf',
     MOVE 'FinancialIntelligence_log' TO N'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\DATA\$(SCRATCH)_log.ldf',
     CHECKSUM, RECOVERY;
GO
USE [$(SCRATCH)];
SET NOCOUNT ON;
BEGIN TRAN;
    DELETE FROM curated.fact_adjustment;
    DELETE FROM curated.fact_payment_attempt;
    DELETE FROM audit.reject_log;
    UPDATE audit.etl_run
       SET run_status = 'RUNNING', run_completed_utc = NULL, rows_loaded = NULL, rows_rejected = NULL, message = NULL
     WHERE run_id IN (1, 2);
COMMIT;
SELECT DB_NAME() AS db, run_id, source_type, run_status, rows_read, rows_loaded, rows_rejected FROM audit.etl_run ORDER BY run_id;
SELECT (SELECT COUNT(*) FROM staging.payment_attempt_raw) AS stg_pay, (SELECT COUNT(*) FROM staging.adjustment_raw) AS stg_adj,
       (SELECT COUNT(*) FROM curated.fact_payment_attempt) AS fpa, (SELECT COUNT(*) FROM curated.fact_adjustment) AS fadj,
       (SELECT COUNT(*) FROM audit.reject_log) AS rejects;
