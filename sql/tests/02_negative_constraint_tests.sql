/* Negative constraint tests: every statement below MUST fail.
   Everything runs inside one transaction that is always rolled back,
   so the real database is unchanged (row counts printed before/after). */
USE FinancialIntelligence;
SET NOCOUNT ON;
SET XACT_ABORT OFF;   -- constraint errors end the statement only, so the outer tran survives to ROLLBACK

DECLARE @before TABLE (tbl sysname, n int);
INSERT @before SELECT 'fact_payment_attempt', COUNT(*) FROM curated.fact_payment_attempt
UNION ALL SELECT 'fact_adjustment', COUNT(*) FROM curated.fact_adjustment
UNION ALL SELECT 'etl_run', COUNT(*) FROM audit.etl_run
UNION ALL SELECT 'reject_log', COUNT(*) FROM audit.reject_log;

DECLARE @results TABLE (test_no int, test_name varchar(80), expected_object varchar(60),
                        outcome varchar(10), error_number int, error_message nvarchar(400));
DECLARE @tx varchar(100), @rev_tx varchar(100), @ok_date int = 20260701;
SELECT TOP 1 @tx = transaction_id FROM curated.fact_payment_attempt WHERE status='Success' ORDER BY transaction_id;
SELECT TOP 1 @rev_tx = transaction_id FROM curated.fact_adjustment WHERE adjustment_type='Reversal' ORDER BY transaction_id;

BEGIN TRAN;

-- helper pattern: each test in TRY/CATCH; reaching the line after the insert = FAIL (constraint missing)
BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T01','2026-07-01',@ok_date,-5.00,'USD','M1',1,'Success',NULL,'2026-07-01',1,1);
  INSERT @results VALUES (1,'Negative amount','CK_fpa_amount','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (1,'Negative amount','CK_fpa_amount','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T02','2026-07-01',@ok_date,5.00,'USD','M1',1,'Success',1,'2026-07-01',1,1);
  INSERT @results VALUES (2,'Failure reason on non-Failed row','CK_fpa_failure','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (2,'Failure reason on non-Failed row','CK_fpa_failure','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T03','2026-07-01',@ok_date,5.00,'USD','M1',1,'Failed',NULL,'2026-07-01',1,1);
  INSERT @results VALUES (3,'Failed without reason','CK_fpa_failure','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (3,'Failed without reason','CK_fpa_failure','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T04','2026-07-01',@ok_date,5.00,'USD','M1',999,'Success',NULL,'2026-07-01',1,1);
  INSERT @results VALUES (4,'Unknown payment method key','FK_fpa_method','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (4,'Unknown payment method key','FK_fpa_method','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T05','2099-01-01',20990101,5.00,'USD','M1',1,'Success',NULL,'2099-01-01',1,1);
  INSERT @results VALUES (5,'Unknown date key (2099)','FK_fpa_date','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (5,'Unknown date key (2099)','FK_fpa_date','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T06','2026-07-01',@ok_date,5.00,'USD','M1',1,'Failed',999,'2026-07-01',1,1);
  INSERT @results VALUES (6,'Unknown failure reason key','FK_fpa_reason','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (6,'Unknown failure reason key','FK_fpa_reason','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T07','2026-07-01',@ok_date,5.00,'EUR','M1',1,'Success',NULL,'2026-07-01',1,1);
  INSERT @results VALUES (7,'Non-USD currency','CK_fpa_currency','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (7,'Non-USD currency','CK_fpa_currency','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T08','2026-07-01',@ok_date,5.00,'USD','M1',1,'Settled',NULL,'2026-07-01',1,1);
  INSERT @results VALUES (8,'Unknown status','CK_fpa_status','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (8,'Unknown status','CK_fpa_status','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_payment_attempt VALUES ('NEG_T09','2026-07-01',@ok_date,5.00,'USD','M1',1,'Success',NULL,'2026-07-01',9999,1);
  INSERT @results VALUES (9,'Unknown inserted_run_id','FK_fpa_ins_run','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (9,'Unknown inserted_run_id','FK_fpa_ins_run','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_adjustment VALUES ('NEG_A10',@rev_tx,'Reversal',1.00,'2026-07-01',@ok_date,@ok_date,1,2);
  INSERT @results VALUES (10,'Second Reversal on same transaction','UX_fadj_one_reversal','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (10,'Second Reversal on same transaction','UX_fadj_one_reversal','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_adjustment VALUES ('NEG_A11','NO_SUCH_TXN','Refund',1.00,'2026-07-01',@ok_date,@ok_date,1,2);
  INSERT @results VALUES (11,'Orphan adjustment (unknown txn)','FK_fadj_txn','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (11,'Orphan adjustment (unknown txn)','FK_fadj_txn','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_adjustment VALUES ('NEG_A12',@tx,'Chargeback',1.00,'2026-07-01',@ok_date,@ok_date,1,2);
  INSERT @results VALUES (12,'Unknown adjustment type','CK_fadj_type','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (12,'Unknown adjustment type','CK_fadj_type','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_adjustment VALUES ('NEG_A13',@tx,'Refund',0.00,'2026-07-01',@ok_date,@ok_date,1,2);
  INSERT @results VALUES (13,'Zero adjustment amount','CK_fadj_amount','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (13,'Zero adjustment amount','CK_fadj_amount','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT curated.fact_adjustment VALUES ('NEG_A14',@tx,'Refund',1.00,'2026-07-01',@ok_date,@ok_date,999,2);
  INSERT @results VALUES (14,'Adjustment unknown payment method','FK_fadj_method','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (14,'Adjustment unknown payment method','FK_fadj_method','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT audit.etl_run (batch_id,source_type,run_status) SELECT batch_id,source_type,'COMPLETED' FROM audit.etl_run WHERE run_id=1;
  INSERT @results VALUES (15,'Second COMPLETED run for same batch','UX_etl_run_completed_batch','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (15,'Second COMPLETED run for same batch','UX_etl_run_completed_batch','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT audit.etl_run (batch_id,source_type,run_status) VALUES ('x','PAYMENT_ATTEMPT','DONE');
  INSERT @results VALUES (16,'Unknown run status','CK_etl_run_status','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (16,'Unknown run status','CK_etl_run_status','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

BEGIN TRY
  INSERT audit.reject_log (run_id,batch_id,source_type,source_row_ref,primary_reject_code) VALUES (1,'b','PAYMENT_ATTEMPT','neg:1','X');
  INSERT audit.reject_log (run_id,batch_id,source_type,source_row_ref,primary_reject_code) VALUES (1,'b','PAYMENT_ATTEMPT','neg:1','Y');
  INSERT @results VALUES (17,'Two reject_log rows for one source row','UQ_reject_one_per_row','FAIL',NULL,'insert succeeded');
END TRY BEGIN CATCH INSERT @results VALUES (17,'Two reject_log rows for one source row','UQ_reject_one_per_row','PASS',ERROR_NUMBER(),ERROR_MESSAGE()); END CATCH;

SELECT @@TRANCOUNT AS trancount_before_rollback, XACT_STATE() AS xact_state;
ROLLBACK;

SELECT test_no, test_name, expected_object, outcome,
       CASE WHEN outcome='PASS' AND error_message LIKE '%'+expected_object+'%' THEN 'yes' ELSE 'NO' END AS named_constraint_fired,
       error_number, error_message
FROM @results ORDER BY test_no;

SELECT b.tbl, b.n AS rows_before,
       CASE b.tbl WHEN 'fact_payment_attempt' THEN (SELECT COUNT(*) FROM curated.fact_payment_attempt)
                  WHEN 'fact_adjustment' THEN (SELECT COUNT(*) FROM curated.fact_adjustment)
                  WHEN 'etl_run' THEN (SELECT COUNT(*) FROM audit.etl_run)
                  ELSE (SELECT COUNT(*) FROM audit.reject_log) END AS rows_after_rollback
FROM @before b;
