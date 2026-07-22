# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.osv import expression


# ===========================================================
# 1. STAGE MODEL (Simple Data Container)
# ===========================================================
class ProjectStage(models.Model):
    _inherit = 'project.project.stage'

    # We add the type, but we DO NOT touch _search.
    # This prevents the Access Error completely.
    project_type = fields.Selection([
        ('standard', 'Standard Project'),
        ('scrum', 'Software (Scrum) Project')
    ], string="Project Type", default='standard', required=True)

    # NEW: Stage Categories for Workflow Enforcement
    # FIX: Renamed 'closed' to 'finalized' to avoid Odoo keyword conflicts
    category = fields.Selection([
        ('backlog', 'Backlog'),
        ('active', 'Active'),
        ('completed', 'Completed / Delivered'),
        ('finalized', 'Finalized / Closed')
    ], string="Stage Category", default='backlog', required=True,
        help="Defines the behavior and strict validation rules for projects entering this stage.")


# ===========================================================
# 2. PROJECT MODEL (The Logic)
# ===========================================================
class Project(models.Model):
    _inherit = 'project.project'

    # --- 1. OVERRIDE STAGE_ID TO CONTROL COLUMNS & ACCESS ---

    # FIX: By setting groups="", we completely bypass Odoo's hardcoded
    # 'project.group_project_stages' toggle restriction. This allows
    # all users to access this field as long as they have access to the model.
    stage_id = fields.Many2one(
        'project.project.stage',
        string='Stage',
        ondelete='restrict',
        groups="",
        tracking=True,
        index=True,
        copy=False,
        domain="[('project_type', '=', project_type)]",  # <--- NEW: Strict Data Domain
        group_expand='_read_group_stage_ids'
    )

    rolling_velocity = fields.Float(string="Current Rolling Velocity", default=0.0, readonly=True)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        """
        FIXED: 'order' is now optional (order=None) to prevent TypeErrors
        if Odoo calls this method without the sort argument.
        Groups Kanban columns strictly by App Context.
        Added a defensive fallback to prevent Scrum stages from bleeding
        into standard Odoo if context is lost.
        """
        search_domain = []

        # 1. Scrum App -> Only Scrum Stages
        if self.env.context.get('is_scrum_app') or self.env.context.get('default_project_type') == 'scrum':
            search_domain = [('project_type', '=', 'scrum')]

        # 2. Standard App -> Only Standard Stages
        elif self.env.context.get('is_standard_project_app') or self.env.context.get(
                'default_project_type') == 'standard':
            search_domain = [('project_type', '=', 'standard')]

        # 3. THE FIREWALL: If Odoo calls this from a generic view without our context,
        # default to standard to protect the Scrum stages from leaking out.
        else:
            search_domain = [('project_type', '=', 'standard')]

        if search_domain:
            return stages.search(search_domain, order=order)

        return stages

    # --- 2. PROJECT TYPE SEPARATION ---
    project_type = fields.Selection([
        ('standard', 'Standard Project'),
        ('scrum', 'Software (Scrum) Project')
    ], string="Project Type", default='standard', required=True, tracking=True)

    is_scrum_project = fields.Boolean(
        string="Is a Scrum Project?",
        compute="_compute_is_scrum_project",
        store=True
    )

    # --- 3. RELATIONS ---
    sprint_ids = fields.One2many('project.scrum.sprint', 'project_id', string='Sprints')
    release_ids = fields.One2many('project.scrum.release', 'project_id', string='Releases')
    meeting_ids = fields.One2many('project.scrum.meeting', 'project_id', string='Meetings')

    # ============================================
    # BACKLOG (ONLY PARENT TASKS)
    # ============================================
    backlog_task_ids = fields.One2many(
        'project.task',
        'project_id',
        string="Backlog Tasks",
        domain=[
            ('is_scrum_project', '=', True),
            ('sprint_id', '=', False),
            ('parent_id', '=', False)  # ? RESTORED: only root tasks
        ]
    )

    # ============================================
    # ACTIVE TASKS (ONLY PARENT TASKS)
    # ============================================
    active_task_ids = fields.One2many(
        'project.task',
        'project_id',
        string="Active Tasks",
        domain=[
            ('is_scrum_project', '=', True),
            ('sprint_id', '!=', False),
            ('parent_id', '=', False)  # ? RESTORED: only root tasks
        ]
    )

    # --- 4. TEAM & STATS ---
    team_member_ids = fields.Many2many('res.users', string="Team Members", compute='_compute_team_members', store=True)

    sprint_count = fields.Integer(compute='_compute_scrum_counts', string="Sprint Count")
    task_count = fields.Integer(compute='_compute_scrum_counts', string="Total Tasks")
    completed_task_count = fields.Integer(compute='_compute_scrum_counts', string="Completed Tasks")
    backlog_task_count = fields.Integer(compute='_compute_scrum_counts', string="Backlog Tasks")
    active_task_count = fields.Integer(compute='_compute_scrum_counts', string="Active Tasks")

    status = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('locked', 'Locked'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Project Status', default='new', tracking=True)

    # --- 5. VELOCITY & FORECASTING ---
    automate_story_points = fields.Boolean(string="Automate Story Point Calculation", default=True)
    average_velocity = fields.Float(string="Average Velocity", compute='_compute_velocity_and_forecast', digits=(16, 1))
    total_backlog_sp = fields.Integer(string="Total Backlog Story Points", compute='_compute_velocity_and_forecast')
    estimated_sprints_remaining = fields.Float(string="Estimated Sprints Remaining",
                                               compute='_compute_velocity_and_forecast', digits=(16, 1))

    project_burn_rate_per_day = fields.Float(
        string="Project Burn Rate",
        compute='_compute_project_burn_rate',
        digits=(16, 1),
        help="Story Points completed per day across all active sprints."
    )

    # ===========================================================
    # SERVER-SIDE VIEW ID LOOKUP
    # ===========================================================
    @api.model
    def get_scrum_view_ids(self):
        return {
            'project_kanban': self.env.ref('scrum_management.view_project_kanban_unlocked').id,
            'planning_kanban': self.env.ref('scrum_management.view_scrum_project_planning_kanban').id,
            'backlog_kanban': self.env.ref('scrum_management.view_scrum_backlog_global_kanban').id,
            'active_tasks_kanban': self.env.ref('scrum_management.view_scrum_active_tasks_global_kanban').id,

            # THE FIX: Pointing to the newly renamed ID for the Sprint Kanban
            'sprint_kanban': self.env.ref('scrum_management.view_project_scrum_sprint_stage_kanban').id,

            # THE CRITICAL FIX: Pre-fetching the Search View ID to avoid ir.model.data RPC error
            'sprint_search_view': self.env.ref('scrum_management.view_project_scrum_sprint_search_forced').id,
        }

    # ===========================================================
    # SEARCH OVERRIDE (Smart App Isolation)
    # ===========================================================
    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """
        Smart App Isolation for PROJECTS.
        - In Scrum App         -> show ONLY Scrum projects
        - In Standard Project  -> hide Scrum projects
        - Everywhere else      -> show everything (Timesheets, Invoicing, Sales, etc.)
        """
        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return super()._search(domain, offset=offset, limit=limit, order=order)

        is_direct_lookup = any(
            isinstance(leaf, (list, tuple)) and leaf[0] in ('id', 'res_id')
            for leaf in domain
        )

        if not is_direct_lookup:
            if self.env.context.get('is_scrum_app'):
                # We are in the Scrum App -> Show ONLY Scrum Projects
                domain = expression.AND([domain, [('project_type', '=', 'scrum')]])
            elif self.env.context.get('is_standard_project_app'):
                # THE FIREWALL FIX: We are in the native Odoo Project app
                # Aggressively hide all Scrum projects.
                domain = expression.AND(
                    [domain, ['|', ('project_type', '=', 'standard'), ('project_type', '=', False)]])
            # else: any other module (Timesheets, Invoicing, Sales, etc.)
            # -> no filter applied, show everything

        return super()._search(domain, offset=offset, limit=limit, order=order)

    # ===========================================================
    # STAGE CATEGORY VALIDATION & WRITE INTERCEPTOR
    # ===========================================================
    def write(self, vals):
        # 1. Intercept the stage change to run Category Validation Rules
        if 'stage_id' in vals:
            # FIX: Hard database read to prevent ORM caching from bypassing rules
            stage_data = self.env['project.project.stage'].browse(vals['stage_id']).read(['category'])
            if stage_data:
                real_category = stage_data[0].get('category')
                if real_category:
                    for project in self:
                        # We only enforce these strict rules on Scrum projects
                        if project.project_type == 'scrum':
                            project._check_stage_category_rules(real_category)

        # 2. Log workflow changes
        if 'project_type' in vals:
            for project in self:
                if project.project_type == 'scrum' and vals.get('project_type') == 'standard':
                    project.message_post(body=_("<b>Workflow Changed:</b> Converted from Scrum to Standard."))

        return super(Project, self).write(vals)

    def _check_stage_category_rules(self, new_category):
        """ Enforces strict agile constraints based on the destination stage's category. """
        self.ensure_one()

        # Hard database counts to prevent cache trickery
        sprint_count = self.env['project.scrum.sprint'].search_count([('project_id', '=', self.id)])

        # ===============================================================================
        # 1. THE FOOLPROOF SHIELD: Single shared logic for all forward-moving stages
        # ===============================================================================
        if sprint_count == 0 and new_category in ['active', 'completed', 'finalized']:
            if new_category == 'active' and getattr(self, 'allow_billable', False):
                pass  # Exception: Let it into Active if marked Billable
            else:
                raise ValidationError(_(
                    "Action Denied: You cannot move a project to the '%s' category if it has no sprints."
                ) % new_category.capitalize())

        # ===============================================================================
        # 2. CATEGORY-SPECIFIC SECONDARY CHECKS
        # ===============================================================================

        # CATEGORY: BACKLOG
        if new_category == 'backlog':
            if sprint_count > 0:
                raise ValidationError(_(
                    "Action Denied: A project cannot be moved to a 'Backlog' stage if it already has sprints. "
                    "Please remove or archive existing sprints first."
                ))

        # CATEGORY: ACTIVE
        elif new_category == 'active':
            pass  # Already covered securely by the shield above

        # CATEGORY: COMPLETED / DELIVERED
        elif new_category == 'completed':
            if any(s.state != 'completed' for s in self.sprint_ids):
                raise ValidationError(
                    _("Action Denied: All sprints must be 'Completed' before moving the project to Completed/Delivered."))

            if self.backlog_task_ids:
                raise ValidationError(
                    _("Action Denied: You cannot complete a project that still has tasks sitting in the Backlog."))

            scrum_tasks = self.task_ids.filtered(lambda t: t.is_scrum_project)
            if any(not t.is_closed for t in scrum_tasks):
                raise ValidationError(
                    _("Action Denied: All tasks must be closed before moving to Completed/Delivered."))

        # CATEGORY: FINALIZED (Previously Closed)
        elif new_category == 'finalized':
            open_sprints = self.sprint_ids.filtered(lambda s: s.state not in ['completed', 'closed', 'archived'])
            if open_sprints:
                raise ValidationError(
                    _("Action Denied: All sprints must be Closed, Completed, or Archived before moving the project to Finalized."))

            if self.backlog_task_ids:
                raise ValidationError(
                    _("Action Denied: You cannot move a project that still has tasks sitting in the Backlog to Finalized."))

            scrum_tasks = self.task_ids.filtered(lambda t: t.is_scrum_project)
            if any(not t.is_closed for t in scrum_tasks):
                raise ValidationError(_("Action Denied: No active tasks or bugs can exist when moving to 'Finalized'."))

    # --- COMPUTE METHODS ---

    @api.depends('project_type')
    def _compute_is_scrum_project(self):
        for project in self:
            project.is_scrum_project = (project.project_type == 'scrum')

    @api.depends('active_task_ids.user_ids', 'project_type')
    def _compute_team_members(self):
        for project in self:
            new_members = self.env['res.users']
            if project.project_type == 'scrum':
                new_members = project.active_task_ids.mapped('user_ids')
            if set(project.team_member_ids.ids) != set(new_members.ids):
                project.team_member_ids = new_members

    @api.depends('sprint_ids', 'task_ids.is_closed', 'task_ids.sprint_id', 'project_type')
    def _compute_scrum_counts(self):
        for project in self:
            if project.project_type == 'scrum':
                scrum_tasks = project.task_ids.filtered('is_scrum_project')
                project.sprint_count = len(project.sprint_ids)
                project.task_count = len(scrum_tasks)
                project.completed_task_count = len(scrum_tasks.filtered('is_closed'))
                project.backlog_task_count = len(scrum_tasks.filtered(lambda t: not t.sprint_id))
                project.active_task_count = len(scrum_tasks.filtered('sprint_id'))
            else:
                project.sprint_count = project.task_count = project.completed_task_count = 0
                project.backlog_task_count = project.active_task_count = 0

    @api.depends('sprint_ids.state', 'sprint_ids.velocity', 'backlog_task_ids.story_points', 'project_type')
    def _compute_velocity_and_forecast(self):
        for project in self:
            if project.project_type == 'scrum':
                completed_sprints = project.sprint_ids.filtered(lambda s: s.state == 'completed')
                project.average_velocity = sum(completed_sprints.mapped('velocity')) / len(
                    completed_sprints) if completed_sprints else 0.0
                project.total_backlog_sp = sum(project.backlog_task_ids.mapped('story_points'))
                if project.average_velocity > 0:
                    project.estimated_sprints_remaining = project.total_backlog_sp / project.average_velocity
                else:
                    project.estimated_sprints_remaining = 0
            else:
                project.average_velocity = project.total_backlog_sp = project.estimated_sprints_remaining = 0

    @api.depends('sprint_ids.state', 'sprint_ids.start_date', 'sprint_ids.completed_story_points', 'project_type')
    def _compute_project_burn_rate(self):
        today = fields.Date.today()
        for project in self:
            if project.project_type == 'scrum':
                active_sprints = project.sprint_ids.filtered(lambda s: s.state == 'active')
                if not active_sprints:
                    project.project_burn_rate_per_day = 0.0
                    continue
                total_completed_sp = sum(active_sprints.mapped('completed_story_points'))
                total_days = sum(
                    (today - s.start_date).days + 1 for s in active_sprints if s.start_date and s.start_date <= today)
                project.project_burn_rate_per_day = total_completed_sp / total_days if total_days > 0 else 0.0
            else:
                project.project_burn_rate_per_day = 0.0

    def action_open_scrum_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'scrum_management.scrum_client_action',
            'params': {'project_id': self.id, 'view_type': 'dashboard'}
        }

    def action_lock_project(self):
        self.ensure_one()
        if self.project_type != 'scrum':
            self.write({'status': 'locked'})
            return
        if not self.backlog_task_ids and all(s.state == 'completed' for s in self.sprint_ids):
            self.write({'status': 'locked'})
        else:
            raise ValidationError(_("Scrum projects require an empty backlog and completed sprints before locking."))

    def action_view_sprints(self):
        self.ensure_one()
        return {
            'name': _('Sprints'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.scrum.sprint',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id}
        }

    # --- NEW METHOD: Open Sprint Kanban ---
    def action_open_project_sprints_kanban(self):
        """ Triggered by clicking a project card. Opens the Sprint Kanban. """
        self.ensure_one()
        return {
            'name': _('Sprints for %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'project.scrum.sprint',
            'view_mode': 'kanban,list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
                'is_scrum_app': True
            }
        }

    def action_open_sprint_wizard(self):
        self.ensure_one()
        wizard = self.env['project.sprint.details.wizard'].create({'project_name': self.name})
        lines_to_create = []
        today = fields.Date.today()
        for sprint in self.sprint_ids:
            sprint_tasks = sprint.task_ids
            completed_tasks = sprint_tasks.filtered('is_closed')
            team_members = sprint_tasks.mapped('user_ids')
            days_elapsed = days_remaining = 0
            if sprint.start_date and sprint.end_date:
                total_duration = (sprint.end_date - sprint.start_date).days + 1
                if today < sprint.start_date:
                    days_remaining = total_duration
                elif today > sprint.end_date:
                    days_elapsed = total_duration
                else:
                    days_elapsed = (today - sprint.start_date).days + 1
                    days_remaining = (sprint.end_date - today).days
            lines_to_create.append({
                'wizard_id': wizard.id,
                'sprint_id': sprint.id,
                'sprint_name': sprint.name,
                'team_member_count': len(team_members),
                'work_progress': sprint.progress,
                'days_elapsed': days_elapsed,
                'days_remaining': days_remaining,
                'task_count': len(sprint_tasks),
                'completed_task_count': len(completed_tasks),
            })
        if lines_to_create:
            self.env['project.sprint.details.wizard.line'].create(lines_to_create)
        return {
            'name': 'Project Sprint Statistics',
            'type': 'ir.actions.act_window',
            'res_model': 'project.sprint.details.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }