/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class WalletChoicePopup extends Component {
    static template = "tpv_plus_pos_nfc.WalletChoicePopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        title: { type: String, optional: true },
        body: String,
    };

    onPartial() {
        this.props.getPayload({ action: 'partial' });
        this.props.close();
    }

    onTotal() {
        this.props.getPayload({ action: 'total' });
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}

