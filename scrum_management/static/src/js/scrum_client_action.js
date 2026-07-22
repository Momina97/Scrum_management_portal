/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { View } from "@web/views/view";
import { useService } from "@web/core/utils/hooks";

// Import the Velocity Chart component
import { VelocityChart } from "@scrum_management/js/velocity_chart";
// Import the Burndown Chart component
import { BurndownChart } from "@scrum_management/js/burndown_chart";

class ScrumClientAction extends Component {
    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");

        this.state = useState({
            activeKey: `dashboard_main_${Date.now()}`,
            viewProps: {},
            isProjectsExpanded: false,
            isConfigExpanded: true, // Configuration menu is visible on load

            projects: [],

            filteredProjects: [],

            expandedProjectId: null,
            sprintsByProject: {},
            activeProjectId: null,
            activeProjectName: '',
            activeSprintId: null,
            viewType: 'dashboard',

            // Internal history stack for custom XML breadcrumbs and navigation
            navHistory: [],

            // ===== Sidebar responsive state =====
            isSidebarCollapsed: this.getInitialCollapseState(),
            isMobile: window.innerWidth < 768,
            isMobileSidebarOpen: false,
        });

        this.cachedViewIds = {};
        this.cachedActionIds = {}; // Stores real Action IDs for Control Panel gear menu

        // Listen to the browser's physical back/forward buttons
        this.onPopState = this.onPopState.bind(this);
        window.addEventListener("popstate", this.onPopState);

        // Listen to window resize for responsive behavior
        this.onWindowResize = this.onWindowResize.bind(this);
        window.addEventListener("resize", this.onWindowResize);

        onWillStart(async () => {
            try {
                this.cachedViewIds = await this.orm.call('project.project', 'get_scrum_view_ids', []);
            } catch (e) {
                console.error("Failed to fetch Scrum View IDs from server:", e);
            }

            // Fetch Real Action IDs for the Action Menus (Export/Delete)
            await this.fetchActionIds();

            const params = this.props.action.params || {};
            if (params.project_id) {
                if (params.view_type === 'settings') {
                    await this.toggleProject(params.project_id, true);
                } else {
                    await this.toggleProject(params.project_id);
                }
            } else {
                await this.selectItem('dashboard');
            }
        });

        this.refreshInterval = setInterval(() => {
            if (this.state.expandedProjectId) {
                this.fetchSprintsForProject(this.state.expandedProjectId, true);
            }
        }, 15000);

        onWillDestroy(() => {
            if (this.refreshInterval) clearInterval(this.refreshInterval);
            window.removeEventListener("popstate", this.onPopState);
            window.removeEventListener("resize", this.onWindowResize);
        });
    }

    // ==========================================
    // SIDEBAR RESPONSIVE / COLLAPSE LOGIC
    // ==========================================

    getInitialCollapseState() {
        try {
            const saved = localStorage.getItem("scrum_sidebar_collapsed");
            if (saved !== null) return saved === "true";
        } catch (e) {}
        // Default: collapsed on smaller screens, expanded on large
        return window.innerWidth < 1024;
    }

    toggleSidebar() {
        if (this.state.isMobile) {
            this.state.isMobileSidebarOpen = !this.state.isMobileSidebarOpen;
        } else {
            this.state.isSidebarCollapsed = !this.state.isSidebarCollapsed;
            try {
                localStorage.setItem("scrum_sidebar_collapsed", this.state.isSidebarCollapsed);
            } catch (e) {}
            // When collapsing, close any expanded submenus for a clean look
            if (this.state.isSidebarCollapsed) {
                this.state.isProjectsExpanded = false;
                this.state.isConfigExpanded = false;
            }
        }
    }

    closeMobileSidebar() {
        if (this.state.isMobile) {
            this.state.isMobileSidebarOpen = false;
        }
    }

    onWindowResize() {
        const wasMobile = this.state.isMobile;
        this.state.isMobile = window.innerWidth < 768;
        // Close mobile drawer when transitioning back to desktop
        if (wasMobile && !this.state.isMobile) {
            this.state.isMobileSidebarOpen = false;
        }
    }

    // ==========================================
    // CUSTOM ROUTING & BREADCRUMB ENGINE
    // ==========================================

    pushToHistory(key, title, resId, viewProps, activeKey, isRoot = false) {
        // Clicking a main sidebar item clears the breadcrumb trail to start fresh
        if (isRoot) {
            this.state.navHistory = [];
        }

        // ─────────────────────────────────────────────────────────────
        // DEDUPLICATION: Scan the ENTIRE trail for an existing entry
        // that represents the same record (same resId + same category).
        //
        // If found → TRIM the trail to that entry (navigate back to it).
        //            All entries after it are removed.
        //            The view is updated to the found entry's props.
        //            No new browser history entry is pushed.
        //
        // If not found → APPEND normally as a new breadcrumb node.
        // ─────────────────────────────────────────────────────────────
        const existingIndex = this._findExistingBreadcrumbIndex(key, resId);

        if (existingIndex !== -1) {
            // TRIM: Navigate back to the existing entry
            const existing = this.state.navHistory[existingIndex];
            existing.key = key;
            existing.title = title;
            existing.viewProps = viewProps;
            existing.activeKey = activeKey;
            this.state.navHistory = this.state.navHistory.slice(0, existingIndex + 1);
            // Sync the active view immediately
            Object.assign(this.state, { activeKey, viewProps });
            // Do NOT push to window.history — this is a lateral/backward navigation
            return;
        }

        // No duplicate found — append as a new breadcrumb node
        this.state.navHistory.push({ key, title, resId, viewProps, activeKey });

        // Push generic state to the browser to enable the physical 'Back' button
        window.history.pushState({ scrumSPA: Date.now() }, "");
    }

    onPopState(event) {
        // Handle physical back/forward browser buttons
        if (this.state.navHistory.length > 1) {
            this.state.navHistory.pop(); // Remove current view
            const previous = this.state.navHistory[this.state.navHistory.length - 1];
            if (previous) this.restoreHistoryState(previous);
        } else {
            // If we back out of the SPA entirely
            this.actionService.doAction('cancel');
        }
    }

    goToHistoryIndex(index) {
        // Handle clicks directly on the XML Breadcrumbs
        if (index < 0 || index >= this.state.navHistory.length) return;
        const target = this.state.navHistory[index];
        // Trim future history stack
        this.state.navHistory = this.state.navHistory.slice(0, index + 1);
        this.restoreHistoryState(target);
    }

    /**
     * Called when clicking the permanent "Scrum" root breadcrumb.
     * Navigates back to the global dashboard.
     */
    goToScrumRoot() {
        this.selectItem('dashboard');
    }

    restoreHistoryState(step) {
        Object.assign(this.state, {
            activeKey: step.activeKey,
            viewProps: step.viewProps
        });
    }

    // ==========================================
    // BREADCRUMB DEDUPLICATION ENGINE
    // ==========================================

    /**
     * Maps a breadcrumb key to a logical category so that different keys
     * representing the same model type are treated as equivalent.
     *
     * Example: A sprint can appear as 'sprint_form' (sidebar click),
     *          'sprint_board' (kanban drill-down), or '_ctx_sprint'
     *          (auto-injected context). All three refer to a sprint record
     *          and must not coexist in the trail for the same resId.
     */
    _getBreadcrumbCategory(key) {
        if (['project_dashboard', 'sprints_project', '_ctx_project'].includes(key)) {
            return 'project';
        }
        if (['sprint_form', 'sprint_board', '_ctx_sprint'].includes(key)) {
            return 'sprint';
        }
        if (['task_form'].includes(key)) {
            return 'task';
        }
        // For section-level entries (dashboard, sprints, backlog, config_*),
        // use the exact key as its own category.
        return key;
    }

    /**
     * Scans the entire navHistory trail for an entry that represents
     * the same record (or section) as the one being pushed.
     *
     * Matching rules:
     *   - For record-level entries (resId is set):
     *     Match by resId AND category. This ensures Sprint 5 from
     *     'sprint_form' matches Sprint 5 from 'sprint_board'.
     *
     *   - For section-level entries (resId is null/undefined):
     *     Match by category (which equals the exact key for sections).
     *
     * Returns the index of the existing entry, or -1 if not found.
     */
    _findExistingBreadcrumbIndex(key, resId) {
        const category = this._getBreadcrumbCategory(key);

        if (resId !== null && resId !== undefined) {
            // Record-level: match by resId within the same category
            return this.state.navHistory.findIndex(step =>
                step.resId === resId &&
                this._getBreadcrumbCategory(step.key) === category
            );
        }

        // Section-level: match by category (no resId)
        return this.state.navHistory.findIndex(step =>
            !step.resId && this._getBreadcrumbCategory(step.key) === category
        );
    }

    // ==========================================
    // BREADCRUMB CONTEXT INJECTION HELPERS
    // ==========================================

    /**
     * Checks whether a project entry already exists in navHistory.
     * Delegates to the central dedup engine for consistent matching.
     */
    _hasProjectInBreadcrumb(projectId) {
        return this._findExistingBreadcrumbIndex('_ctx_project', projectId) !== -1;
    }

    /**
     * Checks whether a sprint entry already exists in navHistory.
     * Delegates to the central dedup engine for consistent matching.
     */
    _hasSprintInBreadcrumb(sprintId) {
        return this._findExistingBreadcrumbIndex('_ctx_sprint', sprintId) !== -1;
    }

    /**
     * Injects a project breadcrumb entry if the current navHistory
     * doesn't already contain one for this project.
     *
     * When the user clicks this breadcrumb, they'll see the project's
     * sprint kanban (same view as clicking a project card in Projects Kanban).
     */
    _injectProjectBreadcrumb(projectId, projectName) {
        if (this._hasProjectInBreadcrumb(projectId)) return;

        const appCtx = { is_scrum_app: true, active_id: projectId };
        const activeKey = `_ctx_project_${projectId}_${Date.now()}`;

        const sprintKanbanId = this.cachedViewIds.sprint_kanban || false;
        const searchViewId = this.cachedViewIds.sprint_search_view || false;

        const viewProps = {
            ...this.getStandardViewProps('project.scrum.sprint', 'kanban', {
                default_project_id: projectId,
                search_default_group_by_stage_forced: 1,
                ...appCtx
            }),
            viewId: sprintKanbanId,
            searchViewId: searchViewId,
            views: [[sprintKanbanId, 'kanban'], [false, 'form'], [searchViewId, 'search']],
            state: { groupBy: ['stage_id'] },
            domain: [['project_id', '=', projectId]],
            selectRecord: (sprintId) => this.openSprintBoard(sprintId),
        };

        this.state.navHistory.push({
            key: '_ctx_project',
            title: projectName,
            resId: projectId,
            viewProps,
            activeKey
        });

        // Keep browser history in sync so the physical Back button
        // can step through each breadcrumb entry.
        window.history.pushState({ scrumSPA: Date.now() }, "");
    }

    /**
     * Injects a sprint breadcrumb entry if the current navHistory
     * doesn't already contain one for this sprint.
     *
     * When the user clicks this breadcrumb, they'll see the sprint's
     * task board (kanban grouped by stage).
     */
    _injectSprintBreadcrumb(sprintId, sprintName) {
        if (this._hasSprintInBreadcrumb(sprintId)) return;

        const appCtx = {
            is_scrum_app: true,
            default_sprint_id: sprintId,
            search_default_sprint_id: sprintId
        };

        const activeKey = `_ctx_sprint_${sprintId}_${Date.now()}`;
        const viewProps = {
            ...this.getStandardViewProps('project.task', 'kanban', appCtx),
            domain: [['sprint_id', '=', sprintId]],
            state: { groupBy: ['stage_id'] },
            selectRecord: (taskId) => this.openTask(taskId),
        };

        this.state.navHistory.push({
            key: '_ctx_sprint',
            title: sprintName,
            resId: sprintId,
            viewProps,
            activeKey
        });

        window.history.pushState({ scrumSPA: Date.now() }, "");
    }

    // ==========================================
    // DATA FETCHING & HELPER PROPS
    // ==========================================

    async fetchActionIds() {
        const mapping = {
            'config_projects': 'project.open_view_project_all',
            'config_task_stages': 'scrum_management.action_scrum_task_stages',
            'config_stages': 'scrum_management.action_scrum_project_stages',
            'config_sprint_stages': 'scrum_management.action_scrum_sprint_stages',
            'config_dod_templates': 'scrum_management.action_scrum_dod_template',
            'config_tags': 'project.project_tags_action',
            'config_activity_types': 'mail.mail_activity_type_action',
            'config_activity_plans': 'mail.mail_activity_plan_action',
            'projects_kanban': 'project.open_view_project_all'
        };

        const promises = Object.entries(mapping).map(async ([key, xmlId]) => {
            try {
                const resId = await this.orm.call('ir.model.data', 'xmlid_to_res_id', [xmlId]);
                if (resId) {
                    this.cachedActionIds[key] = resId;
                }
            } catch (e) {
                console.warn(`Could not fetch action ID for ${xmlId}`, e);
            }
        });

        await Promise.all(promises);
    }

    async fetchProjects() {
        try {
            const projects = await this.orm.searchRead(
                'project.project',
                [['project_type', '=', 'scrum']],
                ['id', 'name'],
                { context: { is_scrum_app: true } }
            );
            this.state.projects = projects;
            this.state.filteredProjects = projects;
        } catch (e) {
            console.error("Error fetching projects:", e);
        }
    }


    // ==========================================
    // 🔍 SEARCH FUNCTION
    // ==========================================
    onSearchProject(ev) {
        const query = ev.target.value.toLowerCase();

        if (!query) {
            this.state.filteredProjects = this.state.projects;
            return;
        }

        this.state.filteredProjects = this.state.projects.filter(project =>
            project.name.toLowerCase().includes(query)
        );
    }

    async fetchSprintsForProject(projectId, silent = false) {
        try {
            const sprints = await this.orm.searchRead(
                'project.scrum.sprint',
                [['project_id', '=', projectId]],
                ['id', 'name', 'state'],
                {
                    order: 'name asc',
                    context: { is_scrum_app: true }
                }
            );
            this.state.sprintsByProject[projectId] = sprints;
        } catch (e) {
            if (!silent) console.error("Error fetching sprints:", e);
        }
    }

    getStandardViewProps(resModel, viewType, context, actionKey = null) {
        const props = {
            resModel: resModel,
            type: viewType,
            context: context,
            views: [[false, viewType], [false, 'form'], [false, 'search']],
            loadActionMenus: true, // Crucial for rendering Gear/Action Menu
        };

        // Fix: Pass the action ID inside an 'action' object.
        if (actionKey && this.cachedActionIds[actionKey]) {
            props.action = {
                id: this.cachedActionIds[actionKey]
            };
        }

        return props;
    }

    getConfigListProps(resModel, titleName, context, actionKey, domain = []) {
        return {
            ...this.getStandardViewProps(resModel, 'list', context, actionKey),
            domain: domain,

            // Handle clicking an existing row to edit
            selectRecord: async (resId) => {
                let recordTitle = titleName;
                try {
                    const result = await this.orm.call(resModel, 'name_get', [[resId]]);
                    if (result && result.length) recordTitle = result[0][1];
                } catch (e) {}

                const formProps = { ...this.getStandardViewProps(resModel, 'form', context), resId: resId };
                const formKey = `${actionKey}_form_${resId}_${Date.now()}`;

                Object.assign(this.state, { activeKey: formKey, viewProps: formProps });
                this.pushToHistory(`${actionKey}_form`, recordTitle, resId, formProps, formKey, false);
            },

            // Handle clicking the "New" button
            createRecord: () => {
                const formProps = { ...this.getStandardViewProps(resModel, 'form', context), resId: false };
                const formKey = `${actionKey}_form_new_${Date.now()}`;

                Object.assign(this.state, { activeKey: formKey, viewProps: formProps });
                this.pushToHistory(`${actionKey}_form`, `New ${titleName}`, null, formProps, formKey, false);
            }
        };
    }

    // ==========================================
    // NAVIGATION METHODS
    // ==========================================

    /**
     * Opens a task form view inside the SPA.
     *
     * BREADCRUMB ENRICHMENT:
     *   Before pushing the task breadcrumb, we fetch the task's project
     *   and sprint context. If either is missing from the current breadcrumb
     *   chain, we inject it so the trail always reads:
     *       ... → Project Name → Sprint Name → Task Name
     */
    async openTask(taskId) {
        let taskName = "Task Details";
        let projectId = null;
        let projectName = null;
        let sprintId = null;
        let sprintName = null;

        try {
            const data = await this.orm.read(
                'project.task', [taskId],
                ['display_name', 'sprint_id', 'project_id']
            );
            if (data.length) {
                taskName = data[0].display_name || taskName;
                if (data[0].project_id) {
                    projectId = data[0].project_id[0];
                    projectName = data[0].project_id[1];
                }
                if (data[0].sprint_id) {
                    sprintId = data[0].sprint_id[0];
                    sprintName = data[0].sprint_id[1];
                }
            }
        } catch (e) {
            // Fallback: try name_get if read fails
            try {
                const result = await this.orm.call('project.task', 'name_get', [[taskId]]);
                if (result && result.length) taskName = result[0][1];
            } catch (_) {}
        }

        // Inject project context if missing from breadcrumb chain
        if (projectId && projectName) {
            this._injectProjectBreadcrumb(projectId, projectName);
        }

        // Inject sprint context if missing from breadcrumb chain
        if (sprintId && sprintName) {
            this._injectSprintBreadcrumb(sprintId, sprintName);
        }

        const appCtx = { is_scrum_app: true };
        const activeKey = `task_form_${taskId}_${Date.now()}`;
        const viewProps = {
            ...this.getStandardViewProps('project.task', 'form', appCtx),
            resId: taskId,
        };

        Object.assign(this.state, { activeKey, viewProps });
        this.pushToHistory('task_form', taskName, taskId, viewProps, activeKey, false);
        this.closeMobileSidebar();
    }

    /**
     * Opens the task Kanban Board for a specific Sprint.
     *
     * BREADCRUMB ENRICHMENT:
     *   Before pushing the sprint board breadcrumb, we fetch the sprint's
     *   project context. If the project is missing from the breadcrumb chain,
     *   we inject it so the trail always reads:
     *       ... → Project Name → Sprint Name
     */
    async openSprintBoard(sprintId) {
        let sprintName = "Sprint Board";
        let projectId = null;
        let projectName = null;

        try {
            const data = await this.orm.read(
                'project.scrum.sprint', [sprintId],
                ['name', 'project_id']
            );
            if (data.length) {
                sprintName = data[0].name || sprintName;
                if (data[0].project_id) {
                    projectId = data[0].project_id[0];
                    projectName = data[0].project_id[1];
                }
            }
        } catch (e) {
            // Fallback
            try {
                const result = await this.orm.call('project.scrum.sprint', 'name_get', [[sprintId]]);
                if (result && result.length) sprintName = result[0][1];
            } catch (_) {}
        }

        // Inject project context if missing from breadcrumb chain
        if (projectId && projectName) {
            this._injectProjectBreadcrumb(projectId, projectName);
        }

        const appCtx = {
            is_scrum_app: true,
            default_sprint_id: sprintId,
            search_default_sprint_id: sprintId
        };

        const activeKey = `sprint_board_${sprintId}_${Date.now()}`;
        const viewProps = {
            ...this.getStandardViewProps('project.task', 'kanban', appCtx),
            domain: [['sprint_id', '=', sprintId]],
            state: { groupBy: ['stage_id'] },
            selectRecord: (taskId) => this.openTask(taskId),
        };

        Object.assign(this.state, { activeKey, viewProps });
        this.pushToHistory('sprint_board', sprintName, sprintId, viewProps, activeKey, false);
        this.closeMobileSidebar();
    }

    async selectItem(key) {
        // Handle Sidebar Expanders first
        if (key === 'projects') {
            // If sidebar is collapsed on desktop, expand it so submenu is usable
            if (this.state.isSidebarCollapsed && !this.state.isMobile) {
                this.state.isSidebarCollapsed = false;
                try {
                    localStorage.setItem("scrum_sidebar_collapsed", "false");
                } catch (e) {}
            }
            this.state.activeKey = `projects_sidebar_tree_${Date.now()}`;
            this.state.isProjectsExpanded = !this.state.isProjectsExpanded;
            if (this.state.isProjectsExpanded) await this.fetchProjects();
            return;
        }

        // Handle Configuration Expansion
        if (key === 'config_menu') {
            if (this.state.isSidebarCollapsed && !this.state.isMobile) {
                this.state.isSidebarCollapsed = false;
                try {
                    localStorage.setItem("scrum_sidebar_collapsed", "false");
                } catch (e) {}
            }
            this.state.isConfigExpanded = !this.state.isConfigExpanded;
            return;
        }

        if (key === 'config_settings') {
            this.actionService.doAction({
                type: 'ir.actions.act_window', name: 'Settings', res_model: 'res.config.settings',
                views: [[false, 'form']], target: 'inline', context: { module: 'project', bin_size: false },
            });
            this.closeMobileSidebar();
            return;
        }

        const titles = {
            'dashboard': 'Dashboard',
            'projects_kanban': 'All Projects',
            'sprints': 'All Sprints',
            'active_tasks': 'Active Tasks',
            'backlog': 'Backlog',
            'releases': 'Releases',
            'config_projects': 'Projects',
            'config_task_stages': 'Task Stages',
            'config_stages': 'Project Stages',
            'config_sprint_stages': 'Sprint Stages',
            'config_dod_templates': 'DoD Templates',
            'config_story_points': 'Story Point Config',
            'config_activity_types': 'Activity Types',
            'config_activity_plans': 'Activity Plans',
            'config_tags': 'Tags'
        };
        const title = titles[key] || "Scrum App";

        const appCtx = { is_scrum_app: true };
        this.state.viewType = 'dashboard';
        this.state.activeProjectId = null;
        this.state.activeSprintId = null;
        this.state.activeProjectName = '';

        let viewProps = {};
        const activeKey = `${key}_${Date.now()}`;

        if (key === 'dashboard') {
            const dashboardId = await this.orm.call('scrum.dashboard', 'search', [[]], { limit: 1, context: appCtx });
            viewProps = {
                resModel: 'scrum.dashboard', type: 'form', resId: dashboardId[0] || false,
                context: appCtx, display: { controlPanel: false }, mode: 'readonly',
            };
        }
        else if (key === 'projects_kanban') {
            viewProps = {
                ...this.getStandardViewProps('project.project', 'kanban', { default_project_type: 'scrum', default_is_scrum_project: true, ...appCtx }, 'projects_kanban'),
                viewId: this.cachedViewIds.project_kanban || false,
                domain: [['project_type', '=', 'scrum']],

                selectRecord: async (resId) => {
                    let projectName = "Project Sprints";
                    try {
                        const result = await this.orm.call('project.project', 'name_get', [[resId]]);
                        if (result && result.length) projectName = result[0][1];
                    } catch (e) {}

                    this.state.activeProjectId = resId;
                    const nestedActiveKey = `sprints_project_${resId}_${Date.now()}`;

                    const sprintKanbanId = this.cachedViewIds.sprint_kanban || false;
                    const searchViewId = this.cachedViewIds.sprint_search_view || false;

                    const nestedProps = {
                        ...this.getStandardViewProps('project.scrum.sprint', 'kanban', {
                            default_project_id: resId,
                            search_default_group_by_stage_forced: 1,
                            ...appCtx
                        }),
                        viewId: sprintKanbanId,
                        searchViewId: searchViewId,
                        views: [[sprintKanbanId, 'kanban'], [false, 'form'], [searchViewId, 'search']],
                        state: { groupBy: ['stage_id'] },
                        domain: [['project_id', '=', resId]],
                        selectRecord: (sprintId) => this.openSprintBoard(sprintId),
                    };
                    Object.assign(this.state, { activeKey: nestedActiveKey, viewProps: nestedProps });
                    this.pushToHistory('sprints_project', projectName, resId, nestedProps, nestedActiveKey, false);
                },
            };
        }
        else if (key === 'sprints') {
            viewProps = {
                ...this.getStandardViewProps('project.scrum.sprint', 'list', { search_default_group_by_project: 1, ...appCtx }),
                domain: [['project_type', '=', 'scrum']],
                selectRecord: (sprintId) => this.openSprintBoard(sprintId),
            };
        }
        else if (key === 'active_tasks' || key === 'backlog') {
            const isBacklog = key === 'backlog';
            const targetViewId = isBacklog ? this.cachedViewIds.backlog_kanban : this.cachedViewIds.active_tasks_kanban;
            viewProps = {
                ...this.getStandardViewProps('project.task', 'kanban', { group_by: 'project_id', default_project_type: 'scrum', ...appCtx }),
                viewId: targetViewId || false,
                domain: [['project_id.project_type', '=', 'scrum'], ['sprint_id', isBacklog ? '=' : '!=', false]],
                selectRecord: (resId) => this.openTask(resId),
            };
        }
        else if (key === 'releases') {
            viewProps = {
                ...this.getStandardViewProps('project.scrum.release', 'list', appCtx),
                domain: [['project_id.project_type', '=', 'scrum']],
                selectRecord: async (resId) => {
                    let relTitle = "Release Details";
                    try {
                        const result = await this.orm.call('project.scrum.release', 'name_get', [[resId]]);
                        if (result && result.length) relTitle = result[0][1];
                    } catch (e) {}

                    const releaseProps = { ...this.getStandardViewProps('project.scrum.release', 'form', appCtx), resId: resId };
                    const releaseKey = `release_form_${resId}_${Date.now()}`;
                    Object.assign(this.state, { activeKey: releaseKey, viewProps: releaseProps });
                    this.pushToHistory('release_form', relTitle, resId, releaseProps, releaseKey, false);
                },
            };
        }

        // =========================================================
        // SMART CONFIGURATION LIST ROUTING
        // =========================================================
        else if (key === 'config_projects') { viewProps = this.getConfigListProps('project.project', 'Project', { 'default_project_type': 'scrum', 'default_is_scrum_project': true, ...appCtx }, 'config_projects', [['project_type', '=', 'scrum']]); }
        else if (key === 'config_task_stages') { viewProps = this.getConfigListProps('project.task.type', 'Task Stage', { 'default_project_type': 'scrum', ...appCtx }, 'config_task_stages'); }
        else if (key === 'config_stages') { viewProps = this.getConfigListProps('project.project.stage', 'Project Stage', { 'default_project_type': 'scrum', ...appCtx }, 'config_stages', [['project_type', '=', 'scrum']]); }
        else if (key === 'config_sprint_stages') { viewProps = this.getConfigListProps('project.scrum.sprint.stage', 'Sprint Stage', appCtx, 'config_sprint_stages'); }
        else if (key === 'config_dod_templates') { viewProps = this.getConfigListProps('project.scrum.dod.template', 'DoD Template', appCtx, 'config_dod_templates'); }
        else if (key === 'config_story_points') {
            const recordId = await this.orm.call('project.scrum.story.point.config', 'get_singleton_id', []);
            viewProps = {
                ...this.getStandardViewProps('project.scrum.story.point.config', 'form', appCtx),
                resId: recordId,
            };
        }
        else if (key === 'config_activity_types') { viewProps = this.getConfigListProps('mail.activity.type', 'Activity Type', appCtx, 'config_activity_types'); }
        else if (key === 'config_activity_plans') { viewProps = this.getConfigListProps('mail.activity.plan', 'Activity Plan', appCtx, 'config_activity_plans'); }
        else if (key === 'config_tags') { viewProps = this.getConfigListProps('project.tags', 'Tag', appCtx, 'config_tags'); }

        Object.assign(this.state, { activeKey, viewProps });
        this.pushToHistory(key, title, null, viewProps, activeKey, true);
        this.closeMobileSidebar();
    }

    async toggleProject(projectId, isSettings = false) {
        const appCtx = { is_scrum_app: true, active_id: projectId };

        this.state.activeSprintId = null;
        this.state.activeProjectId = projectId;

        if (this.state.projects.length === 0) await this.fetchProjects();
        const project = this.state.projects.find(p => p.id === projectId);
        this.state.activeProjectName = project ? project.name : 'Project';

        if (this.state.expandedProjectId !== projectId) {
            this.state.expandedProjectId = projectId;
            await this.fetchSprintsForProject(projectId);
        }
        this.state.isProjectsExpanded = true;

        let title = this.state.activeProjectName;
        let viewProps = {};
        const activeKey = `project_nav_${projectId}_${Date.now()}`;

        if (isSettings) {
            title += " Settings";
            viewProps = { ...this.getStandardViewProps('project.project', 'form', appCtx), resId: projectId };
        } else {
            try {
                const dashboardId = await this.orm.call('scrum.project.dashboard', 'compute_dashboard_data', [projectId], { context: appCtx });
                viewProps = {
                    resModel: 'scrum.project.dashboard', type: 'form', resId: dashboardId,
                    context: appCtx, display: { controlPanel: false }, mode: 'readonly',
                };
            } catch (e) {
                console.error("Project Dashboard failed to load:", e);
            }
        }

        Object.assign(this.state, { activeKey, viewProps });
        this.pushToHistory('project_dashboard', title, projectId, viewProps, activeKey, true);
        this.closeMobileSidebar();
    }

    /**
     * Opens a Sprint form view (from sidebar sprint links).
     *
     * BREADCRUMB ENRICHMENT:
     *   Fetches the sprint's project context and injects it if missing,
     *   so the trail reads: ... → Project Name → Sprint Name
     *   (The project is normally already there from toggleProject, but
     *    this guards against edge cases.)
     */
    async selectSprint(sprintId) {
        let sprintName = "Sprint Details";
        let projectId = null;
        let projectName = null;

        try {
            const data = await this.orm.read(
                'project.scrum.sprint', [sprintId],
                ['name', 'project_id']
            );
            if (data.length) {
                sprintName = data[0].name || sprintName;
                if (data[0].project_id) {
                    projectId = data[0].project_id[0];
                    projectName = data[0].project_id[1];
                }
            }
        } catch (e) {
            try {
                const result = await this.orm.call('project.scrum.sprint', 'name_get', [[sprintId]]);
                if (result && result.length) sprintName = result[0][1];
            } catch (_) {}
        }

        const appCtx = { is_scrum_app: true };
        this.state.activeSprintId = sprintId;

        // Inject project context if missing (guards sidebar direct-click edge cases)
        if (projectId && projectName) {
            this._injectProjectBreadcrumb(projectId, projectName);
        }

        const activeKey = `sprint_form_${sprintId}_${Date.now()}`;
        const viewProps = { ...this.getStandardViewProps('project.scrum.sprint', 'form', appCtx), resId: sprintId };

        Object.assign(this.state, { activeKey, viewProps });
        this.pushToHistory('sprint_form', sprintName, sprintId, viewProps, activeKey, false);
        this.closeMobileSidebar();
    }
}

ScrumClientAction.template = "scrum_management.ScrumClientAction";

// Register the VelocityChart and BurndownChart components alongside the standard View
ScrumClientAction.components = { View, VelocityChart, BurndownChart };

registry.category("actions").add("scrum_management.scrum_client_action", ScrumClientAction);












































// /** @odoo-module */
//
// import { registry } from "@web/core/registry";
// import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
// import { View } from "@web/views/view";
// import { useService } from "@web/core/utils/hooks";
//
// // Import the Velocity Chart component
// import { VelocityChart } from "@scrum_management/js/velocity_chart";
// // Import the Burndown Chart component
// import { BurndownChart } from "@scrum_management/js/burndown_chart";
//
// class ScrumClientAction extends Component {
//     setup() {
//         this.actionService = useService("action");
//         this.orm = useService("orm");
//
//         this.state = useState({
//             activeKey: `dashboard_main_${Date.now()}`,
//             viewProps: {},
//             isProjectsExpanded: false,
//             isConfigExpanded: true, // Configuration menu is visible on load
//
//             projects: [],
//
//             filteredProjects: [],
//
//             expandedProjectId: null,
//             sprintsByProject: {},
//             activeProjectId: null,
//             activeProjectName: '',
//             activeSprintId: null,
//             viewType: 'dashboard',
//
//             // Internal history stack for custom XML breadcrumbs and navigation
//             navHistory: [],
//
//             // ===== Sidebar responsive state =====
//             isSidebarCollapsed: this.getInitialCollapseState(),
//             isMobile: window.innerWidth < 768,
//             isMobileSidebarOpen: false,
//         });
//
//         this.cachedViewIds = {};
//         this.cachedActionIds = {}; // Stores real Action IDs for Control Panel gear menu
//
//         // Listen to the browser's physical back/forward buttons
//         this.onPopState = this.onPopState.bind(this);
//         window.addEventListener("popstate", this.onPopState);
//
//         // Listen to window resize for responsive behavior
//         this.onWindowResize = this.onWindowResize.bind(this);
//         window.addEventListener("resize", this.onWindowResize);
//
//         onWillStart(async () => {
//             try {
//                 this.cachedViewIds = await this.orm.call('project.project', 'get_scrum_view_ids', []);
//             } catch (e) {
//                 console.error("Failed to fetch Scrum View IDs from server:", e);
//             }
//
//             // Fetch Real Action IDs for the Action Menus (Export/Delete)
//             await this.fetchActionIds();
//
//             const params = this.props.action.params || {};
//             if (params.project_id) {
//                 if (params.view_type === 'settings') {
//                     await this.toggleProject(params.project_id, true);
//                 } else {
//                     await this.toggleProject(params.project_id);
//                 }
//             } else {
//                 await this.selectItem('dashboard');
//             }
//         });
//
//         this.refreshInterval = setInterval(() => {
//             if (this.state.expandedProjectId) {
//                 this.fetchSprintsForProject(this.state.expandedProjectId, true);
//             }
//         }, 15000);
//
//         onWillDestroy(() => {
//             if (this.refreshInterval) clearInterval(this.refreshInterval);
//             window.removeEventListener("popstate", this.onPopState);
//             window.removeEventListener("resize", this.onWindowResize);
//         });
//     }
//
//     // ==========================================
//     // SIDEBAR RESPONSIVE / COLLAPSE LOGIC
//     // ==========================================
//
//     getInitialCollapseState() {
//         try {
//             const saved = localStorage.getItem("scrum_sidebar_collapsed");
//             if (saved !== null) return saved === "true";
//         } catch (e) {}
//         // Default: collapsed on smaller screens, expanded on large
//         return window.innerWidth < 1024;
//     }
//
//     toggleSidebar() {
//         if (this.state.isMobile) {
//             this.state.isMobileSidebarOpen = !this.state.isMobileSidebarOpen;
//         } else {
//             this.state.isSidebarCollapsed = !this.state.isSidebarCollapsed;
//             try {
//                 localStorage.setItem("scrum_sidebar_collapsed", this.state.isSidebarCollapsed);
//             } catch (e) {}
//             // When collapsing, close any expanded submenus for a clean look
//             if (this.state.isSidebarCollapsed) {
//                 this.state.isProjectsExpanded = false;
//                 this.state.isConfigExpanded = false;
//             }
//         }
//     }
//
//     closeMobileSidebar() {
//         if (this.state.isMobile) {
//             this.state.isMobileSidebarOpen = false;
//         }
//     }
//
//     onWindowResize() {
//         const wasMobile = this.state.isMobile;
//         this.state.isMobile = window.innerWidth < 768;
//         // Close mobile drawer when transitioning back to desktop
//         if (wasMobile && !this.state.isMobile) {
//             this.state.isMobileSidebarOpen = false;
//         }
//     }
//
//     // ==========================================
//     // CUSTOM ROUTING & BREADCRUMB ENGINE
//     // ==========================================
//
//     pushToHistory(key, title, resId, viewProps, activeKey, isRoot = false) {
//         // Prevent consecutive duplicate pushes
//         const last = this.state.navHistory[this.state.navHistory.length - 1];
//         if (last && last.key === key && last.resId === resId) return;
//
//         // Clicking a main sidebar item clears the breadcrumb trail to start fresh
//         if (isRoot) {
//             this.state.navHistory = [];
//         }
//
//         // Push state to our internal stack (Read by the XML template for breadcrumbs)
//         this.state.navHistory.push({ key, title, resId, viewProps, activeKey });
//
//         // Push generic state to the browser to enable the physical 'Back' button
//         window.history.pushState({ scrumSPA: Date.now() }, "");
//     }
//
//     onPopState(event) {
//         // Handle physical back/forward browser buttons
//         if (this.state.navHistory.length > 1) {
//             this.state.navHistory.pop(); // Remove current view
//             const previous = this.state.navHistory[this.state.navHistory.length - 1];
//             if (previous) this.restoreHistoryState(previous);
//         } else {
//             // If we back out of the SPA entirely
//             this.actionService.doAction('cancel');
//         }
//     }
//
//     goToHistoryIndex(index) {
//         // Handle clicks directly on the XML Breadcrumbs
//         if (index < 0 || index >= this.state.navHistory.length) return;
//         const target = this.state.navHistory[index];
//         // Trim future history stack
//         this.state.navHistory = this.state.navHistory.slice(0, index + 1);
//         this.restoreHistoryState(target);
//     }
//
//     restoreHistoryState(step) {
//         Object.assign(this.state, {
//             activeKey: step.activeKey,
//             viewProps: step.viewProps
//         });
//     }
//
//     // ==========================================
//     // DATA FETCHING & HELPER PROPS
//     // ==========================================
//
//     async fetchActionIds() {
//         const mapping = {
//             'config_projects': 'project.open_view_project_all',
//             'config_task_stages': 'scrum_management.action_scrum_task_stages',
//             'config_stages': 'scrum_management.action_scrum_project_stages',
//             'config_sprint_stages': 'scrum_management.action_scrum_sprint_stages',
//             'config_dod_templates': 'scrum_management.action_scrum_dod_template',
//             'config_tags': 'project.project_tags_action',
//             'config_activity_types': 'mail.mail_activity_type_action',
//             'config_activity_plans': 'mail.mail_activity_plan_action',
//             'projects_kanban': 'project.open_view_project_all'
//         };
//
//         const promises = Object.entries(mapping).map(async ([key, xmlId]) => {
//             try {
//                 const resId = await this.orm.call('ir.model.data', 'xmlid_to_res_id', [xmlId]);
//                 if (resId) {
//                     this.cachedActionIds[key] = resId;
//                 }
//             } catch (e) {
//                 console.warn(`Could not fetch action ID for ${xmlId}`, e);
//             }
//         });
//
//         await Promise.all(promises);
//     }
//
//     async fetchProjects() {
//         try {
//             const projects = await this.orm.searchRead(
//                 'project.project',
//                 [['project_type', '=', 'scrum']],
//                 ['id', 'name'],
//                 { context: { is_scrum_app: true } }
//             );
//             this.state.projects = projects;
//             this.state.filteredProjects = projects;
//         } catch (e) {
//             console.error("Error fetching projects:", e);
//         }
//     }
//
//
//     // ==========================================
//     // 🔍 SEARCH FUNCTION
//     // ==========================================
//     onSearchProject(ev) {
//         const query = ev.target.value.toLowerCase();
//
//         if (!query) {
//             this.state.filteredProjects = this.state.projects;
//             return;
//         }
//
//         this.state.filteredProjects = this.state.projects.filter(project =>
//             project.name.toLowerCase().includes(query)
//         );
//     }
//
//     async fetchSprintsForProject(projectId, silent = false) {
//         try {
//             const sprints = await this.orm.searchRead(
//                 'project.scrum.sprint',
//                 [['project_id', '=', projectId]],
//                 ['id', 'name', 'state'],
//                 {
//                     order: 'name asc',
//                     context: { is_scrum_app: true }
//                 }
//             );
//             this.state.sprintsByProject[projectId] = sprints;
//         } catch (e) {
//             if (!silent) console.error("Error fetching sprints:", e);
//         }
//     }
//
//     getStandardViewProps(resModel, viewType, context, actionKey = null) {
//         const props = {
//             resModel: resModel,
//             type: viewType,
//             context: context,
//             views: [[false, viewType], [false, 'form'], [false, 'search']],
//             loadActionMenus: true, // Crucial for rendering Gear/Action Menu
//         };
//
//         // Fix: Pass the action ID inside an 'action' object.
//         if (actionKey && this.cachedActionIds[actionKey]) {
//             props.action = {
//                 id: this.cachedActionIds[actionKey]
//             };
//         }
//
//         return props;
//     }
//
//     getConfigListProps(resModel, titleName, context, actionKey, domain = []) {
//         return {
//             ...this.getStandardViewProps(resModel, 'list', context, actionKey),
//             domain: domain,
//
//             // Handle clicking an existing row to edit
//             selectRecord: async (resId) => {
//                 let recordTitle = titleName;
//                 try {
//                     const result = await this.orm.call(resModel, 'name_get', [[resId]]);
//                     if (result && result.length) recordTitle = result[0][1];
//                 } catch (e) {}
//
//                 const formProps = { ...this.getStandardViewProps(resModel, 'form', context), resId: resId };
//                 const formKey = `${actionKey}_form_${resId}_${Date.now()}`;
//
//                 Object.assign(this.state, { activeKey: formKey, viewProps: formProps });
//                 this.pushToHistory(`${actionKey}_form`, recordTitle, resId, formProps, formKey, false);
//             },
//
//             // Handle clicking the "New" button
//             createRecord: () => {
//                 const formProps = { ...this.getStandardViewProps(resModel, 'form', context), resId: false };
//                 const formKey = `${actionKey}_form_new_${Date.now()}`;
//
//                 Object.assign(this.state, { activeKey: formKey, viewProps: formProps });
//                 this.pushToHistory(`${actionKey}_form`, `New ${titleName}`, null, formProps, formKey, false);
//             }
//         };
//     }
//
//     // ==========================================
//     // NAVIGATION METHODS
//     // ==========================================
//
//     async openTask(taskId) {
//         let title = "Task Details";
//         try {
//             const result = await this.orm.call('project.task', 'name_get', [[taskId]]);
//             if (result && result.length) title = result[0][1];
//         } catch (e) {}
//
//         const appCtx = { is_scrum_app: true };
//         const activeKey = `task_form_${taskId}_${Date.now()}`;
//         const viewProps = {
//             ...this.getStandardViewProps('project.task', 'form', appCtx),
//             resId: taskId,
//         };
//
//         Object.assign(this.state, { activeKey, viewProps });
//         this.pushToHistory('task_form', title, taskId, viewProps, activeKey, false);
//         this.closeMobileSidebar();
//     }
//
//     // Opens the Kanban Board for a specific Sprint natively in the SPA
//     async openSprintBoard(sprintId) {
//         let title = "Sprint Board";
//         try {
//             const result = await this.orm.call('project.scrum.sprint', 'name_get', [[sprintId]]);
//             if (result && result.length) title = `${result[0][1]} Tasks`;
//         } catch (e) {}
//
//         const appCtx = {
//             is_scrum_app: true,
//             default_sprint_id: sprintId,
//             search_default_sprint_id: sprintId
//         };
//
//         const activeKey = `sprint_board_${sprintId}_${Date.now()}`;
//         const viewProps = {
//             ...this.getStandardViewProps('project.task', 'kanban', appCtx),
//             domain: [['sprint_id', '=', sprintId]],
//             state: { groupBy: ['stage_id'] },
//             selectRecord: (taskId) => this.openTask(taskId),
//         };
//
//         Object.assign(this.state, { activeKey, viewProps });
//         this.pushToHistory('sprint_board', title, sprintId, viewProps, activeKey, false);
//         this.closeMobileSidebar();
//     }
//
//     async selectItem(key) {
//         // Handle Sidebar Expanders first
//         if (key === 'projects') {
//             // If sidebar is collapsed on desktop, expand it so submenu is usable
//             if (this.state.isSidebarCollapsed && !this.state.isMobile) {
//                 this.state.isSidebarCollapsed = false;
//                 try {
//                     localStorage.setItem("scrum_sidebar_collapsed", "false");
//                 } catch (e) {}
//             }
//             this.state.activeKey = `projects_sidebar_tree_${Date.now()}`;
//             this.state.isProjectsExpanded = !this.state.isProjectsExpanded;
//             if (this.state.isProjectsExpanded) await this.fetchProjects();
//             return;
//         }
//
//         // Handle Configuration Expansion
//         if (key === 'config_menu') {
//             if (this.state.isSidebarCollapsed && !this.state.isMobile) {
//                 this.state.isSidebarCollapsed = false;
//                 try {
//                     localStorage.setItem("scrum_sidebar_collapsed", "false");
//                 } catch (e) {}
//             }
//             this.state.isConfigExpanded = !this.state.isConfigExpanded;
//             return;
//         }
//
//         if (key === 'config_settings') {
//             this.actionService.doAction({
//                 type: 'ir.actions.act_window', name: 'Settings', res_model: 'res.config.settings',
//                 views: [[false, 'form']], target: 'inline', context: { module: 'project', bin_size: false },
//             });
//             this.closeMobileSidebar();
//             return;
//         }
//
//         const titles = {
//             'dashboard': 'Global Dashboard', 'projects_kanban': 'All Projects', 'sprints': 'Global Sprints',
//             'active_tasks': 'Active Tasks', 'backlog': 'Global Backlog', 'releases': 'Releases',
//             'config_projects': 'Projects Config',
//             'config_task_stages': 'Task Stages',
//             'config_stages': 'Project Stages',
//             'config_sprint_stages': 'Sprint Stages', 'config_dod_templates': 'DoD Templates',
//             'config_story_points': 'Story Point Config',
//             'config_activity_types': 'Activity Types',
//             'config_activity_plans': 'Activity Plans', 'config_tags': 'Tags Config'
//         };
//         const title = titles[key] || "Scrum App";
//
//         const appCtx = { is_scrum_app: true };
//         this.state.viewType = 'dashboard';
//         this.state.activeProjectId = null;
//         this.state.activeSprintId = null;
//         this.state.activeProjectName = '';
//
//         let viewProps = {};
//         const activeKey = `${key}_${Date.now()}`;
//
//         if (key === 'dashboard') {
//             const dashboardId = await this.orm.call('scrum.dashboard', 'search', [[]], { limit: 1, context: appCtx });
//             viewProps = {
//                 resModel: 'scrum.dashboard', type: 'form', resId: dashboardId[0] || false,
//                 context: appCtx, display: { controlPanel: false }, mode: 'readonly',
//             };
//         }
//         else if (key === 'projects_kanban') {
//             viewProps = {
//                 ...this.getStandardViewProps('project.project', 'kanban', { default_project_type: 'scrum', default_is_scrum_project: true, ...appCtx }, 'projects_kanban'),
//                 viewId: this.cachedViewIds.project_kanban || false,
//                 domain: [['project_type', '=', 'scrum']],
//
//                 selectRecord: async (resId) => {
//                     let projectName = "Project Sprints";
//                     try {
//                         const result = await this.orm.call('project.project', 'name_get', [[resId]]);
//                         if (result && result.length) projectName = result[0][1];
//                     } catch (e) {}
//
//                     this.state.activeProjectId = resId;
//                     const nestedActiveKey = `sprints_project_${resId}_${Date.now()}`;
//
//                     const sprintKanbanId = this.cachedViewIds.sprint_kanban || false;
//                     const searchViewId = this.cachedViewIds.sprint_search_view || false;
//
//                     const nestedProps = {
//                         ...this.getStandardViewProps('project.scrum.sprint', 'kanban', {
//                             default_project_id: resId,
//                             search_default_group_by_stage_forced: 1,
//                             ...appCtx
//                         }),
//                         viewId: sprintKanbanId,
//                         searchViewId: searchViewId,
//                         views: [[sprintKanbanId, 'kanban'], [false, 'form'], [searchViewId, 'search']],
//                         state: { groupBy: ['stage_id'] },
//                         domain: [['project_id', '=', resId]],
//                         selectRecord: (sprintId) => this.openSprintBoard(sprintId),
//                     };
//                     Object.assign(this.state, { activeKey: nestedActiveKey, viewProps: nestedProps });
//                     this.pushToHistory('sprints_project', projectName, resId, nestedProps, nestedActiveKey, false);
//                 },
//             };
//         }
//         else if (key === 'sprints') {
//             viewProps = {
//                 ...this.getStandardViewProps('project.scrum.sprint', 'list', { search_default_group_by_project: 1, ...appCtx }),
//                 domain: [['project_type', '=', 'scrum']],
//                 selectRecord: (sprintId) => this.openSprintBoard(sprintId),
//             };
//         }
//         else if (key === 'active_tasks' || key === 'backlog') {
//             const isBacklog = key === 'backlog';
//             const targetViewId = isBacklog ? this.cachedViewIds.backlog_kanban : this.cachedViewIds.active_tasks_kanban;
//             viewProps = {
//                 ...this.getStandardViewProps('project.task', 'kanban', { group_by: 'project_id', default_project_type: 'scrum', ...appCtx }),
//                 viewId: targetViewId || false,
//                 domain: [['project_id.project_type', '=', 'scrum'], ['sprint_id', isBacklog ? '=' : '!=', false]],
//                 selectRecord: (resId) => this.openTask(resId),
//             };
//         }
//         else if (key === 'releases') {
//             viewProps = {
//                 ...this.getStandardViewProps('project.scrum.release', 'list', appCtx),
//                 domain: [['project_id.project_type', '=', 'scrum']],
//                 selectRecord: async (resId) => {
//                     let relTitle = "Release Details";
//                     try {
//                         const result = await this.orm.call('project.scrum.release', 'name_get', [[resId]]);
//                         if (result && result.length) relTitle = result[0][1];
//                     } catch (e) {}
//
//                     const releaseProps = { ...this.getStandardViewProps('project.scrum.release', 'form', appCtx), resId: resId };
//                     const releaseKey = `release_form_${resId}_${Date.now()}`;
//                     Object.assign(this.state, { activeKey: releaseKey, viewProps: releaseProps });
//                     this.pushToHistory('release_form', relTitle, resId, releaseProps, releaseKey, false);
//                 },
//             };
//         }
//
//         // =========================================================
//         // SMART CONFIGURATION LIST ROUTING
//         // =========================================================
//         else if (key === 'config_projects') { viewProps = this.getConfigListProps('project.project', 'Project', { 'default_project_type': 'scrum', 'default_is_scrum_project': true, ...appCtx }, 'config_projects', [['project_type', '=', 'scrum']]); }
//         else if (key === 'config_task_stages') { viewProps = this.getConfigListProps('project.task.type', 'Task Stage', { 'default_project_type': 'scrum', ...appCtx }, 'config_task_stages'); }
//         else if (key === 'config_stages') { viewProps = this.getConfigListProps('project.project.stage', 'Project Stage', { 'default_project_type': 'scrum', ...appCtx }, 'config_stages', [['project_type', '=', 'scrum']]); }
//         else if (key === 'config_sprint_stages') { viewProps = this.getConfigListProps('project.scrum.sprint.stage', 'Sprint Stage', appCtx, 'config_sprint_stages'); }
//         else if (key === 'config_dod_templates') { viewProps = this.getConfigListProps('project.scrum.dod.template', 'DoD Template', appCtx, 'config_dod_templates'); }
//         else if (key === 'config_story_points') {
//             const recordId = await this.orm.call('project.scrum.story.point.config', 'get_singleton_id', []);
//             viewProps = {
//                 ...this.getStandardViewProps('project.scrum.story.point.config', 'form', appCtx),
//                 resId: recordId,
// //                display: { controlPanel: true },
//             };
//         }
//         else if (key === 'config_activity_types') { viewProps = this.getConfigListProps('mail.activity.type', 'Activity Type', appCtx, 'config_activity_types'); }
//         else if (key === 'config_activity_plans') { viewProps = this.getConfigListProps('mail.activity.plan', 'Activity Plan', appCtx, 'config_activity_plans'); }
//         else if (key === 'config_tags') { viewProps = this.getConfigListProps('project.tags', 'Tag', appCtx, 'config_tags'); }
//
//         Object.assign(this.state, { activeKey, viewProps });
//         this.pushToHistory(key, title, null, viewProps, activeKey, true);
//         this.closeMobileSidebar();
//     }
//
//     async toggleProject(projectId, isSettings = false) {
//         const appCtx = { is_scrum_app: true, active_id: projectId };
//
//         this.state.activeSprintId = null;
//         this.state.activeProjectId = projectId;
//
//         if (this.state.projects.length === 0) await this.fetchProjects();
//         const project = this.state.projects.find(p => p.id === projectId);
//         this.state.activeProjectName = project ? project.name : 'Project';
//
//         if (this.state.expandedProjectId !== projectId) {
//             this.state.expandedProjectId = projectId;
//             await this.fetchSprintsForProject(projectId);
//         }
//         this.state.isProjectsExpanded = true;
//
//         let title = this.state.activeProjectName;
//         let viewProps = {};
//         const activeKey = `project_nav_${projectId}_${Date.now()}`;
//
//         if (isSettings) {
//             title += " Settings";
//             viewProps = { ...this.getStandardViewProps('project.project', 'form', appCtx), resId: projectId };
//         } else {
//             try {
//                 const dashboardId = await this.orm.call('scrum.project.dashboard', 'compute_dashboard_data', [projectId], { context: appCtx });
//                 viewProps = {
//                     resModel: 'scrum.project.dashboard', type: 'form', resId: dashboardId,
//                     context: appCtx, display: { controlPanel: false }, mode: 'readonly',
//                 };
//             } catch (e) {
//                 console.error("Project Dashboard failed to load:", e);
//             }
//         }
//
//         Object.assign(this.state, { activeKey, viewProps });
//         this.pushToHistory('project_dashboard', title, projectId, viewProps, activeKey, true);
//         this.closeMobileSidebar();
//     }
//
//     // Still available internally if needed via sidebar or other deep links
//     async selectSprint(sprintId) {
//         let title = "Sprint Details";
//         try {
//             const result = await this.orm.call('project.scrum.sprint', 'name_get', [[sprintId]]);
//             if (result && result.length) title = result[0][1];
//         } catch (e) {}
//
//         const appCtx = { is_scrum_app: true };
//         this.state.activeSprintId = sprintId;
//
//         const activeKey = `sprint_form_${sprintId}_${Date.now()}`;
//         const viewProps = { ...this.getStandardViewProps('project.scrum.sprint', 'form', appCtx), resId: sprintId };
//
//         Object.assign(this.state, { activeKey, viewProps });
//         this.pushToHistory('sprint_form', title, sprintId, viewProps, activeKey, false);
//         this.closeMobileSidebar();
//     }
// }
//
// ScrumClientAction.template = "scrum_management.ScrumClientAction";
//
// // Register the VelocityChart and BurndownChart components alongside the standard View
// ScrumClientAction.components = { View, VelocityChart, BurndownChart };
//
// registry.category("actions").add("scrum_management.scrum_client_action", ScrumClientAction);