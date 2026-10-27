import contextlib
import hashlib
import ipaddress
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from odoo import SUPERUSER_ID, api
import odoo.modules.module

API_VERSION = '1'

CODE_RE = re.compile(r'[^0-9A-Z]')
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
CENT = Decimal('0.01')


class FeriaError(Exception):
    """Business error mapped by the controllers to {error_code, message}."""

    def __init__(self, error_code, message, http_status=400, **extra):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.extra = extra


def normalize_code(raw):
    """Uppercase and drop every separator: '04:a3-1f' -> '04A31F'."""
    return CODE_RE.sub('', (raw or '').upper())


def parse_amount(raw, allow_zero=False):
    """Parse an API amount into a Decimal with 2 decimals, never through float (positive unless allow_zero)."""
    if isinstance(raw, bool) or raw is None:
        raise FeriaError('VALIDATION_ERROR', 'amount is required')
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation:
        raise FeriaError('VALIDATION_ERROR', 'amount is not a number') from None
    if not value.is_finite():
        raise FeriaError('VALIDATION_ERROR', 'amount is not a number')
    if value != value.quantize(CENT, rounding=ROUND_HALF_UP):
        raise FeriaError('VALIDATION_ERROR', 'amount must have at most 2 decimals')
    value = value.quantize(CENT, rounding=ROUND_HALF_UP)
    if value < 0 or (value == 0 and not allow_zero):
        raise FeriaError('VALIDATION_ERROR', 'amount must be positive')
    return value


def sha256_hex(*parts):
    return hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()


def parse_networks(text):
    """Parse '192.168.1.0/24, 10.0.0.5' into network objects (empty text = no restriction)."""
    return [ipaddress.ip_network(part.strip(), strict=False) for part in (text or '').split(',') if part.strip()]


def ip_allowed(address, networks):
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


@contextlib.contextmanager
def serial_env(env):
    """Yield an environment on its own READ COMMITTED transaction, committed on exit.

    Odoo cursors run in REPEATABLE READ: after waiting for a row lock the snapshot
    is stale and PostgreSQL aborts with a serialization failure. Critical sections
    that serialize on a row lock (balance, rate limits) need READ COMMITTED to see
    what the previous lock holder committed. The commit happens before the caller
    answers the client, which is what makes a confirmation durable.
    """
    with env.registry.cursor() as cr:
        if not odoo.modules.module.current_test:
            # a test cursor shares the test transaction, where this is not allowed
            cr.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
        yield api.Environment(cr, env.uid or SUPERUSER_ID, {}, su=True)
    env.invalidate_all()
