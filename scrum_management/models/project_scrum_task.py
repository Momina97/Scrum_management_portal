# -*- coding: utf-8 -*-

from odoo import models, fields, api, Command, _

from odoo.exceptions import ValidationError, AccessError

from odoo.osv import expression

from dateutil.relativedelta import relativedelta

from markupsafe import Markup

import logging

_logger = logging.getLogger(__name__)


# --- HELPER UTILITY ---

def get_period_start_date(period):
    """ Standardizes date filtering across the module. """

    today = fields.Date.today()

    if period == 'week':
        return today - relativedelta(days=today.weekday())

    if period == 'month':
        return today.replace(day=1)

    if period == 'quarter':
        current_month = today.month

        start_month = ((current_month - 1) // 3) * 3 + 1

        return today.replace(month=start_month, day=1)

    if period == 'year':
        return today.replace(month=1, day=1)

    return today


class Task(models.Model):
    """

    Inheriting project.task to inject Agile estimation and planning logic.

    Provides strict Scrum workflow enforcement and App Isolation.

    """

    _inherit = 'project.task'

    # ? REQUIRED FOR TREE HIERARCHY

    _parent_name = "parent_id"

    _parent_store = True

    parent_path = fields.Char(index=True)

    allocated_time = fields.Float(

        string="Allocated Time",

        default=0.0,

    )

    spent_time = fields.Float(

        string="Spent Time (Hours)"

    )

    # ==========================================

    # ? ROW NUMBER FIELD

    # ==========================================

    row_number = fields.Integer(

        string="#",

        compute="_compute_row_number",

        store=False

    )

    @api.depends()
    def _compute_row_number(self):

        for index, record in enumerate(self, start=1):
            record.row_number = index

    def _get_root_tasks(self):

        tasks = self

        while tasks.filtered(lambda t: t.parent_id):
            tasks = tasks.mapped('parent_id')

        return tasks

    # --- SCRUM FIELDS ---

    # RESTORED: Compute and Inverse logic for subtask syncing

    sprint_id = fields.Many2one(

        'project.scrum.sprint',

        string='Sprint',

        compute='_compute_sprint_id',

        inverse='_inverse_sprint_id',

        recursive=True,

        store=True,

        domain="[('project_id', '=', project_id), ('state', '!=', 'completed')]",

        tracking=True,

        group_expand='_read_group_sprint_id',

        help="The Scrum Sprint this task is currently assigned to."

    )

    # 1. REVERTED: Back to an Integer to protect dashboard math

    story_points = fields.Integer(

        string="Story Points",

        help="Underlying mathematical field."

    )

    # 2. NEW FIELD: The UI Dropdown (String keys prevent the Odoo Validation Error)

    story_point_selection = fields.Selection([

        ('1', '1 SP'),

        ('2', '2 SP'),

        ('3', '3 SP'),

        ('5', '5 SP'),

        ('8', '8 SP'),

        ('13', '13 SP')

    ], string="Story Points", compute="_compute_sp_selection", inverse="_inverse_sp_selection", store=True)

    blocked_by_ids = fields.Many2many(

        'project.task',

        'project_task_blocked_rel',

        'task_id',

        'blocked_id',

        string='Blocked By',

        domain="[('project_id', '=', project_id), ('id', '!=', id)]",

        help="Tasks that must be completed before this task can be closed."

    )

    project_type = fields.Selection(

        related='project_id.project_type',

        string="Project Workflow Type",

        store=True,

        readonly=True

    )

    is_scrum_project = fields.Boolean(

        related='project_id.is_scrum_project',

        string="Is a Scrum Project Task",

        store=True,

        help="Technical field used for filtering views and logic."

    )

    assigned_by_id = fields.Many2one(

        'res.users',

        string="Assigned By",

        default=lambda self: self.env.user,

        tracking=True

    )

    # RESTORED: Subtask strict relations from File B

    subtask_count = fields.Integer(string="Subtasks", compute="_compute_subtask_counts", store=True)

    closed_subtask_count = fields.Integer(string="Closed Subtasks", compute="_compute_subtask_counts", store=True)

    subtask_ids = fields.One2many('project.task', 'parent_id', string="Subtasks (Strict)")

    subtask_count_display = fields.Char(

        string="Subtasks Label",

        compute="_compute_subtask_count_display"

    )

    expand_ui = fields.Char(

        string="Expand UI",

        compute="_compute_expand_ui"

    )

    def _compute_expand_ui(self):

        for rec in self:
            rec.expand_ui = rec.name or ""

    def expand_js(self):

        return True

    # ==========================================

    # count to display

    # ==========================================

    @api.depends('child_ids')
    def _compute_subtask_count_display(self):

        for rec in self:
            rec.subtask_count_display = f"Sub-tasks ({len(rec.child_ids)})"

    # ==========================================

    # ? STORY POINT SYNC & AUTOMATION

    # ==========================================

    @api.depends('story_points')
    def _compute_sp_selection(self):

        """ Keeps the dropdown synced if the integer changes (e.g., via backend/API) """

        for task in self:

            if task.story_points in [1, 2, 3, 5, 8, 13]:

                task.story_point_selection = str(task.story_points)

            else:

                task.story_point_selection = False

    def _inverse_sp_selection(self):
        """
        Safely assigns values directly to the ORM cache.
        Using .write() here causes data loss in modern Odoo.
        """
        for task in self:
            if task.story_point_selection:
                task.story_points = int(task.story_point_selection)
            else:
                task.story_points = 0

    @api.onchange('story_point_selection')
    def _onchange_story_point_selection_allocate_time(self):
        """ Rule 1: User picks SP → snap hours to that SP's MAX.

            Cascade-safe: if the current hours already map to the selected SP
            (meaning this onchange was triggered by the hours-typing cascade),
            we leave hours alone. The user's typed value wins.
        """
        if self.story_point_selection:
            self.story_points = int(self.story_point_selection)

            # Determine current hours (handle both possible fields)
            current_hours = self.allocated_time
            if hasattr(self,
                       'allocated_hours') and self.allocated_hours and self.allocated_hours != self.allocated_time:
                current_hours = self.allocated_hours

            # Check if current hours already belong to the selected SP's band.
            # If YES → this is a cascade from hours_onchange → don't touch hours.
            # If NO  → user picked SP directly → overwrite hours to SP's MAX.
            current_band_sp = self.env['project.scrum.story.point.config'].compute_sp_from_hours(current_hours)

            if current_band_sp != self.story_point_selection:
                config_vals = self.env['project.scrum.story.point.config'].get_sp_configuration()
                hours = config_vals.get(self.story_point_selection, 0.0)
                self.allocated_time = hours
                if hasattr(self, 'allocated_hours'):
                    self.allocated_hours = hours
        else:
            self.story_points = 0
            self.allocated_time = 0.0
            if hasattr(self, 'allocated_hours'):
                self.allocated_hours = 0.0

    @api.onchange('allocated_time', 'allocated_hours')
    def _onchange_allocated_time_assign_sp(self):
        """ Rule 2: User types hours → assign matching SP → preserve typed hours. """
        hours = self.allocated_time
        if hasattr(self, 'allocated_hours') and self.allocated_hours and self.allocated_hours != self.allocated_time:
            hours = self.allocated_hours
            self.allocated_time = hours

        if hours <= 0:
            self.story_point_selection = False
            self.story_points = 0
            if hasattr(self, 'allocated_hours'):
                self.allocated_hours = 0.0
            return

        computed_sp = self.env['project.scrum.story.point.config'].compute_sp_from_hours(hours)

        if computed_sp != '0':
            self.story_point_selection = computed_sp
            self.story_points = int(computed_sp)
        else:
            self.story_point_selection = False
            self.story_points = 0

        if hasattr(self, 'allocated_hours'):
            self.allocated_hours = hours

    # strict subtask gain

    # ==========================================

    @api.model
    def get_subtasks_strict(self, task_id):

        tasks = self.search([('parent_id', '=', task_id)])

        result = []

        for t in tasks:
            result.append({

                'id': t.id,

                'name': t.name,

                'stage_name': t.stage_id.name if t.stage_id else '',

                'children': self.get_subtasks_strict(t.id)

            })

        return result

    # ==========================================

    # ? COMPUTE & HELPER METHODS (RESTORED)

    # ==========================================

    @api.depends('parent_id.sprint_id')
    def _compute_sprint_id(self):

        for task in self:

            if task.parent_id:
                task.sprint_id = task.parent_id.sprint_id

    def _inverse_sprint_id(self):

        for task in self:

            if task.parent_id:
                task.sprint_id = task.parent_id.sprint_id

    def get_direct_subtasks(self):

        self.ensure_one()

        return self.env['project.task'].search([('parent_id', '=', self.id)])

    @api.depends('child_ids', 'child_ids.is_closed')
    def _compute_subtask_counts(self):

        grouped = self.env['project.task'].read_group(
            [('parent_id', 'in', self.ids)],
            ['parent_id'],
            ['parent_id']
        )

        count_map = {
            g['parent_id'][0]: g['parent_id_count']
            for g in grouped
        }

        for task in self:
            task.subtask_count = count_map.get(task.id, 0)

            task.closed_subtask_count = len(
                task.child_ids.filtered(lambda t: t.is_closed)
            )
    # ===========================================================

    # ? FIX: DYNAMIC DEFAULT STAGE (Forces rendering in Popups)

    # ===========================================================

    @api.model
    def default_get(self, fields_list):

        """

        Ensure 'stage_id' is pre-filled with the 'New' category

        before the form modal even opens.

        """

        res = super(Task, self).default_get(fields_list)

        # Only apply logic if creating a task for a Scrum Project

        is_scrum = self.env.context.get('is_scrum_app') or self.env.context.get('default_project_type') == 'scrum'

        if is_scrum and 'stage_id' in fields_list:

            # Look for the stage tagged with our 'new' category

            new_stage = self.env['project.task.type'].search([

                ('category', '=', 'new'),

                ('project_type', '=', 'scrum')

            ], limit=1, order='sequence asc')

            if new_stage:

                res.update({'stage_id': new_stage.id})

            else:

                # Fallback: Find the first scrum stage available

                fallback_stage = self.env['project.task.type'].search([

                    ('project_type', '=', 'scrum')

                ], limit=1, order='sequence asc')

                if fallback_stage:
                    res.update({'stage_id': fallback_stage.id})

        # Inherit parent task's owners when creating a subtask
        parent_id = self.env.context.get('default_parent_id')
        if parent_id and 'user_ids' in fields_list:
            parent_task = self.env['project.task'].browse(parent_id)
            if parent_task.exists() and parent_task.user_ids:
                res['user_ids'] = [Command.set(parent_task.user_ids.ids)]

        return res

    # ===========================================================

    # THE TASK ISOLATION FIX

    # ===========================================================

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):

        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return super()._search(domain, offset=offset, limit=limit, order=order)

        is_direct_lookup = any(

            isinstance(leaf, (list, tuple)) and leaf[0] in ('id', 'res_id')

            for leaf in domain

        )

        if not is_direct_lookup:

            if self.env.context.get('is_scrum_app'):

                domain = expression.AND([domain, [('project_type', '=', 'scrum')]])

            elif self.env.context.get('is_standard_project_app'):

                domain = expression.AND([domain, [('project_type', '=', 'standard')]])

        return super()._search(domain, offset=offset, limit=limit, order=order)

    @api.model
    def _read_group_sprint_id(self, sprints, domain, read_group_order=None):

        project_id = self._context.get('active_id') or self._context.get('default_project_id')

        if not project_id or not self._context.get('is_scrum_app'):
            return sprints

        if isinstance(project_id, list):
            project_id = project_id[0]

        return self.env['project.scrum.sprint'].search([

            ('project_id', '=', project_id),

            ('state', 'in', ('draft', 'active'))

        ], order='start_date asc, id asc')

    # ===========================================================

    # ? FIX: FORCE ALL SCRUM STAGES TO SHOW IN KANBAN

    # ===========================================================

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None, **kwargs):

        """

        Overrides the default Odoo stage grouping to ensure ALL Scrum stages

        appear as columns on the Kanban board, even if they are empty.

        """

        if self.env.context.get('is_scrum_app'):
            # If order is None, fallback to standard sequence sorting

            search_order = order if order else 'sequence asc, id asc'

            return self.env['project.task.type'].search([('project_type', '=', 'scrum')], order=search_order)

        # Safely pass to standard Odoo depending on whether 'order' was provided

        if order is not None:
            return super(Task, self)._read_group_stage_ids(stages, domain, order=order, **kwargs)

        return super(Task, self)._read_group_stage_ids(stages, domain, **kwargs)

    @api.constrains('stage_id', 'sprint_id', 'blocked_by_ids')
    def _check_scrum_workflow_constraints(self):

        for task in self:

            if not task.project_id or task.project_id.project_type != 'scrum':
                continue

            # 1. BLOCKED BY CHECK: Prevent closing if blockers are still active

            if task.stage_id.category == 'closed' and any(not t.is_closed for t in task.blocked_by_ids):
                blocker_names = ", ".join(task.blocked_by_ids.filtered(lambda t: not t.is_closed).mapped('name'))

                raise ValidationError(_(

                    "? BLOCKED TASK: Task '%s' cannot be closed because it is blocked by the following active tasks: %s"

                ) % (task.name, blocker_names))

            # 2. BACKLOG LOCK: Check if task is in the Backlog

            if not task.sprint_id and task.stage_id:

                # Blocks Backlog items from skipping ahead to review/closed

                if task.stage_id.category in ['qa', 'review', 'closed']:

                    if self.env.context.get('is_creating_scrum_task') or self.env.context.get('is_transferring_task'):
                        continue

                    category_label = dict(task.stage_id._fields['category'].selection).get(task.stage_id.category)

                    raise ValidationError(_(

                        "? BACKLOG LOCK: Task '%s' is in the Backlog.\n"

                        "You must assign this task to a Sprint before it can be moved to the '%s' stage."

                    ) % (task.name, category_label or task.stage_id.name))

    # ===========================================================
    # BACKEND ESTIMATION SYNC (BULLETPROOF FIX)
    # ===========================================================
    def _sync_backend_estimations(self, vals):
        """
        Forces allocated_time and story_points to stay synced globally
        even if the user modifies data from a list view or external API.
        """
        incoming_hours = vals.get('allocated_time', vals.get('allocated_hours'))

        if incoming_hours is not None and 'story_point_selection' not in vals:
            computed_sp = self.env['project.scrum.story.point.config'].compute_sp_from_hours(incoming_hours)
            vals['story_point_selection'] = computed_sp if computed_sp != '0' else False
            vals['story_points'] = int(computed_sp) if computed_sp != '0' else 0
            vals['allocated_time'] = incoming_hours
            if hasattr(self, 'allocated_hours'):
                vals['allocated_hours'] = incoming_hours

        elif 'story_point_selection' in vals and 'allocated_time' not in vals and 'allocated_hours' not in vals:
            sp = vals['story_point_selection']
            if sp:
                config_vals = self.env['project.scrum.story.point.config'].get_sp_configuration()
                hrs = config_vals.get(sp, 0.0)
                vals['allocated_time'] = hrs
                vals['story_points'] = int(sp)
                if hasattr(self, 'allocated_hours'):
                    vals['allocated_hours'] = hrs
            else:
                vals['allocated_time'] = 0.0
                vals['story_points'] = 0
                if hasattr(self, 'allocated_hours'):
                    vals['allocated_hours'] = 0.0

        # Guarantee integer field saves properly if UI only passes the selection string
        if 'story_point_selection' in vals and 'story_points' not in vals:
            vals['story_points'] = int(vals['story_point_selection']) if vals['story_point_selection'] else 0

    # ===========================================================
    # 🆕 SUBTASK DETACHMENT LOGIC
    # ===========================================================

    def _detect_manual_subtask_sprint_change(self, vals):
        """
        Detects subtasks where the user is manually changing the sprint
        to a value DIFFERENT from their parent's sprint.

        Returns a list of dicts with detachment context:
            [{
                'task': <task record>,
                'old_sprint': <sprint record or empty>,
                'new_sprint': <sprint record or empty>,
                'old_parent': <parent task record>,
            }, ...]

        Rules:
        - Task must have a parent_id (it's currently a subtask).
        - vals must explicitly contain 'sprint_id' (user-initiated write).
        - The new sprint must differ from the parent's current sprint.
        - Skipped when context says we are syncing from parent automatically
          or transferring across projects, or during creation.
        """

        # Skip during auto-syncs, creation, project transfers, or recursive detachment
        if self.env.context.get('is_creating_scrum_task'):
            return []
        if self.env.context.get('is_transferring_task'):
            return []
        if self.env.context.get('scrum_subtask_detaching'):
            return []
        if self.env.context.get('scrum_parent_sprint_sync'):
            return []

        # Only react when the user actually wrote sprint_id in this call
        if 'sprint_id' not in vals:
            return []

        new_sprint_id = vals.get('sprint_id') or False

        detachments = []
        for task in self:
            # Must be a subtask
            if not task.parent_id:
                continue

            parent_sprint_id = task.parent_id.sprint_id.id or False

            # If the user is setting sprint to the SAME value as parent,
            # that's just inheritance — do not detach.
            if new_sprint_id == parent_sprint_id:
                continue

            # If unchanged from current sprint, no real change happened
            if new_sprint_id == (task.sprint_id.id or False):
                continue

            detachments.append({
                'task': task,
                'old_sprint': task.sprint_id,
                'new_sprint': self.env['project.scrum.sprint'].browse(new_sprint_id) if new_sprint_id else self.env['project.scrum.sprint'],
                'old_parent': task.parent_id,
            })

        return detachments

    def _perform_subtask_detachment(self, detachments, vals):
        """
        Detaches subtasks from their parents and assigns them to the new sprint.
        Posts a chatter message to the relevant sprint(s) describing the action.

        We bypass the standard write() orchestrator using a guard context
        (scrum_subtask_detaching=True) so we don't recurse or trigger
        re-validation/inheritance.
        """

        if not detachments:
            return

        new_sprint_id = vals.get('sprint_id') or False

        for entry in detachments:
            task = entry['task']
            old_sprint = entry['old_sprint']
            new_sprint = entry['new_sprint']
            old_parent = entry['old_parent']

            # 1. Detach + reassign in a single, guarded write.
            #    The guard context prevents recursive detachment detection and
            #    prevents the parent-sprint inheritance from overwriting our value.
            detach_vals = {
                'parent_id': False,
                'sprint_id': new_sprint_id,
            }

            task.with_context(
                scrum_subtask_detaching=True,
                is_transferring_task=False,
            ).write(detach_vals)

            # 2. Post a structured chatter log on the NEW sprint (primary destination).
            #    Falls back to the old sprint if no new sprint (i.e. moved to backlog).
            target_sprint = new_sprint or old_sprint

            if target_sprint:
                old_sprint_name = old_sprint.name if old_sprint else _('Backlog')
                new_sprint_name = new_sprint.name if new_sprint else _('Backlog')
                user_name = self.env.user.name or 'System'

                changes_html = (
                    f"<li>Converted from <b>Subtask</b> to <b>Independent Task</b></li>"
                    f"<li>Parent Removed: <b>{old_parent.name or 'N/A'}</b></li>"
                    f"<li>Sprint: <b>{old_sprint_name}</b> → <b>{new_sprint_name}</b></li>"
                    f"<li>Action by: <b>{user_name}</b></li>"
                )

                message = Markup(
                    "<div>"
                    "<b>Task Updated:</b> %s"
                    "<ul>%s</ul>"
                    "</div>"
                ) % (task.name or '', Markup(changes_html))

                target_sprint.message_post(
                    body=message,
                    subtype_xmlid="mail.mt_note",
                )

            # 3. Also log on the OLD sprint (if different) so audit trail
            #    is visible from both sides.
            if old_sprint and old_sprint != target_sprint:
                user_name = self.env.user.name or 'System'
                changes_html = (
                    f"<li>Subtask <b>{task.name}</b> detached from parent "
                    f"<b>{old_parent.name or 'N/A'}</b></li>"
                    f"<li>Moved to sprint: <b>{new_sprint.name if new_sprint else _('Backlog')}</b></li>"
                    f"<li>Action by: <b>{user_name}</b></li>"
                )
                message = Markup(
                    "<div>"
                    "<b>Subtask Removed:</b> %s"
                    "<ul>%s</ul>"
                    "</div>"
                ) % (task.name or '', Markup(changes_html))

                old_sprint.message_post(
                    body=message,
                    subtype_xmlid="mail.mt_note",
                )

            # 4. Trigger sprint metric recompute on both sprints.
            sprints_to_recompute = (old_sprint | new_sprint).filtered(lambda s: s.exists())
            if sprints_to_recompute:
                sprints_to_recompute._update_stage_from_tasks()
                for sprint in sprints_to_recompute:
                    sprint._compute_allocated_time()
                    sprint._compute_time()
                    sprint._compute_efficiency()

    # ===========================================================

    # 🚀 REFACTORED WRITE ORCHESTRATOR

    # ===========================================================

    def write(self, vals):

        # =========================================================
        # 🆕 SUBTASK DETACHMENT GATE
        # Detect manual sprint change on subtasks BEFORE anything else.
        # If detected, handle those records separately and remove them
        # from `self` so the rest of write() runs only on normal records.
        # =========================================================
        detachments = self._detect_manual_subtask_sprint_change(vals)

        if detachments:
            detaching_tasks = self.env['project.task'].browse([d['task'].id for d in detachments])
            self._perform_subtask_detachment(detachments, vals)

            # Remove handled tasks from the recordset so they are not
            # written to again with the original vals (which would re-trigger
            # parent inheritance or constraint cycles).
            remaining = self - detaching_tasks

            if not remaining:
                return True

            # Continue normal write flow only on remaining records.
            # We strip sprint_id from vals only for the detached set above;
            # for remaining tasks, the original vals still apply as intended.
            return remaining.write(vals)

        old_sprints = self.mapped('sprint_id')

        old_values = self._capture_old_values_for_chatter()

        # Handle project transfers early

        is_transfer = self._handle_project_transfer(vals)

        if is_transfer:
            result = super(Task, self.with_context(is_transferring_task=True)).write(vals)

            self._trigger_sprint_metrics_recompute(old_sprints, self.mapped('sprint_id'), vals)

            return result

        # Apply constraints and bi-directional syncs before write

        self._sync_scrum_state_and_stage(vals)

        # 🆕 Block parent completion if any subtask (direct or nested) is still open.
        # Runs AFTER state/stage sync so it catches both the dropdown path
        # (state='1_done') and the Kanban-drag path (stage->closed, synced to done).
        self._check_subtasks_completed_before_close(vals)

        self._validate_agile_stage_transition(vals)

        self._apply_backlog_constraints(vals)

        # Core database write

        result = super(Task, self).write(vals)

        # Post-write computations and logging

        new_sprints = self.mapped('sprint_id')

        self._trigger_sprint_metrics_recompute(old_sprints, new_sprints, vals)

        self._log_scrum_chatter_changes(old_values, vals)

        return result

    # ===========================================================

    # 🚀 REFACTORED CREATE ORCHESTRATOR

    # ===========================================================

    @api.model_create_multi
    def create(self, vals_list):

        ctx = dict(self.env.context, is_creating_scrum_task=True)

        self._apply_scrum_create_failsafes(vals_list)

        records = super(Task, self.with_context(ctx)).create(vals_list)

        self._force_subtask_hierarchy(records)

        # Trigger sprint engine updates manually on creation

        new_sprints = records.mapped('sprint_id')

        self._trigger_sprint_metrics_recompute(

            self.env['project.scrum.sprint'],

            new_sprints,

            {'allocated_time': True, 'sprint_id': True, 'stage_id': True}

        )

        self._log_scrum_creation_chatter(records)

        return records

    def unlink(self):

        # NEW: Intercept Unlink to update Sprint when tasks are deleted

        sprints = self.mapped('sprint_id')

        res = super(Task, self).unlink()

        if sprints:
            sprints.filtered(lambda s: s.exists())._update_stage_from_tasks()

        return res

    # ===========================================================

    # 🛡️ PRIVATE HELPER METHODS (THE CONTROLLERS)

    # ===========================================================

    def _capture_old_values_for_chatter(self):

        old_values = {}

        for task in self:
            old_values[task.id] = {

                'stage_id': task.stage_id.name if task.stage_id else 'None',

                'user_ids': task.user_ids.mapped('name'),

                'assigned_by': task.assigned_by_id.name if task.assigned_by_id else 'None',

                'sprint': task.sprint_id.name if task.sprint_id else 'None',

                'state': task.state,

                'allocated_time': float(task.read(['allocated_hours'])[0]['allocated_hours'] or 0),

                'story_points': task.story_points or 0,

                'name': task.name or '',

            }

        return old_values

    def _handle_project_transfer(self, vals):

        target_project_id = vals.get('project_id')

        is_transfer = False

        if target_project_id:

            for task in self:

                if task.project_id.id != target_project_id:
                    is_transfer = True

                    break

        if is_transfer:

            vals['sprint_id'] = False

            vals['state'] = '01_in_progress'

            if 'stage_id' not in vals:

                target_p = self.env['project.project'].browse(target_project_id)

                backlog_stages = target_p.type_ids.filtered(lambda s: s.category in ['new', 'committed'])

                if backlog_stages:

                    vals['stage_id'] = backlog_stages[0].id

                elif target_p.type_ids:

                    vals['stage_id'] = target_p.type_ids[0].id

        return is_transfer

    def _sync_scrum_state_and_stage(self, vals):

        if 'state' in vals and 'stage_id' not in vals:

            for task in self:

                if task.project_id.project_type == 'scrum':

                    new_state = vals['state']

                    target_category = None

                    if new_state in ['1_done', '1_canceled']:

                        target_category = 'closed'

                    elif new_state == '03_approved':

                        target_category = 'review'

                    elif new_state == '02_changes_requested':

                        target_category = 'blocked'

                    elif new_state == '01_in_progress':

                        target_category = 'active'

                    if target_category:

                        stage = self.env['project.task.type'].search([

                            ('project_type', '=', 'scrum'),

                            ('category', '=', target_category)

                        ], limit=1)

                        if stage:
                            vals['stage_id'] = stage.id

        if 'stage_id' in vals and 'state' not in vals:

            new_stage = self.env['project.task.type'].browse(vals['stage_id'])

            if new_stage.project_type == 'scrum':

                if new_stage.category == 'closed':

                    vals['state'] = '1_done'

                elif new_stage.category == 'review':

                    vals['state'] = '03_approved'

                elif new_stage.category == 'blocked':

                    vals['state'] = '02_changes_requested'

                else:

                    vals['state'] = '01_in_progress'

    # ===========================================================
    # 🆕 SUBTASK COMPLETION GUARD
    # ===========================================================
    def _check_subtasks_completed_before_close(self, vals):
        """
        Blocks moving a PARENT task to 'Done' while any of its subtasks
        (direct or nested) are still open.

        Behaviour:
        - Only triggers when this write would set the task state to '1_done'.
          (Cancelling a parent is intentionally NOT blocked.)
        - A subtask is treated as "completed" when it is closed (Done or
          Cancelled), matching how the rest of the module reasons about
          completion via `is_closed`. To require strictly 'Done', change the
          filter below to `lambda t: t.state != '1_done'`.
        - Walks the full subtask tree using `child_of` (parent_path), so deeply
          nested subtasks are also checked.
        """
        # Only act when this write is actually trying to mark the task Done.
        if vals.get('state') != '1_done':
            return

        for task in self:

            if task.project_id.project_type != 'scrum':
                continue

            # All descendants (direct + nested), excluding the task itself.
            descendants = self.env['project.task'].search([
                ('id', 'child_of', task.id),
                ('id', '!=', task.id),
            ])

            if not descendants:
                continue

            incomplete = descendants.filtered(lambda t: not t.is_closed)

            if incomplete:
                names = "\n - ".join(incomplete.mapped('name'))
                raise ValidationError(_(
                    "🛑 Cannot complete task '%s'.\n\n"
                    "The following subtask(s) are not completed yet:\n\n - %s\n\n"
                    "Please finish or cancel them before marking the parent as Done."
                ) % (task.name, names))

    def _validate_agile_stage_transition(self, vals):

        if 'stage_id' in vals:

            new_stage = self.env['project.task.type'].browse(vals['stage_id'])

            for task in self:

                if task.project_id.project_type == 'scrum' and task.stage_id:

                    old_cat = task.stage_id.category

                    new_cat = new_stage.category

                    if old_cat and new_cat and old_cat != new_cat:

                        if new_cat == 'closed':

                            is_project_admin = self.env.user.has_group('project.group_project_manager')

                            if not is_project_admin and self.env.user != task.project_id.user_id:
                                raise AccessError(
                                    _("? ACCESS DENIED: Only the Scrum Master or a Project Administrator can move a task to the 'Closed' stage."))

                        if old_cat == 'closed':
                            raise ValidationError(
                                _("? LOCKED: This task is Closed. You cannot move it to another stage."))

                        if old_cat == 'blocked' and new_cat != 'active':
                            raise ValidationError(
                                _("? INVALID TRANSITION: A Blocked task can only be moved to 'Active'."))

                        if old_cat == 'review' and new_cat not in ['qa', 'active', 'closed']:
                            raise ValidationError(
                                _("? INVALID TRANSITION: A task 'In Review' can only move to 'QA', 'Active', or 'Closed'."))

                        if new_cat == 'review' and old_cat != 'qa':
                            raise ValidationError(
                                _("? QA REQUIRED: A task must pass through 'In QA' before it can be moved to 'In Review'."))

                        if new_cat == 'closed' and old_cat != 'review':
                            raise ValidationError(
                                _("? REVIEW REQUIRED: A task must pass through 'In Review' before it can be 'Closed'."))

                        if new_cat == 'new':
                            raise ValidationError(
                                _("? INVALID TRANSITION: You cannot move an ongoing task backward to 'New'."))

                        if new_cat == 'committed' and old_cat != 'new':
                            raise ValidationError(
                                _("? INVALID TRANSITION: You cannot move a task backward to 'Committed'."))

    def _apply_backlog_constraints(self, vals):

        for task in self:

            if task.project_id.project_type != 'scrum':
                continue

            new_sprint_id = vals.get('sprint_id', task.sprint_id.id if 'sprint_id' not in vals else False)

            if not new_sprint_id:

                if 'stage_id' in vals:

                    target_stage = self.env['project.task.type'].browse(vals['stage_id'])

                    if target_stage.category not in ['new', 'committed']:
                        raise ValidationError(
                            _("? BACKLOG LOCK: Backlog items must remain in 'New' or 'Committed' categories."))

                if 'sprint_id' in vals and not vals.get('sprint_id'):

                    backlog_stage = task.project_id.type_ids.filtered(lambda s: s.category == 'new')

                    if backlog_stage:
                        vals['stage_id'] = backlog_stage[0].id

    def _trigger_sprint_metrics_recompute(self, old_sprints, new_sprints, vals):

        # --- STAGE SYNC ---
        if 'stage_id' in vals or 'sprint_id' in vals or 'state' in vals:
            all_sprints = (old_sprints | new_sprints).filtered(lambda s: s.exists())
            if all_sprints:
                all_sprints._update_stage_from_tasks()

        # --- ALWAYS RECOMPUTE ALLOCATED TIME ---
        all_related_tasks = self | self.mapped('child_ids') | self.mapped('parent_id')
        sprints = all_related_tasks.mapped('sprint_id').filtered(lambda s: s)

        for sprint in sprints:
            sprint._compute_allocated_time()

        # --- EXISTING METRICS ---
        root_tasks = self._get_root_tasks()
        sprints = root_tasks.mapped('sprint_id').filtered(lambda s: s)

        for sprint in sprints:
            sprint._compute_time()
            sprint._compute_efficiency()

    def _log_scrum_chatter_changes(self, old_values, vals):

        for task in self:

            if not task.sprint_id:
                continue

            old = old_values.get(task.id, {})

            changes = []

            # 1. Stage

            if old.get('stage_id') != (task.stage_id.name or 'None'):
                changes.append(f"Stage: {old.get('stage_id')}  {task.stage_id.name}")

            # 2. Owners

            old_users = ", ".join(old.get('user_ids', [])) or 'None'

            new_users = ", ".join(task.user_ids.mapped('name')) or 'None'

            if old_users != new_users:
                changes.append(f"Owners: {old_users} →  {new_users}")

            # 3. Assigned By

            new_assigned = task.assigned_by_id.name if task.assigned_by_id else 'None'

            if old.get('assigned_by') != new_assigned:
                changes.append(f"Assigned By: {old.get('assigned_by')} →  {new_assigned}")

            # 4. Sprint

            new_sprint = task.sprint_id.name if task.sprint_id else 'None'

            if old.get('sprint') != new_sprint:
                changes.append(f"Sprint: {old.get('sprint')} →  {new_sprint}")

            # 5. State

            if old.get('state') != task.state:
                changes.append(f"State: {old.get('state')} →  {task.state}")

            # 6. Story Points

            old_sp = old.get('story_points', 0)

            new_sp = task.story_points or 0

            if old_sp != new_sp:
                changes.append(f"Story Points: {old_sp} →  {new_sp}")

            # 7. Allocated Time (FINAL RELIABLE FIX)

            # 🔥 USE allocated_hours (REAL SOURCE OF TRUTH)

            old_alloc = float(old.get('allocated_time', 0))  # keep old as is

            new_alloc = float(task.allocated_hours or 0)

            if old_alloc != new_alloc:
                changes.append(f"Allocated Time: {old_alloc}h → {new_alloc}h")




            # 8. Title Change

            old_name = old.get('name', '')

            if old_name != task.name:
                changes.append(f"Title: {old_name} →  {task.name}")

            if changes:
                message = Markup("""
<div>
<b>Task Updated:</b> %s
<ul>%s</ul>
</div>

                """ % (

                    task.name,

                    "".join([f"<li>{c}</li>" for c in changes])

                ))

                task.sprint_id.message_post(

                    body=message,

                    subtype_xmlid="mail.mt_note"

                )

    def _apply_scrum_create_failsafes(self, vals_list):

        for vals in vals_list:

            # =========================================================
            # 🆕 OWNER INHERITANCE: subtask inherits parent's user_ids
            # =========================================================
            # Resolve parent_id from vals first, then fallback to context.
            # We only auto-fill when the caller did NOT explicitly pass user_ids.
            # This makes the behavior work for EVERY creation path:
            #   - Form "Add subtask" (default_parent_id in context)
            #   - Kanban/list quick create
            #   - Inline One2many child_ids row
            #   - Direct backend ORM: self.env['project.task'].create({...})
            #   - XML-RPC / JSON-RPC external API calls
            #
            # Rules:
            #   1. parent_id must resolve to a real task
            #   2. user_ids must NOT already be in vals (respects explicit input)
            #   3. parent must have at least one owner (no point copying empty)
            parent_id_for_owners = vals.get('parent_id') or self.env.context.get('default_parent_id')

            if parent_id_for_owners and 'user_ids' not in vals:
                parent_task = self.env['project.task'].browse(parent_id_for_owners)
                # exists() check guards against stale IDs from broken clients/APIs
                if parent_task.exists() and parent_task.user_ids:
                    vals['user_ids'] = [Command.set(parent_task.user_ids.ids)]

            if not vals.get('sprint_id') and self.env.context.get('default_sprint_id'):
                vals['sprint_id'] = self.env.context.get('default_sprint_id')

            if not vals.get('project_id'):

                if vals.get('sprint_id'):

                    sprint = self.env['project.scrum.sprint'].browse(vals['sprint_id'])

                    vals['project_id'] = sprint.project_id.id

                elif self.env.context.get('default_project_id'):

                    vals['project_id'] = self.env.context.get('default_project_id')

            if vals.get('project_id'):

                project = self.env['project.project'].browse(vals.get('project_id'))

                if project.project_type == 'scrum':

                    if not vals.get('stage_id'):

                        backlog_stage = project.type_ids.filtered(lambda s: s.category == 'new')

                        if backlog_stage:

                            vals['stage_id'] = backlog_stage[0].id

                        elif project.type_ids:

                            vals['stage_id'] = project.type_ids[0].id

                    if not vals.get('sprint_id') and vals.get('stage_id'):
                        vals['state'] = '01_in_progress'

    def _force_subtask_hierarchy(self, records):

        for rec in records:

            if rec.parent_id:
                parent = rec.parent_id

                parent.invalidate_recordset(['child_ids'])

                _logger.warning(f"LINKED SUBTASK {rec.id} →  PARENT {parent.id}")

        parents = records.mapped('parent_id')

        if parents:
            parents.invalidate_recordset(['child_ids'])

        for record in records:

            if record.parent_id:

                siblings = record.parent_id.child_ids

                if siblings:

                    min_sequence = min(siblings.mapped('sequence'))

                    record.sequence = min_sequence - 1

                else:

                    record.sequence = 0

    def _log_scrum_creation_chatter(self, records):

        for task in records:

            if not task.sprint_id:
                continue

            message = Markup("""
<div>
<b>→  Task Created</b>
<ul>
<li><b>Task:</b> %s</li>
<li><b>Owners:</b> %s</li>
<li><b>Assigned By:</b> %s</li>
<li><b>State:</b> %s</li>
</ul>
</div>

            """ % (

                task.name,

                ", ".join(task.user_ids.mapped('name')) or 'None',

                task.assigned_by_id.name or 'None',

                task.state or 'N/A'

            ))

            task.sprint_id.message_post(

                body=message,

                subtype_xmlid="mail.mt_note"

            )

    # --- DASHBOARD & ANALYTICS ---

    @api.model
    def get_scrum_data(self, period):

        start_date = get_period_start_date(period)

        base_domain = [('project_id.project_type', '=', 'scrum')]

        scrum_tasks_period = self.search(base_domain + [('create_date', '>=', start_date)])

        all_scrum_tasks = self.search(base_domain)

        completed_tasks = scrum_tasks_period.filtered('is_closed')

        return {

            'backlog_tasks': len(scrum_tasks_period.filtered(lambda t: not t.sprint_id)),

            'active_tasks': len(scrum_tasks_period.filtered('sprint_id')),

            'total_sp': sum(all_scrum_tasks.mapped('story_points')),

            'completed_sp': sum(all_scrum_tasks.filtered('is_closed').mapped('story_points')),

            'completion_ratio': round(

                (len(completed_tasks) / len(scrum_tasks_period) * 100) if scrum_tasks_period else 0, 2),

            'unassigned_tasks': self.search_count(

                base_domain + [('user_ids', '=', False), ('create_date', '>=', start_date)])

        }

    @api.model
    def get_tasks_by_stage_pie(self, period):

        start_date = get_period_start_date(period)

        self._cr.execute("""

            SELECT pt.name, COUNT(t.id)

            FROM project_task t

            JOIN project_task_type pt ON t.stage_id = pt.id

            JOIN project_project pp ON t.project_id = pp.id

            WHERE pp.project_type = 'scrum' AND t.create_date >= %s

            GROUP BY pt.name

        """, (start_date,))

        data = self._cr.dictfetchall()

        return [[rec['count'] for rec in data], [rec['name'] for rec in data]]

    @api.model
    def get_burnup_chart_data(self, period):

        start_date = get_period_start_date(period)

        completed_tasks = self.search([

            ('project_id.project_type', '=', 'scrum'),

            ('is_closed', '=', True),

            ('write_date', '>=', start_date)

        ], order='write_date asc')

        cumulative_count, chart_data = 0, {}

        for task in completed_tasks:
            day = task.write_date.strftime('%Y-%m-%d')

            cumulative_count += 1

            chart_data[day] = cumulative_count

        return {'labels': list(chart_data.keys()), 'data': list(chart_data.values())}

    @api.model
    def get_upcoming_meetings(self):

        meetings = self.env['project.scrum.meeting'].search([('date', '>=', fields.Datetime.now())], order='date asc',

                                                            limit=10)

        return [{'subject': m.subject, 'date': m.date.strftime('%Y-%m-%d %H:%M'), 'project': m.project_id.name or '',

                 'sprint': m.sprint_id.name or ''} for m in meetings]

    @api.model
    def get_top_performers(self, period):

        start_date = get_period_start_date(period)

        completed_tasks = self.search(

            [('project_id.project_type', '=', 'scrum'), ('is_closed', '=', True), ('write_date', '>=', start_date)])

        assignee_points = {}

        for task in completed_tasks:

            for user in task.user_ids:
                assignee_points[user] = assignee_points.get(user, 0) + task.story_points

        top_performers = sorted(assignee_points.items(), key=lambda item: item[1], reverse=True)[:5]

        return [{'name': user.partner_id.name, 'completed_sp': points} for user, points in top_performers]