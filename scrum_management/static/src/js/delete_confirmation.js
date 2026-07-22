/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(ListRenderer.prototype, {

    async onDeleteRecord(record) {

        this.env.services.dialog.add(ConfirmationDialog, {
            title: _t("Confirm Deletion"),
            body: _t("Are you sure you want to delete this record?"),

            confirm: async () => {
                await super.onDeleteRecord(record);
            },

            cancel: () => {},
        });

    }

});