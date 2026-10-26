/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

// 4-column keypad: digits + the quick amounts in the last column
const KEYS = ["7", "8", "9", "half", "4", "5", "6", "max", "1", "2", "3", "⌫", ",", "0", "00", "C"];

export class WalletAmountPopup extends Component {
    static template = "tpv_plus_pos_nfc.WalletAmountPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        getPayload: Function,
        title: { type: String, optional: true },
        partnerName: String,
        walletBalance: Number,
        orderTotal: Number,
        paymentMethods: { type: Array, optional: true },
    };

    setup() {
        this.keys = KEYS;
        this.state = useState({
            text: this._toText(this.maxAmount),
            fresh: true, // the first key pressed replaces the suggested amount
        });
    }

    get maxAmount() {
        return Math.max(0, Math.min(this.props.walletBalance, this.props.orderTotal));
    }

    get amount() {
        const value = parseFloat(String(this.state.text).replace(",", "."));
        return isNaN(value) ? 0 : value;
    }

    get remaining() {
        return Math.max(0, this.props.orderTotal - this.amount);
    }

    get isOver() {
        return this.amount > this.maxAmount + 0.004;
    }

    get isValid() {
        return this.amount > 0.004 && !this.isOver;
    }

    get isFullyCovered() {
        return this.remaining < 0.005;
    }

    _toText(value) {
        return (Math.round(value * 100) / 100).toString().replace(".", ",");
    }

    formatMoney(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    onKey(key) {
        if (key === "half") {
            return this.setAmount(this.maxAmount / 2);
        }
        if (key === "max") {
            return this.setAmount(this.maxAmount);
        }
        if (key === "C") {
            this.state.text = "";
            this.state.fresh = false;
            return;
        }
        if (key === "00") {
            this.onKey("0");
            return this.onKey("0");
        }
        let text = this.state.fresh ? "" : this.state.text;
        this.state.fresh = false;
        if (key === "⌫") {
            text = text.slice(0, -1);
        } else if (key === ",") {
            if (!text.includes(",")) {
                text = (text || "0") + ",";
            }
        } else {
            const [, decimals] = text.split(",");
            if (decimals !== undefined && decimals.length >= 2) {
                return;
            }
            text = text === "0" ? key : text + key;
        }
        this.state.text = text;
    }

    setAmount(value) {
        this.state.text = this._toText(value);
        this.state.fresh = true;
    }

    /** @param {number|null} methodId payment method that collects the remainder */
    onConfirm(methodId = null) {
        if (!this.isValid) {
            return;
        }
        this.props.getPayload({ amount: this.amount, methodId });
        this.props.close();
    }

    onCancel() {
        this.props.close();
    }
}
