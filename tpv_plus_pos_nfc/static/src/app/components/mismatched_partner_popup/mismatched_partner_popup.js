/** @odoo-module */

import { Component } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class MismatchedPartnerPopup extends Component {
    static template = "tpv_plus_pos_nfc.MismatchedPartnerPopup";
    static components = { Dialog };
    static props = {
        currentPartner: Object,
        scannedPartner: Object,
        close: Function,
        getPayload: Function,
    };

    confirmChange() {
        this.props.getPayload("change");
        this.props.close();
    }

    confirmKeep() {
        this.props.getPayload("keep");
        this.props.close();
    }

    cancel() {
        this.props.getPayload(false);
        this.props.close();
    }
}
