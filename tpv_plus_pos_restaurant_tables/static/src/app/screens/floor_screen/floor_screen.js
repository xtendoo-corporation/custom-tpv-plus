import { FloorScreen } from "@pos_restaurant/app/screens/floor_screen/floor_screen";
import { FeriaTableGrid } from "@tpv_plus_pos_restaurant_tables/app/components/feria_table_grid/feria_table_grid";
import { patch } from "@web/core/utils/patch";

patch(FloorScreen, {
    components: { ...FloorScreen.components, FeriaTableGrid },
});
