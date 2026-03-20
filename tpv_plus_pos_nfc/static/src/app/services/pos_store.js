/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { NfcScanPopup } from "@tpv_plus_pos_nfc/app/components/nfc_scan_popup/nfc_scan_popup";
import { MismatchedPartnerPopup } from "@tpv_plus_pos_nfc/app/components/mismatched_partner_popup/mismatched_partner_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(PosStore.prototype, {
    /**
     * Open the NFC/Barcode scan wizard.
     * Returns the scanned value or null if cancelled.
     */
    async openNfcScanWizard() {
        const scannedValue = await makeAwaitable(this.dialog, NfcScanPopup, {});

        if (!scannedValue) {
            return null;
        }

        await this._tpvNfcHandleCustomerWalletFlow(scannedValue);
        return scannedValue;
    },

    async _tpvNfcHandleCustomerWalletFlow(barcode) {
        const order = this.getOrder();
        if (!order || order.isEmpty()) {
            this.notification.add(_t("No hay líneas en el pedido actual."), {
                type: "warning",
            });
            return;
        }

        const partner = await this._tpvNfcGetPartnerByBarcode(barcode);
        if (!partner) {
            this.dialog.add(AlertDialog, {
                title: _t("Cliente no encontrado"),
                body: _t("No existe ningún cliente con ese código de barras."),
            });
            return;
        }

        const currentPartner = order.getPartner();
        let confirmedPayload = true;
        if (currentPartner && currentPartner.id !== partner.id) {
            confirmedPayload = await makeAwaitable(this.dialog, MismatchedPartnerPopup, {
                currentPartner: currentPartner,
                scannedPartner: partner,
            });
            if (!confirmedPayload) {
                return;
            }
        }

        // Always keep current partner if mismatch was confirmed with "keep"
        const targetPartner = confirmedPayload === "keep" ? currentPartner : partner;
        
        const ewalletPrograms = this.models["loyalty.program"].filter(
            (program) => program.program_type === "ewallet"
        );
        if (ewalletPrograms.length > 1) {
            this.dialog.add(AlertDialog, {
                title: _t("Configuración inválida"),
                body: _t("Hay más de un programa eWallet activo en el POS. Deje solo uno configurado."),
            });
            return;
        }

        this._tpvNfcRemoveExistingEwalletRewardLines(order);
        
        const walletCard = this._tpvNfcGetPartnerEwalletCard(partner);
        if (walletCard) {
            order.uiState.couponPointChanges[walletCard.id] = {
                coupon_id: walletCard.id,
                program_id: walletCard.program_id.id,
                points: walletCard.points,
            };
        }

        await this.updateRewards?.();

        const walletBalance = walletCard?.points || 0;
        const orderTotal = Math.max(order.priceIncl, 0);
        const formattedBalance = formatCurrency(walletBalance, order.currency);
        const formattedTotal = formatCurrency(orderTotal, order.currency);

        if (walletBalance >= orderTotal && walletCard) {
            const applied = await this._tpvNfcApplyEwalletReward(walletCard);
            if (!applied) {
                return;
            }

            await this._tpvNfcValidateCurrentOrder(order);
            return;
        }

        if (walletCard && walletBalance > 0) {
            const applied = await this._tpvNfcApplyEwalletReward(walletCard);
            if (!applied) {
                return;
            }
            this.notification.add(
                _t("Saldo aplicado del monedero: %s. Complete el importe restante en pagos.", formattedBalance),
                {
                    type: "warning",
                }
            );
        } else {
            this.dialog.add(AlertDialog, {
                title: _t("Saldo insuficiente"),
                body: _t(
                    "El cliente no dispone de saldo suficiente en el monedero. Saldo: %s · Total: %s",
                    formattedBalance,
                    formattedTotal
                ),
            });
        }

        this.navigate("PaymentScreen", { orderUuid: order.uuid });
    },

    async _tpvNfcGetPartnerByBarcode(barcode) {
        let partner = this.models["res.partner"].getBy("barcode", barcode);
        if (partner) {
            return partner;
        }

        const result = await this.data.searchRead("res.partner", [["barcode", "=", barcode]]);
        return result.length ? result[0] : null;
    },

    _tpvNfcGetPartnerEwalletCard(partner) {
        const couponIds = this.partnerId2CouponIds?.[partner.id]
            ? [...this.partnerId2CouponIds[partner.id]]
            : [];

        return (
            couponIds
                .map((couponId) => this.models["loyalty.card"].get(couponId))
                .filter(
                    (card) =>
                        card &&
                        card.program_id?.program_type === "ewallet" &&
                        !card.isExpired()
                )
                .sort((a, b) => (b.points || 0) - (a.points || 0))[0] || null
        );
    },

    _tpvNfcRemoveExistingEwalletRewardLines(order) {
        const lines = order.getOrderlines().filter(
            (line) =>
                line.is_reward_line &&
                line.coupon_id?.program_id?.program_type === "ewallet"
        );

        for (const line of lines) {
            line.delete();
        }
    },

    async _tpvNfcApplyEwalletReward(walletCard) {
        const order = this.getOrder();
        const rewardToApply = order
            .getClaimableRewards(walletCard.id)
            .find(({ reward }) => reward.program_id.program_type === "ewallet");

        if (!rewardToApply) {
            this.dialog.add(AlertDialog, {
                title: _t("Monedero no aplicable"),
                body: _t("No se ha podido aplicar el monedero al pedido actual."),
            });
            return false;
        }

        const result = order._applyReward(rewardToApply.reward, rewardToApply.coupon_id, {});

        if (result !== true) {
            this.dialog.add(AlertDialog, {
                title: _t("Error"),
                body: result,
            });
            return false;
        }

        await this.updateRewards?.();
        return true;
    },

    async _tpvNfcValidateCurrentOrder(order) {
        const isRestaurant = this.config.module_pos_restaurant;
        const tableId = order.table_id;
        const partner = order.getPartner();

        const validation = new OrderPaymentValidation({
            pos: this,
            orderUuid: order.uuid,
        });
        const isValidated = await validation.validateOrder(false);
        if (isValidated && isRestaurant) {
            order.setScreenData({ name: "" });

            if (tableId) {
                const newOrder = this.addNewOrder({ table_id: tableId.id || tableId });
                if (partner) {
                    newOrder.setPartner(partner);
                }
            }
        }
    },
});

