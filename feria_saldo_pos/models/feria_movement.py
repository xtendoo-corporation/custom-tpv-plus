import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class FeriaMovement(models.Model):
    _inherit = 'feria.movement'

    @api.model
    def _feria_register(self, **kwargs):
        """Register as usual (durable, idempotent) and then, if linked, send the POS order.

        The movement is already committed here: whatever happens with the POS can only delay
        the order (the cron retries), never lose or block the wallet operation.
        """
        result = super()._feria_register(**kwargs)
        try:
            self.env['feria.pos.link']._after_movement(result)
        except Exception:  # noqa: BLE001
            _logger.exception('TpvPlus: POS link failed after movement %s', result.get('uuid'))
        return result
