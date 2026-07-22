# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import ValidationError, AccessError
import logging
import difflib
from bs4 import BeautifulSoup


class ProjectScrumSprintStage(models.Model):
    _name = 'project.scrum.sprint.stage'
    _description = 'Sprint Stage'
    _order = 'sequence, id'

    name = fields.Char(string="Stage Name", required=True, translate=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(string="Folded in Kanban", default=False)

    category = fields.Selection([
        ('backlog', 'Backlog'),
        ('todo', 'Active / To Do'),
        ('in_progress', 'Active / In Progress'),
        ('qa', 'In QA'),
        ('review', 'In Review'),
        ('finalized', 'Finished / Closed')
    ], string="Stage Category", default='todo', required=True)


# ===========================================================
# 2. DOD TEMPLATES (Master Data Configuration)
# ===========================================================
class ScrumDoDTemplate(models.Model):
    _name = 'project.scrum.dod.template'
    _description = 'Definition of Done Template'

    name = fields.Char(string="Template Name", required=True)

    description = fields.Text(string="Description", help="Explain when to use this DoD template.")

    # NEW: Favorite / Default Flag
    is_default = fields.Boolean(string="Default Template", help="Starred template auto-applies to new sprints.")

    item_ids = fields.One2many('project.scrum.dod.template.item', 'template_id', string="Checklist Items")

    @api.model_create_multi
    def create(self, vals_list):
        # Ensure only one template is the default
        for vals in vals_list:
            if vals.get('is_default'):
                self.search([('is_default', '=', True)]).write({'is_default': False})
        return super(ScrumDoDTemplate, self).create(vals_list)

    def write(self, vals):
        # Ensure only one template is the default when updating
        if vals.get('is_default'):
            self.search([('id', '!=', self.id), ('is_default', '=', True)]).write({'is_default': False})
        return super(ScrumDoDTemplate, self).write(vals)


class ScrumDoDTemplateItem(models.Model):
    _name = 'project.scrum.dod.template.item'
    _description = 'DoD Template Item'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Checklist Item", required=True)
    template_id = fields.Many2one('project.scrum.dod.template', string="Template", ondelete='cascade')


# ===========================================================
# 3. SPRINT DOD (The actual checklist instance for a Sprint)
# ===========================================================
class ScrumSprintDoD(models.Model):
    _name = 'project.scrum.sprint.dod'
    _description = 'Sprint DoD Checklist'
    _order = 'id'

    sprint_id = fields.Many2one('project.scrum.sprint', string="Sprint", required=True, ondelete='cascade')
    description = fields.Char(string="Checklist Item", required=True)
    status = fields.Boolean(string="Completed", default=False)

    def write(self, vals):
        res = super(ScrumSprintDoD, self).write(vals)

        # --- REOPEN LOGIC: If a DoD item is unchecked, reopen the sprint ---
        if 'status' in vals and not vals.get('status'):
            for dod in self:
                sprint = dod.sprint_id
                if sprint.state == 'completed' or (sprint.stage_id and sprint.stage_id.category == 'finalized'):
                    revert_stage = self.env['project.scrum.sprint.stage'].search([('category', '=', 'in_progress')],
                                                                                 limit=1)
                    if not revert_stage:
                        revert_stage = self.env['project.scrum.sprint.stage'].search([('category', '=', 'backlog')],
                                                                                     limit=1)

                    if revert_stage:
                        sprint.write({
                            'stage_id': revert_stage.id,
                            'end_date': False
                        })
        return res


# ===========================================================
# 4. SPRINT MODEL (Core Logic)
# ===========================================================
class ScrumSprint(models.Model):
    """
    Model representing a Scrum Sprint.
    Includes automated progress tracking, velocity snapshots,
    strict separation logic for Software projects, and DoD enforcement.
    """
    _name = 'project.scrum.sprint'
    _description = 'Scrum Sprint'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, name desc'

    name = fields.Char(string='Sprint Name', required=True, tracking=True)

    _logger = logging.getLogger(__name__)

    # UPDATED: description now tracked in chatter
    description = fields.Html(string="Sprint Description")

    row_number = fields.Integer(
        string="#",
        compute="_compute_row_number",
        store=False
    )

    # =========================================
    # RELATIONS
    # =========================================
    # RESTORED: Only fetch parent tasks so subtasks don't clutter the sprint board

    #########################
    #########################
    #  Refactor the name of the task_id to parent task (all the tasks information
    #  from db which is creating confusing so this name should be updated
    #   *****note ( this is data of task for using in the sprint )***
    ########################
    ########################

    task_ids = fields.One2many(
        'project.task',
        'sprint_id',
        string="Tasks",
        domain=[('parent_id', '=', False)]
    )

    project_id = fields.Many2one(
        'project.project',
        string='Project',
        required=True,
        ondelete='cascade',
        domain=[('project_type', '=', 'scrum')],
        tracking=True
    )

    project_type = fields.Selection(
        related='project_id.project_type',
        string="Project Workflow Type",
        store=True,
        readonly=True
    )

    # =========================================
    # 🔥 TIME FIELDS (HOURS + PROGRESS)
    # =========================================

    spent_time = fields.Float(
        string="Spent Time (Hours)",
        compute="_compute_time",
        store=True,
        digits=(16, 2)
    )

    time_progress = fields.Integer(
        string="Time Progress (%)",
        compute="_compute_time",
        store=True
    )

    efficiency_hours = fields.Float(
        string="Efficiency (Hours)",
        compute="_compute_efficiency",
        store=True,
        digits=(16, 2)
    )

    efficiency_status = fields.Selection([
        ('good', 'Efficient'),
        ('over', 'Overused'),
        ('exact', 'Exact')
    ], compute="_compute_efficiency", store=True)

    # =========================================
    # 🔥 ALLOCATED TIME COMPUTE (FINAL)
    # =========================================
    allocated_time = fields.Float(
        string="Allocated Time",
        compute="_compute_allocated_time",
        store=True
    )

    @api.depends('task_ids.allocated_hours')
    def _compute_allocated_time(self):
        for sprint in self:
            all_tasks = self.env['project.task'].search([
                ('id', 'child_of', sprint.task_ids.ids)
            ])
            sprint.allocated_time = sum(all_tasks.mapped('allocated_hours'))

    # =========================================
    # get name
    # =========================================

    def action_open_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tasks',
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('sprint_id', '=', self.id)],
            'context': {'default_sprint_id': self.id},
        }

    # =========================================
    # 🔥 SPENT TIME + PROGRESS (KEEP % FOR UI)
    # =========================================
    @api.depends('task_ids', 'task_ids.child_ids')
    def _compute_time(self):
        for sprint in self:
            all_tasks = sprint.task_ids
            to_process = sprint.task_ids

            while to_process:
                children = to_process.mapped('child_ids')
                all_tasks |= children
                to_process = children

            timesheets = self.env['account.analytic.line'].search([
                ('task_id', 'in', all_tasks.ids)
            ])

            spent = sum(timesheets.mapped('unit_amount'))
            sprint.spent_time = spent

            if sprint.allocated_time:
                sprint.time_progress = int((spent / sprint.allocated_time) * 100)
            else:
                sprint.time_progress = 0

    # =========================================
    # 🔥 EFFICIENCY
    # =========================================
    @api.depends('allocated_time', 'spent_time')
    def _compute_efficiency(self):
        for sprint in self:
            diff = sprint.allocated_time - sprint.spent_time
            sprint.efficiency_hours = diff

            if diff > 0:
                sprint.efficiency_status = 'good'
            elif diff < 0:
                sprint.efficiency_status = 'over'
            else:
                sprint.efficiency_status = 'exact'

    @api.depends()
    def _compute_row_number(self):
        for index, record in enumerate(self, start=1):
            record.row_number = index

    @api.model
    def _default_stage_id(self):
        stage = self.env['project.scrum.sprint.stage'].search([('category', '=', 'backlog')], limit=1)
        if not stage:
            stage = self.env['project.scrum.sprint.stage'].search([], order='sequence', limit=1)
        return stage.id if stage else False

    # --- DOD FIELDS ---
    dod_template_id = fields.Many2one('project.scrum.dod.template', string="DoD Template")
    dod_ids = fields.One2many('project.scrum.sprint.dod', 'sprint_id', string="Definition of Done")
    dod_progress_display = fields.Char(compute='_compute_dod_progress', string="DoD Progress")

    @api.depends('dod_ids.status')
    def _compute_dod_progress(self):
        """Calculates the progress string for Kanban cards and Wizards."""
        for sprint in self:
            total = len(sprint.dod_ids)
            completed = len(sprint.dod_ids.filtered(lambda d: d.status))
            if total == 0:
                sprint.dod_progress_display = "No DoD"
            else:
                sprint.dod_progress_display = f"☑ {completed}/{total}"

    @api.onchange('dod_template_id')
    def _onchange_dod_template_id(self):
        """Auto-populate the DoD checklist when a template is selected."""
        if self.dod_template_id:
            # Clear existing lines to prevent duplicates
            self.dod_ids = [(5, 0, 0)]
            new_lines = []
            for item in self.dod_template_id.item_ids:
                new_lines.append((0, 0, {
                    'description': item.name,
                    'status': False
                }))
            self.dod_ids = new_lines

    # --- DYNAMIC KANBAN FIELDS ---
    stage_id = fields.Many2one(
        'project.scrum.sprint.stage',
        string='Sprint Stage',
        default=_default_stage_id,
        group_expand='_read_group_stage_ids',
        tracking=True
    )

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        return self.env['project.scrum.sprint.stage'].search([], order=order)

    start_date = fields.Date(string='Start Date', tracking=True)
    end_date = fields.Date(string='End Date', tracking=True)

    # --- THE STATE BRIDGE ---
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('closed', 'Closed'),
        ('archived', 'Archived')
    ], string='Status', compute='_compute_state_from_stage', store=True, readonly=False, tracking=True)

    committed_story_points = fields.Integer(
        string="Committed Story Points"
    )

    velocity = fields.Integer(
        string="Sprint Velocity",
        readonly=True,
        copy=False
    )

    total_story_points = fields.Integer(compute='_compute_sprint_progress')
    completed_story_points = fields.Integer(compute='_compute_sprint_progress')
    progress = fields.Integer(compute='_compute_sprint_progress')
    days_remaining = fields.Integer(compute='_compute_sprint_progress')

    on_track_status = fields.Selection([
        ('ahead', 'Ahead of Schedule'),
        ('on_track', 'On Track'),
        ('behind', 'Behind Schedule'),
        ('not_started', 'Not Started'),
        ('done', 'Completed')
    ], compute='_compute_sprint_progress')

    @api.depends('stage_id.category')
    def _compute_state_from_stage(self):
        for sprint in self:
            cat = sprint.stage_id.category
            if not cat or cat in ['backlog', 'todo']:
                sprint.state = 'draft'
            elif cat in ['in_progress', 'qa', 'review']:
                sprint.state = 'active'
            elif cat == 'finalized':
                sprint.state = 'completed'

    @api.depends('task_ids.story_points', 'task_ids.is_closed', 'start_date', 'end_date', 'state')
    def _compute_sprint_progress(self):
        today = fields.Date.today()

        for sprint in self:
            if sprint.state == 'completed':
                sprint.on_track_status = 'done'
                sprint.progress = 100
                sprint.time_progress = 100
                sprint.days_remaining = 0
                sprint.total_story_points = sum(sprint.task_ids.mapped('story_points'))
                sprint.completed_story_points = sprint.total_story_points
                continue

            total_sp = sum(sprint.task_ids.mapped('story_points'))
            completed_sp = sum(sprint.task_ids.filtered(lambda t: t.is_closed).mapped('story_points'))

            sprint.total_story_points = total_sp
            sprint.completed_story_points = completed_sp
            sprint.progress = (completed_sp / total_sp * 100) if total_sp > 0 else 0

            if not sprint.start_date or not sprint.end_date or sprint.start_date > today:
                sprint.time_progress = 0
                sprint.on_track_status = 'not_started'
                sprint.days_remaining = (
                                                    sprint.end_date - sprint.start_date).days + 1 if sprint.start_date and sprint.end_date else 0
            else:
                total_days = (sprint.end_date - sprint.start_date).days + 1
                days_passed = (today - sprint.start_date).days + 1
                sprint.days_remaining = (sprint.end_date - today).days if today <= sprint.end_date else 0

                # RESTORED: Calculate temporary time_progress logic just for tracking status
                # so we don't accidentally overwrite the hours-based sprint.time_progress
                calculated_time_prog = min(100, (days_passed / total_days * 100) if total_days > 0 else 0)

                if sprint.progress >= calculated_time_prog:
                    sprint.on_track_status = 'ahead'
                elif sprint.progress >= (calculated_time_prog - 15):
                    sprint.on_track_status = 'on_track'
                else:
                    sprint.on_track_status = 'behind'

    # ===========================================================
    # AGILE STAGE SYNC ENGINE
    # ===========================================================
    def _update_stage_from_tasks(self):
        """
        Dynamically calculates and updates the Sprint Stage based on the highest
        priority task stage currently active within the sprint.
        """
        for sprint in self:
            if not sprint.task_ids:
                target_cat = 'backlog'
            else:
                categories = sprint.task_ids.mapped('stage_id.category')

                if all(c == 'closed' for c in categories):
                    continue  # Safety measure: respect manual close & DoD rules
                elif 'review' in categories:
                    target_cat = 'review'
                elif 'qa' in categories:
                    target_cat = 'qa'
                elif 'active' in categories or 'blocked' in categories:
                    target_cat = 'in_progress'
                elif 'committed' in categories:
                    target_cat = 'todo'
                else:
                    target_cat = 'backlog'

            if sprint.stage_id.category != target_cat:
                new_stage = self.env['project.scrum.sprint.stage'].search([('category', '=', target_cat)], limit=1)
                if new_stage:
                    sprint.with_context(auto_stage_sync=True).write({'stage_id': new_stage.id})

    def action_activate_sprint(self):
        in_progress_stage = self.env['project.scrum.sprint.stage'].search([('category', '=', 'in_progress')], limit=1)
        for sprint in self:
            vals = {'state': 'active'}
            if in_progress_stage:
                vals['stage_id'] = in_progress_stage.id
            if not sprint.start_date:
                vals['start_date'] = fields.Date.today()
            sprint.write(vals)
            sprint.message_post(body=_("Sprint Started"))

    def action_complete_sprint(self):
        finalized_stage = self.env['project.scrum.sprint.stage'].search([('category', '=', 'finalized')], limit=1)
        for sprint in self:
            vals = {'state': 'completed', 'end_date': fields.Date.today()}
            if finalized_stage:
                vals['stage_id'] = finalized_stage.id
            sprint.write(vals)
            sprint.message_post(body=_("Sprint Completed. Velocity: %s Story Points") % sprint.velocity)

    def action_open_sprint_tasks(self):
        self.ensure_one()
        return {
            'name': _('Tasks: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'domain': [('sprint_id', '=', self.id)],
            'context': {
                'default_sprint_id': self.id,
                'default_project_id': self.project_id.id,
                'is_scrum_app': True
            }
        }



    def action_open_dod_wizard(self):
        """ Opens the Definition of Done wizard from the Kanban board indicator. """
        self.ensure_one()
        return {
            'name': _('Definition of Done: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'project.scrum.dod.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sprint_id': self.id,
                'default_dod_ids': self.dod_ids.ids
            },
        }



    def action_open_sprint_form_dialog(self):
        """
        Open THIS sprint's full form view in an EDITABLE modal dialog.

        Used from readonly dashboards/embedded lists where the default
        row-click opens the record in readonly mode (which hides the
        'Add a line' option on the Tasks tab). Because this returns a
        fresh act_window with target='new', the form opens in edit mode,
        restoring full task-creation behaviour.
        """
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'project.scrum.sprint',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('scrum_management.view_project_scrum_sprint_form').id,
            'target': 'new',
            'context': {
                'default_project_id': self.project_id.id,
                'default_sprint_id': self.id,
                'is_scrum_app': True,
            },
        }

    # --- ORM OVERRIDES ---

    @api.model_create_multi
    def create(self, vals_list):
        default_template = self.env['project.scrum.dod.template'].search([('is_default', '=', True)], limit=1)
        for vals in vals_list:
            if not vals.get('dod_template_id') and default_template:
                vals['dod_template_id'] = default_template.id
                if not vals.get('dod_ids'):
                    vals['dod_ids'] = [(0, 0, {'description': item.name, 'status': False}) for item in
                                       default_template.item_ids]

        return super(ScrumSprint, self).create(vals_list)

    def write(self, vals):
        # NEW: Enforce the "Cannot move out of Backlog" rule manually
        if 'stage_id' in vals and not self.env.context.get('auto_stage_sync'):
            target_stage = self.env['project.scrum.sprint.stage'].browse(vals['stage_id'])
            for sprint in self:
                categories = sprint.task_ids.mapped('stage_id.category')
                if (not categories or all(
                        c in ['new', False] for c in categories)) and target_stage.category != 'backlog':
                    raise ValidationError(_(
                        "🛑 Sprint Locked: The sprint is either empty or all tasks are in the 'New' stage. "
                        "You must commit at least one task to advance this sprint out of the Backlog."
                    ))

        is_completing = False
        if vals.get('state') == 'completed':
            is_completing = True
        elif 'stage_id' in vals:
            stage_data = self.env['project.scrum.sprint.stage'].browse(vals['stage_id']).read(['category'])
            if stage_data and stage_data[0].get('category') == 'finalized':
                is_completing = True

        if is_completing:
            # --- SPRINT ACCESS RIGHTS ENFORCEMENT ---
            if not self.env.user.has_group('project.group_project_manager') and not self.env.user.has_group(
                    'base.group_system'):
                raise AccessError(
                    _("Access Denied: Only Project Managers or Administrators can move a Sprint to the Finished/Closed stage."))

            for sprint in self:
                # 1. Validation: All tasks in the sprint MUST be closed
                uncompleted_tasks = sprint.task_ids.filtered(lambda t: not t.is_closed)
                if uncompleted_tasks:
                    task_names = "\n - ".join(uncompleted_tasks.mapped('name'))
                    raise ValidationError(
                        _("The sprint '%s' cannot be marked as Finished/Closed because the following tasks are still in progress:\n\n - %s") % (
                        sprint.name, task_names))

                # 2. Validation: DoD Checklist MUST be completely checked
                pending_dod = sprint.dod_ids.filtered(lambda d: not d.status)
                if pending_dod:
                    dod_names = "\n - ".join(pending_dod.mapped('description'))
                    raise ValidationError(
                        _("The sprint '%s' cannot be closed until the Definition of Done is fully checked. Pending items:\n\n - %s") % (
                        sprint.name, dod_names))

                # Snapshot Velocity
                total_sp = sum(sprint.task_ids.mapped('story_points'))
                completed_sp = sum(sprint.task_ids.filtered(lambda t: t.is_closed).mapped('story_points'))
                vals['velocity'] = completed_sp

                if not sprint.end_date and not vals.get('end_date'):
                    vals['end_date'] = fields.Date.today()

        # Gather pre-write states for chatter logging
        old_tasks = {}
        old_points = {}
        old_description = {}

        for sprint in self:
            old_tasks[sprint.id] = sprint.task_ids.mapped('name')
            old_points[sprint.id] = sprint.committed_story_points
            old_description[sprint.id] = sprint.description

        result = super(ScrumSprint, self).write(vals)

        # Log chatter events post-write
        for sprint in self:
            if 'committed_story_points' in vals:
                old = old_points.get(sprint.id)
                new = sprint.committed_story_points
                if old != new:
                    sprint.message_post(body=_("Committed Story Points: %s → %s") % (old, new))

            #         description addded and updated to get updated content

            if 'description' in vals:
                old_desc = old_description.get(sprint.id) or ""
                new_desc = sprint.description or ""

                # New description added
                if not old_desc.strip() and new_desc.strip():
                    sprint.message_post(
                        body=_("Sprint description added")
                    )

                # Existing description updated
                elif old_desc != new_desc:

                    # Convert HTML to readable text
                    old_text = BeautifulSoup(old_desc, "html.parser").get_text(" ")
                    new_text = BeautifulSoup(new_desc, "html.parser").get_text(" ")

                    diff = list(difflib.ndiff(
                        old_text.split(),
                        new_text.split()
                    ))

                    added = []
                    removed = []

                    for item in diff:
                        if item.startswith("+ "):
                            added.append(item[2:])
                        elif item.startswith("- "):
                            removed.append(item[2:])

                    message = "Description Updated"

                    if added:
                        message += "\n\nAdded:\n" + " ".join(added)

                    if removed:
                        message += "\n\nRemoved:\n" + " ".join(removed)

                    sprint.message_post(body=message)
            # if 'description' in vals:
            #     old_desc = old_description.get(sprint.id)
            #     new_desc = sprint.description
            #     if not old_desc and new_desc:
            #         sprint.message_post(body=_("Sprint description added"))
            #     elif old_desc != new_desc:
            #         sprint.message_post(body=_("Sprint description updated"))

            old_list = set(old_tasks.get(sprint.id, []))
            new_list = set(sprint.task_ids.mapped('name'))

            for task in new_list - old_list:
                sprint.message_post(body=_("Task created: %s") % task)

            for task in old_list - new_list:
                sprint.message_post(body=_("Task removed: %s") % task)

        return result


# ===========================================================
# 5. DOD WIZARD (Transient Model for Kanban Quick-Update)
# ===========================================================
class ScrumDoDWizard(models.TransientModel):
    _name = 'project.scrum.dod.wizard'
    _description = 'DoD Checklist Wizard'

    sprint_id = fields.Many2one('project.scrum.sprint', string="Sprint")

    dod_ids = fields.Many2many(
        'project.scrum.sprint.dod',
        string="Checklist Items"
    )

    def action_done(self):
        """ Closes the wizard. Changes to dod_ids are saved automatically by Odoo. """
        return {'type': 'ir.actions.act_window_close'}


# ===========================================================
# 6. PROJECT MODEL EXTENSION (Access Rights for Project Stages)
# ===========================================================
class ProjectProject(models.Model):
    _inherit = 'project.project'

    def write(self, vals):
        if 'stage_id' in vals:
            target_stage = self.env['project.project.stage'].browse(vals['stage_id'])
            if target_stage.fold:
                # --- PROJECT ACCESS RIGHTS ENFORCEMENT ---
                if not self.env.user.has_group('project.group_project_manager') and not self.env.user.has_group(
                        'base.group_system'):
                    raise AccessError(
                        _("Access Denied: Only Project Managers or Administrators can move a Project to a closed/folded stage."))

        return super(ProjectProject, self).write(vals)