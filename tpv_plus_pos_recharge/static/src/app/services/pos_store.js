/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(PosStore.prototype, {
    /**
     * Open the recharge wizard: a NumberPopup to enter the amount.
     * Then add the recharge product to the current order with that exact price.
     * No discount is applied — the entered amount is the final price.
     */
    async openRechargeWizard() {
        const order = this.getOrder();
        if (!order) {
            this.notification.add(_t("No hay pedido activo."), { type: "warning" });
            return;
        }

        const rechargeProduct = this.config.recharge_product_id;
        if (!rechargeProduct) {
            this.notification.add(
                _t("No se ha configurado el producto de recarga. Configúrelo en Ajustes del POS."),
                { type: "danger", sticky: true }
            );
            return;
        }

        const amount = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Recarga de Monedero"),
            subtitle: _t("Introduzca el importe a recargar"),
            startingValue: "",
            placeholder: _t("0,00"),
            confirmButtonLabel: _t("Aceptar"),
        });

        if (!amount || parseFloat(amount) <= 0) {
            return;
        }

        const rechargeAmount = parseFloat(amount);

        // Get the product template for the recharge product
        const productTmpl = rechargeProduct.product_tmpl_id;

        // Add the recharge product to the order with the entered amount as the final price.
        // We pass discount: 0 and price_type: "manual" to prevent any automatic
        // pricelist recalculation from applying a discount to the recharge line.
        const line = await this.addLineToCurrentOrder(
            {
                product_id: rechargeProduct,
                product_tmpl_id: productTmpl,
                price_unit: rechargeAmount,
                price_type: "manual",
                discount: 0,
                qty: 1,
            },
            {}
        );

        // Force the price and discount after creation to override any automatic recomputation
        if (line) {
            line.price_unit = rechargeAmount;
            line.discount = 0;
            line.price_type = "manual";
        }
    },
});

