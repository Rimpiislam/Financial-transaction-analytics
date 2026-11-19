"""Reject-path + failure-path fixture test for python/03_validate_and_load_curated.py.

NEVER touches the real database: it (re)creates FinancialIntelligence_Fixture from the
pre-Phase-4C backup (real curated data present, so cross-batch codes can be exercised),
stages data/fixtures/reject_path/*.csv as NEW runs, and drives the real loader.

    ./.venv/Scripts/python.exe python/tests/run_reject_fixture.py

Exit code 0 only if every check passes.
"""
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pyodbc

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / 'data' / 'fixtures' / 'reject_path'
LOADER = ROOT / 'python' / '03_validate_and_load_curated.py'
SERVER = r'localhost\SQLEXPRESS01'
DB = 'FinancialIntelligence_Fixture'
BACKUP = r'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\Backup\FinancialIntelligence_pre_phase4C_20261118.bak'
DATA_DIR = r'C:\Program Files\Microsoft SQL Server\MSSQL17.SQLEXPRESS01\MSSQL\DATA'
CUTOFF = '2026-11-13T00:00:00'
PAY_COLS = (['transaction_id', 'attempt_timestamp_utc', 'amount', 'currency', 'merchant_id',
             'payment_method', 'status', 'failure_reason', 'status_updated_at_utc'],
            ['transaction_id_raw', 'attempt_timestamp_raw', 'amount_raw', 'currency_raw', 'merchant_id_raw',
             'payment_method_raw', 'status_raw', 'failure_reason_raw', 'status_updated_at_raw'])
ADJ_COLS = (['adjustment_id', 'transaction_id', 'adjustment_type', 'adjustment_amount', 'adjustment_timestamp_utc'],
            ['adjustment_id_raw', 'transaction_id_raw', 'adjustment_type_raw', 'adjustment_amount_raw',
             'adjustment_timestamp_raw'])

assert DB != 'FinancialIntelligence'
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))


def conn(database: str = DB, autocommit: bool = False) -> pyodbc.Connection:
    return pyodbc.connect('DRIVER={ODBC Driver 18 for SQL Server};'
                          f'SERVER={SERVER};DATABASE={database};'
                          'Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;',
                          timeout=15, autocommit=autocommit)


def restore_fixture_db() -> None:
    c = conn('master', autocommit=True)
    cur = c.cursor()
    cur.execute(f"IF DB_ID('{DB}') IS NOT NULL BEGIN ALTER DATABASE [{DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{DB}]; END")
    cur.execute(f"""RESTORE DATABASE [{DB}] FROM DISK = N'{BACKUP}'
        WITH MOVE 'FinancialIntelligence' TO N'{DATA_DIR}\\{DB}.mdf',
             MOVE 'FinancialIntelligence_log' TO N'{DATA_DIR}\\{DB}_log.ldf', CHECKSUM, RECOVERY""")
    while cur.nextset():
        pass
    c.close()


def stage(c, source_type: str, filename: str, table: str, cols, batch_id: str, rows_read: int | None = None) -> int:
    src_cols, tgt_cols = cols
    with (FIX / filename).open(newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == src_cols, reader.fieldnames
        rows = list(reader)
    cur = c.cursor()
    cur.execute("""INSERT INTO audit.etl_run (batch_id, source_type, batch_extraction_cutoff_utc, run_status, rows_read)
                   OUTPUT INSERTED.run_id VALUES (?, ?, ?, 'RUNNING', ?)""",
                batch_id, source_type, CUTOFF, len(rows) if rows_read is None else rows_read)
    run_id = int(cur.fetchone()[0])
    sql = (f"INSERT INTO {table} (run_id, batch_id, source_row_ref, {', '.join(tgt_cols)}) "
           f"VALUES ({', '.join('?' * (3 + len(tgt_cols)))})")
    cur.executemany(sql, [(run_id, batch_id, f'{filename}:{i}', *[r[k] for k in src_cols])
                          for i, r in enumerate(rows, start=2)])
    c.commit()
    return run_id


def loader(*args: str) -> str:
    p = subprocess.run([sys.executable, str(LOADER), '--database', DB, *args], capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    print('    loader> ' + out.replace('\n', '\n    loader> '))
    return out


def fingerprint(c) -> tuple:
    cur = c.cursor()
    cur.execute("""SELECT
        (SELECT COUNT(*) FROM curated.fact_payment_attempt), (SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM curated.fact_payment_attempt),
        (SELECT COUNT(*) FROM curated.fact_adjustment),      (SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM curated.fact_adjustment),
        (SELECT COUNT(*) FROM audit.reject_log),             (SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM audit.reject_log),
        (SELECT COUNT(*) FROM staging.payment_attempt_raw),  (SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM staging.payment_attempt_raw),
        (SELECT COUNT(*) FROM staging.adjustment_raw),       (SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) FROM staging.adjustment_raw)""")
    r = tuple(cur.fetchone())
    c.commit()
    return r


def run_row(c, run_id: int) -> dict:
    cur = c.cursor()
    cur.execute('SELECT run_status, rows_read, rows_loaded, rows_rejected, message FROM audit.etl_run WHERE run_id = ?', run_id)
    r = cur.fetchone()
    c.commit()
    return dict(zip(['status', 'rows_read', 'rows_loaded', 'rows_rejected', 'message'], r))


def main() -> int:
    print(f'== Restoring {DB} from backup (real DB untouched)')
    restore_fixture_db()
    c = conn()

    pay_run = stage(c, 'PAYMENT_ATTEMPT', 'payment_attempts_fixture.csv', 'staging.payment_attempt_raw', PAY_COLS, 'fixture_payment_v1')
    adj_run = stage(c, 'ADJUSTMENT', 'adjustments_fixture.csv', 'staging.adjustment_raw', ADJ_COLS, 'fixture_adjustment_v1')
    print(f'== Staged fixture runs: payment run_id={pay_run}, adjustment run_id={adj_run}')
    base = fingerprint(c)

    print('\n== F1: adjustment run before its payment run is COMPLETED -> FAILED, no data change')
    loader('--run-id', str(adj_run))
    r = run_row(c, adj_run)
    check('F1 adjustment run marked FAILED', r['status'] == 'FAILED', r['message'] or '')
    check('F1 no data/staging change', fingerprint(c) == base)

    print('\n== F2: run locked by another session -> skipped, not marked FAILED')
    holder = conn()
    hc = holder.cursor()
    hc.execute("DECLARE @rc INT; EXEC @rc = sp_getapplock @Resource=?, @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=0; SELECT @rc",
               f'FI_curated_run_{pay_run}')
    check('F2 test session acquired the lock', hc.fetchone()[0] >= 0)
    out = loader('--run-id', str(pay_run))
    holder.rollback(); holder.close()
    r = run_row(c, pay_run)
    check('F2 loader reports lock busy', 'being processed by another session' in out)
    check('F2 run still RUNNING (not FAILED)', r['status'] == 'RUNNING', r['status'])
    check('F2 no data/staging change', fingerprint(c) == base)

    print('\n== F3: failure after all validation + writes -> full rollback, run FAILED')
    loader('--run-id', str(pay_run), '--fail-after-load')
    r = run_row(c, pay_run)
    check('F3 payment run marked FAILED', r['status'] == 'FAILED', r['message'] or '')
    check('F3 rejects + curated writes rolled back, staging intact', fingerprint(c) == base)

    print('\n== F4: retry the SAME run_ids after FAILED -> COMPLETED (payment, then adjustment)')
    loader('--run-id', str(pay_run), '--run-id', str(adj_run))
    rp, ra = run_row(c, pay_run), run_row(c, adj_run)
    check('F4 payment run COMPLETED on retry', rp['status'] == 'COMPLETED', rp['message'] or '')
    check('F4 adjustment run COMPLETED on retry', ra['status'] == 'COMPLETED', ra['message'] or '')
    for label, rr in (('payment', rp), ('adjustment', ra)):
        check(f'F4 {label} reconciliation rows_read = loaded + rejected',
              rr['status'] == 'COMPLETED' and rr['rows_read'] == rr['rows_loaded'] + rr['rows_rejected'], str(rr))
    if ra['status'] != 'COMPLETED':
        print('Adjustment run did not complete; remaining checks skipped.')
        return 1

    print('\n== R: every fixture row has the expected outcome / primary code / details')
    cur = c.cursor()
    cur.execute('SELECT source_type, source_row_ref, primary_reject_code, reject_details FROM audit.reject_log WHERE run_id IN (?, ?)', pay_run, adj_run)
    rejects = {(r[0], r[1]): (r[2], r[3] or '') for r in cur.fetchall()}
    cur.execute('''SELECT s.source_row_ref,
                          CASE WHEN f.inserted_run_id = s.run_id THEN 'INSERTED'
                               WHEN f.status_updated_run_id = s.run_id THEN 'UPDATED' END
                   FROM staging.payment_attempt_raw s
                   JOIN curated.fact_payment_attempt f ON f.transaction_id = LTRIM(RTRIM(s.transaction_id_raw))
                   WHERE s.run_id = ?''', pay_run)
    accepted = {('PAYMENT_ATTEMPT', r[0]): r[1] for r in cur.fetchall() if r[1]}
    cur.execute('''SELECT s.source_row_ref FROM staging.adjustment_raw s
                   JOIN curated.fact_adjustment f ON f.adjustment_id = LTRIM(RTRIM(s.adjustment_id_raw)) AND f.loaded_run_id = s.run_id
                   WHERE s.run_id = ?''', adj_run)
    accepted.update({('ADJUSTMENT', r[0]): 'INSERTED' for r in cur.fetchall()})
    c.commit()
    with (FIX / 'expected_results.csv').open(newline='', encoding='utf-8') as fh:
        expected = list(csv.DictReader(fh))
    codes_seen = set()
    for e in expected:
        key = (e['source_type'], e['source_row_ref'])
        if key in rejects:           # reject_log is keyed by source row, so it wins over the by-ID join
            got, got_det = rejects[key]
        else:
            got, got_det = accepted.get(key, 'MISSING'), ''
        codes_seen.add(got)
        ok = got == e['expected_outcome'] and got_det == e['expected_details']
        check(f"R {e['source_row_ref']:<34} {e['expected_outcome']}", ok,
              e['what_it_proves'] if ok else f'got {got} [{got_det}] expected {e["expected_outcome"]} [{e["expected_details"]}]')
    check('R every staged row has exactly one outcome',
          len(expected) == rp['rows_read'] + ra['rows_read'] and len(rejects) == rp['rows_rejected'] + ra['rows_rejected'])

    sys.path.insert(0, str(LOADER.parent))
    precedence = __import__('03_validate_and_load_curated').PRECEDENCE
    missing = [code for code in precedence if code not in codes_seen]
    check('R every one of the 17 reject codes was triggered as a primary code', not missing, f'missing: {missing}' if missing else '')

    print('\n== D: derived values on accepted rows')
    cur.execute('''SELECT transaction_id, attempt_date_key, amount_usd, currency, status FROM curated.fact_payment_attempt
                   WHERE transaction_id IN ('FX_ET_DATE','FX_ET_SUMMER','FX_LOWER')''')
    d = {r[0]: r[1:] for r in cur.fetchall()}
    cur.execute('''SELECT f.transaction_id, m.payment_method_name FROM curated.fact_payment_attempt f
                   JOIN curated.dim_payment_method m ON m.payment_method_key = f.payment_method_key WHERE f.transaction_id = 'FX_LOWER' ''')
    lower_method = cur.fetchone()[1]
    cur.execute('''SELECT a.adjustment_id, a.attempt_date_key, a.payment_method_key, p.attempt_date_key, p.payment_method_key
                   FROM curated.fact_adjustment a JOIN curated.fact_payment_attempt p ON p.transaction_id = a.transaction_id
                   WHERE a.loaded_run_id = ?''', adj_run)
    adj_keys = cur.fetchall()
    c.commit()
    check('D UTC 2026-11-02 03:30 -> ET date 20261101 (after DST end, UTC-5)', d['FX_ET_DATE'][0] == 20261101, str(d['FX_ET_DATE'][0]))
    check('D UTC 2026-07-01 03:30 -> ET date 20260630 (DST, UTC-4)', d['FX_ET_SUMMER'][0] == 20260630, str(d['FX_ET_SUMMER'][0]))
    check("D ' FX_LOWER ' trimmed, usd->USD, card->Card, success->Success, 10.5->10.50",
          d['FX_LOWER'][1:] == (__import__('decimal').Decimal('10.50'), 'USD', 'Success') and lower_method == 'Card',
          f'{d["FX_LOWER"]} {lower_method}')
    check('D adjustment attempt_date_key + payment_method_key copied from parent',
          bool(adj_keys) and all(r[1] == r[3] and r[2] == r[4] for r in adj_keys), f'{len(adj_keys)} rows')

    print('\n== I: idempotency + duplicate staging run of a COMPLETED batch')
    before = fingerprint(c)
    loader('--run-id', str(pay_run), '--run-id', str(adj_run))
    check('I re-invoking COMPLETED runs changes no data', fingerprint(c) == before)
    cur.execute("SELECT COUNT(*) FROM audit.etl_run WHERE run_status = 'ALREADY_PROCESSED' AND batch_id IN ('fixture_payment_v1','fixture_adjustment_v1')")
    check('I two ALREADY_PROCESSED audit rows logged', cur.fetchone()[0] == 2)
    c.commit()
    dup_run = stage(c, 'PAYMENT_ATTEMPT', 'payment_attempts_fixture.csv', 'staging.payment_attempt_raw', PAY_COLS, 'fixture_payment_v1')
    before = fingerprint(c)
    loader('--run-id', str(dup_run))
    r = run_row(c, dup_run)
    check('I second RUNNING run of a COMPLETED batch -> ALREADY_PROCESSED', r['status'] == 'ALREADY_PROCESSED', r['message'] or '')
    check('I ...and no curated/reject change', fingerprint(c) == before)

    print('\n== F5: staged row count != rows_read -> FAILED before any write')
    bad_run = stage(c, 'PAYMENT_ATTEMPT', 'payment_attempts_fixture.csv', 'staging.payment_attempt_raw', PAY_COLS,
                    'fixture_payment_bad_count', rows_read=999)
    before = fingerprint(c)
    loader('--run-id', str(bad_run))
    r = run_row(c, bad_run)
    check('F5 run marked FAILED with count message', r['status'] == 'FAILED' and 'rows_read 999' in (r['message'] or ''), r['message'] or '')
    check('F5 no data change', fingerprint(c) == before)

    c.close()
    failed = [n for n, ok, _ in results if not ok]
    print(f'\n== SUMMARY: {len(results) - len(failed)} passed, {len(failed)} failed')
    for n in failed:
        print(f'   FAILED: {n}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
