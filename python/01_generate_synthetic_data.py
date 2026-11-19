"""Generate reproducible, entirely synthetic payment and adjustment CSVs.
Run from repository root using the project virtual environment.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

SEED = 20261113
N_ATTEMPTS = 1000
OUT = Path(__file__).resolve().parents[1] / 'data' / 'raw'
RNG = random.Random(SEED)
START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
ET = ZoneInfo('America/New_York')
PAYMENT_FIELDS = ['transaction_id', 'attempt_timestamp_utc', 'amount', 'currency',
                  'merchant_id', 'payment_method', 'status', 'failure_reason',
                  'status_updated_at_utc']
ADJUSTMENT_FIELDS = ['adjustment_id', 'transaction_id', 'adjustment_type',
                     'adjustment_amount', 'adjustment_timestamp_utc']
FAILURES = ['AUTH_TIMEOUT', 'INSUFFICIENT_FUNDS', 'FRAUD_DECLINE',
            'INVALID_PAYMENT_DETAILS', 'PROCESSOR_ERROR', 'LIMIT_EXCEEDED', 'OTHER']


def fmt(ts: datetime) -> str:
    return ts.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def money(cents: int) -> str:
    return f'{Decimal(cents) / 100:.2f}'


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    attempts: list[dict] = []
    adjustments: list[dict] = []
    adjustment_number = 0
    duration_seconds = int((END - START).total_seconds())

    for i in range(1, N_ATTEMPTS + 1):
        attempted = START + timedelta(seconds=RNG.randrange(duration_seconds + 1))
        et_hour = attempted.astimezone(ET).hour
        # Deliberately seeded pattern: elevated timeouts at 02:00-03:59 ET.
        timeout_window = 2 <= et_hour < 4
        status = RNG.choices(
            ['Success', 'Failed', 'Cancelled', 'Pending'],
            weights=[66, 29, 3, 2] if timeout_window else [80, 15, 3, 2],
        )[0]
        reason = ''
        if status == 'Failed':
            reason = ('AUTH_TIMEOUT' if timeout_window and RNG.random() < .7
                      else RNG.choice(FAILURES))
        amount_cents = RNG.randint(500, 120000)
        txn_id = f'TXN{i:06d}'
        # Final status is represented as a later update; pending remains unchanged.
        updated = attempted if status == 'Pending' else attempted + timedelta(minutes=RNG.randint(1, 20))
        attempts.append({
            'transaction_id': txn_id,
            'attempt_timestamp_utc': fmt(attempted),
            'amount': money(amount_cents),
            'currency': 'USD',
            'merchant_id': f'M{RNG.randint(1, 35):03d}',
            'payment_method': RNG.choice(['Card', 'ACH', 'Wallet']),
            'status': status,
            'failure_reason': reason,
            'status_updated_at_utc': fmt(updated),
        })

        if status != 'Success' or RNG.random() >= .12:
            continue
        # Synthetic settlement: 24 hours after attempt. Refund after settlement;
        # reversal before settlement. Never both on one transaction.
        is_reversal = RNG.random() < .22
        kind = 'Reversal' if is_reversal else 'Refund'
        event_time = (attempted + timedelta(hours=RNG.randint(1, 23))
                      if is_reversal else attempted + timedelta(days=RNG.randint(2, 21)))
        adjustment_number += 1
        adjustment_cents = amount_cents if is_reversal else RNG.randint(1, amount_cents)
        adjustments.append({
            'adjustment_id': f'ADJ{adjustment_number:06d}',
            'transaction_id': txn_id,
            'adjustment_type': kind,
            'adjustment_amount': money(adjustment_cents),
            'adjustment_timestamp_utc': fmt(event_time),
        })

    write_csv(OUT / 'payment_attempts.csv', PAYMENT_FIELDS, attempts)
    write_csv(OUT / 'adjustments.csv', ADJUSTMENT_FIELDS, adjustments)
    print(f'Generated {len(attempts)} payment attempts and {len(adjustments)} adjustments')
    print(f'Output folder: {OUT}')
    print('All records are synthetic; random seed:', SEED)


if __name__ == '__main__':
    main()
