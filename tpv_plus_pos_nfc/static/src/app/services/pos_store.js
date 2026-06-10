/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { NfcScanPopup } from "@tpv_plus_pos_nfc/app/components/nfc_scan_popup/nfc_scan_popup";
import { WalletAmountPopup } from "@tpv_plus_pos_nfc/app/components/wallet_amount_popup/wallet_amount_popup";
import { WalletChoicePopup } from "@tpv_plus_pos_nfc/app/components/wallet_choice_popup/wallet_choice_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog, ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

patch(PosStore.prototype, {
    setup() {
        super.setup(...arguments);
        this.tablePartnerMemory = {};
    },

    _tpvNfcNormalizeScannedValue(scannedValue) {
        if (typeof scannedValue === "string") {
            return scannedValue.trim();
        }

        return String(
            scannedValue?.base_code || scannedValue?.code || scannedValue?.value || ""
        ).trim();
    },

    _tpvNfcShouldHandleBarcodeDirectly() {
        const order = this.getOrder();
        return Boolean(order);
    },

    async _tpvNfcProcessScannedValue(scannedValue, isDirect = false) {
        const normalizedValue = this._tpvNfcNormalizeScannedValue(scannedValue);
        if (!normalizedValue) {
            return { handled: false, success: false, scannedValue: null };
        }

        const partner = await this._tpvNfcGetPartnerByBarcode(normalizedValue);
        if (!partner) {
            if (isDirect) {
                // Si es escaneo directo y no es cliente, no hacemos nada (será un producto)
                return { handled: false, success: false, scannedValue: normalizedValue };
            }
            this.dialog.add(AlertDialog, {
                title: _t("Cliente no encontrado"),
                body: _t("No existe ningún cliente con ese código de barras."),
            });
            return { handled: true, success: false, scannedValue: normalizedValue };
        }

        const order = this.getOrder();
        if (!order || order.isEmpty()) {
            if (isDirect) {
                // Si el pedido está vacío, solo asignamos el cliente
                order.setPartner(partner);
                return { handled: true, success: true, scannedValue: normalizedValue };
            }
            this.notification.add(_t("No hay líneas en el pedido actual."), {
                type: "warning",
            });
            return { handled: true, success: false, scannedValue: normalizedValue };
        }

        const success = await this._tpvNfcHandleCustomerWalletFlow(partner);
        return { handled: true, success, scannedValue: normalizedValue };
    },

    /**
     * Open the NFC/Barcode scan wizard.
     * Returns the scanned value or null if cancelled.
     */
    async openNfcScanWizard() {
        const scannedValue = await makeAwaitable(this.dialog, NfcScanPopup, {});

        if (!scannedValue) {
            return null;
        }

        const result = await this._tpvNfcProcessScannedValue(scannedValue);
        return result.success ? result.scannedValue : null;
    },

    async _tpvNfcHandleCustomerWalletFlow(partner) {
        const order = this.getOrder();
        const originalPartner = order.getPartner();

        // 1. Automatically switch to the scanned partner
        if (order.getPartner()?.id !== partner.id) {
            console.log("[tpv_plus_pos_nfc] Switching partner to:", partner.name);
            order.setPartner(partner);
        }

        // 2. Force Odoo to sync loyalty programs and coupons for the new partner
        await this.orderUpdateLoyaltyPrograms();

        // 3. Find the ewallet card
        const walletCard = await this._tpvNfcGetPartnerEwalletCard(partner);
        if (!walletCard || walletCard.points <= 0) {
            // Option A: Just assign partner and stay in product screen
            return true;
        }

        // 3b. Ask for confirmation before paying with multiple choices
        const walletBalance = walletCard.points.toFixed(2);
        const orderTotal = order.priceIncl.toFixed(2);
        const currency = order.currency.symbol;

        const payload = await makeAwaitable(this.dialog, WalletChoicePopup, {
            title: _t("Pago con Monedero"),
            body: _t("¿Desea pagar el pedido con el monedero de %s? (Saldo: %s%s, Total: %s%s)",
                partner.name, walletBalance, currency, orderTotal, currency),
        });

        if (!payload || payload.action === 'cancel') {
            return true;
        }

        let amountToUse = null;
        if (payload.action === 'partial') {
            amountToUse = await makeAwaitable(this.dialog, WalletAmountPopup, {
                title: _t("Pagar cantidad específica"),
                partnerName: partner.name,
                walletBalance: walletCard.points,
                orderTotal: order.priceIncl,
                currencySymbol: order.currency.symbol,
            });
            if (!amountToUse) return true;
        } else {
            // Pay as much as possible (up to total or points)
            amountToUse = Math.min(walletCard.points, order.priceIncl);
        }

        // 4. Apply the eWallet reward
        this._tpvNfcRemoveExistingEwalletRewardLines(order);
        const applied = await this._tpvNfcApplyEwalletReward(walletCard, amountToUse);

        if (!applied) {
            console.error("[tpv_plus_pos_nfc] Failed to apply eWallet reward.");
            return false;
        }

        // 5. Finalize payment or navigate to payment screen
        if (order.isPaid() || Math.abs(order.priceIncl) < 0.001) {
            console.log("[tpv_plus_pos_nfc] Order fully paid via eWallet. Validating...");
            await this._tpvNfcValidateCurrentOrder(order, originalPartner);
        } else {
            console.log("[tpv_plus_pos_nfc] Partial payment via eWallet. Navigating to Payment Screen.");
            this.navigate("PaymentScreen", { orderUuid: order.uuid });
        }

        return true;
    },

    setPartner(partner) {
        super.setPartner(partner);
        const order = this.getOrder();
        if (this.config.module_pos_restaurant && order?.table_id && partner) {
            this.tablePartnerMemory[order.table_id.id] = partner;
        }
    },

    addNewOrder(data = {}) {
        console.log("[tpv_plus_pos_nfc] addNewOrder called with data:", data);
        console.trace("[tpv_plus_pos_nfc] addNewOrder Stack Trace");
        const order = super.addNewOrder(...arguments);
        if (this.config.module_pos_restaurant && order?.table_id) {
            const rememberedPartner = this.tablePartnerMemory[order.table_id.id];
            if (rememberedPartner) {
                console.log("[tpv_plus_pos_nfc] Restoring remembered partner for table:", rememberedPartner.name);
                order.setPartner(rememberedPartner);
            }
        }
        return order;
    },

    async _tpvNfcGetPartnerByBarcode(barcode) {
        let partner = this.models["res.partner"].getBy("barcode", barcode);
        if (partner) {
            return partner;
        }

        const result = await this.data.searchRead("res.partner", [["barcode", "=", barcode]]);
        return result.length ? result[0] : null;
    },

    async _tpvNfcGetPartnerEwalletCard(partner) {
        const ewalletPrograms = this.models["loyalty.program"].filter(
            (program) => program.program_type === "ewallet"
        );

        const cards = [];
        for (const program of ewalletPrograms) {
            const card = await this.fetchLoyaltyCard(program.id, partner.id);
            if (card && !card.isExpired()) {
                cards.push(card);
            }
        }

        return cards.sort((a, b) => (b.points || 0) - (a.points || 0))[0] || null;
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

    async _tpvNfcApplyEwalletReward(walletCard, amountToUse = null) {
        const order = this.getOrder();

        // 1. Try to find the reward in Odoo's claimable rewards list
        const claimableRewards = order.getClaimableRewards(walletCard.id);
        const ewalletReward = claimableRewards.find(r =>
            r.reward.program_id.program_type === 'ewallet' &&
            r.reward.reward_type === 'discount'
        );

        if (ewalletReward) {
            console.log("[tpv_plus_pos_nfc] Applying eWallet reward from claimable list:", ewalletReward.reward.id);
            // If amountToUse is provided, Odoo's _applyReward might need adjustment or we trust it handles partials
            // In ewallet, _applyReward usually applies as much as possible up to order total or points
            const result = order._applyReward(ewalletReward.reward, ewalletReward.coupon_id);
            if (result === true) {
                if (amountToUse !== null) {
                    this._tpvNfcAdjustRewardLineAmount(order, amountToUse);
                }
                return true;
            }
        }

        // 2. Fallback: Manual search in the program's rewards
        const program = walletCard.program_id;
        const reward = program.reward_ids.find(r => r.reward_type === "discount");

        if (!reward) {
            this.dialog.add(AlertDialog, {
                title: _t("Monedero no aplicable"),
                body: _t("No se ha encontrado un premio de descuento en el programa de monedero."),
            });
            return false;
        }

        // Register the card in couponPointChanges if Odoo hasn't done it yet
        if (!order.uiState.couponPointChanges[walletCard.id]) {
            order.uiState.couponPointChanges[walletCard.id] = {
                points: walletCard.points,
                program_id: program.id,
                coupon_id: walletCard.id,
            };
        }

        console.log("[tpv_plus_pos_nfc] Applying eWallet reward manually:", reward.id);
        const result = order._applyReward(reward, walletCard.id);

        if (result !== true) {
            this.dialog.add(AlertDialog, {
                title: _t("Error al aplicar monedero"),
                body: typeof result === 'string' ? result : _t("Error desconocido"),
            });
            return false;
        }

        if (amountToUse !== null) {
            this._tpvNfcAdjustRewardLineAmount(order, amountToUse);
        }

        // Final precision adjustment for small floating point errors (Standard check)
        const total = order.priceIncl;
        if (Math.abs(total) < 0.0001 && total !== 0) {
            const rewardLines = order.getOrderlines().filter(line => line.is_reward_line);
            const lastRewardLine = rewardLines[rewardLines.length - 1];
            if (lastRewardLine) {
                lastRewardLine.price_unit = lastRewardLine.price_unit - total;
            }
        }

        return true;
    },

    _tpvNfcAdjustRewardLineAmount(order, amount) {
        const rewardLines = order.getOrderlines().filter(
            (line) =>
                line.is_reward_line &&
                line.coupon_id?.program_id?.program_type === "ewallet"
        );
        const lastRewardLine = rewardLines[rewardLines.length - 1];
        if (lastRewardLine) {
            // Reward lines are usually negative
            lastRewardLine.price_unit = -Math.abs(amount);
        }
    },

    async _tpvNfcValidateCurrentOrder(order, originalPartner = null) {
        console.log("[tpv_plus_pos_nfc] Validating order with standard validateOrder(true). Total Incl:", order.priceIncl);

        const validation = new OrderPaymentValidation({
            pos: this,
            orderUuid: order.uuid,
        });

        // validateOrder(true) handles the full Odoo sequence:
        // finalizeValidation -> shouldHideValidationBehindFeedbackScreen -> navigate to ReceiptScreen
        const isValidated = await validation.validateOrder(true);

        if (isValidated) {
            // Restore the original partner to the memory for this table
            // so the NEXT order created for this table (manually or via New Order) gets it.
            if (this.config.module_pos_restaurant && order.table_id && originalPartner) {
                console.log("[tpv_plus_pos_nfc] Saving original partner to memory for restoration:", originalPartner.name);
                this.tablePartnerMemory[order.table_id.id] = originalPartner;
            }
        }
    },
});
