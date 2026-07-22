# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError


class ScrumBulkTaskWizard(models.TransientModel):
    """
    Bulk Task Operations Wizard.

    ROOT CAUSE OF SPRINT BEING IGNORED:
    ═════════════════════════════════════════════════════════════════════
    project.task likely has a write() override or _onchange_project_id
    that clears sprint_id whenever project_id changes in the same write
    call. The sequence inside a single write({project_id, sprint_id}):

        1. ORM sets project_id = X
        2. Odoo triggers _onchange_project_id on the record
        3. _onchange_project_id clears sprint_id = False
        4. ORM then sets sprint_id = Y  ...but onchange already cleared it
           OR the write override sees project change and forces sprint = False

    SOLUTION — Two-step write:
    ─────────────────────────────────────────────────────────────────────
    Step 1: Write project_id alone (triggers any project-related onchanges)
    Step 2: Write sprint_id alone immediately after (sets it cleanly with
            no competing onchange that would clear it)

    This matches how Odoo's own UI works — the form view sends two
    separate onchange/write sequences when you change project then sprint.
    """

    _name        = 'scrum.bulk.task.wizard'
    _description = 'Scrum Bulk Task Operations Wizard'

    # ─── hidden / technical ─────────────────────────────────────────────────
    task_ids = fields.Many2many(
        'project.task',
        'scrum_bulk_wizard_task_rel', 'wizard_id', 'task_id',
        string='Selected Tasks', readonly=True,
    )
    task_count = fields.Integer(compute='_compute_task_count')
    operation  = fields.Selection(
        [('update', 'Info Change'), ('delete', 'Delete')],
        default='update', required=True,
    )

    # ─── the 3 visible fields ────────────────────────────────────────────────

    user_ids = fields.Many2many(
        'res.users',
        'scrum_bulk_wizard_user_rel', 'wizard_id', 'user_id',
        string='Owner(s)',
        domain=[('share', '=', False), ('active', '=', True)],
    )

    project_id = fields.Many2one(
        'project.project',
        string='Project',
        domain=[('project_type', '=', 'scrum')],
    )

    sprint_id = fields.Many2one(
        'project.scrum.sprint',
        string='Sprint',
        domain="[('state', '!=', 'completed')]",
    )

    # ─── compute ────────────────────────────────────────────────────────────
    @api.depends('task_ids')
    def _compute_task_count(self):
        for w in self:
            w.task_count = len(w.task_ids)

    # ─── onchange ───────────────────────────────────────────────────────────
    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.sprint_id = False
        if self.project_id:
            sprint_domain = [
                ('project_id', '=', self.project_id.id),
                ('state', '!=', 'completed'),
            ]
        else:
            sprint_domain = [('id', '=', False)]
        return {'domain': {'sprint_id': sprint_domain}}

    # ─── admin guard ────────────────────────────────────────────────────────
    def _check_admin(self):
        u = self.env.user
        if not (u.has_group('base.group_system') or
                u.has_group('project.group_project_manager')):
            raise AccessError(_(
                'Access Denied: Only Project Managers or System Administrators '
                'can perform bulk task operations.'
            ))

    # ─── view resolver ───────────────────────────────────────────────────────
    def _get_view_id(self, operation):
        name = ('scrum.bulk.task.wizard.update.form'
                if operation == 'update'
                else 'scrum.bulk.task.wizard.delete.form')
        view = self.env['ir.ui.view'].search(
            [('name',  '=', name),
             ('model', '=', self._name),
             ('type',  '=', 'form'),
             ('active', '=', True)],
            order='priority asc', limit=1,
        )
        return view.id or False

    # ─── JS entry-point ─────────────────────────────────────────────────────
    @api.model
    def open_bulk_wizard(self, task_ids, operation='update'):
        u = self.env.user
        if not (u.has_group('base.group_system') or
                u.has_group('project.group_project_manager')):
            raise AccessError(_('Access Denied.'))

        if not task_ids:
            raise UserError(_('No tasks selected.'))
        if operation not in ('update', 'delete'):
            raise UserError(_('Invalid operation.'))

        wizard = self.with_context(is_scrum_app=True).create({
            'task_ids' : [(6, 0, task_ids)],
            'operation': operation,
        })

        title   = (_('Bulk Update Tasks')
                   if operation == 'update'
                   else _('Delete Selected Tasks'))
        view_id = self._get_view_id(operation)

        return {
            'type'     : 'ir.actions.act_window',
            'name'     : title,
            'res_model': self._name,
            'res_id'   : wizard.id,
            'view_mode': 'form',
            'views'    : [[view_id, 'form']],
            'target'   : 'new',
            'context'  : {
                'is_scrum_app'        : True,
                'default_project_type': 'scrum',
                'dialog_size'         : 'medium',
            },
        }

    # ─── bulk update ────────────────────────────────────────────────────────
    def action_apply_update(self):
        self._check_admin()
        self.ensure_one()

        if not self.task_ids:
            raise UserError(_('No tasks selected.'))

        # Context used for ALL writes — tells task write() overrides not to
        # auto-clear sprint and to respect the scrum hierarchy
        ctx = {
            'is_scrum_app'       : True,
            'is_transferring_task': bool(self.project_id),
            # This flag tells any _onchange_project_id override on project.task
            # to NOT clear sprint_id — we are doing a programmatic bulk write
            'bulk_task_update'   : True,
        }
        tasks = self.task_ids.with_context(**ctx)

        # ── Owner ─────────────────────────────────────────────────────────
        if self.user_ids:
            tasks.write({'user_ids': [(6, 0, self.user_ids.ids)]})

        # ── Project + Sprint ──────────────────────────────────────────────
        if self.project_id and self.sprint_id:
            # CASE 1: Both project AND sprint selected.
            #
            # TWO-STEP WRITE to prevent project_id write from clearing sprint:
            #
            # Step 1 — write project_id first (triggers project-related logic)
            tasks.write({'project_id': self.project_id.id})
            #
            # Step 2 — write sprint_id separately AFTER project is set.
            # At this point, the project write is complete and no further
            # onchange can clear sprint_id because we're in a new write call.
            tasks.write({'sprint_id': self.sprint_id.id})

        elif self.project_id and not self.sprint_id:
            # CASE 2: Project only — tasks go to project backlog
            tasks.write({
                'project_id': self.project_id.id,
                'sprint_id' : False,   # explicit backlog
            })

        elif self.sprint_id and not self.project_id:
            # CASE 3: Sprint only (no project change)
            for task in self.task_ids:
                if self.sprint_id.project_id.id != task.project_id.id:
                    raise UserError(_(
                        'Sprint "%s" does not belong to the project of task "%s". '
                        'Please also select the matching Project.'
                    ) % (self.sprint_id.name, task.name))
            tasks.write({'sprint_id': self.sprint_id.id})

        elif not self.user_ids:
            # Nothing was filled at all
            raise UserError(_(
                'Nothing to update. '
                'Please fill at least one field (Owner, Project, or Sprint).'
            ))

        return {'type': 'ir.actions.act_window_close'}

    # ─── bulk delete ────────────────────────────────────────────────────────
    def action_apply_delete(self):
        self._check_admin()
        self.ensure_one()
        if not self.task_ids:
            raise UserError(_('No tasks selected.'))
        self.task_ids.unlink()
        return {'type': 'ir.actions.act_window_close'}