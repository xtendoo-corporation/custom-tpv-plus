import logging
from random import randint

from odoo import api, fields, models
from odoo.addons.feria_saldo.feria_tools import serial_env
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 30
POS_LOCK = 727002  # advisory lock: POS orders are created one at a time (the POS locks its own sequences)


class FeriaPosLink(models.Model):
    _name = 'feria.pos.link'
    _description = 'Pedido del TPV de un cobro'
    _order = 'id desc'

    movement_id = fields.Many2one('feria.movement', string='Cobro', required=True, index=True, ondelete='restrict')
    partner_id = fields.Many2one(related='movement_id.partner_id', string='Cliente')
    amount = fields.Monetary(related='movement_id.amount', string='Importe', currency_field='currency_id')
    currency_id = fields.Many2one(related='movement_id.currency_id')
    received_at = fields.Datetime(related='movement_id.received_at', string='Fecha')
    state = fields.Selection(
        [
            ('pending', 'Pendiente de enviar'),
            ('done', 'Enviado al TPV'),
            ('review', 'Revisar en el TPV'),
            ('cancelled', 'Anulado antes de enviar'),
        ],
        string='Estado', required=True, default='pending', index=True,
    )
    pos_order_id = fields.Many2one('pos.order', string='Pedido del TPV', readonly=True, ondelete='set null')
    error = fields.Text(string='Ultimo error', readonly=True)
    attempts = fields.Integer(string='Intentos', readonly=True)

    _movement_unique = models.UniqueIndex('(movement_id)', 'Este cobro ya tiene su pedido del TPV.')

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @api.model
    def _link_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_bool('feria.pos_link')

    @api.model
    def _settings(self):
        """The configured TPV, payment method and auxiliary product, or a UserError saying what is missing."""
        params = self.env['ir.config_parameter'].sudo()
        config = self.env['pos.config'].browse(params.get_int('feria.pos_config_id')).exists()
        method = self.env['pos.payment.method'].browse(params.get_int('feria.pos_payment_method_id')).exists()
        product = self.env['product.product'].browse(params.get_int('feria.pos_product_id')).exists()
        if not config:
            raise UserError('Elige el TPV en Ajustes > TpvPlus > Vinculo con el TPV de Odoo.')
        if not method or method not in config.payment_method_ids:
            raise UserError(f'Elige un metodo de pago que pertenezca al TPV «{config.display_name}».')
        if not product:
            raise UserError('Falta el producto auxiliar del vinculo con el TPV.')
        return config, method, product

    # ------------------------------------------------------------------
    # After a movement is registered (called by the feria.movement override)
    # ------------------------------------------------------------------
    @api.model
    def _after_movement(self, result):
        """Queue and try to send the POS order of a freshly registered COBRAR; cancel it if it is cancelled."""
        if not self._link_enabled() or result.get('duplicate'):
            return
        if result['type'] == 'COBRAR':
            with serial_env(self.env) as env:
                env['feria.pos.link']._enqueue(result['uuid'])
            with serial_env(self.env) as env:
                # Wait for our turn instead of failing: concurrent POS orders fight for its sequence
                # (could not obtain lock on ir_sequence). This does not touch the wallet's own locks.
                env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [POS_LOCK])
                link = env['feria.pos.link'].search([('movement_id.uuid', '=', result['uuid'])], limit=1)
                if link:
                    link._sync_one()
        elif result['type'] == 'ANULACION' and result.get('ref_uuid'):
            with serial_env(self.env) as env:
                env['feria.pos.link']._on_cancellation(result['ref_uuid'], result['uuid'])

    @api.model
    def _enqueue(self, movement_uuid):
        movement = self.env['feria.movement'].search([('uuid', '=', movement_uuid), ('type', '=', 'COBRAR')], limit=1)
        if movement and not self.search_count([('movement_id', '=', movement.id)]):
            return self.create({'movement_id': movement.id})
        return self.browse()

    @api.model
    def _on_cancellation(self, original_uuid, cancellation_uuid):
        link = self.search([('movement_id.uuid', '=', original_uuid)], limit=1)
        if link.state == 'pending':
            link.state = 'cancelled'
        elif link.state == 'done':
            link.state = 'review'
            self.env['feria.incident'].create({
                'type': 'other',
                'partner_id': link.partner_id.id,
                'movement_id': link.movement_id.id,
                'description': f'El cobro anulado ya estaba en el TPV (pedido {link.pos_order_id.display_name}): '
                               'revisalo o abonalo alli.',
            })

    # ------------------------------------------------------------------
    # Sending to the POS
    # ------------------------------------------------------------------
    def _sync_one(self):
        """Create the POS order of one cobro. Never raises: the outcome is stored on the link."""
        self.ensure_one()
        if self.state != 'pending':
            return
        if self.env['feria.movement'].search_count([('ref_movement_id', '=', self.movement_id.id), ('type', '=', 'ANULACION')]):
            self.state = 'cancelled'
            return
        self.attempts += 1
        try:
            with self.env.cr.savepoint():
                order = self._create_pos_order()
        except UserError as error:
            self.error = error.args[0]
        except Exception as error:  # noqa: BLE001 - the POS must never break the wallet; retried by the cron
            _logger.exception('TpvPlus: could not create the POS order of cobro %s', self.movement_id.uuid)
            self.error = str(error)
        else:
            self.write({'state': 'done', 'pos_order_id': order.id, 'error': False})

    def _create_pos_order(self):
        movement = self.movement_id
        config, method, product = self._settings()
        session = config.current_session_id
        if not session or session.state != 'opened':
            raise UserError(f'No hay una sesion abierta en el TPV «{config.display_name}»: abrela y el cobro se enviara solo.')
        currency = session.currency_id
        price = float(movement.amount)
        fiscal_position = config.default_fiscal_position_id
        taxes = fiscal_position.map_tax(
            product.taxes_id.filtered_domain(self.env['account.tax']._check_company_domain(config.company_id))
        )
        if taxes:
            totals = taxes.compute_all(price, currency, 1, product=product, partner=movement.partner_id)
        else:
            totals = {'total_excluded': price, 'total_included': price}
        total = totals['total_included']
        order_data = {
            'name': f'Order {movement.uuid}',
            'uuid': movement.uuid,
            'session_id': session.id,
            'pricelist_id': config.pricelist_id.id,
            'fiscal_position_id': fiscal_position.id,
            'partner_id': movement.partner_id.id,
            'user_id': self.env.uid,
            'date_order': fields.Datetime.to_string(movement.received_at),
            'to_invoice': False,
            'amount_total': total,
            'amount_tax': total - totals['total_excluded'],
            'amount_paid': total,
            'amount_return': 0,
            'lines': [(0, 0, {
                'id': randint(1, 1000000),
                'product_id': product.id,
                'qty': 1,
                'price_unit': price,
                'price_subtotal': totals['total_excluded'],
                'price_subtotal_incl': total,
                'tax_ids': [(6, 0, taxes.ids)],
                'full_product_name': product.display_name,
            })],
            'payment_ids': [(0, 0, {
                'amount': total,
                'name': fields.Datetime.now(),
                'payment_method_id': method.id,
            })],
        }
        self.env['pos.order'].sync_from_ui([order_data])
        order = self.env['pos.order'].search([('uuid', '=', movement.uuid)], limit=1)
        if not order:
            raise UserError('El TPV no ha creado el pedido.')
        return order

    def action_retry(self):
        if not self.env.user.has_group('feria_saldo.group_feria_manager'):
            raise UserError('Solo un gestor puede reintentar el envio.')
        for link in self.sudo().filtered(lambda l: l.state == 'pending'):
            link._sync_one()
        return True

    @api.model
    def _cron_sync(self):
        """Resend what could not reach the POS (no open session, POS unavailable, ...)."""
        if not self._link_enabled():
            return
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [POS_LOCK])
        for link in self.sudo().search([('state', '=', 'pending'), ('attempts', '<', MAX_ATTEMPTS)], limit=50, order='id'):
            link._sync_one()
