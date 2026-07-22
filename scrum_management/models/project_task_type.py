# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.osv import expression

class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    project_type = fields.Selection([
        ('standard', 'Standard Project'),
        ('scrum', 'Software (Scrum) Project')
    ], string="Project Type", default='standard')

    category = fields.Selection([
        ('new', 'New'),
        ('committed', 'Committed'),
        ('active', 'Active'),
        ('blocked', 'Blocked'),
        ('qa', 'In QA'),
        ('review', 'In Review'),
        ('closed', 'Closed')
    ], string="Stage Category", default='new',
        help="Defines the strict agile behavior for tasks entering this stage.")

    # ===========================================================
    # THE BUG FIX: PREVENTING PERSONAL "GHOST" STAGES
    # ===========================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Strip the user_id to ensure the stage is globally visible
            p_type = vals.get('project_type') or self.env.context.get('default_project_type')
            if p_type == 'scrum' or self.env.context.get('is_scrum_app'):
                vals['user_id'] = False
        return super(ProjectTaskType, self).create(vals_list)

    def write(self, vals):
        # Prevent Odoo from retroactively making a global scrum stage private
        if 'user_id' in vals and vals.get('user_id'):
            for stage in self:
                if stage.project_type == 'scrum':
                    vals['user_id'] = False
                    break
        return super(ProjectTaskType, self).write(vals)

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None):
        """
        App Isolation for Task Stages.
        Ensures Scrum projects only see Scrum stages, and vice versa.
        """
        if self.env.context.get('install_mode') or self.env.context.get('import_file'):
            return super()._search(domain, offset=offset, limit=limit, order=order)

        # Allow direct ID lookups to bypass the firewall
        is_direct_lookup = any(
            isinstance(leaf, (list, tuple)) and leaf[0] in ('id', 'res_id')
            for leaf in domain
        )

        if not is_direct_lookup:
            if self.env.context.get('is_scrum_app'):
                domain = expression.AND([domain, [('project_type', '=', 'scrum')]])
            elif self.env.context.get('is_standard_project_app') or self.env.context.get('default_project_type') == 'standard':
                domain = expression.AND([domain, [('project_type', '=', 'standard')]])

        return super()._search(domain, offset=offset, limit=limit, order=order)