/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { makeAwaitable, ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";

const TPV_PURSE_LOG_PREFIX = "[tpv_purse_price_variable]";

patch(PosStore.prototype, {
    _tpvPurseDebug(message, payload = {}) {
        // console.info(`${TPV_PURSE_LOG_PREFIX} ${message}`, payload);
    },

    _tpvPurseSerializeCouponPointChanges(order) {
        return Object.values(order?.uiState?.couponPointChanges || {}).map((pointChange) => ({
            couponId: pointChange.coupon_id,
            programId: pointChange.program_id,
            points: pointChange.points,
            partnerId: pointChange.partner_id || null,
            barcode: pointChange.barcode || null,
            manual: Boolean(pointChange.manual),
        }));
    },

    _tpvPurseGetVariableRechargeLines(order) {
        return order?.lines?.filter(
            (line) =>
                !line.is_reward_line &&
                Boolean(line.product_id?.product_tmpl_id?.pos_variable_price)
        ) || [];
    },

    _tpvPurseGetRechargeAmountFromLine(line) {
        const amount =
            line?.priceIncl ??
            line?.prices?.total_included ??
            (typeof line?.price_unit === "number" && typeof line?.qty === "number"
                ? line.price_unit * line.qty
                : 0);
        return Number(amount) || 0;
    },

    async _tpvPurseEnsureVariableEwalletCouponPointChanges(order) {
        if (!order?.getPartner?.()) {
            this._tpvPurseDebug("Skipping variable eWallet fallback: order has no partner", {
                orderUuid: order?.uuid || null,
            });
            return;
        }

        const variableLines = this._tpvPurseGetVariableRechargeLines(order);
        for (const line of variableLines) {
            const program =
                line._e_wallet_program_id || this._tpvPurseGetLinkedEwalletProgram(line.product_id);
            if (!program || program.program_type !== "ewallet") {
                continue;
            }

            const amount = this._tpvPurseGetRechargeAmountFromLine(line);
            if (!(amount > 0)) {
                this._tpvPurseDebug("Skipping variable eWallet fallback: non-positive amount", {
                    lineUuid: line.uuid,
                    amount,
                    productId: line.product_id?.id || null,
                    programId: program.id,
                });
                continue;
            }

            let couponPointChange = Object.values(order.uiState.couponPointChanges || {}).find(
                (pointChange) => pointChange.program_id === program.id
            );
            let coupon = couponPointChange && this.models["loyalty.card"].get(couponPointChange.coupon_id);
            if (!coupon) {
                const partner = order.getPartner();
                if (partner) {
                    coupon = await this.fetchLoyaltyCard(program.id, partner.id);
                } else {
                    coupon = await this.couponForProgram(program);
                }
            }

            order.uiState.couponPointChanges = Object.fromEntries(
                Object.entries(order.uiState.couponPointChanges || {}).filter(
                    ([, pointChange]) => pointChange.program_id !== program.id
                )
            );

            order.uiState.couponPointChanges[coupon.id] = {
                points: amount,
                program_id: program.id,
                coupon_id: coupon.id,
                partner_id: order.getPartner()?.id || null,
                appliedRules: [],
                expiration_date: program.date_to || null,
            };

            this._tpvPurseDebug("Injected fallback couponPointChange for variable eWallet line", {
                orderUuid: order.uuid,
                lineUuid: line.uuid,
                productId: line.product_id?.id || null,
                productName: line.product_id?.display_name || line.product_id?.name || null,
                amount,
                programId: program.id,
                couponId: coupon.id,
                couponPointChanges: this._tpvPurseSerializeCouponPointChanges(order),
            });
        }
    },

    _tpvPurseResolveProductAndTemplate(vals) {
        let product = vals.product_id;
        if (typeof product === "number") {
            product = this.models["product.product"].get(product);
        }

        let productTemplate = vals.product_tmpl_id;
        if (typeof productTemplate === "number") {
            productTemplate = this.models["product.template"].get(productTemplate);
        }

        if (!productTemplate && product) {
            productTemplate = product.product_tmpl_id;
        }

        if (!product && productTemplate?.product_variant_ids?.length === 1) {
            product = productTemplate.product_variant_ids[0];
        }

        return { product, productTemplate };
    },

    _tpvPurseGetLinkedEwalletProgram(product) {
        if (!product) {
            this._tpvPurseDebug("No product available to resolve linked eWallet program");
            return null;
        }
        const program =
            this.models["loyalty.program"].find(
                (program) =>
                    program.program_type === "ewallet" &&
                    program.trigger_product_ids?.some((triggerProduct) => triggerProduct.id === product.id)
            ) || null;
        this._tpvPurseDebug("Linked eWallet program resolved", {
            productId: product.id,
            productName: product.display_name || product.name,
            programId: program?.id || null,
            programName: program?.name || null,
            triggerProductIds: this.models["loyalty.program"]
                .filter((loyaltyProgram) => loyaltyProgram.program_type === "ewallet")
                .map((loyaltyProgram) => ({
                    id: loyaltyProgram.id,
                    name: loyaltyProgram.name,
                    triggerProductIds: loyaltyProgram.trigger_product_ids?.map(
                        (triggerProduct) => triggerProduct.id
                    ),
                })),
        });
        return program;
    },

    async _tpvPurseEnsurePartnerForRecharge(program) {
        if (!program) {
            return true;
        }

        const order = this.getOrder();
        if (order?.getPartner()) {
            return true;
        }

        const confirmed = await ask(this.dialog, {
            title: _t("Cliente requerido"),
            body: _t("Debes seleccionar el cliente que recibirá el saldo del monedero."),
            confirmLabel: _t("Seleccionar cliente"),
            cancelLabel: _t("Cancelar"),
        });

        if (!confirmed) {
            return false;
        }

        const partner = await this.selectPartner();
        return Boolean(partner);
    },

    async _tpvPurseAskVariablePrice(productTemplate, defaultPrice) {
        const payload = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Precio del producto"),
            subtitle: productTemplate?.display_name || productTemplate?.name || _t("Introduzca el precio"),
            startingValue:
                defaultPrice && defaultPrice > 0 ? String(defaultPrice).replace(".", ",") : "",
            placeholder: _t("0,00"),
            confirmButtonLabel: _t("Aceptar"),
        });

        if (payload === undefined || payload === null || payload === "") {
            return null;
        }

        const normalized = String(payload).replace(",", ".");
        const amount = Number(normalized);

        if (!(amount > 0)) {
            this.dialog.add(AlertDialog, {
                title: _t("Importe inválido"),
                body: _t("El precio debe ser mayor que 0."),
            });
            return null;
        }

        return amount;
    },

    async addLineToCurrentOrder(vals, options = {}, configure = true) {
        const { product, productTemplate } = this._tpvPurseResolveProductAndTemplate(vals);
        const order = this.getOrder();
        const presetVariablePrice = Number(vals.price_unit);
        const shouldReusePresetVariablePrice =
            Boolean(options?.tpvPurseSkipVariablePricePopup) && presetVariablePrice > 0;

        this._tpvPurseDebug("addLineToCurrentOrder called", {
            configure,
            productId: product?.id || vals.product_id,
            productTemplateId: productTemplate?.id || vals.product_tmpl_id,
            productTemplateName: productTemplate?.display_name || productTemplate?.name,
            partnerId: order?.partner_id?.id || order?.getPartner?.()?.id || null,
            hasVariablePrice: Boolean(productTemplate?.pos_variable_price),
            shouldReusePresetVariablePrice,
            options,
            vals,
        });

        if (!productTemplate?.pos_variable_price) {
            return super.addLineToCurrentOrder(vals, options, configure);
        }

        const ewalletProgram = this._tpvPurseGetLinkedEwalletProgram(product);
        const partnerReady = await this._tpvPurseEnsurePartnerForRecharge(ewalletProgram);
        if (!partnerReady) {
            this._tpvPurseDebug("Partner selection aborted for variable-price recharge", {
                programId: ewalletProgram?.id || null,
            });
            return;
        }

        const defaultPrice =
            vals.price_unit ?? product?.lst_price ?? productTemplate?.list_price ?? 0;

        const variablePrice = shouldReusePresetVariablePrice
            ? presetVariablePrice
            : await this._tpvPurseAskVariablePrice(productTemplate, defaultPrice);
        if (variablePrice === null) {
            this._tpvPurseDebug("Variable price popup cancelled", {
                productId: product?.id || null,
                productTemplateId: productTemplate?.id || null,
            });
            return;
        }

        let computedPriceUnit = variablePrice;
        if (!shouldReusePresetVariablePrice && product?.id && order) {
            try {
                computedPriceUnit = await this.data.call(
                    "product.product",
                    "pos_get_price_unit_from_final_amount",
                    [
                        product.id,
                        variablePrice,
                        this.config.id,
                        order.partner_id?.id || false,
                        order.fiscal_position_id?.id || false,
                    ]
                );
            } catch {
                computedPriceUnit = variablePrice;
            }
        }

        this._tpvPurseDebug("Variable price resolved", {
            productId: product?.id || null,
            productTemplateId: productTemplate?.id || null,
            variablePrice,
            computedPriceUnit,
            ewalletProgramId: ewalletProgram?.id || null,
            partnerId: order?.getPartner?.()?.id || null,
        });

        const line = await super.addLineToCurrentOrder(
            {
                ...vals,
                product_id: product || vals.product_id,
                product_tmpl_id: productTemplate || vals.product_tmpl_id,
                qty: 1,
                price_unit: computedPriceUnit,
                price_type: "manual",
                discount: 0,
            },
            {
                ...options,
                quantity: 1,
                merge: false,
                ...(ewalletProgram
                    ? {
                          eWalletGiftCardProgram: ewalletProgram,
                          tpvPurseProgram: ewalletProgram,
                      }
                    : {}),
            },
            configure
        );

        this._tpvPurseDebug("Line created after super.addLineToCurrentOrder", {
            lineUuid: line?.uuid || null,
            lineId: line?.id || null,
            linePriceUnit: line?.price_unit,
            lineQty: line?.qty,
            lineProgramType: line?.getEWalletGiftCardProgramType?.() || null,
            lineProgramId: line?._e_wallet_program_id?.id || null,
            couponPointChangesBeforeFix: this._tpvPurseSerializeCouponPointChanges(order),
        });

        if (line && ewalletProgram) {
            line.tpv_purse_program_id = ewalletProgram;
            if (line.getEWalletGiftCardProgramType?.() !== "ewallet") {
                line.setOptions({
                    eWalletGiftCardProgram: ewalletProgram,
                    tpvPurseProgram: ewalletProgram,
                });
                await this.updatePrograms?.();
                this.updateRewards?.();
                this._tpvPurseDebug("Applied fallback eWallet program on line and forced loyalty recompute", {
                    lineUuid: line.uuid,
                    lineProgramType: line.getEWalletGiftCardProgramType?.() || null,
                    lineProgramId: line._e_wallet_program_id?.id || null,
                    persistedProgramId: line.tpv_purse_program_id?.id || null,
                    couponPointChangesAfterFix: this._tpvPurseSerializeCouponPointChanges(order),
                });
            } else {
                this._tpvPurseDebug("Line already marked as eWallet by standard flow", {
                    lineUuid: line.uuid,
                    lineProgramId: line._e_wallet_program_id?.id || null,
                    persistedProgramId: line.tpv_purse_program_id?.id || null,
                    couponPointChanges: this._tpvPurseSerializeCouponPointChanges(order),
                });
            }
        }

        if (line && ewalletProgram) {
            await this._tpvPurseEnsureVariableEwalletCouponPointChanges(order);
        }

        return line;
    },

    async _updatePrograms() {
        const order = this.getOrder();
        this._tpvPurseDebug("Before loyalty _updatePrograms", {
            orderUuid: order?.uuid || null,
            partnerId: order?.getPartner?.()?.id || null,
            lineSummary:
                order?.lines?.map((line) => ({
                    uuid: line.uuid,
                    productId: line.product_id?.id,
                    priceUnit: line.price_unit,
                    qty: line.qty,
                    isRewardLine: line.is_reward_line,
                    ewalletProgramId: line._e_wallet_program_id?.id || null,
                    ewalletProgramType: line.getEWalletGiftCardProgramType?.() || null,
                    persistedProgramId: line.tpv_purse_program_id?.id || null,
                    priceIncl: line.priceIncl,
                    templateVariablePrice: Boolean(line.product_id?.product_tmpl_id?.pos_variable_price),
                })) || [],
            couponPointChanges: this._tpvPurseSerializeCouponPointChanges(order),
        });
        await super._updatePrograms(...arguments);
        this._tpvPurseDebug("After loyalty _updatePrograms", {
            orderUuid: order?.uuid || null,
            couponPointChanges: this._tpvPurseSerializeCouponPointChanges(order),
        });
    },

    async postProcessLoyalty(order) {
        await this._tpvPurseEnsureVariableEwalletCouponPointChanges(order);
        const ProgramModel = this.models["loyalty.program"];
        let couponData = Object.values(order?.uiState?.couponPointChanges || {}).reduce((agg, pe) => {
            const program = ProgramModel.get(pe.program_id);
            agg[pe.coupon_id] = {
                ...pe,
                program_type: program?.program_type || null,
            };
            return agg;
        }, {});
        this._tpvPurseDebug("Before postProcessLoyalty", {
            orderId: order?.id || null,
            orderUuid: order?.uuid || null,
            partnerId: order?.getPartner?.()?.id || null,
            rewardLines:
                order?._get_reward_lines?.().map((line) => ({
                    uuid: line.uuid,
                    couponId: line.coupon_id?.id || null,
                    rewardId: line.reward_id?.id || null,
                    pointsCost: line.points_cost,
                })) || [],
            couponPointChanges: this._tpvPurseSerializeCouponPointChanges(order),
            couponData,
        });
        const result = await super.postProcessLoyalty(...arguments);
        this._tpvPurseDebug("After postProcessLoyalty", {
            orderId: order?.id || null,
            orderUuid: order?.uuid || null,
            newCouponInfo: order?.new_coupon_info || [],
            partnerCoupons:
                (order?.getPartner?.() &&
                    this.getLoyaltyCards?.(order.getPartner())?.map((coupon) => ({
                        id: coupon.id,
                        partnerId: coupon.partner_id?.id || null,
                        programId: coupon.program_id?.id || null,
                        programType: coupon.program_id?.program_type || null,
                        points: coupon.points,
                    }))) || [],
        });
        return result;
    },

    async couponForProgram(program) {
        if (program.program_type === "ewallet") {
            const order = this.getOrder();
            const partner = order?.getPartner();
            if (partner) {
                return await this.fetchLoyaltyCard(program.id, partner.id);
            }
        }
        return await super.couponForProgram(...arguments);
    },
});

