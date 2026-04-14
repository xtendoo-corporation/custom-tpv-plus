/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        if (this.pos._tpvNfcShouldHandleBarcodeDirectly?.()) {
            const result = await this.pos._tpvNfcProcessScannedValue(code);
            if (result?.handled) {
                this.sound.play(result.success ? "beep" : "scan-error");
                this.numberBuffer.reset();
                return;
            }
        }

        await super._barcodeProductAction(code);
    },
});

