# -*- coding: utf-8 -*-

from odoo import models, fields


class SprintDetailsWizard(models.TransientModel):
    """ The main wizard that holds the list of sprint statistics. """
    _name = 'project.sprint.details.wizard'
    _description = 'Sprint Details Dashboard Wizard'

    project_name = fields.Char(string="Project Name", readonly=True)
    line_ids = fields.One2many(
        'project.sprint.details.wizard.line',
        'wizard_id',
        string="Sprint Details",
        readonly=True
    )


class SprintDetailsWizardLine(models.TransientModel):
    """ A single line in the wizard, representing one sprint's statistics. """
    _name = 'project.sprint.details.wizard.line'
    _description = 'Sprint Details Wizard Line'

    wizard_id = fields.Many2one('project.sprint.details.wizard', readonly=True)
    sprint_id = fields.Many2one('project.scrum.sprint', readonly=True)

    # Fields for display
    sprint_name = fields.Char(string="Sprint Name", readonly=True)
    team_member_count = fields.Integer(string="Team Members", readonly=True)
    work_progress = fields.Integer(string="Work Progress (%)", readonly=True)
    days_elapsed = fields.Integer(string="Days Elapsed", readonly=True)
    days_remaining = fields.Integer(string="Days Remaining", readonly=True)
    task_count = fields.Integer(string="Total Tasks", readonly=True)
    completed_task_count = fields.Integer(string="Completed Tasks", readonly=True)

    # --- THIS METHOD IS NOW CORRECTED ---
    def action_open_sprint(self):
        """
        This method is called when a Kanban card is clicked.
        It now returns an action that correctly redirects the main window
        to the specific sprint form view you requested.
        """
        self.ensure_one()

        # Get the database ID of the specific form view you want to open
        view_id = self.env.ref('scrum_management.view_project_scrum_sprint_form').id

        return {
            'name': 'Sprint Details',
            'type': 'ir.actions.act_window',
            'res_model': 'project.scrum.sprint',
            'view_mode': 'form',

            # CHANGE 1: Explicitly specify the view to use
            'views': [[view_id, 'form']],

            'res_id': self.sprint_id.id,

            # CHANGE 2: This is the key. 'current' redirects the main page.
            'target': 'current',
        }