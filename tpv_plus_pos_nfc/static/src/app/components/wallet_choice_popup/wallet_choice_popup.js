/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class WalletChoicePopup extends Component {
    static template = "tpv_plus_pos_nfc.WalletChoicePopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        title: { type: String, optional: true },
        partnerName: String,
        walletBalance: Number,
        orderTotal: Number,
    };

    get payAmount() {
        return Math.max(0, Math.min(this.props.walletBalance, this.props.orderTotal));
    }

    get remainingToCharge() {
        return Math.max(0, this.props.orderTotal - this.props.walletBalance);
    }

    get balanceAfter() {
        return Math.max(0, this.props.walletBalance - this.payAmount);
    }

    get isInsufficient() {
        return this.remainingToCharge > 0.004;
    }

    formatMoney(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    onPartial() {
        this.props.getPayload({ action: "partial" });
        this.props.close();
    }

    onTotal() {
        this.props.getPayload({ action: "total" });
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}
