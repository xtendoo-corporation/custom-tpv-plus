from odoo import api, fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def pos_get_price_unit_from_final_amount(
        self,
        product_id,
        final_amount,
        config_id,
        partner_id=False,
        fiscal_position_id=False,
    ):
        product = self.browse(product_id).exists()
        if not product:
            return final_amount

        config = self.env["pos.config"].browse(config_id).exists()
        partner = self.env["res.partner"].browse(partner_id).exists() if partner_id else self.env["res.partner"]
        fiscal_position = (
            self.env["account.fiscal.position"].browse(fiscal_position_id).exists()
            if fiscal_position_id
            else self.env["account.fiscal.position"]
        )

        taxes = product.taxes_id.filtered(
            lambda tax: not tax.company_id or tax.company_id == (config.company_id if config else self.env.company)
        )
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes)

        if not taxes:
            return float(final_amount)

        currency = (config.currency_id if config else self.env.company.currency_id)
        target = float(final_amount)
        sign = -1.0 if target < 0 else 1.0
        target_abs = abs(target)

        def _total_included_for(base_amount):
            res = taxes.compute_all(
                sign * base_amount,
                currency=currency,
                quantity=1.0,
                product=product,
                partner=partner[:1],
            )
            return abs(res["total_included"])

        low = 0.0
        high = max(target_abs, 1.0)
        total_at_high = _total_included_for(high)
        expansion_count = 0
        while total_at_high < target_abs and expansion_count < 20:
            high *= 2.0
            total_at_high = _total_included_for(high)
            expansion_count += 1

        for _index in range(60):
            mid = (low + high) / 2.0
            total_mid = _total_included_for(mid)
            if total_mid < target_abs:
                low = mid
            else:
                high = mid

        return sign * high


