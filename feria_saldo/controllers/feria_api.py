import functools
import logging
from datetime import UTC, datetime

from odoo import SUPERUSER_ID, fields, http
from odoo.http import request

from ..feria_tools import API_VERSION, FeriaError, ip_allowed, normalize_code, parse_amount, parse_networks

_logger = logging.getLogger(__name__)

HISTORY_MAX = 200


def _respond(data, status=200):
    return request.make_json_response(data, status=status, headers=[('X-Feria-Api-Version', API_VERSION)])


def _error_response(error):
    body = {'error_code': error.error_code, 'message': error.message, **error.extra}
    return _respond(body, error.http_status)


def _server_time():
    return fields.Datetime.now().isoformat() + 'Z'


def _parse_datetime(raw):
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        raise FeriaError('VALIDATION_ERROR', 'invalid datetime, use ISO 8601') from None
    if value.tzinfo:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def _body():
    try:
        data = request.get_json_data()
    except ValueError:
        raise FeriaError('VALIDATION_ERROR', 'body must be JSON') from None
    if not isinstance(data, dict):
        raise FeriaError('VALIDATION_ERROR', 'body must be a JSON object')
    return data


def check_network(env):
    """The kiosk has no login: the network is the access control (Ajustes > Redes permitidas)."""
    text = env['ir.config_parameter'].sudo().get_str('feria.allowed_networks')
    try:
        networks = parse_networks(text)
    except ValueError:
        _logger.warning('feria.allowed_networks is invalid, refusing every request')
        raise FeriaError('FORBIDDEN', 'Redes permitidas mal configuradas', 403) from None
    if not ip_allowed(request.httprequest.remote_addr, networks):
        raise FeriaError('FORBIDDEN', 'Esta red no tiene acceso a la caja', 403)


def endpoint(network_check=True):
    """Wrap a handler: network and version check, FeriaError mapping."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                requested = request.httprequest.headers.get('X-Api-Version')
                if requested and requested != API_VERSION:
                    raise FeriaError('VALIDATION_ERROR', f'Unsupported API version {requested}')
                env = request.env(user=SUPERUSER_ID)
                if network_check:
                    check_network(env)
                return func(self, env, *args, **kwargs)
            except FeriaError as error:
                return _error_response(error)
        return wrapper
    return decorator


ROUTE = {'type': 'http', 'auth': 'none', 'csrf': False, 'save_session': False, 'readonly': False}


class FeriaApi(http.Controller):
    # Every route sets readonly=False: Odoo 20 would otherwise serve GETs from a replica,
    # and a lagging replica could answer "unknown" for a movement that is already committed.

    @http.route('/feria/api/v1/health', methods=['GET'], **ROUTE)
    def health(self):
        try:
            cr = request.env.cr
            cr.execute('SELECT 1')
            db_ok = cr.fetchone() == (1,)
        except Exception:  # noqa: BLE001 - the probe must answer even if the database is gone
            _logger.exception('TpvPlus health check: database unreachable')
            db_ok = False
        return _respond(
            {'status': 'ok' if db_ok else 'error', 'server_time': _server_time(), 'db_ok': db_ok},
            200 if db_ok else 503,
        )

    @http.route('/feria/api/v1/config', methods=['GET'], **ROUTE)
    @endpoint()
    def config(self, env):
        movement = env['feria.movement']
        return _respond({
            'api_version': API_VERSION,
            'currency': movement._feria_currency().name,
            'offline_mode': 'disabled',
            'server_time': _server_time(),
            'max_amount': movement._feria_param('max_amount', '0'),
        })

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    @http.route('/feria/api/v1/contacts/lookup', methods=['GET'], **ROUTE)
    @endpoint()
    def lookup(self, env, code=None, contact_id=None, **kwargs):
        """Customer by card code, or by id."""
        code_record = env['feria.code']
        if contact_id:
            try:
                partner = env['res.partner'].browse(int(contact_id)).exists()
            except ValueError:
                raise FeriaError('VALIDATION_ERROR', 'contact_id must be an integer') from None
            if not partner or not partner.feria_code_ids:
                raise FeriaError('CODE_UNKNOWN', 'Unknown customer', 404)
        else:
            code_record = self._find_code(env, code)
            partner = code_record.partner_id
        return _respond(self._contact_payload(partner, code_record))

    @staticmethod
    def _find_code(env, raw):
        normalized = normalize_code(raw)
        if not normalized:
            raise FeriaError('VALIDATION_ERROR', 'code is required')
        code_record = env['feria.code'].search([('code', '=', normalized)], limit=1)
        if not code_record:
            raise FeriaError('CODE_UNKNOWN', 'Unknown code', 404)
        return code_record

    @staticmethod
    def _contact_payload(partner, code_record):
        return {
            'contact': {'id': partner.id, 'name': partner.name, 'ref': partner.ref or None},
            'balance': _money(partner.feria_balance),
            'currency': partner.feria_currency_id.name,
            'codes': [{'code': c.code, 'kind': c.kind, 'blocked': c.blocked} for c in partner.feria_code_ids],
            'blocked': bool(partner.feria_blocked or (code_record and code_record.blocked)),
        }

    # ------------------------------------------------------------------
    # Movements
    # ------------------------------------------------------------------
    @http.route('/feria/api/v1/movements', methods=['GET', 'POST'], **ROUTE)
    @endpoint()
    def movements(self, env, contact_id=None, limit=50, **kwargs):
        if request.httprequest.method == 'POST':
            return self._create_movement(env)
        try:
            partner_id = int(contact_id)
            limit = max(1, min(int(limit), HISTORY_MAX))
        except (TypeError, ValueError):
            raise FeriaError('VALIDATION_ERROR', 'contact_id and limit must be integers') from None
        movements = env['feria.movement'].search([('partner_id', '=', partner_id)], limit=limit)
        return _respond({'movements': [m._to_api() for m in movements]})

    @staticmethod
    def _create_movement(env):
        data = _body()
        movement_type = str(data.get('type') or '').upper()
        amount = parse_amount(data.get('amount'))
        code = data.get('code_used') or data.get('code')
        if code:
            partner_id = FeriaApi._find_code(env, code).partner_id.id
        else:
            try:
                partner_id = int(data.get('contact_id') or 0)
            except (TypeError, ValueError):
                raise FeriaError('VALIDATION_ERROR', 'contact_id must be an integer') from None
            if not partner_id:
                raise FeriaError('VALIDATION_ERROR', 'code_used or contact_id is required')
        if code and data.get('contact_id') is not None and int(data['contact_id']) != partner_id:
            raise FeriaError('VALIDATION_ERROR', 'contact_id does not match the code')
        sequence = data.get('sequence')
        if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1):
            raise FeriaError('VALIDATION_ERROR', 'sequence must be a positive integer')
        result = env['feria.movement']._feria_register(
            uuid=data.get('uuid'),
            partner_id=partner_id,
            type=movement_type,
            amount=amount,
            code_used=code,
            created_at_device=_parse_datetime(data.get('created_at_device')),
            sequence=sequence,
            note=str(data['note'])[:255] if data.get('note') else None,
            from_kiosk=True,
            payment_method=str(data['payment_method']).lower() if data.get('payment_method') else None,
        )
        return _respond(result)

    @http.route('/feria/api/v1/movements/<string:uuid>', methods=['GET'], **ROUTE)
    @endpoint()
    def movement_status(self, env, uuid):
        movement = env['feria.movement'].search([('uuid', '=', uuid)], limit=1)
        if not movement:
            return _respond({'uuid': uuid, 'status': 'unknown', 'error_code': 'NOT_FOUND', 'message': 'No movement with this uuid'}, 404)
        return _respond(movement._to_api())

    # ------------------------------------------------------------------
    # Cash desk
    # ------------------------------------------------------------------
    @http.route('/feria/api/v1/cash', methods=['GET', 'POST'], **ROUTE)
    @endpoint()
    def cash(self, env):
        """GET: the cash that should be in the drawer. POST: store a recuento or a cierre de caja."""
        cash = env['feria.cash']
        if request.httprequest.method == 'POST':
            data = _body()
            counted = parse_amount(data.get('counted'), allow_zero=True)
            kept = parse_amount(data['kept'], allow_zero=True) if data.get('kept') is not None else None
            result = cash._cash_register(
                uuid=data.get('uuid'), kind=data.get('kind'), counted=counted, kept=kept,
                note=str(data['note'])[:255] if data.get('note') else None,
            )
            return _respond(result)
        result = cash._summary_to_api(cash._summary())
        last = cash.search([('kind', '=', 'close')], limit=1)
        result['last_close'] = last and {
            'date': last.date.isoformat() + 'Z', 'kept': _money(last.kept), 'counted': _money(last.counted),
        } or None
        return _respond(result)

    @http.route('/feria/api/v1/orders', methods=['GET'], **ROUTE)
    @endpoint()
    def orders(self, env, contact_id=None, **kwargs):
        try:
            partner_id = int(contact_id)
        except (TypeError, ValueError):
            raise FeriaError('VALIDATION_ERROR', 'contact_id must be an integer') from None
        if 'sale.order' not in env:
            return _respond({'orders': []})
        orders = env['sale.order'].search([('partner_id', '=', partner_id)], limit=50, order='id desc')
        return _respond({'orders': [{
            'id': o.id,
            'name': o.name,
            'date': o.date_order and o.date_order.isoformat() + 'Z' or None,
            'state': o.state,
            'amount_total': _money(o.amount_total),
            'currency': o.currency_id.name,
        } for o in orders]})


def _money(value):
    return f'{value:.2f}'
