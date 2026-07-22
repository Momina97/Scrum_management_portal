/** @odoo-module **/

import { registry }                  from "@web/core/registry";
import { patch }                     from "@web/core/utils/patch";
import { X2ManyField, x2ManyField }  from "@web/views/fields/x2many/x2many_field";
import { ListRenderer }              from "@web/views/list/list_renderer";
import { FormController }            from "@web/views/form/form_controller";
import { standardWidgetProps }       from "@web/views/widgets/standard_widget_props";
import { useService }                from "@web/core/utils/hooks";
import { ConfirmationDialog }        from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t }                        from "@web/core/l10n/translation";
import {
    App, Component, useState, xml,
    onWillStart, onMounted, onWillUnmount, useSubEnv,
} from "@odoo/owl";


// ─────────────────────────────────────────────────────────────────────────────
// 1. STUB WIDGET
// ─────────────────────────────────────────────────────────────────────────────
class ScrumExpandWidget extends Component {
    static template = xml`<span/>`;
    static props    = { ...standardWidgetProps };
}
registry.category("view_widgets").add("scrum_expand", { component: ScrumExpandWidget });


// ─────────────────────────────────────────────────────────────────────────────
// 2. GLOBAL SCRUM STORE
// ─────────────────────────────────────────────────────────────────────────────
const SCRUM_STORE = {
    count     : 0,
    _getIds   : () => [],
    _reload   : async () => {},
    _clear    : () => {},
    _listeners: new Set(),

    set(getIds, reload, clear) {
        this._getIds = getIds;
        this._reload = reload;
        this._clear  = clear;
    },
    write(count) {
        this.count = count;
        this._listeners.forEach(fn => { try { fn(count); } catch (_) {} });
    },
    subscribe(fn)  { this._listeners.add(fn); return () => this._listeners.delete(fn); },
    getIds()       { return this._getIds(); },
    async reload() { return this._reload(); },
    clear()        { this._clear(); this.write(0); },
};


// ─────────────────────────────────────────────────────────────────────────────
// 3. RENDERER
// ─────────────────────────────────────────────────────────────────────────────
export class ScrumTaskListRenderer extends ListRenderer {

    static template          = "scrum_management.ScrumListRenderer";
    static recordRowTemplate = "scrum_management.ScrumTaskList.RecordRow";

    get hasSelectionColumn() { return true; }

    setup() {
        super.setup();
        this.orm           = useService("orm");
        this.actionService = useService("action");
        this.expandState   = useState({ expanded: {}, subtasks: {}, loading: {} });
    }

    toggleRecordSelection(record) {
        try { record.selected = !record.selected; }
        catch (_) { try { super.toggleRecordSelection(...arguments); } catch (_) {} }
        try { this.props.list?.model?.notify?.(); } catch (_) {}
        const count = (this.props.list?.records || []).filter(r => r.selected).length;
        SCRUM_STORE.write(count);
        this.env.scrumOnSelectionChange?.(count);
    }

    async _loadSubtasks(parentId) {
        this.expandState.loading[parentId] = true;
        try {
            const tasks = await this.orm.searchRead(
                "project.task",
                [["parent_id", "=", parentId]],
                ["id", "name", "stage_id", "user_ids", "assigned_by_id","allocated_hours",
                 "story_points", "state", "subtask_count"],
            );
            const allIds = [...new Set(tasks.flatMap(t => t.user_ids))];
            const uMap   = {};
            if (allIds.length) {
                (await this.orm.read("res.users", allIds, ["name"]))
                    .forEach(u => { uMap[u.id] = u.name; });
            }
            tasks.forEach(t => {
                t._owners = t.user_ids.map(id => ({ id, name: uMap[id] || "" }));
            });
            this.expandState.subtasks[parentId] = tasks;
        } catch (e) {
            console.error("[ScrumExpand]", e);
        } finally {
            this.expandState.loading[parentId] = false;
        }
    }

    async toggleExpand(record) {
        console.log("record.data.id",record.data.id)
        console.log("record.resId",record.resId)
        const id = record.resId;
        if (!id) return;
        if (this.expandState.expanded[id]) { this.expandState.expanded[id] = false; return; }
        await this._loadSubtasks(id);
        this.expandState.expanded[id] = true;
    }

    openSubtask(subtaskId, parentId) {
        this.actionService.doAction(
            { type: "ir.actions.act_window", res_model: "project.task",
              res_id: subtaskId, view_mode: "form", views: [[false, "form"]], target: "new" },
            { onClose: () => this._loadSubtasks(parentId) }
        );
    }

    addSubtask(record) {
        const ctx = { ...this.props.list?.context || {},
                      default_parent_id: record.resId, is_scrum_app: true };
        this.actionService.doAction(
            { type: "ir.actions.act_window", res_model: "project.task",
              view_mode: "form", views: [[false, "form"]], target: "new", context: ctx },
            { onClose: async () => {
                await this._loadSubtasks(record.resId);
                try { await this.props.list.model.load(); } catch (_) {}
            }}
        );
    }

    isExpanded(r)  { return !!this.expandState.expanded[r.resId]; }
    isLoading(r)   { return !!this.expandState.loading[r.resId]; }
    getSubtasks(r) { return this.expandState.subtasks[r.resId] || []; }

    getStateLabel(s) {
        return { "01_in_progress": "In Progress", "1_done": "Done",
                 "1_canceled": "Cancelled", "04_waiting_normal": "Waiting",
                 "02_changes_requested": "Changes Requested",
                 "03_approved": "Approved" }[s] || s || "";
    }

    deleteSubtask(subtaskId, parentId) {
        this.env.services.dialog.add(ConfirmationDialog, {
            title: _t("Delete Subtask"),
            body: _t("Are you sure you want to delete this subtask?"),
            confirm: async () => {
                await this.orm.unlink("project.task", [subtaskId]);
                await this._loadSubtasks(parentId);
                try { await this.props.list.model.load(); } catch (_) {}
            },
        });
    }

    getRowNumber(record) {
        const idx = this.props.list.records.findIndex(r => r === record);
        return idx >= 0 ? idx + 1 : "";
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. SCRUM BULK BAR
//
// APPROACH: useState + direct instance method call.
//
// isAdmin comes in as a prop (known before mount, never changes).
// count lives in useState and is updated by calling instance.setCount(n)
// directly from the FormController after mount() resolves.
//
// This is the ONLY approach that is:
//   (a) guaranteed to work in Odoo 18 OWL (no reactive, no props factory)
//   (b) immune to CSS display state at update time (synchronous mutation)
//   (c) immune to resize events (no async path after initial mount)
// ─────────────────────────────────────────────────────────────────────────────
class ScrumBulkBar extends Component {

    static props = {
        isAdmin: { type: Boolean },
    };

static template = xml/* xml */`
    <div class="scrum-bulk-bar-root">
        <div t-if="state.count > 0 and props.isAdmin"
             class="scrum-bulk-bar d-inline-flex align-items-center"
             style="animation:scrumBarFadeIn 0.18s ease both;">
 
            <div class="position-relative">
 
                <!-- ── Unified button ───────────────────────────────────────
                     Desktop :  [⚡  Bulk Actions (2)  ▾]
                     Small   :  [⚡  2  ▾]
                ─────────────────────────────────────────────────────────── -->
                <button type="button"
                        class="scrum-bulk-btn btn btn-primary d-inline-flex align-items-center rounded-pill shadow-sm"
                        style="font-size:12px;font-weight:600;gap:5px;"
                        t-on-click.stop="toggleMenu">
 
                    <!-- Lightning bolt icon — always visible -->
                    <i class="fa fa-bolt fa-fw"/>
 
                    <!-- "Bulk Actions" label — hidden on small screens -->
                    <span class="scrum-btn-label">Bulk Actions</span>
 
                    <!-- Count badge inside button — desktop style: "(2)" -->
                    <!-- Hidden on small screens; replaced by scrum-btn-count-sm -->
                    <span class="scrum-btn-count"
                          style="background:rgba(255,255,255,0.25);
                                 border-radius:20px;
                                 padding:1px 7px;
                                 font-size:11px;
                                 font-weight:700;
                                 line-height:1.5;
                                 letter-spacing:0.01em;">
                        <t t-esc="state.count"/>
                    </span>
 
                    <!-- Count number — small screen only (no parentheses, tighter) -->
                    <span class="scrum-btn-count-sm"
                          style="font-size:12px;font-weight:700;line-height:1;">
                        <t t-esc="state.count"/>
                    </span>
 
                    <!-- Chevron — always visible -->
                    <i t-att-class="'fa fa-fw '+(state.menuOpen?'fa-chevron-up':'fa-chevron-down')"
                       style="font-size:9px;opacity:.85;"/>
                </button>
 
                <!-- ── Dropdown menu (unchanged) ─────────────────────────── -->
                <div t-if="state.menuOpen"
                     class="scrum-dropdown-menu position-absolute bg-white py-2"
                     style="top:calc(100% + 8px);left:0;min-width:230px;z-index:99999;
                            border:1px solid #e2e8f0;border-radius:14px;
                            box-shadow:0 12px 32px -6px rgba(15,23,42,.18),
                                        0 4px 10px -3px rgba(15,23,42,.10);">
 
                    <a href="#"
                       class="d-flex align-items-center gap-3 px-3 py-2 text-decoration-none"
                       style="border-radius:10px;margin:2px 6px;cursor:pointer;"
                       t-on-click.prevent="openUpdate">
                        <span style="width:30px;height:30px;border-radius:8px;background:#eff6ff;
                                     display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;">
                            <i class="fa fa-pencil text-primary" style="font-size:12px;"/>
                        </span>
                        <div>
                            <div style="font-size:13px;font-weight:600;color:#1e293b;">Info Change</div>
                            <div style="font-size:11px;color:#94a3b8;">Update owner, project or sprint</div>
                        </div>
                    </a>
 
                    <div style="height:1px;background:#f1f5f9;margin:3px 10px;"/>
 
                    <a href="#"
                       class="d-flex align-items-center gap-3 px-3 py-2 text-decoration-none"
                       style="border-radius:10px;margin:2px 6px;cursor:pointer;"
                       t-on-click.prevent="openDelete">
                        <span style="width:30px;height:30px;border-radius:8px;background:#fef2f2;
                                     display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;">
                            <i class="fa fa-trash text-danger" style="font-size:12px;"/>
                        </span>
                        <div>
                            <div style="font-size:13px;font-weight:600;color:#dc2626;">Delete</div>
                            <div style="font-size:11px;color:#94a3b8;">Permanently remove tasks</div>
                        </div>
                    </a>
 
                </div>
            </div>
 
        </div>
    </div>
`;

    setup() {
        this.state = useState({ count: 0, menuOpen: false });
        this._orm    = useService("orm");
        this._dialog = useService("dialog");
        this._action = useService("action");
        this._notif  = useService("notification");
    }

    // Called directly from FormController.
    // Mutating a useState property is synchronous and always triggers re-render.
    setCount(n) {
        this.state.count = n;
    }

    toggleMenu(ev) {
        ev?.preventDefault(); ev?.stopPropagation();
        this.state.menuOpen = !this.state.menuOpen;
        if (this.state.menuOpen) {
            const close = () => {
                this.state.menuOpen = false;
                document.removeEventListener("click", close);
            };
            setTimeout(() => document.addEventListener("click", close), 0);
        }
    }

    clearSelection() { SCRUM_STORE.clear(); }

    async openUpdate(ev) {
        ev?.preventDefault(); ev?.stopPropagation();
        this.state.menuOpen = false;
        const ids = SCRUM_STORE.getIds();
        if (!ids.length) {
            this._notif.add(_t("Select at least one task."), { type: "warning" });
            return;
        }
        try {
            const action = await this._orm.call(
                "scrum.bulk.task.wizard", "open_bulk_wizard", [ids, "update"]
            );
            await this._action.doAction(action, {
                onClose: async () => { SCRUM_STORE.write(0); await SCRUM_STORE.reload(); },
            });
        } catch (err) {
            this._notif.add(
                err?.data?.message || _t("Could not open the wizard."),
                { type: "danger", sticky: true }
            );
        }
    }

    openDelete(ev) {
        ev?.preventDefault(); ev?.stopPropagation();
        this.state.menuOpen = false;
        const ids   = SCRUM_STORE.getIds();
        const count = ids.length;
        if (!count) {
            this._notif.add(_t("Select at least one task."), { type: "warning" });
            return;
        }
        this._dialog.add(ConfirmationDialog, {
            title: _t("Delete Selected Tasks"),
            body: count === 1
                ? _t("Are you sure you want to delete 1 selected task? This cannot be undone.")
                : _t(`Are you sure you want to delete ${count} selected tasks? This cannot be undone.`),
            confirmLabel: _t("Yes, Delete"),
            cancelLabel:  _t("No"),
            confirm: async () => {
                try {
                    await this._orm.unlink("project.task", ids);
                    this._notif.add(_t(`Deleted ${count} task(s).`), { type: "success" });
                    SCRUM_STORE.write(0);
                    await SCRUM_STORE.reload();
                } catch (err) {
                    this._notif.add(
                        err?.data?.message || _t("Delete failed."),
                        { type: "danger", sticky: true }
                    );
                }
            },
            cancel: () => {},
        });
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// 5. FIELD WIDGET
// ─────────────────────────────────────────────────────────────────────────────
class ScrumTasksField extends X2ManyField {

    static components = {
        ...X2ManyField.components,
        ListRenderer: ScrumTaskListRenderer,
    };

    static template = "web.X2ManyField";

    setup() {
        super.setup();
        this._scrumAction = useService("action");

        SCRUM_STORE.set(
            () => (this.list?.records || []).filter(r => r.selected).map(r => r.resId).filter(Boolean),
            async () => {
                try { await this.list.model.load(); this.list.model.notify(); }
                catch (_) { try { this._scrumAction.restore(); } catch (_) {} }
            },
            () => {
                let changed = false;
                for (const r of (this.list?.records || [])) {
                    if (r.selected) { r.selected = false; changed = true; }
                }
                if (changed) { try { this.list?.model?.notify?.(); } catch (_) {} }
            }
        );

        useSubEnv({ scrumOnSelectionChange: (count) => { SCRUM_STORE.write(count); } });
    }

    get listProps() { return { ...super.listProps, allowSelectors: true }; }
}

registry.category("fields").add("scrum_tasks_x2many", {
    ...x2ManyField,
    component: ScrumTasksField,
    additionalClasses: ["o_field_one2many"],
});


// ─────────────────────────────────────────────────────────────────────────────
// 6. FORM CONTROLLER PATCH
// ─────────────────────────────────────────────────────────────────────────────
patch(FormController.prototype, {

    setup() {
        super.setup();
        this._scrumIsAdmin = false;
        this._scrumBarApp  = null;
        this._scrumBarHost = null;
        this._scrumBarInst = null;  // direct ref to ScrumBulkBar instance
        this._scrumUnsub   = null;

        const orm = useService("orm");

        onWillStart(async () => {
            try {
                const ok = await orm.call(
                    "res.groups",
                    "user_has_groups",
                    ["project.group_project_manager,base.group_system"],
                );
                this._scrumIsAdmin = !!ok;
            } catch (_) {
                this._scrumIsAdmin = true;
            }
        });

        onMounted(()     => { this._scrumMount(); });
        onWillUnmount(() => {
            if (this._scrumUnsub) { this._scrumUnsub(); this._scrumUnsub = null; }
            this._scrumDestroy();
            SCRUM_STORE.write(0);
        });
    },

    _scrumFindCP() {
        const root = this.__owl__?.bdom?.el;
        return (
            root?.closest?.(".o_action")?.querySelector(".o_control_panel_breadcrumbs") ||
            document.querySelector(".o_action.o_form_view .o_control_panel_breadcrumbs") ||
            document.querySelector(".o_control_panel_breadcrumbs")
        );
    },

    _scrumMount() {
        const cp = this._scrumFindCP();
        if (!cp || cp.querySelector("#_scrum_bulk_host")) return;

        const host = document.createElement("div");
        host.id = "_scrum_bulk_host";
        host.style.cssText = "display:inline-flex;align-items:center;flex-shrink:0;margin-left:4px;";
        cp.appendChild(host);
        this._scrumBarHost = host;

        const env = this.__owl__?.app?.env;
        if (!env) return;

        // isAdmin is resolved in onWillStart — pass as prop once at mount time.
        this._scrumBarApp = new App(ScrumBulkBar, {
            env,
            props: { isAdmin: this._scrumIsAdmin },
        });

        this._scrumBarApp.mount(host).then(() => {
            // Get the live component instance from the OWL fiber root.
            this._scrumBarInst = this._scrumBarApp.root?.component ?? null;

            // Sync any count that arrived before mount resolved.
            if (SCRUM_STORE.count > 0 && this._scrumBarInst) {
                this._scrumBarInst.setCount(SCRUM_STORE.count);
            }

            // Subscribe AFTER instance is ready.
            this._scrumUnsub = SCRUM_STORE.subscribe((count) => {
                // Direct synchronous useState mutation.
                // Cannot race with CSS — mutation and re-render are synchronous
                // in OWL's scheduler queue.
                if (this._scrumBarInst) {
                    try { this._scrumBarInst.setCount(count); } catch (_) {}
                }
            });

        }).catch(e => console.error("[ScrumBulk] mount error:", e));
    },

    _scrumDestroy() {
        this._scrumBarInst = null;
        try { this._scrumBarApp?.destroy(); this._scrumBarApp = null; } catch (_) {}
        try { this._scrumBarHost?.remove();  this._scrumBarHost = null; } catch (_) {}
    },
});

