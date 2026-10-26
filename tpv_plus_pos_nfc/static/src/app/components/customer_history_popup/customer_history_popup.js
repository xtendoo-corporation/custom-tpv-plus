/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { deserializeDateTime } from "@web/core/l10n/dates";

export class CustomerHistoryPopup extends Component {
    static template = "tpv_plus_pos_nfc.CustomerHistoryPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        partnerId: Number,
        partnerName: String,
    };

    setup() {
        this.pos = usePos();
        this.state = useState({
            loading: true,
            error: false,
            tab: "wallet",
            openOrderId: null,
            data: { balance: 0, wallet_moves: [], orders: [] },
        });
        onWillStart(async () => {
            try {
                this.state.data = await this.pos.data.call(
                    "res.partner",
                    "tpv_plus_customer_history",
                    [this.props.partnerId]
                );
            } catch {
                this.state.error = true;
            } finally {
                this.state.loading = false;
            }
        });
    }

    formatMoney(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    formatDate(value) {
        return value ? deserializeDateTime(value).toFormat("dd/MM HH:mm") : "";
    }

    /** Signed wallet movement: + top-up, - payment. */
    moveAmount(move) {
        return (move.issued || 0) - (move.used || 0);
    }

    toggleOrder(orderId) {
        this.state.openOrderId = this.state.openOrderId === orderId ? null : orderId;
    }
}
