/** @odoo-module */

import { Component, useState, onMounted, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class WalletAmountPopup extends Component {
    static template = "tpv_plus_pos_nfc.WalletAmountPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        title: { type: String, optional: true },
        partnerName: String,
        walletBalance: Number,
        orderTotal: Number,
        currencySymbol: String,
    };

    setup() {
        const initialAmount = Math.min(this.props.walletBalance, this.props.orderTotal).toFixed(2);
        this.state = useState({
            amount: initialAmount,
            error: "",
        });
        this.inputRef = useRef("amountInput");

        onMounted(() => {
            if (this.inputRef.el) {
                this.inputRef.el.focus();
                this.inputRef.el.select();
            }
        });
    }

    get formattedBalance() {
        return this.props.walletBalance.toFixed(2);
    }

    get formattedTotal() {
        return this.props.orderTotal.toFixed(2);
    }

    onConfirm() {
        const amount = parseFloat(this.state.amount);
        if (isNaN(amount) || amount <= 0) {
            this.state.error = _t("Por favor, introduce un monto válido.");
            return;
        }
        if (amount > this.props.walletBalance + 0.001) {
            this.state.error = _t("El monto supera el saldo disponible (") + this.formattedBalance + this.props.currencySymbol + ").";
            return;
        }
        if (amount > this.props.orderTotal + 0.01) {
            this.state.error = _t("El monto supera el total del pedido.");
            return;
        }

        this.props.getPayload(amount);
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}

