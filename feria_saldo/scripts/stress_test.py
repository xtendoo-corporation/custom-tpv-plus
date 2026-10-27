#!/usr/bin/env python3
"""Concurrency check against a running server (stdlib only).

Usage: stress_test.py BASE_URL CODE [CONCURRENCY]

Needs a contact with CODE. Checks that N concurrent charges never
overspend and that one uuid sent 100 times is registered once. Exit 0 only if all pass.
"""
import json
import random
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal

RETRIES = {'count': 0}


def call(base, method, path, token=None, data=None):
    """One API call, retried with backoff and jitter on connection errors like a real client."""
    body = json.dumps(data).encode() if data is not None else None
    for attempt in range(8):
        request = urllib.request.Request(
            f'{base}/feria/api/v1{path}', method=method, data=body,
            headers={'Content-Type': 'application/json', **({'Authorization': f'Bearer {token}'} if token else {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            except ValueError:
                return error.code, {}
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            RETRIES['count'] += 1
            time.sleep(min(2 ** attempt * 0.05, 2) * (0.5 + random.random()))
    return 0, {}


def fire(count, task):
    results = [None] * count
    barrier = threading.Barrier(count)

    def worker(index):
        barrier.wait()
        results[index] = task(index)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def report(checks):
    ok = True
    for name, passed in checks.items():
        print(f'   [{"OK" if passed else "FAIL"}] {name}')
        ok &= passed
    return ok


def main():
    base, code = sys.argv[1], sys.argv[2]
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    token = None

    def movement(kind, amount, movement_uuid=None):
        return {'uuid': movement_uuid or str(uuid.uuid4()), 'code_used': code, 'type': kind, 'amount': amount}

    status, body = call(base, 'POST', '/movements', token, movement('RECARGAR', '100.00'))
    assert status == 200, body
    start = Decimal(body['balance_after'])

    # A: concurrent COBRAR 3.00 on one contact
    results = fire(concurrency, lambda i: call(base, 'POST', '/movements', token, movement('COBRAR', '3.00')))
    confirmed = [r for r in results if r[0] == 200]
    rejected = [r for r in results if r[0] == 409 and r[1].get('error_code') == 'INSUFFICIENT_BALANCE']
    other = [r for r in results if r not in confirmed and r not in rejected]
    expected_ok = min(concurrency, int(start // 3))
    final = Decimal(call(base, 'GET', f'/contacts/lookup?code={code}', token)[1]['balance'])
    after = [Decimal(r[1]['balance_after']) for r in confirmed]
    print(f'A: {concurrency} concurrent charges: {len(confirmed)} confirmed, {len(rejected)} insufficient, {len(other)} other')
    print(f'   start {start}, final {final}, expected {start - 3 * expected_ok}')
    ok = report({
        'no unexpected responses': not other,
        'confirmed count': len(confirmed) == expected_ok,
        'final balance': final == start - 3 * expected_ok,
        'never negative': final >= 0,
        'balance_after values all distinct (serialized)': len(set(after)) == len(after),
    })

    # B: same uuid 100 times concurrently
    before = Decimal(call(base, 'POST', '/movements', token, movement('RECARGAR', '50.00'))[1]['balance_after'])
    same = str(uuid.uuid4())
    results = fire(100, lambda i: call(base, 'POST', '/movements', token, movement('COBRAR', '1.00', same)))
    statuses = sorted({r[0] for r in results})
    balances = {r[1].get('balance_after') for r in results}
    replays = sum(1 for r in results if r[1].get('duplicate'))
    final = Decimal(call(base, 'GET', f'/contacts/lookup?code={code}', token)[1]['balance'])
    print(f'B: same uuid x100: statuses {statuses}, distinct balance_after {balances}, replays {replays}')
    ok &= report({
        'all answered 200': statuses == [200],
        'same result for every call': len(balances) == 1,
        'exactly one original': replays == 99,
        'charged once': final == before - 1,
    })

    print(f'connection retries needed: {RETRIES["count"]}')
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
