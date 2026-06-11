/** @odoo-module */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class NfcScanPopup extends Component {
    static template = "tpv_plus_pos_nfc.NfcScanPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
    };

    setup() {
        this.state = useState({
            value: "",
            status: "waiting",       // waiting | scanning | success | error
            statusMessage: _t("Esperando escaneo…"),
            nfcSupported: false,
            nfcActive: false,
            barcodeBuffer: "",
        });

        // Forzar detección en entornos con polyfill (como la App Android)
        if ("NDEFReader" in window) {
            this.state.nfcSupported = true;
        }

        this.inputRef = useRef("valueInput");
        this._nfcReader = null;
        this._nfcAbortController = null;
        this._barcodeTimeout = null;

        onMounted(() => {
            // Focus the hidden input to capture barcode scanner keystrokes
            this._focusInput();

            // Check Web NFC support
            if ("NDEFReader" in window) {
                this.state.nfcSupported = true;
                this.state.nfcActive = true; // Forzamos activo si existe la clase
                this._startNfc();
            }

            // Escuchar evento personalizado desde el WebView si el polyfill lo lanza
            this._onNfcReady = () => {
                this.state.nfcSupported = true;
                this.state.nfcActive = true;
                this._startNfc();
            };
            window.addEventListener('nfc-ready', this._onNfcReady);

            // Listen for barcode scanner keystrokes globally
            this._onKeyDown = this._handleKeyDown.bind(this);
            document.addEventListener("keydown", this._onKeyDown, true);
        });

        onWillUnmount(() => {
            this._stopNfc();
            window.removeEventListener('nfc-ready', this._onNfcReady);
            if (this._onKeyDown) {
                document.removeEventListener("keydown", this._onKeyDown, true);
            }
            if (this._barcodeTimeout) {
                clearTimeout(this._barcodeTimeout);
            }
        });
    }

    // ─── NFC Methods ───────────────────────────────────────────

    async _startNfc() {
        try {
            if (!("NDEFReader" in window)) {
                throw new Error("NDEFReader not in window");
            }
            this._nfcAbortController = new AbortController();
            this._nfcReader = new NDEFReader();

            // Intentamos el escaneo
            await this._nfcReader.scan({ signal: this._nfcAbortController.signal });

            this.state.nfcActive = true;
            this.state.nfcSupported = true;
            this.state.statusMessage = _t("NFC activo · Esperando lectura…");

            this._nfcReader.addEventListener("reading", (event) => {
                // First: try to read NDEF text records (contains the barcode)
                if (event.message && event.message.records) {
                    for (const record of event.message.records) {
                        if (record.recordType === "text") {
                            const textDecoder = new TextDecoder(record.encoding || "utf-8");
                            const text = textDecoder.decode(record.data);
                            if (text) {
                                this._onValueScanned(text.trim(), "nfc");
                                return;
                            }
                        }
                    }
                }
                // Fallback: use serial number (UID) if no text records found
                const serialNumber = event.serialNumber || "";
                if (serialNumber) {
                    const cleanId = serialNumber.replace(/:/g, "").toUpperCase();
                    this._onValueScanned(cleanId, "nfc");
                }
            });

            this._nfcReader.addEventListener("readingerror", () => {
                this.state.statusMessage = _t("Error al leer NFC. Intente de nuevo.");
                this.state.status = "error";
                setTimeout(() => {
                    if (this.state.status === "error") {
                        this.state.status = "scanning";
                        this.state.statusMessage = _t("NFC activo · Esperando lectura…");
                    }
                }, 2000);
            });

        } catch (error) {
            console.warn("Web NFC not available or permission denied:", error);
            this.state.nfcSupported = false;
            this.state.statusMessage = _t("NFC no disponible · Use escáner de código de barras");
        }
    }

    _stopNfc() {
        if (this._nfcAbortController) {
            this._nfcAbortController.abort();
            this._nfcAbortController = null;
        }
        this._nfcReader = null;
        this.state.nfcActive = false;
    }

    // ─── Barcode Scanner Methods ───────────────────────────────

    _handleKeyDown(event) {
        // Ignore modifier keys
        if (event.key === "Shift" || event.key === "Control" || event.key === "Alt" || event.key === "Meta") {
            return;
        }

        // Enter key = barcode scan complete
        if (event.key === "Enter") {
            event.preventDefault();
            event.stopPropagation();
            if (this.state.barcodeBuffer.length >= 3) {
                this._onValueScanned(this.state.barcodeBuffer.trim(), "barcode");
            }
            this.state.barcodeBuffer = "";
            if (this._barcodeTimeout) {
                clearTimeout(this._barcodeTimeout);
                this._barcodeTimeout = null;
            }
            return;
        }

        // Escape = close
        if (event.key === "Escape") {
            return; // Let Dialog handle it
        }

        // Accumulate characters (barcode scanners type fast)
        if (event.key.length === 1) {
            event.preventDefault();
            event.stopPropagation();
            this.state.barcodeBuffer += event.key;

            // Reset timeout - barcode scanners typically send all chars within 50-100ms
            if (this._barcodeTimeout) {
                clearTimeout(this._barcodeTimeout);
            }
            this._barcodeTimeout = setTimeout(() => {
                // If we have at least 3 chars after timeout, treat as barcode
                if (this.state.barcodeBuffer.length >= 3) {
                    this._onValueScanned(this.state.barcodeBuffer.trim(), "barcode");
                }
                this.state.barcodeBuffer = "";
            }, 150);
        }
    }

    // ─── Common ────────────────────────────────────────────────

    _onValueScanned(value, source) {
        this.state.value = value;
        this.state.status = "success";

        if (source === "nfc") {
            this.state.statusMessage = _t("¡Tag NFC leído correctamente!");
        } else {
            this.state.statusMessage = _t("¡Código de barras escaneado!");
        }

        // Vibrate on mobile if supported
        if ("vibrate" in navigator) {
            navigator.vibrate(100);
        }

        this.confirm();
    }

    _focusInput() {
        if (this.inputRef.el) {
            this.inputRef.el.focus();
        }
    }

    onInputChange(event) {
        this.state.value = event.target.value;
    }

    clearValue() {
        this.state.value = "";
        this.state.status = "waiting";
        this.state.statusMessage = this.state.nfcActive
            ? _t("NFC activo · Esperando lectura…")
            : _t("Esperando escaneo…");
        this._focusInput();
    }

    confirm() {
        if (this.state.value) {
            this.props.getPayload(this.state.value);
            this.props.close();
        }
    }

    cancel() {
        this.props.close();
    }
}
