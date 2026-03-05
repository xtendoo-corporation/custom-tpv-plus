/** @odoo-module */

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { NfcScanPopup } from "@tpv_plus_pos_nfc/app/components/nfc_scan_popup/nfc_scan_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(PosStore.prototype, {
    /**
     * Open the NFC/Barcode scan wizard.
     * Returns the scanned value or null if cancelled.
     */
    async openNfcScanWizard() {
        const result = await makeAwaitable(this.dialog, NfcScanPopup, {});

        if (result) {
            this.notification.add(
                _t("Valor escaneado: %s", result),
                { type: "success" }
            );
            // The scanned value is available here for further processing
            console.log("[NFC/Barcode] Scanned value:", result);
        }

        return result || null;
    },
});

