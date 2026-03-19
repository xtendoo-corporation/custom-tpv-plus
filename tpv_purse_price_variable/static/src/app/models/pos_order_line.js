/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline, {
    extraFields: {
        ...(PosOrderline.extraFields || {}),
        tpv_purse_program_id: {
            model: "pos.order.line",
            name: "tpv_purse_program_id",
            relation: "loyalty.program",
            type: "many2one",
        },
    },
});

patch(PosOrderline.prototype, {
    setOptions(options) {
        if (options.eWalletGiftCardProgram) {
            this.tpv_purse_program_id = options.eWalletGiftCardProgram;
        }
        if (options.tpvPurseProgram) {
            this.tpv_purse_program_id = options.tpvPurseProgram;
        }
        return super.setOptions(...arguments);
    },
});

