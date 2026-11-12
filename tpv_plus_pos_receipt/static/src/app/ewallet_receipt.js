/** @odoo-module */
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
patch(PosOrder.prototype, {
    getEWalletReceiptInfo() {
        const result = [];
        const orderlines = this.getOrderlines() || [];
        // Buscar reward lines de tipo eWallet
        const eWalletRewardLines = orderlines.filter((line) => {
            if (!line.is_reward_line) {
                return false;
            }
            // Intentar obtener el programa por varias vias
            const coupon = line.coupon_id;
            // Tambien verificar reward_id -> program_id
            const reward = line.reward_id;
            // Verificar por coupon
            if (coupon && coupon.program_id && coupon.program_id.program_type === "ewallet") {
                return true;
            }
            // Verificar por reward
            if (reward && reward.program_id && reward.program_id.program_type === "ewallet") {
                return true;
            }
            return false;
        });
        if (eWalletRewardLines.length === 0) {
            return result;
        }
        const couponMap = {};
        for (const line of eWalletRewardLines) {
            // Obtener coupon y programa por la via que este disponible
            const coupon = line.coupon_id;
            const reward = line.reward_id;
            const program = coupon?.program_id || reward?.program_id;
            const couponId = coupon ? coupon.id : (reward ? reward.id : line.id);
            if (!couponMap[couponId]) {
                couponMap[couponId] = {
                    coupon: coupon,
                    program: program,
                    totalUsed: 0,
                };
            }
            const amount = line.prices
                ? Math.abs(line.prices.total_included || 0)
                : Math.abs(line.price_subtotal_incl || 0);
            couponMap[couponId].totalUsed += amount;
        }
        for (const data of Object.values(couponMap)) {
            const currentBalance = data.coupon ? (data.coupon.points || 0) : 0;
            let remainingBalance;
            if (this.finalized) {
                remainingBalance = currentBalance;
            } else {
                remainingBalance = currentBalance - data.totalUsed;
            }
            const programName = data.program ? (data.program.name || "Monedero Electronico") : "Monedero Electronico";
            result.push({
                programName: programName,
                amountUsed: parseFloat(data.totalUsed.toFixed(2)),
                remainingBalance: parseFloat(Math.max(0, remainingBalance).toFixed(2)),
            });
        }
        return result;
    },
    hasEWalletPayment() {
        return this.getEWalletReceiptInfo().length > 0;
    },
});
