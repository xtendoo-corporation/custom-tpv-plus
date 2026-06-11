/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import * as errorUtils from "@web/core/errors/error_utils";

// In Odoo 17+, we can sometimes patch the module if we have access to it.

// Note: In many JS environments, module exports are immutable.
// If Odoo's module system allows it, we can try to patch it.
try {
    patch(errorUtils, {
        formatTraceback(error) {
            if (!error || !error.stack) {
                return (error && error.message) || String(error) || "Unknown error";
            }
            return super.formatTraceback(...arguments);
        }
    });
} catch (e) {
    console.warn("Could not patch formatTraceback, error reporting might be fragile:", e);
}


