/** @odoo-module */

import { Component, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class WalletChoicePopup extends Component {
    static template = "tpv_plus_pos_nfc.WalletChoicePopup";
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        getPayload: t.function(),
        title: t.string().optional(),
        partnerName: t.string(),
        walletBalance: t.number(),
        orderTotal: t.number(),
    });

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
