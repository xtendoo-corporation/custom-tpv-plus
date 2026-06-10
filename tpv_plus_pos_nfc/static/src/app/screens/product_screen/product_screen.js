/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        if (this.pos._tpvNfcShouldHandleBarcodeDirectly?.()) {
            const result = await this.pos._tpvNfcProcessScannedValue(code, true);
            if (result?.handled) {
                if (result.success) {
                    this.sound.play("beep");
                }
                this.numberBuffer.reset();
                return;
            }
        }

        await super._barcodeProductAction(code);
    },

    async _barcodePartnerAction(code) {
        await super._barcodePartnerAction(code);
        const partner = this.pos.models["res.partner"].getBy("barcode", code);
        if (partner && this.pos._tpvNfcShouldHandleBarcodeDirectly?.()) {
            await this.pos._tpvNfcHandleCustomerWalletFlow(partner);
        }
    },
});
