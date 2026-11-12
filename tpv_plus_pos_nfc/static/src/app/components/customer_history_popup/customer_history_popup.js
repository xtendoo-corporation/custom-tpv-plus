/** @odoo-module */

import { Component, onWillStart, proxy, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { deserializeDateTime } from "@web/core/l10n/dates";

export class CustomerHistoryPopup extends Component {
    static template = "tpv_plus_pos_nfc.CustomerHistoryPopup";
    static components = { Dialog };
    props = useProps({
        close: t.function(),
        partnerId: t.number(),
        partnerName: t.string(),
    });

    setup() {
        this.pos = usePos();
        this.state = proxy({
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
