# -*- coding: utf-8 -*-

from odoo import _, models
from odoo.exceptions import UserError

# Same defaults the standard floor plan editor uses for a new table
FERIA_TABLE_LAYOUT = {'top': 0, 'left': 0, 'width': 100, 'height': 100, 'color': 'green', 'shape': 'square'}


class PosConfig(models.Model):
    _inherit = 'pos.config'

    def _feria_floor(self, floor_id):
        self.ensure_one()
        floor = self.floor_ids.filtered(lambda f: f.id == floor_id and f.active)
        if not floor:
            raise UserError(_("El plano indicado no pertenece a este TPV."))
        return floor

    def _feria_notify_floor_plan(self):
        for config in self.floor_ids.pos_config_ids:
            config._notify("FLOOR_PLAN_UPD", {
                'device_identifier': self.env.context.get('device_identifier', False),
                'session_id': self.current_session_id.id,
            })

    def feria_add_table(self, floor_id):
        """Add one table with the next free number. Done on the server, under a row lock on the
        floor, so two devices adding at the same time never create the same number."""
        floor = self._feria_floor(floor_id)
        self.env.cr.execute("SELECT id FROM restaurant_floor WHERE id = %s FOR UPDATE", (floor.id,))
        tables = self.env['restaurant.table'].with_context(active_test=False).search([('floor_id', '=', floor.id)])
        self.env['restaurant.table'].create({
            'floor_id': floor.id,
            'table_number': max(tables.mapped('table_number') or [0]) + 1,
            'seats': 2,
            'floor_plan_layout': dict(FERIA_TABLE_LAYOUT),
        })
        self._feria_notify_floor_plan()
        return self.get_floor_plan()

    def feria_remove_last_table(self, floor_id):
        """Deactivate the table with the highest number (and free its assigned customer)."""
        floor = self._feria_floor(floor_id)
        self.env.cr.execute("SELECT id FROM restaurant_floor WHERE id = %s FOR UPDATE", (floor.id,))
        tables = self.env['restaurant.table'].search([('floor_id', '=', floor.id)], order='table_number desc', limit=1)
        if tables:
            tables.are_orders_still_in_draft()
            tables.write({'active': False, 'feria_partner_id': False})
            self._feria_notify_floor_plan()
        return self.get_floor_plan()
