/** @odoo-module */

import { Component, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class RechargePaymentPopup extends Component {
    static template = "tpv_plus_pos_recharge.RechargePaymentPopup";
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        getPayload: t.function(),
        partnerName: t.string(),
        amount: t.number(),
        paymentMethods: t.array(),
    });

    formatMoney(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    onSelect(methodId) {
        this.props.getPayload(methodId);
        this.props.close();
    }
}
