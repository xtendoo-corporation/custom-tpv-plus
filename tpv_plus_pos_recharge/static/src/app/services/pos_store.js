/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { RechargePaymentPopup } from "@tpv_plus_pos_recharge/app/components/recharge_payment_popup/recharge_payment_popup";

patch(PosStore.prototype, {
    /**
     * Open the recharge wizard: a NumberPopup to enter the amount.
     * Then add the recharge product to the current order with that exact price.
     * No discount is applied — the entered amount is the final price.
     */
    async openRechargeWizard() {
        console.log("[tpv_plus_pos_recharge] --- START openRechargeWizard ---");
        const order = this.getOrder();
        if (!order) {
            console.warn("[tpv_plus_pos_recharge] No active order found.");
            this.notification.add(_t("No hay pedido activo."), { type: "warning" });
            return;
        }

        const rechargeProduct = this.config.recharge_product_id;
        if (!rechargeProduct) {
            console.warn("[tpv_plus_pos_recharge] No recharge product configured.");
            this.notification.add(
                _t("No se ha configurado el producto de recarga. Configúrelo en Ajustes del POS."),
                { type: "danger", sticky: true }
            );
            return;
        }

        let partner = order.getPartner();
        if (!partner) {
            partner = await this.selectPartner();
            if (!partner) {
                return;
            }
        }

        console.log("[tpv_plus_pos_recharge] Recharge product identified:", rechargeProduct.id, rechargeProduct.display_name);

        const amount = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Recarga de Monedero"),
            subtitle: _t("Introduzca el importe a recargar"),
            startingValue: "",
            placeholder: _t("0,00"),
            confirmButtonLabel: _t("Aceptar"),
        });

        if (!amount || parseFloat(amount) <= 0) {
            console.log("[tpv_plus_pos_recharge] Wizard cancelled or invalid amount entered:", amount);
            return;
        }

        const rechargeAmount = parseFloat(amount);
        console.log("[tpv_plus_pos_recharge] Amount to recharge:", rechargeAmount);

        // Get the product template for the recharge product
        const productTmpl = rechargeProduct.product_tmpl_id;

        const ewalletProgram = this.models["loyalty.program"].find(
            (p) => p.program_type === "ewallet" && p.trigger_product_ids.some(tp => tp.id === rechargeProduct.id)
        ) || this.models["loyalty.program"].find((p) => p.program_type === "ewallet");

        console.log("[tpv_plus_pos_recharge] eWallet Program resolved:", ewalletProgram ? ewalletProgram.id : "NONE");

        // The recharge is its own order for this customer, so it is paid and ticketed
        // on the spot without touching the order (table) that is currently open.
        const originalOrderUuid = this.selectedOrderUuid;
        const rechargeOrder = this.createNewOrder({});
        this.selectedOrderUuid = rechargeOrder.uuid;
        rechargeOrder.setPartner(partner);
        const cancelRecharge = () => {
            this.selectedOrderUuid = originalOrderUuid;
            this.removeOrder(rechargeOrder, false);
        };

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
            {
                ...(ewalletProgram
                    ? {
                          eWalletGiftCardProgram: ewalletProgram,
                          tpvPurseProgram: ewalletProgram,
                      }
                    : {}),
                tpvPurseSkipVariablePricePopup: true,
            }
        );

        console.log("[tpv_plus_pos_recharge] Line added to order:", line ? line.uuid : "FAILED");

        // Force the price and discount after creation to override any automatic recomputation
        if (line) {
            line.price_unit = rechargeAmount;
            line.discount = 0;
            line.price_type = "manual";
            if (ewalletProgram) {
                line.tpv_purse_program_id = ewalletProgram;
                let coupon = await this.couponForProgram(ewalletProgram);
                console.log("[tpv_plus_pos_recharge] Coupon resolved for program:", coupon ? coupon.id : "NONE");
                if (coupon) {
                    if (!rechargeOrder.uiState.couponPointChanges) {
                        rechargeOrder.uiState.couponPointChanges = {};
                    }
                    rechargeOrder.uiState.couponPointChanges[coupon.id] = {
                        points: rechargeAmount,
                        program_id: ewalletProgram.id,
                        coupon_id: coupon.id,
                        partner_id: partner.id,
                        appliedRules: [],
                        expiration_date: ewalletProgram.date_to || null,
                        manual: true,
                    };
                    console.log("[tpv_plus_pos_recharge] Injected manual point change:", JSON.parse(JSON.stringify(rechargeOrder.uiState.couponPointChanges[coupon.id])));
                    await this.updateRewards?.();
                }
            }
        }
        if (!line) {
            cancelRecharge();
            return;
        }

        // Ask how the customer pays, then validate and show the receipt.
        const methodId = await makeAwaitable(this.dialog, RechargePaymentPopup, {
            partnerName: partner.name,
            amount: rechargeAmount,
            paymentMethods: this.config.payment_method_ids
                .filter((method) => method.type !== "pay_later")
                .slice()
                .sort((a, b) => a.sequence - b.sequence)
                .map((method) => ({ id: method.id, name: method.name })),
        });
        if (!methodId) {
            cancelRecharge();
            return;
        }
        const method = this.models["pos.payment.method"].get(methodId);
        const result = rechargeOrder.addPaymentline(method);
        if (!result.status) {
            this.dialog.add(AlertDialog, { title: _t("Error"), body: result.data });
            this.navigate("PaymentScreen", { orderUuid: rechargeOrder.uuid });
            return;
        }
        if (method.use_payment_terminal) {
            // Card terminals need the usual payment screen to send the request
            this.navigate("PaymentScreen", { orderUuid: rechargeOrder.uuid });
            return;
        }
        const validation = new OrderPaymentValidation({ pos: this, orderUuid: rechargeOrder.uuid });
        const validated = await validation.validateOrder(true);
        if (!validated) {
            this.navigate("PaymentScreen", { orderUuid: rechargeOrder.uuid });
        }
        console.log("[tpv_plus_pos_recharge] --- END openRechargeWizard ---");
    },
});

