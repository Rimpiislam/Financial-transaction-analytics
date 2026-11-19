"""Stage synthetic CSVs in SQL Server, preserving a snapshot per ETL run.

Run from the repository root:
    ./.venv/Scripts/python.exe python/02_load_staging.py

This script deliberately leaves audit.etl_run RUNNING. A subsequent curated-load
step must atomically mark the run COMPLETED with its final reconciliation counts.
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / 'data' / 'raw'
SERVER = os.environ.get('FI_SQL_SERVER', r'localhost\SQLEXPRESS01')
DATABASE = os.environ.get('FI_SQL_DATABASE', 'FinancialIntelligence')
CUTOFF_UTC = '2026-11-13T00:00:00'  # fixed batch extraction cutoff; SQL DATETIME2 UTC

SOURCES = {
    'PAYMENT_ATTEMPT': (
        'payment_attempts.csv', 'staging.payment_attempt_raw',
        ['transaction_id', 'attempt_timestamp_utc', 'amount', 'currency',
         'merchant_id', 'payment_method', 'status', 'failure_reason',
         'status_updated_at_utc'],
        ['transaction_id_raw', 'attempt_timestamp_raw', 'amount_raw',
         'currency_raw', 'merchant_id_raw', 'payment_method_raw',
         'status_raw', 'failure_reason_raw', 'status_updated_at_raw'],
    ),
    'ADJUSTMENT': (
        'adjustments.csv', 'staging.adjustment_raw',
        ['adjustment_id', 'transaction_id', 'adjustment_type',
         'adjustment_amount', 'adjustment_timestamp_utc'],
        ['adjustment_id_raw', 'transaction_id_raw', 'adjustment_type_raw',
         'adjustment_amount_raw', 'adjustment_timestamp_raw'],
    ),
}


def connect() -> pyodbc.Connection:
    return pyodbc.connect(
        'DRIVER={ODBC Driver 18 for SQL Server};'
        f'SERVER={SERVER};DATABASE={DATABASE};'
        'Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;',
        timeout=15,
        autocommit=False,
    )


def stage_one(conn: pyodbc.Connection, source_type: str) -> None:
    filename, table, source_cols, target_cols = SOURCES[source_type]
    path = RAW_DIR / filename
    file_bytes = path.read_bytes()
    # Stable batch ID for unchanged file content. A changed CSV becomes a new batch.
    batch_id = f'{source_type.lower()}_{hashlib.sha256(file_bytes).hexdigest()[:20]}'
    with path.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != source_cols:
            raise ValueError(f'{filename}: unexpected CSV headers: {reader.fieldnames}')
        rows = list(reader)

    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM audit.etl_run
           WHERE source_type = ? AND batch_id = ? AND run_status = 'COMPLETED'""",
        source_type, batch_id,
    )
    if cur.fetchone()[0]:
        # A replay is logged but does not stage data.
        cur.execute(
            """INSERT INTO audit.etl_run
               (batch_id, source_type, batch_extraction_cutoff_utc, run_status,
                run_completed_utc, rows_read, rows_loaded, rows_rejected, message)
               VALUES (?, ?, ?, 'ALREADY_PROCESSED', SYSUTCDATETIME(), 0, 0, 0,
                       'Previously completed batch; staging skipped')""",
            batch_id, source_type, CUTOFF_UTC,
        )
        conn.commit()
        print(f'{filename}: already COMPLETED; skipped')
        return

    # Register RUNNING separately, so a failed stage can be diagnosed.
    cur.execute(
        """INSERT INTO audit.etl_run
           (batch_id, source_type, batch_extraction_cutoff_utc, run_status, rows_read)
           OUTPUT INSERTED.run_id VALUES (?, ?, ?, 'RUNNING', ?)""",
        batch_id, source_type, CUTOFF_UTC, len(rows),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()

    try:
        placeholders = ', '.join('?' for _ in range(3 + len(target_cols)))
        columns = ', '.join(['run_id', 'batch_id', 'source_row_ref'] + target_cols)
        statement = f'INSERT INTO {table} ({columns}) VALUES ({placeholders})'
        payload = []
        for row_num, row in enumerate(rows, start=2):  # CSV header occupies line 1
            values = [row.get(column) for column in source_cols]
            payload.append((run_id, batch_id, f'{filename}:{row_num}', *values))
        cur.executemany(statement, payload)
        conn.commit()
        print(f'{filename}: staged {len(rows)} rows (run_id={run_id}, status=RUNNING)')
    except Exception as exc:
        conn.rollback()
        cur.execute(
            """UPDATE audit.etl_run SET run_status='FAILED',
               run_completed_utc=SYSUTCDATETIME(), message=? WHERE run_id=?""",
            str(exc)[:1000], run_id,
        )
        conn.commit()
        raise


def main() -> None:
    with connect() as conn:
        for source_type in SOURCES:
            stage_one(conn, source_type)
    print('Staging finished. Curated ETL and COMPLETED audit status are NOT implemented yet.')


if __name__ == '__main__':
    main()
