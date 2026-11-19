"""Phase 4C: validate staged runs and load curated facts (set-based SQL, one transaction per run).

Run from the repository root:
    ./.venv/Scripts/python.exe python/03_validate_and_load_curated.py --run-id 1 --run-id 2
    ./.venv/Scripts/python.exe python/03_validate_and_load_curated.py --run-id 1 --run-id 2 --database FinancialIntelligence_Scratch

Python only orchestrates. All validation, reject coding and curated writes happen in
sql/etl/10_payment_validate_load.sql and sql/etl/11_adjustment_validate_load.sql.

Per run:
  * COMPLETED run re-invoked         -> new audit row ALREADY_PROCESSED, nothing else.
  * RUNNING run whose batch is COMPLETED in another run -> this run marked ALREADY_PROCESSED.
  * Otherwise ONE transaction (XACT_ABORT ON, sp_getapplock): preflight, validate, reject_log,
    curated inserts/updates, reconciliation, etl_run COMPLETED as the last statement, commit.
  * Any failure -> rollback; separate small transaction marks the run FAILED. Staging is never
    touched, so the same run_id can be retried.
Runs are processed in the order given; processing stops at the first run that does not finish.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / 'sql' / 'etl'

# Locked Phase 2 Step 4 precedence (docs/reject_codes.md). The ONLY copy of the order in code:
# six stages, listed-code order as tie-breaker inside a stage. SQL reads it from #precedence.
PRECEDENCE = [
    # 1 required fields / parse / type / amount / timestamp
    'MISSING_REQUIRED_FIELD', 'INVALID_FORMAT', 'NONPOSITIVE_AMOUNT', 'FUTURE_ATTEMPT_TIMESTAMP',
    # 2 controlled values / status-reason consistency
    'INVALID_CONTROLLED_VALUE', 'FAILURE_REASON_STATUS_MISMATCH',
    # 3 intra-batch duplicate identity
    'DUPLICATE_IN_BATCH',
    # 4 existing-record immutable / lifecycle conflicts
    'DUPLICATE_RECORD', 'IMMUTABLE_FIELD_CONFLICT', 'INVALID_STATUS_TRANSITION',
    'DUPLICATE_ADJUSTMENT', 'ADJUSTMENT_FIELD_CONFLICT',
    # 5 parent relationship and adjustment timing
    'ORPHAN_ADJUSTMENT', 'ADJUSTMENT_ON_NON_SUCCESS', 'INVALID_ADJUSTMENT_TIMING',
    # 6 aggregate / sibling adjustment rules
    'INVALID_ADJUSTMENT_RULE', 'ADJUSTMENT_EXCEEDS_ORIGINAL',
]

SOURCES = {
    'PAYMENT_ATTEMPT': ('staging.payment_attempt_raw', '10_payment_validate_load.sql'),
    'ADJUSTMENT': ('staging.adjustment_raw', '11_adjustment_validate_load.sql'),
}
METHODS = {'Card', 'ACH', 'Wallet'}
FAILURES = {'AUTH_TIMEOUT', 'INSUFFICIENT_FUNDS', 'FRAUD_DECLINE', 'INVALID_PAYMENT_DETAILS',
            'PROCESSOR_ERROR', 'LIMIT_EXCEEDED', 'OTHER'}


class LockBusy(Exception):
    """Another session holds this run's application lock; not a failure of the run."""


def connect(server: str, database: str) -> pyodbc.Connection:
    return pyodbc.connect(
        'DRIVER={ODBC Driver 18 for SQL Server};'
        f'SERVER={server};DATABASE={database};'
        'Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;',
        timeout=15, autocommit=False)


def fetch_run(cur, run_id: int, lock: bool = False) -> dict | None:
    hint = 'WITH (UPDLOCK, HOLDLOCK)' if lock else ''
    cur.execute(f'''SELECT run_id, batch_id, source_type, run_status, rows_read, batch_extraction_cutoff_utc
                    FROM audit.etl_run {hint} WHERE run_id = ?''', run_id)
    r = cur.fetchone()
    if not r:
        return None
    return dict(zip(['run_id', 'batch_id', 'source_type', 'run_status', 'rows_read', 'cutoff'], r))


def completed_sibling(cur, run: dict) -> int | None:
    cur.execute('''SELECT run_id FROM audit.etl_run WHERE source_type = ? AND batch_id = ?
                   AND run_status = 'COMPLETED' AND run_id <> ?''',
                run['source_type'], run['batch_id'], run['run_id'])
    r = cur.fetchone()
    return r[0] if r else None


def log_already_processed(conn, run: dict, completed_run_id: int) -> None:
    """Replay of a COMPLETED batch: audit only, zero curated/staging/reject changes."""
    cur = conn.cursor()
    msg = f'Batch already COMPLETED by run_id={completed_run_id}; no changes'
    if run['run_status'] == 'COMPLETED':
        # The completed run itself was re-invoked: record a new execution row.
        cur.execute('''INSERT INTO audit.etl_run
                (batch_id, source_type, batch_extraction_cutoff_utc, run_status, run_completed_utc,
                 rows_read, rows_loaded, rows_rejected, message)
            VALUES (?, ?, ?, 'ALREADY_PROCESSED', SYSUTCDATETIME(), 0, 0, 0, ?)''',
                    run['batch_id'], run['source_type'], run['cutoff'], msg)
    else:
        # A different (RUNNING/FAILED) execution of an already-completed batch.
        cur.execute('''UPDATE audit.etl_run SET run_status = 'ALREADY_PROCESSED',
                run_completed_utc = SYSUTCDATETIME(), rows_loaded = 0, rows_rejected = 0, message = ?
            WHERE run_id = ? AND run_status IN ('RUNNING', 'FAILED')''', msg, run['run_id'])
    conn.commit()
    print(f"run_id={run['run_id']} {run['source_type']}: ALREADY_PROCESSED ({msg})")


def preflight(cur, run: dict, table: str) -> None:
    if run['run_status'] not in ('RUNNING', 'FAILED'):
        raise RuntimeError(f"run_id={run['run_id']} has status {run['run_status']}; expected RUNNING or FAILED")
    if run['cutoff'] is None or run['rows_read'] is None:
        raise RuntimeError(f"run_id={run['run_id']}: missing batch_extraction_cutoff_utc or rows_read")
    cur.execute(f'SELECT COUNT(*) FROM {table} WHERE run_id = ?', run['run_id'])
    staged = cur.fetchone()[0]
    if staged != run['rows_read']:
        raise RuntimeError(f"run_id={run['run_id']}: staged rows {staged} != rows_read {run['rows_read']}")
    cur.execute('SELECT COUNT(*) FROM audit.reject_log WHERE run_id = ?', run['run_id'])
    if cur.fetchone()[0]:
        raise RuntimeError(f"run_id={run['run_id']}: reject_log already has rows for this run")
    cur.execute('SELECT payment_method_name FROM curated.dim_payment_method')
    methods = {r[0] for r in cur.fetchall()}
    cur.execute('SELECT failure_reason_code FROM curated.dim_failure_reason')
    reasons = {r[0] for r in cur.fetchall()}
    if methods != METHODS or reasons != FAILURES:
        raise RuntimeError('Dimension seed values do not match the approved controlled lists')
    if run['source_type'] == 'ADJUSTMENT':
        # Attempts before adjustments: no unfinished payment run at or before this cutoff.
        cur.execute('''SELECT COUNT(*) FROM audit.etl_run WHERE source_type = 'PAYMENT_ATTEMPT'
                       AND run_status IN ('RUNNING', 'FAILED') AND batch_extraction_cutoff_utc <= ?''',
                    run['cutoff'])
        if cur.fetchone()[0]:
            raise RuntimeError('A payment run at or before this cutoff is not COMPLETED; process it first')


def mark_failed(conn, run_id: int, error: str) -> None:
    cur = conn.cursor()
    cur.execute('''UPDATE audit.etl_run SET run_status = 'FAILED', run_completed_utc = SYSUTCDATETIME(),
                       message = LEFT(?, 1000)
                   WHERE run_id = ? AND run_status IN ('RUNNING', 'FAILED')''', error, run_id)
    conn.commit()


def process_run(conn, run_id: int, fail_after_load: bool = False) -> str:
    cur = conn.cursor()
    run = fetch_run(cur, run_id)
    conn.rollback()
    if run is None:
        print(f'run_id={run_id}: not found')
        return 'NOT_FOUND'
    if run['source_type'] not in SOURCES:
        print(f'run_id={run_id}: unsupported source_type {run["source_type"]}')
        return 'ERROR'
    if run['run_status'] == 'COMPLETED':
        log_already_processed(conn, run, run_id)
        return 'ALREADY_PROCESSED'
    sibling = completed_sibling(cur, run)
    conn.rollback()
    if sibling is not None:
        log_already_processed(conn, run, sibling)
        return 'ALREADY_PROCESSED'

    table, sql_file = SOURCES[run['source_type']]
    sql_text = (SQL_DIR / sql_file).read_text(encoding='utf-8')
    try:
        cur.execute('SET XACT_ABORT ON;')
        cur.execute('''DECLARE @rc INT;
            EXEC @rc = sp_getapplock @Resource = ?, @LockMode = 'Exclusive',
                 @LockOwner = 'Transaction', @LockTimeout = 0;
            SELECT @rc;''', f'FI_curated_run_{run_id}')
        if cur.fetchone()[0] < 0:
            raise LockBusy(f'run_id={run_id} is being processed by another session')
        run = fetch_run(cur, run_id, lock=True)        # re-read under lock
        preflight(cur, run, table)

        cur.execute('DROP TABLE IF EXISTS #precedence; CREATE TABLE #precedence (code VARCHAR(50) PRIMARY KEY, ord INT NOT NULL UNIQUE);')
        cur.executemany('INSERT INTO #precedence (code, ord) VALUES (?, ?)',
                        [(code, i) for i, code in enumerate(PRECEDENCE, start=1)])

        cur.execute(sql_text, run_id)
        row = cur.fetchone()
        while cur.nextset():                           # surface any trailing error
            pass
        staged, inserted, updated, rejected = row
        if not (staged == run['rows_read'] == inserted + updated + rejected):
            raise RuntimeError(f'Reconciliation failed: rows_read={run["rows_read"]}, staged={staged}, '
                               f'inserted={inserted}, updated={updated}, rejected={rejected}')
        if fail_after_load:                            # test hook: prove a late failure rolls everything back
            raise RuntimeError('Injected failure after load (test hook --fail-after-load)')

        cur.execute('''UPDATE audit.etl_run SET run_status = 'COMPLETED', run_completed_utc = SYSUTCDATETIME(),
                           rows_loaded = ?, rows_rejected = ?, message = ?
                       WHERE run_id = ? AND run_status IN ('RUNNING', 'FAILED')''',
                    inserted + updated, rejected,
                    f'Curated load reconciled: inserted={inserted}, updated={updated}, rejected={rejected}',
                    run_id)
        if cur.rowcount != 1:
            raise RuntimeError('COMPLETED update did not affect exactly one row')
        conn.commit()
        print(f"run_id={run_id} {run['source_type']}: COMPLETED rows_read={staged} "
              f"inserted={inserted} updated={updated} rejected={rejected}")
        return 'COMPLETED'
    except LockBusy as exc:
        conn.rollback()
        print(f'{exc}; skipped (run not marked FAILED)')
        return 'LOCKED'
    except Exception as exc:  # noqa: BLE001 - any failure must roll back and be audited
        conn.rollback()
        mark_failed(conn, run_id, f'{type(exc).__name__}: {exc}')
        print(f'run_id={run_id}: FAILED and rolled back: {exc}')
        return 'FAILED'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-id', type=int, action='append', required=True,
                    help='Run to process; repeat in order (payment run first, then adjustment run).')
    ap.add_argument('--server', default=os.getenv('FI_SQL_SERVER', r'localhost\SQLEXPRESS01'))
    ap.add_argument('--database', default=os.getenv('FI_SQL_DATABASE', 'FinancialIntelligence'))
    ap.add_argument('--fail-after-load', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()

    print(f'Target: {args.server} / {args.database}')
    ok = {'COMPLETED', 'ALREADY_PROCESSED'}
    with connect(args.server, args.database) as conn:
        for run_id in args.run_id:
            result = process_run(conn, run_id, args.fail_after_load)
            if result not in ok:
                print('Stopping: later runs not processed.')
                return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
