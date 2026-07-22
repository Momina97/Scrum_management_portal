# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class ScrumRelease(models.Model):
    """
    Model representing a Software Release.
    Links specifically to completed sprints within a Scrum project.
    """
    _name = 'project.scrum.release'
    _description = 'Scrum Release'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'release_date desc, name'

    name = fields.Char(
        string='Release Name',
        required=True,
        tracking=True,
        help="e.g. Version 1.0.0, Q1 Production Release"
    )

    # SEPARATION: The domain ensures only 'Scrum' projects can be selected for a Release.
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        required=True,
        ondelete='cascade',
        domain=[('project_type', '=', 'scrum')],
        tracking=True
    )

    release_date = fields.Date(
        string="Release Date",
        default=fields.Date.context_today,
        tracking=True
    )

    description = fields.Text(
        string='Release Notes',
        help="Details about features, bug fixes, and technical changes in this release."
    )

    # SEPARATION: Only completed sprints from the selected Scrum project can be included.
    # The domain here ensures the UI only allows selecting COMPLETED sprints from the current project.
    sprint_ids = fields.Many2many(
        'project.scrum.sprint',
        'release_sprint_rel',
        'release_id',
        'sprint_id',
        string='Sprints in Release',
        domain="[('project_id', '=', project_id), ('state', '=', 'completed')]",
        help="Link the completed sprints that form this release."
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('finalized', 'Finalized')
    ], string='Status', default='draft', tracking=True)

    # --- CONSTRAINTS ---

    @api.constrains('sprint_ids')
    def _check_sprints_state(self):
        """
        Ensures that only COMPLETED sprints are included in a release.
        This focuses only on the selected sprints, ignoring other project sprints or backlog.
        """
        for release in self:
            incomplete_sprints = release.sprint_ids.filtered(lambda s: s.state != 'completed')
            if incomplete_sprints:
                sprint_names = ", ".join(incomplete_sprints.mapped('name'))
                raise ValidationError(_(
                    "🛑 INVALID RELEASE SCOPE: The following sprints are not 'Completed' and cannot be released:\n\n - %s"
                ) % sprint_names)

    # --- ACTION METHODS ---

    def action_validate(self):
        """
        Transitions the release to 'Validated'.
        Ensures that at least one completed sprint is attached to justify the release.
        """
        self.ensure_one()
        if not self.sprint_ids:
            raise UserError(_("You cannot validate a release without linking at least one completed sprint."))

        # Double check states before validation
        if any(s.state != 'completed' for s in self.sprint_ids):
            raise UserError(_("All sprints linked to this release must be in 'Completed' state."))

        self.write({'state': 'validated'})

    def action_finalize(self):
        """
        Transitions the release to 'Finalized' (Deployed/Released).
        """
        self.ensure_one()
        if self.state != 'validated':
            raise UserError(_("A release must be validated before it can be finalized."))
        self.write({'state': 'finalized'})

    def action_set_to_draft(self):
        """
        Allows resetting a release to draft if it hasn't been finalized yet.
        """
        self.ensure_one()
        self.write({'state': 'draft'})