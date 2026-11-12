/** @odoo-module */

import { Component, useProps, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class MismatchedPartnerPopup extends Component {
    static template = "tpv_plus_pos_nfc.MismatchedPartnerPopup";
    static components = { Dialog };
    props = useProps({
        currentPartner: t.object(),
        scannedPartner: t.object(),
        close: t.function(),
        getPayload: t.function(),
    });

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
