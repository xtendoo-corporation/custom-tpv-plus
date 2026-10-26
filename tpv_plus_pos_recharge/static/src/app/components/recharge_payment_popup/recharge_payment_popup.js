/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class RechargePaymentPopup extends Component {
    static template = "tpv_plus_pos_recharge.RechargePaymentPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        partnerName: String,
        amount: Number,
        paymentMethods: Array,
    };

    formatMoney(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    onSelect(methodId) {
        this.props.getPayload(methodId);
        this.props.close();
    }
}
