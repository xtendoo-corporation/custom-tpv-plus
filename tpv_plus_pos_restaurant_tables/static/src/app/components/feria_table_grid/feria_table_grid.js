import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useFloorPlanStore } from "@pos_restaurant/app/hooks/floor_plan_hook";

/**
 * Simple grid of the tables of the selected floor (replaces the standard floor map).
 * Each table shows its number, the customer permanently assigned to it
 * (feria_partner_id) and the pending changes badge.
 */
export class FeriaTableGrid extends Component {
    static template = "tpv_plus_pos_restaurant_tables.FeriaTableGrid";

    setup() {
        this.pos = usePos();
        this.floorPlanStore = useFloorPlanStore();
        this.dialog = useService("dialog");
    }

    get floor() {
        return this.floorPlanStore.selectedFloor;
    }

    get tables() {
        const elements = this.floor?.getTables() || [];
        return elements
            .map((element) => element.record)
            .filter((table) => table && table.active !== false)
            .sort((a, b) => a.table_number - b.table_number);
    }

    getChangeCount(table) {
        return this.pos.getChangeCount(table.id);
    }

    async onClickTable(table) {
        if (table.parent_id) {
            return this.onClickTable(table.parent_id);
        }
        if (!this.pos.isOrderTransferMode) {
            await this.pos.setTableFromUi(table);
        }
    }

    async onAddTable() {
        if (!this.floor) {
            return;
        }
        const result = await this.pos.data.call("pos.config", "feria_add_table", [
            this.pos.config.id,
            this.floor.id,
        ]);
        this.floorPlanStore.updateFloorPlan(result);
    }

    async onRemoveLastTable() {
        const tables = this.tables;
        if (!this.floor || !tables.length) {
            return;
        }
        const lastTable = tables[tables.length - 1];
        const customerName = lastTable.feria_partner_name;
        if (customerName) {
            const confirmed = await ask(this.dialog, {
                title: _t("Mesa %s - %s", lastTable.table_number, customerName),
                body: _t(
                    "Esta mesa tiene el cliente '%s' asignado. ¿Eliminar de todos modos?",
                    customerName
                ),
            });
            if (!confirmed) {
                return;
            }
        }
        for (const order of this.pos.getOpenOrders()) {
            if (order.table_id?.id === lastTable.id && !order.isSynced) {
                this.pos.removeOrder(order, false);
            }
        }
        const result = await this.pos.data.call("pos.config", "feria_remove_last_table", [
            this.pos.config.id,
            this.floor.id,
        ]);
        this.floorPlanStore.updateFloorPlan(result);
    }
}
