/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

/**
 * Partial eWallet payment.
 *
 * pos_loyalty recomputes every eWallet reward line from scratch (`_updateRewardLines`)
 * and always claims the maximum possible, so a hand-edited `price_unit` is lost and
 * `points_cost` no longer matches what is discounted. Instead, `uiState.tpvWalletCap`
 * (currency amount) limits the points the reward can consume, so the standard
 * computation yields the right price, taxes and points cost, and survives recomputes.
 */
patch(PosOrder.prototype, {
    _getRealCouponPoints(coupon_id) {
        const points = super._getRealCouponPoints(...arguments);
        if (this._tpvWalletCapPoints != null && coupon_id === this._tpvWalletCapCouponId) {
            return Math.min(points, this._tpvWalletCapPoints);
        }
        return points;
    },

    _getRewardLineValuesDiscount(args) {
        const cap = this.uiState.tpvWalletCap;
        const reward = args["reward"];
        if (
            cap == null ||
            reward.program_id.program_type !== "ewallet" ||
            reward.discount_mode !== "per_point" ||
            !reward.discount
        ) {
            return super._getRewardLineValuesDiscount(...arguments);
        }
        this._tpvWalletCapPoints = cap / reward.discount;
        this._tpvWalletCapCouponId = args["coupon_id"];
        try {
            return super._getRewardLineValuesDiscount(...arguments);
        } finally {
            this._tpvWalletCapPoints = null;
            this._tpvWalletCapCouponId = null;
        }
    },
});
