# Backup and recovery

## Pre-Phase-4C-rework backup (2026-11-18)
- **File:** `C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\Backup\FinancialIntelligence_pre_phase4C_20261118.bak`
- **Command:** `BACKUP DATABASE FinancialIntelligence TO DISK = N'<file>' WITH INIT, CHECKSUM`
- **Verified:** `RESTORE VERIFYONLY ... WITH CHECKSUM` → "The backup set on file 1 is valid."
  Evidence: [test_evidence/01_backup_output.txt](test_evidence/01_backup_output.txt)
- **State captured:** runs 1 (PAYMENT_ATTEMPT, 1,000 loaded / 0 rejected) and 2 (ADJUSTMENT,
  102 loaded / 0 rejected) both COMPLETED on 2026-11-15 by the original `03_validate_and_load_curated.py`.
  Curated: 1,000 attempts, 102 adjustments; reject_log empty.

## Restore (run in SSMS or sqlcmd; replaces the database)
```sql
RESTORE DATABASE FinancialIntelligence
FROM DISK = N'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\Backup\FinancialIntelligence_pre_phase4C_20261118.bak'
WITH REPLACE, CHECKSUM;
```

## Restore as a scratch copy (used for replay/fixture tests; real DB untouched)
```sql
RESTORE DATABASE FinancialIntelligence_Scratch
FROM DISK = N'...\FinancialIntelligence_pre_phase4C_20261118.bak'
WITH MOVE 'FinancialIntelligence'     TO N'...\DATA\FinancialIntelligence_Scratch.mdf',
     MOVE 'FinancialIntelligence_log' TO N'...\DATA\FinancialIntelligence_Scratch_log.ldf',
     REPLACE, CHECKSUM;
```

## Note on sqlcmd
Run scripts with `sqlcmd -I` (QUOTED_IDENTIFIER ON). Without it, any insert into a table with
a filtered unique index (`audit.etl_run`, `curated.fact_adjustment`) fails with Msg 1934.
pyodbc sessions have QUOTED_IDENTIFIER ON by default.
