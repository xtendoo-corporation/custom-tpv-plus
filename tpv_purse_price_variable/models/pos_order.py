import json
import logging

from odoo import models


_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _tpv_purse_log(self, message, *args):
        _logger.info("[tpv_purse_price_variable] " + message, *args)

    def _tpv_purse_get_variable_ewallet_program(self, line):
        self.ensure_one()
        if line.tpv_purse_program_id:
            self._tpv_purse_log(
                "Variable eWallet fallback using persisted program order_id=%s line_uuid=%s product_id=%s persisted_program_id=%s",
                self.id,
                line.uuid,
                line.product_id.id,
                line.tpv_purse_program_id.id,
            )
            return line.tpv_purse_program_id.sudo()

        config_programs = self.config_id.sudo()._get_program_ids().filtered(
            lambda program: program.program_type == "ewallet"
        )
        candidate_payload = [
            {
                "program_id": program.id,
                "program_name": program.name,
                "trigger_product_ids": program.trigger_product_ids.ids,
                "rule_product_ids": program.rule_ids.product_ids.ids,
                "pos_config_ids": program.pos_config_ids.ids,
                "company_id": program.company_id.id,
                "currency_id": program.currency_id.id,
                "pos_ok": program.pos_ok,
            }
            for program in config_programs
        ]
        self._tpv_purse_log(
            "Variable eWallet fallback resolving program order_id=%s line_uuid=%s product_id=%s product_tmpl_id=%s config_id=%s config_program_candidates=%s",
            self.id,
            line.uuid,
            line.product_id.id,
            line.product_id.product_tmpl_id.id,
            self.config_id.id,
            candidate_payload,
        )

        programs = config_programs.filtered(
            lambda program: line.product_id in program.trigger_product_ids
            or line.product_id in program.rule_ids.product_ids
        )
        if not programs:
            broad_programs = self.env["loyalty.program"].sudo().search([
                ("active", "=", True),
                ("pos_ok", "=", True),
                ("program_type", "=", "ewallet"),
                ("company_id", "=", self.company_id.id),
                ("currency_id", "=", self.currency_id.id),
            ]).filtered(
                lambda program: line.product_id in program.trigger_product_ids
                or line.product_id in program.rule_ids.product_ids
            )
            if broad_programs:
                self._tpv_purse_log(
                    "Variable eWallet fallback broad match order_id=%s line_uuid=%s product_id=%s program_ids=%s",
                    self.id,
                    line.uuid,
                    line.product_id.id,
                    broad_programs.ids,
                )
                programs = broad_programs
        if len(programs) > 1:
            self._tpv_purse_log(
                "Multiple eWallet programs found for order_id=%s line_uuid=%s product_id=%s program_ids=%s; using first one",
                self.id,
                line.uuid,
                line.product_id.id,
                programs.ids,
            )
        elif not programs:
            self._tpv_purse_log(
                "No eWallet program matched order_id=%s line_uuid=%s product_id=%s product_tmpl_id=%s config_id=%s",
                self.id,
                line.uuid,
                line.product_id.id,
                line.product_id.product_tmpl_id.id,
                self.config_id.id,
            )
        return programs[:1]

    def _tpv_purse_process_variable_ewallet_lines(self):
        LoyaltyCard = self.env["loyalty.card"].sudo().with_context(
            action_no_send_mail=True,
            loyalty_no_mail=True,
        )
        LoyaltyHistory = self.env["loyalty.history"].sudo()

        for order in self:
            order._tpv_purse_log(
                "Variable eWallet fallback START order_id=%s state=%s partner_id=%s line_count=%s",
                order.id,
                order.state,
                order.partner_id.id if order.partner_id else False,
                len(order.lines),
            )

            if not order.partner_id:
                order._tpv_purse_log(
                    "Variable eWallet fallback SKIP order_id=%s reason=no_partner",
                    order.id,
                )
                continue

            if order.state in ("draft", "cancel"):
                order._tpv_purse_log(
                    "Variable eWallet fallback SKIP order_id=%s reason=state_%s",
                    order.id,
                    order.state,
                )
                continue

            variable_lines = order.lines.filtered(
                lambda line: not getattr(line, "is_reward_line", False)
                and line.product_id.product_tmpl_id.pos_variable_price
                and line.qty > 0
                and line.price_subtotal_incl > 0
            )

            order._tpv_purse_log(
                "Variable eWallet fallback candidate lines order_id=%s lines=%s",
                order.id,
                [
                    {
                        "line_id": line.id,
                        "line_uuid": line.uuid,
                        "product_id": line.product_id.id,
                        "product_name": line.full_product_name or line.product_id.display_name,
                        "tpv_purse_program_id": line.tpv_purse_program_id.id,
                        "qty": line.qty,
                        "price_subtotal_incl": line.price_subtotal_incl,
                    }
                    for line in variable_lines
                ],
            )

            for line in variable_lines:
                program = order._tpv_purse_get_variable_ewallet_program(line)
                if not program:
                    order._tpv_purse_log(
                        "Variable eWallet fallback SKIP order_id=%s line_uuid=%s reason=no_program product_id=%s",
                        order.id,
                        line.uuid,
                        line.product_id.id,
                    )
                    continue

                existing_standard_history = LoyaltyHistory.search_count([
                    ("order_model", "=", order._name),
                    ("order_id", "=", order.id),
                    ("card_id.program_id", "=", program.id),
                    ("description", "not like", "[tpv_purse_price_variable] Recharge line %"),
                ])
                if existing_standard_history:
                    order._tpv_purse_log(
                        "Variable eWallet fallback SKIP order_id=%s line_uuid=%s reason=standard_history_exists program_id=%s",
                        order.id,
                        line.uuid,
                        program.id,
                    )
                    continue

                history_description = (
                    "[tpv_purse_price_variable] Recharge line %s (%s)"
                    % (line.uuid, line.full_product_name or line.product_id.display_name)
                )
                existing_line_history = LoyaltyHistory.search_count([
                    ("order_model", "=", order._name),
                    ("order_id", "=", order.id),
                    ("card_id.program_id", "=", program.id),
                    ("description", "=", history_description),
                ])
                if existing_line_history:
                    order._tpv_purse_log(
                        "Variable eWallet fallback SKIP order_id=%s line_uuid=%s reason=already_processed program_id=%s",
                        order.id,
                        line.uuid,
                        program.id,
                    )
                    continue

                amount = line.price_subtotal_incl
                if amount <= 0:
                    order._tpv_purse_log(
                        "Variable eWallet fallback SKIP order_id=%s line_uuid=%s reason=non_positive_amount amount=%s",
                        order.id,
                        line.uuid,
                        amount,
                    )
                    continue

                card = LoyaltyCard.search([
                    ("partner_id", "=", order.partner_id.id),
                    ("program_id", "=", program.id),
                ], limit=1)
                if not card:
                    card = LoyaltyCard.create({
                        "program_id": program.id,
                        "partner_id": order.partner_id.id,
                        "points": 0,
                        "expiration_date": program.date_to,
                        "source_pos_order_id": order.id,
                    })
                    order._tpv_purse_log(
                        "Variable eWallet fallback CREATED card_id=%s order_id=%s partner_id=%s program_id=%s",
                        card.id,
                        order.id,
                        order.partner_id.id,
                        program.id,
                    )

                previous_points = card.points
                card.write({"points": previous_points + amount})
                LoyaltyHistory.create({
                    "card_id": card.id,
                    "order_model": order._name,
                    "order_id": order.id,
                    "description": history_description,
                    "used": 0,
                    "issued": amount,
                })
                order._tpv_purse_log(
                    "Variable eWallet fallback APPLIED order_id=%s line_uuid=%s card_id=%s program_id=%s amount=%s points_before=%s points_after=%s",
                    order.id,
                    line.uuid,
                    card.id,
                    program.id,
                    amount,
                    previous_points,
                    card.points,
                )

            related_cards = LoyaltyCard.search([
                ("partner_id", "=", order.partner_id.id),
                ("program_id.program_type", "=", "ewallet"),
            ])
            order._tpv_purse_log(
                "Variable eWallet fallback END order_id=%s related_cards=%s",
                order.id,
                related_cards.read(["id", "program_id", "partner_id", "points", "code", "source_pos_order_id"]),
            )

    def _process_order(self, order, existing_order):
        pos_order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(pos_order_id)
        pos_order.with_company(pos_order.company_id)._tpv_purse_process_variable_ewallet_lines()
        return pos_order_id

    def confirm_coupon_programs(self, coupon_data):
        self.ensure_one()
        partner = self.partner_id
        coupon_data = dict(coupon_data or {})
        filtered_coupon_keys = []
        for coupon_key, coupon_vals in list(coupon_data.items()):
            program_id = int(coupon_vals.get("program_id") or 0)
            if not program_id:
                continue
            program = self.env["loyalty.program"].sudo().browse(program_id)
            if program.program_type != "ewallet":
                continue
            existing_fallback_history = self.env["loyalty.history"].sudo().search_count([
                ("order_model", "=", self._name),
                ("order_id", "=", self.id),
                ("card_id.program_id", "=", program_id),
                ("description", "like", "[tpv_purse_price_variable] Recharge line %"),
            ])
            if existing_fallback_history:
                filtered_coupon_keys.append(coupon_key)
                coupon_data.pop(coupon_key, None)

        payload_snapshot = json.loads(json.dumps(coupon_data or {}))
        _logger.info(
            "[tpv_purse_price_variable] confirm_coupon_programs START order_id=%s order_name=%s partner_id=%s partner_name=%s filtered_coupon_keys=%s coupon_data=%s",
            self.id,
            self.name,
            partner.id if partner else False,
            partner.name if partner else False,
            filtered_coupon_keys,
            payload_snapshot,
        )

        if not coupon_data:
            result = {
                "coupon_updates": [],
                "program_updates": [],
                "new_coupon_info": [],
                "coupon_report": {},
            }
            _logger.info(
                "[tpv_purse_price_variable] confirm_coupon_programs EARLY RETURN order_id=%s result=%s",
                self.id,
                result,
            )
            return result

        result = super().confirm_coupon_programs(coupon_data)

        program_ids = {
            int(vals.get("program_id"))
            for vals in payload_snapshot.values()
            if vals.get("program_id")
        }
        related_cards = self.env["loyalty.card"].sudo().search([
            ("program_id", "in", list(program_ids) or [0]),
            "|",
            ("partner_id", "=", partner.id if partner else False),
            ("source_pos_order_id", "=", self.id),
        ])

        _logger.info(
            "[tpv_purse_price_variable] confirm_coupon_programs END order_id=%s result=%s related_cards=%s",
            self.id,
            result,
            related_cards.read(["id", "program_id", "partner_id", "points", "code", "source_pos_order_id"]),
        )
        return result

