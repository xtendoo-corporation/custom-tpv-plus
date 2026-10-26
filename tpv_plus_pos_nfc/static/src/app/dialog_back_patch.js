/** @odoo-module */

import { dialogService } from "@web/core/dialog/dialog_service";
import { patch } from "@web/core/utils/patch";

/**
 * "Back" on the PDA (Android back button / PWA) must close the open modal or wizard
 * instead of navigating the POS underneath.
 *
 * Inside the Android app the native back button asks the POS first (window.tpvHandleBack,
 * called from MainActivity): no history involved, so it cannot get out of sync. The app
 * announces itself with window.__tpvNativeBack.
 *
 * In a normal browser / installed PWA, dialogs are not part of the browser history, so back
 * used to move the POS router. Every dialog then pushes a sentinel history entry; a popstate that consumes it closes
 * the top dialog and is hidden from the POS router. Sentinels left behind by dialogs
 * closed from the UI are skipped transparently, so one back press still goes back
 * exactly one screen.
 */
let sentinels = []; // sentinel entries above the last real history entry, oldest first
const dialogs = []; // dialogs currently open, oldest first
let internalPush = false;

const nativePushState = window.history.pushState.bind(window.history);
window.history.pushState = function () {
    if (!internalPush) {
        // A real navigation (or another component such as Odoo's mobile bottom sheets):
        // older sentinels are now buried under it.
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

/** Close the newest open dialog; returns false if none is open. */
function closeTopDialog() {
    const entry = dialogs.at(-1);
    if (!entry) {
        return false;
    }
    entry.remove();
    return true;
}

/** Called by the Android app on the native back button: true = back consumed. */
window.tpvHandleBack = () => closeTopDialog();

window.addEventListener(
    "popstate",
    (ev) => {
        if (sentinels.length) {
            // We just left the newest sentinel entry.
            const entry = sentinels.pop();
            ev.stopImmediatePropagation();
            if (!entry.closed) {
                entry.remove();
            } else if (!closeTopDialog()) {
                // Its dialog was closed from the UI and nothing else is open: skip it.
                window.history.back();
            }
        } else if (dialogs.length) {
            // Back with a dialog open but the sentinel bookkeeping lost (another component
            // pushed history entries meanwhile): the dialog still has to close first, and
            // the URL must stay where the POS router expects it.
            ev.stopImmediatePropagation();
            const href = dialogs.at(-1).href;
            closeTopDialog();
            if (window.location.href !== href) {
                internalPush = true;
                try {
                    nativePushState({}, "", href);
                } finally {
                    internalPush = false;
                }
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
            const entry = { closed: false, href: window.location.href };
            if (!window.__tpvNativeBack) {
                pushSentinel(entry);
            } else {
                entry.closed = true; // no history entry to skip later
            }
            dialogs.push(entry);
            const onClose = options.onClose;
            entry.remove = originalAdd(dialogClass, props, {
                ...options,
                onClose: async (params) => {
                    entry.closed = true;
                    const index = dialogs.indexOf(entry);
                    if (index > -1) {
                        dialogs.splice(index, 1);
                    }
                    return onClose?.(params);
                },
            });
            return entry.remove;
        };
        return service;
    },
});
