/** @odoo-module */

import { dialogService } from "@web/core/dialog/dialog_service";
import { patch } from "@web/core/utils/patch";

/**
 * "Back" on the PDA (Android back button / PWA) must close the open modal or wizard
 * instead of navigating the POS underneath.
 *
 * Dialogs are not part of the browser history, so back used to move the POS router.
 * Every dialog now pushes a sentinel history entry; a popstate that consumes it closes
 * the top dialog and is hidden from the POS router. Sentinels left behind by dialogs
 * closed from the UI are skipped transparently, so one back press still goes back
 * exactly one screen.
 */
let sentinels = []; // sentinel entries above the last real history entry, oldest first
let internalPush = false;

const nativePushState = window.history.pushState.bind(window.history);
window.history.pushState = function () {
    if (!internalPush) {
        // A real navigation: older sentinels are now buried under it.
        sentinels = [];
    }
    return nativePushState(...arguments);
};

function pushSentinel(entry) {
    internalPush = true;
    try {
        nativePushState({ tpvDialog: true }, "", window.location.href);
        sentinels.push(entry);
    } finally {
        internalPush = false;
    }
}

window.addEventListener(
    "popstate",
    (ev) => {
        if (sentinels.length) {
            // We just left the newest sentinel entry.
            const entry = sentinels.pop();
            ev.stopImmediatePropagation();
            if (entry.closed) {
                // Its dialog was closed from the UI: skip it and go back again.
                window.history.back();
            } else {
                entry.remove();
            }
        } else if (ev.state?.tpvDialog) {
            // Landed on a stale sentinel buried under later navigation.
            ev.stopImmediatePropagation();
            window.history.back();
        }
    },
    true
);

patch(dialogService, {
    start() {
        const service = super.start(...arguments);
        const originalAdd = service.add;
        service.add = (dialogClass, props, options = {}) => {
            const entry = { closed: false };
            pushSentinel(entry);
            const onClose = options.onClose;
            entry.remove = originalAdd(dialogClass, props, {
                ...options,
                onClose: async (params) => {
                    entry.closed = true;
                    return onClose?.(params);
                },
            });
            return entry.remove;
        };
        return service;
    },
});
